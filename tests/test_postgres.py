import os
import unittest
import uuid
from dataclasses import replace
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory

from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository
from helpers import SECURITY, financial_record, ts


@unittest.skipUnless(os.environ.get("STOCK_RESEARCH_TEST_DSN"), "dedicated PostgreSQL test DSN not configured")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.repo = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        self.repo.migrate()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = ArtifactStore(self.temp.name)
        self.scope = "test-" + uuid.uuid4().hex
        self.old = financial_record(self.artifacts, self.scope)
        self.new = financial_record(self.artifacts, self.scope, available="2025-04-20T10:00:00",
                                    retrieved="2025-04-21T10:00:00", revenue="90")

    def test_migration_idempotency_and_persistence_across_repository_instances(self):
        self.repo.migrate()
        snapshot = self.repo.commit(self.scope, (self.old,))
        reopened = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        self.assertEqual(reopened.read(self.scope, snapshot.snapshot_id), (self.old,))

    def test_append_revision_does_not_rewrite_snapshot(self):
        first = self.repo.commit(self.scope, (self.old,))
        second = self.repo.commit(self.scope, (self.new,), first.snapshot_id)
        self.assertEqual(self.repo.read(self.scope, first.snapshot_id), (self.old,))
        self.assertEqual(len(self.repo.read(self.scope, second.snapshot_id)), 2)

    def test_duplicate_concurrent_commits_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.repo.commit(self.scope, (self.old,)), range(6)))
        self.assertEqual(len({s.snapshot_id for s in results}), 1)
        self.assertEqual(self.repo.read(self.scope, results[0].snapshot_id), (self.old,))

    def test_scope_isolation(self):
        snapshot = self.repo.commit(self.scope, (self.old,))
        with self.assertRaises(PermissionDenied):
            self.repo.read("different-tenant", snapshot.snapshot_id)
        with self.assertRaises(PermissionDenied):
            self.repo.commit("different-tenant", (), snapshot.snapshot_id)

    def test_database_rejects_update_and_delete(self):
        import psycopg
        self.repo.commit(self.scope, (self.old,))
        for statement in ("UPDATE stock_research.records SET provider='tampered' WHERE scope=%s",
                          "DELETE FROM stock_research.records WHERE scope=%s"):
            with self.assertRaises(psycopg.errors.RaiseException):
                with self.repo._connect() as connection:
                    connection.execute(statement, (self.scope,))

    def test_failed_commit_rolls_back_records_and_manifest(self):
        # Database length constraints are not needed: an invalid parent must fail before writes.
        with self.assertRaises(PermissionDenied):
            self.repo.commit(self.scope, (self.old,), "f" * 64)
        with self.repo._connect() as connection:
            count = connection.execute("SELECT count(*) FROM stock_research.records WHERE scope=%s", (self.scope,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_failure_after_insert_rolls_back_transaction(self):
        first = self.repo.commit(self.scope, (self.old,))
        conflicting = replace(self.old, provider="tampered")
        original_id = self.old.record_id
        class Conflict:
            record_id = original_id
            def __getattr__(self, key):
                return getattr(conflicting, key)
        with self.assertRaises(IntegrityError):
            self.repo.commit(self.scope, (self.new, Conflict()), first.snapshot_id)
        with self.repo._connect() as connection:
            count = connection.execute("SELECT count(*) FROM stock_research.records WHERE scope=%s", (self.scope,)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_postgres_to_service_pit_end_to_end(self):
        snapshot = self.repo.commit(self.scope, (self.old, self.new))
        access = AccessContext(self.scope, frozenset({"fixture"}))
        request = DataRequest(SECURITY, Dataset.FINANCIAL_INCOME, date(2024, 12, 31), date(2024, 12, 31))
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, self.repo, self.artifacts)
            context = QueryContext(access, snapshot.snapshot_id, ts("2025-03-21T00:00:00"))
            self.assertEqual(service.query(request, context).records, (self.old,))
            self.assertEqual(service.query(request, replace(context, mode=PITMode.SYSTEM)).records, ())

    def _domain_record(self):
        from test_domains import CAPTURED, synthetic_row, request, response
        from stock_research.domains import DomainDataset
        from stock_research.providers.tushare_domains import TushareDomainProvider
        domain = DomainDataset.ADJUSTMENT
        provider = TushareDomainProvider("synthetic", self.artifacts,
            lambda *_: response(domain, [synthetic_row(domain)]), lambda: CAPTURED)
        return request(domain), provider.fetch(request(domain), self.scope, 5)[0]

    def test_v2_mixed_legacy_domain_snapshot_and_authorized_pit(self):
        from test_domains import CAPTURED
        req, record = self._domain_record()
        first = self.repo.commit(self.scope, (self.old,))
        mixed = self.repo.commit(self.scope, (record,), first.snapshot_id)
        self.repo.migrate()
        reopened = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        self.assertEqual(reopened.read(self.scope, first.snapshot_id), (self.old,))
        self.assertEqual(set(reopened.read(self.scope, mixed.snapshot_id)), {self.old, record})
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, reopened, self.artifacts)
            ctx = QueryContext(AccessContext(self.scope, frozenset({"tushare"})), mixed.snapshot_id, CAPTURED)
            self.assertEqual(service.query(req, ctx).records, (record,))
            self.assertFalse(service.query(req, replace(ctx, access=AccessContext(self.scope, frozenset({"fixture"})))).records)
        with reopened._connect() as conn:
            self.assertEqual(conn.execute("SELECT record_kind FROM stock_research.records WHERE scope=%s AND record_id=%s",
                             (self.scope, record.record_id)).fetchone()[0], "domain_v2")
            self.assertEqual(conn.execute("SELECT max(version) FROM stock_research.schema_versions").fetchone()[0], 2)

    def test_v2_domain_rows_reject_update_delete_and_wrong_scope(self):
        import psycopg
        _, record = self._domain_record()
        snap = self.repo.commit(self.scope, (record,))
        with self.assertRaises(PermissionDenied):
            self.repo.read("other-synthetic-scope", snap.snapshot_id)
        for sql in ("UPDATE stock_research.records SET record_kind='tampered' WHERE scope=%s",
                    "DELETE FROM stock_research.records WHERE scope=%s"):
            with self.assertRaises(psycopg.errors.RaiseException):
                with self.repo._connect() as conn:
                    conn.execute(sql, (self.scope,))

    def test_qualified_release_date_roundtrip_and_pit_attachments(self):
        from test_release_date import at, qualification
        from stock_research.providers.qualified_income import QualifiedCNInfoIncomeProvider
        path, pin = qualification(self.temp.name)
        provider = QualifiedCNInfoIncomeProvider(path, pin, self.artifacts,
            clock=lambda: at("2025-05-01T00:00:00"))
        req = DataRequest(SECURITY, Dataset.FINANCIAL_INCOME, date(2024, 12, 31), date(2024, 12, 31))
        rows = provider.fetch(req, self.scope, 5)
        first = self.repo.commit(self.scope, (rows[0],))
        second = self.repo.commit(self.scope, (rows[1],), first.snapshot_id)
        reopened = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        self.assertEqual(reopened.read(self.scope, first.snapshot_id), (rows[0],))
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, reopened, self.artifacts)
            ctx = QueryContext(AccessContext(self.scope, frozenset({"cninfo"})),
                               second.snapshot_id, at("2025-04-21T00:00:00"))
            self.assertEqual(service.query(req, ctx).records, (rows[1],))
            self.assertFalse(service.query(req, replace(ctx, mode=PITMode.SYSTEM)).records)
            for aid in rows[1].artifact_ids:
                self.assertTrue(service.evidence(req, ctx, rows[1].record_id, aid))
