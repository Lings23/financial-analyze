"""Isolated PostgreSQL integration; synthetic facts are not provider validation."""
import os
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from research_fixtures import fixture
from study_fixtures import with_event
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.study import StudyRuntime
from stock_research.storage.postgres import PostgresRepository


@unittest.skipUnless(os.environ.get("STOCK_RESEARCH_TEST_DSN"), "dedicated PostgreSQL test DSN not configured")
class StudyPostgresTests(unittest.TestCase):
    def test_date_anchor_persistence_reopened_report_and_revoked_scope(self):
        repo = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        repo.migrate()
        with TemporaryDirectory() as directory:
            f = fixture(Path(directory), repo=repo, scope="phase3-test-"+uuid.uuid4().hex)
            request, record = with_event(f, date_only=True)
            report = StudyRuntime(f.service, f.store).run(request, f.access)
            f.service.repository = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
            runtime = StudyRuntime(f.service, CheckpointStore(f.store.root))
            self.assertEqual(runtime.run(request, f.access, resume=report["run_id"]), report)
            self.assertEqual(report["event_anchor"]["record_id"], record.record_id)
            self.assertEqual(report["verification"]["status"], "verified")
            with self.assertRaises(PermissionDenied):
                runtime.run(request, AccessContext("wrong-scope", frozenset({"fixture"})))
