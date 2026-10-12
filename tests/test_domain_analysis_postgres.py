"""Dedicated isolated database mechanisms; synthetic data, no Provider truth."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid

from research_fixtures import fixture
from study_fixtures import study_request
from test_domain_analysis_runtime import AnalysisModel
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest
from stock_research.research.domain_analysis_contracts import DomainAnalysisParentSpec
from stock_research.storage.postgres import PostgresRepository


@unittest.skipUnless(os.environ.get("STOCK_RESEARCH_TEST_DSN"), "dedicated PostgreSQL test DSN not configured")
class DomainAnalysisPostgresTests(unittest.TestCase):
    def exercise(self, mode):
        repo = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        repo.migrate()
        with TemporaryDirectory() as directory:
            f = fixture(Path(directory), repo=repo, scope="analysis-test-" + uuid.uuid4().hex)
            request = DynamicRequest.from_dict({**study_request(f, hypotheses=("financial_deterioration",)).to_dict(),
                                               "question": "SYNTHETIC: frozen Financial and Market analysis"})
            spec = DomainAnalysisParentSpec(mode=mode)
            report = DynamicRuntime(f.service, f.store, AnalysisModel(), spec).run(request, f.access)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["verification"]["status"], "verified")
            f.service.repository = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
            model = AnalysisModel()
            runtime = DynamicRuntime(f.service, CheckpointStore(f.store.root), model, spec)
            rows = len(f.store.history(f.access.scope, report["run_id"]))
            self.assertEqual(runtime.run(request, f.access, resume=report["run_id"]), report)
            self.assertEqual(model.counts, {})
            self.assertEqual(len(f.store.history(f.access.scope, report["run_id"])), rows)
            with self.assertRaises(PermissionDenied):
                runtime.run(request, AccessContext(f.access.scope, frozenset({"revoked"})), resume=report["run_id"])

    def test_parallel_children_persist_authorize_and_replay(self):
        self.exercise("child")

    def test_composite_domain_tools_persist_authorize_and_replay(self):
        self.exercise("tool")


if __name__ == "__main__":
    unittest.main()
