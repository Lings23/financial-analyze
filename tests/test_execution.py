import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from tempfile import TemporaryDirectory

from stock_research.errors import (IntegrityError, PermissionDenied, ProviderAuthError,
                                  ProviderSchemaError, ProviderUnavailable, TransientProviderError)
from stock_research.models import AccessContext, DataRequest, Dataset, QueryContext
from stock_research.providers.base import ProviderCapability, ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository
from helpers import SECURITY, financial_record, ts


class FakeProvider:
    def __init__(self, handler, name="fixture"):
        self.handler = handler
        self.capability = ProviderCapability(name, "1", frozenset({Dataset.FINANCIAL_INCOME}),
                                            frozenset({"consolidated_cumulative_cny"}), True)
        self.calls = 0
        self.lock = threading.Lock()

    def fetch(self, request, scope, timeout):
        with self.lock:
            self.calls += 1
        return self.handler(request, scope, timeout)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = ArtifactStore(self.temp.name)
        self.record = financial_record(self.artifacts)
        self.request = DataRequest(SECURITY, Dataset.FINANCIAL_INCOME, date(2024, 12, 31), date(2024, 12, 31))
        self.access = AccessContext("tenant-a", frozenset({"fixture"}))
        self.executor = ProviderExecutor(ExecutionPolicy(min_interval=0, retry_base=0, total_timeout=2))
        self.addCleanup(self.executor.close)
        self.repo = MemoryRepository()
        self.registry = ProviderRegistry()
        self.service = DataService(self.registry, self.executor, self.repo, self.artifacts)

    def test_concurrent_duplicate_requests_share_one_call(self):
        started, release = threading.Event(), threading.Event()
        def handler(*_):
            started.set()
            if not release.wait(1):
                raise AssertionError("test coordination timed out")
            return (self.record,)
        provider = FakeProvider(handler)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self.executor.fetch, provider, self.request, self.access) for _ in range(8)]
            self.assertTrue(started.wait(1))
            deadline = time.monotonic() + 1
            while self.executor.stats["logical_calls"] < 8 and time.monotonic() < deadline:
                time.sleep(0.001)
            release.set()
            results = [future.result() for future in futures]
        self.assertEqual(provider.calls, 1)
        self.assertTrue(all(result == (self.record,) for result in results))
        self.assertEqual(self.executor.stats["dedup_hits"], 7)

    def test_cache_and_scope_separation(self):
        provider = FakeProvider(lambda *_: (self.record,))
        self.executor.fetch(provider, self.request, self.access)
        self.executor.fetch(provider, self.request, self.access)
        self.assertEqual(provider.calls, 1)
        self.executor.fetch(provider, self.request, AccessContext("tenant-b", frozenset({"fixture"})))
        self.assertEqual(provider.calls, 2)

    def test_transient_retry_has_one_owner(self):
        def handler(*_):
            if provider.calls < 3:
                raise TransientProviderError()
            return (self.record,)
        provider = FakeProvider(handler)
        self.assertEqual(self.executor.fetch(provider, self.request, self.access), (self.record,))
        self.assertEqual(provider.calls, 3)
        self.assertEqual(self.executor.stats["retries"], 2)

    def test_auth_and_schema_errors_are_not_retried_or_cached(self):
        for error in (ProviderAuthError, ProviderSchemaError):
            def fail(*_):
                raise error("test failure")
            provider = FakeProvider(fail)
            for _ in range(2):
                with self.assertRaises(error):
                    self.executor.fetch(provider, self.request, self.access)
            self.assertEqual(provider.calls, 2)

    def test_empty_response_is_not_cached(self):
        provider = FakeProvider(lambda *_: ())
        self.executor.fetch(provider, self.request, self.access)
        self.executor.fetch(provider, self.request, self.access)
        self.assertEqual(provider.calls, 2)

    def test_retry_after_larger_than_deadline_does_not_retry(self):
        def fail(*_):
            raise TransientProviderError(retry_after=10)
        provider = FakeProvider(fail)
        with self.assertRaises(TransientProviderError):
            self.executor.fetch(provider, self.request, self.access)
        self.assertEqual(provider.calls, 1)

    def test_late_result_is_discarded_and_not_cached(self):
        policy = ExecutionPolicy(min_interval=0, retry_base=0, total_timeout=0.03, max_attempts=1)
        def late(*_):
            time.sleep(0.06)
            return (self.record,)
        provider = FakeProvider(late)
        with ProviderExecutor(policy) as executor:
            with self.assertRaises(TransientProviderError):
                executor.fetch(provider, self.request, self.access)
        self.assertEqual(executor.stats["cache_hits"], 0)
        self.assertEqual(len(executor._cache), 0)

    def test_rate_limited_requests_have_spaced_start_times(self):
        starts = []
        def capture(*_):
            starts.append(time.monotonic())
            return (self.record,)
        provider = FakeProvider(capture)
        with ProviderExecutor(ExecutionPolicy(min_interval=0.03)) as executor:
            executor.fetch(provider, self.request, self.access, use_cache=False)
            executor.fetch(provider, self.request, self.access, use_cache=False)
        self.assertGreaterEqual(starts[1] - starts[0], 0.025)

    def test_permission_checked_before_cache_or_network(self):
        provider = FakeProvider(lambda *_: (self.record,))
        self.registry.register(provider)
        good = self.service.refresh(self.request, self.access, ("fixture",))
        self.assertEqual(good.record_count, 1)
        with self.assertRaises(PermissionDenied):
            self.service.refresh(self.request, AccessContext("tenant-a", frozenset({"other"})), ("fixture",))
        self.assertEqual(provider.calls, 1)

    def test_ingestion_time_is_real_and_cached_recommit_preserves_first_ingestion(self):
        self.registry.register(FakeProvider(lambda *_: (self.record,)))
        first = self.service.refresh(self.request, self.access, ("fixture",))
        stored = self.repo.read("tenant-a", first.snapshot.snapshot_id)[0]
        self.assertGreater(stored.ingested_at, self.record.retrieved_at)
        second = self.service.refresh(self.request, self.access, ("fixture",))
        self.assertEqual(first.snapshot.snapshot_id, second.snapshot.snapshot_id)
        self.assertEqual(self.repo.read("tenant-a", second.snapshot.snapshot_id)[0].ingested_at,
                         stored.ingested_at)

    def test_fallback_records_actual_source_and_error(self):
        def fail(*_):
            raise ProviderSchemaError("schema drift")
        self.registry.register(FakeProvider(fail, "primary"))
        self.registry.register(FakeProvider(lambda *_: (self.record,)))
        access = AccessContext("tenant-a", frozenset({"primary", "fixture"}))
        result = self.service.refresh(self.request, access, ("primary", "fixture"))
        self.assertEqual(result.provider, "fixture")
        self.assertEqual(result.warnings, ("primary:ProviderSchemaError",))

    def test_exhausted_provider_does_not_commit_snapshot(self):
        def fail(*_):
            raise TransientProviderError()
        self.registry.register(FakeProvider(fail))
        with self.assertRaises(ProviderUnavailable):
            self.service.refresh(self.request, self.access, ("fixture",))
        self.assertEqual(len(self.repo._snapshots), 0)

    def test_unqualified_provider_cannot_claim_historical_release(self):
        provider = FakeProvider(lambda *_: (self.record,))
        provider.capability = replace(provider.capability, historical_release_verified=False)
        self.registry.register(provider)
        for _ in range(2):
            with self.assertRaises(ProviderUnavailable):
                self.service.refresh(self.request, self.access, ("fixture",))
        self.assertEqual(provider.calls, 2)

    def test_missing_artifact_blocks_published_query(self):
        snapshot = self.repo.commit("tenant-a", (self.record,))
        self.artifacts._path("tenant-a", self.record.artifact_id).unlink()
        with self.assertRaises(IntegrityError):
            self.service.query(self.request, QueryContext(self.access, snapshot.snapshot_id, ts("2025-05-01T00:00:00")))

    def test_mutated_scope_cannot_extend_other_snapshot(self):
        provider = FakeProvider(lambda *_: ())
        self.registry.register(provider)
        snapshot = self.repo.commit("tenant-a", ())
        with self.assertRaises(PermissionDenied):
            self.service.refresh(self.request, AccessContext("tenant-b", frozenset({"fixture"})),
                                 ("fixture",), snapshot.snapshot_id)
        self.assertEqual(provider.calls, 0)
