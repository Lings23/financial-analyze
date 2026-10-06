import unittest
from dataclasses import replace
from datetime import date, datetime
from tempfile import TemporaryDirectory

from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository
from stock_research.temporal import select_records
from helpers import SECURITY, financial_record, ts


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = ArtifactStore(self.temp.name)
        self.old = financial_record(self.artifacts)
        self.new = financial_record(self.artifacts, available="2025-04-20T10:00:00",
                                    retrieved="2025-04-21T10:00:00", revenue="90")
        self.request = DataRequest(SECURITY, Dataset.FINANCIAL_INCOME, date(2024, 12, 31), date(2024, 12, 31))
        self.access = AccessContext("tenant-a", frozenset({"fixture"}))
        self.repo = MemoryRepository()
        self.snapshot = self.repo.commit("tenant-a", (self.old, self.new))

    def query(self, cutoff, mode=PITMode.PUBLIC):
        context = QueryContext(self.access, self.snapshot.snapshot_id, ts(cutoff), mode)
        return select_records(self.repo.read("tenant-a", self.snapshot.snapshot_id), self.request, context)

    def test_report_period_does_not_make_unannounced_data_visible(self):
        result = self.query("2025-02-01T00:00:00")
        self.assertEqual(result.status, "no_visible_data")
        self.assertEqual(result.records, ())

    def test_exact_release_boundary_is_inclusive(self):
        self.assertEqual(self.query("2025-03-20T10:00:00").records, (self.old,))
        self.assertEqual(self.query("2025-03-20T09:59:59").records, ())

    def test_revision_is_filtered_before_latest_selection(self):
        self.assertEqual(self.query("2025-04-10T00:00:00").records, (self.old,))
        self.assertEqual(self.query("2025-04-20T10:00:00").records, (self.new,))

    def test_public_and_system_replay_differ(self):
        self.assertEqual(self.query("2025-03-21T00:00:00").records, (self.old,))
        self.assertEqual(self.query("2025-03-21T00:00:00", PITMode.SYSTEM).records, ())
        self.assertEqual(self.query("2025-04-01T10:00:00", PITMode.SYSTEM).records, (self.old,))

    def test_timezone_equivalent_cutoff(self):
        context = QueryContext(self.access, self.snapshot.snapshot_id,
                               datetime.fromisoformat("2025-03-20T18:00:00+08:00"))
        self.assertEqual(select_records((self.old,), self.request, context).records, (self.old,))

    def test_naive_timestamp_and_unknown_mode_rejected(self):
        with self.assertRaises(ValidationError):
            QueryContext(self.access, "id", datetime(2025, 3, 20))
        with self.assertRaises(ValidationError):
            QueryContext(self.access, "id", ts("2025-03-20T00:00:00"), "bypass")

    def test_current_observation_cannot_be_backdated(self):
        with self.assertRaises(ValidationError):
            replace(self.old, availability_basis="observed_at")

    def test_future_observations_and_publication_are_rejected(self):
        with self.assertRaises(ValidationError):
            replace(self.old, period=date(2026, 1, 1))
        with self.assertRaises(ValidationError):
            replace(self.old, announcement_date=date(2026, 1, 1))

    def test_same_time_conflicting_revision_is_not_arbitrarily_selected(self):
        conflict = replace(self.new, available_at=self.old.available_at, published_at=self.old.published_at)
        context = QueryContext(self.access, "id", ts("2025-05-01T00:00:00"))
        with self.assertRaises(IntegrityError):
            select_records((self.old, conflict), self.request, context)

    def test_snapshot_does_not_change_when_revision_arrives(self):
        first = self.repo.commit("tenant-a", (self.old,))
        second = self.repo.commit("tenant-a", (self.new,), first.snapshot_id)
        self.assertEqual(self.repo.read("tenant-a", first.snapshot_id), (self.old,))
        self.assertEqual(len(self.repo.read("tenant-a", second.snapshot_id)), 2)
        self.assertEqual(self.repo.commit("tenant-a", (self.old,)).snapshot_id, first.snapshot_id)

    def test_scope_isolation(self):
        with self.assertRaises(PermissionDenied):
            self.repo.read("tenant-b", self.snapshot.snapshot_id)
        with self.assertRaises(PermissionDenied):
            self.repo.commit("tenant-b", (), self.snapshot.snapshot_id)

    def test_provider_permissions_rechecked_on_read(self):
        context = QueryContext(AccessContext("tenant-a", frozenset({"other"})), self.snapshot.snapshot_id,
                               ts("2025-05-01T00:00:00"))
        self.assertEqual(select_records((self.old,), self.request, context).records, ())

    def test_explicit_security_and_bounded_window(self):
        with self.assertRaises(ValidationError):
            Security("600000", "UNKNOWN")
        with self.assertRaises(ValidationError):
            DataRequest(SECURITY, Dataset.MARKET_DAILY, date(2020, 1, 1), date(2025, 1, 1))

    def test_serialization_preserves_exact_decimal_and_timestamps(self):
        from stock_research.models import DataRecord
        self.assertEqual(DataRecord.from_dict(self.old.to_dict()), self.old)
        self.assertEqual(DataRecord.from_dict(self.old.to_dict()).record_id, self.old.record_id)

    def test_artifact_scope_and_hash(self):
        with self.assertRaises(FileNotFoundError):
            self.artifacts.get("tenant-b", self.old.artifact_id)
        path = self.artifacts._path("tenant-a", self.old.artifact_id)
        path.write_bytes(b"corrupt")
        with self.assertRaises(IntegrityError):
            self.artifacts.get("tenant-a", self.old.artifact_id)
        with self.assertRaises(ValidationError):
            self.artifacts.get("tenant-a", "../../secret")
