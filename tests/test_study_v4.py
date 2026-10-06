"""Versioned diagnostics/replay mechanisms using clearly synthetic source rows."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from research_fixtures import BundleFixtureModel, FixtureModel, fixture
from study_fixtures import study_request
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import AccessContext
from stock_research.research.cli import run as cli_run
from stock_research.research.context import study_messages
from stock_research.research.scoped import ScopedReadService, SourceGrant
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudySpec
from stock_research.research.tools import read_domain


class StudyV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fixture(self.root)
        self.request = study_request(self.f)
        self.v4 = StudySpec(version="single-research-v4")

    def runtime(self, **kwargs):
        return StudyRuntime(self.f.service, self.f.store, spec=self.v4, **kwargs)

    def datasets(self):
        return {key: value for domain in ("market", "financial")
                for key, value in read_domain(self.f.service, self.request, self.f.access, domain).items()}

    def test_v4_new_identity_retains_v3_numeric_and_hypothesis_payload(self):
        v3 = StudySpec(version="single-research-v3")
        self.assertNotEqual(self.v4.identity, v3.identity)
        self.assertEqual(StudySpec().version, "single-research-v3")
        old = StudyRuntime(self.f.service, self.f.store, spec=v3)._calculate(self.datasets(), self.request)
        new = self.runtime()._calculate(self.datasets(), self.request)
        diagnostics = new.pop("insufficiency_diagnostics")
        self.assertEqual(old, new)
        self.assertTrue(diagnostics)
        self.assertTrue(all(item["status"] == "insufficient" for item in diagnostics))

    def test_v4_resume_recomputes_diagnostics_and_binds_version(self):
        runtime = self.runtime()
        report = runtime.run(self.request, self.f.access)
        self.assertEqual(report["diagnostics_version"], "study-insufficiency-v1")
        self.assertIn("insufficiency_diagnostics", report)
        self.assertEqual(runtime.run(self.request, self.f.access, resume=report["run_id"]), report)
        with self.assertRaises(PermissionDenied):
            StudyRuntime(self.f.service, self.f.store).run(self.request, self.f.access, resume=report["run_id"])

    def test_v4_rejects_report_diagnostics_tampering_even_on_valid_checkpoint_chain(self):
        runtime = self.runtime()
        report = runtime.run(self.request, self.f.access)
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        forged = copy.deepcopy(state)
        forged["report"]["insufficiency_diagnostics"][0]["insufficiency_reasons"][0]["failure_category"] = "research_agent_implementation_defect"
        self.f.store.append(self.f.access.scope, report["run_id"], forged)
        with self.assertRaises(IntegrityError):
            runtime.run(self.request, self.f.access, resume=report["run_id"])

    def test_v4_rejects_unknown_diagnostics_or_report_schema_on_completed_replay(self):
        for field, value in (("diagnostics_version", "unknown-schema-version"),
                             ("schema", "single-overview/v1")):
            with self.subTest(field=field):
                runtime = self.runtime()
                report = runtime.run(self.request, self.f.access)
                forged = self.f.store.read(self.f.access.scope, report["run_id"])
                forged["report"][field] = value
                self.f.store.append(self.f.access.scope, report["run_id"], forged)
                with self.assertRaises(IntegrityError):
                    runtime.run(self.request, self.f.access, resume=report["run_id"])

    def test_v4_stopped_report_cannot_publish_unverified_fabricated_diagnostics(self):
        runtime = self.runtime(cancelled=lambda: True)
        report = runtime.run(self.request, self.f.access)
        self.assertEqual(report["verification"]["status"], "not_completed")
        self.assertEqual(report["hypotheses"], [])
        self.assertEqual(runtime.run(self.request, self.f.access, resume=report["run_id"]), report)
        forged = self.f.store.read(self.f.access.scope, report["run_id"])
        forged["report"]["insufficiency_diagnostics"] = [{
            "hypothesis_id": "financial_deterioration", "status": "insufficient", "insufficiency_reasons": [{
                "code": "positive_base_precondition_failed", "failure_category": "intrinsic_precondition_or_temporal_impossibility",
                "datasets": [], "record_refs": [], "evidence_refs": [], "detail": "synthetic fabricated diagnostic"}]}]
        self.f.store.append(self.f.access.scope, report["run_id"], forged)
        with self.assertRaises(IntegrityError):
            runtime.run(self.request, self.f.access, resume=report["run_id"])

    def test_v4_replay_does_not_bypass_current_source_grant_revocation(self):
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot,
                              self.request.data_request(b), b.provider) for b in self.request.bindings]
        service = ScopedReadService("synthetic-v4-recipient", lambda: tuple(grants))
        access = AccessContext("synthetic-v4-recipient", frozenset({"fixture"}))
        runtime = StudyRuntime(service, self.f.store, spec=self.v4)
        report = runtime.run(self.request, access)
        self.assertIn("insufficiency_diagnostics", report)
        grants.clear()
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, access, resume=report["run_id"])

    def test_v3_and_v4_model_bundles_are_identical_and_diagnostics_remain_local(self):
        old = StudyRuntime(self.f.service, self.f.store)._calculate(self.datasets(), self.request)
        new = self.runtime()._calculate(self.datasets(), self.request)
        old_messages, old_context = study_messages(old, self.request, 12000, version="single-research-v3")
        new_messages, new_context = study_messages(new, self.request, 12000, version="single-research-v4")
        self.assertEqual(old_messages, new_messages)
        self.assertEqual(old_context, new_context)
        self.assertNotIn("insufficiency_diagnostics", json.loads(new_messages[1]["content"]))
        model = BundleFixtureModel()
        report = self.runtime(model=model).run(self.request, self.f.access)
        self.assertEqual(model.calls, 1)
        self.assertEqual(report["model"]["status"], "verified")

    def test_v4_rejects_incomplete_model_bundle_without_upgrading_insufficient(self):
        model = FixtureModel('{"highlights":["F1"],"hypotheses":["financial_deterioration"],"assessment":"descriptive_research_only"}')
        report = self.runtime(model=model).run(self.request, self.f.access)
        self.assertEqual(report["model"]["status"], "rejected_or_failed")
        self.assertTrue(any(h["status"] == "insufficient" for h in report["hypotheses"]))
        self.assertTrue(report["insufficiency_diagnostics"])
        self.assertEqual(model.calls, 1)

    def test_cli_new_research_defaults_v4_and_can_explicitly_pin_legacy_v3(self):
        path = self.root / "request.json"
        path.write_text(json.dumps(self.request.to_dict()), encoding="utf8")
        args = SimpleNamespace(request=str(path), workflow="research", with_model=False,
                               output=str(self.root / "new-cli"), artifacts=[str(self.root / "artifacts")],
                               runs=str(self.root / "cli-runs"), scope=self.f.access.scope,
                               allow_provider=["fixture"], resume=None, preview_model=False)
        cli_run(args, self.f.repo)
        new = json.loads((self.root / "new-cli/report.json").read_bytes())
        self.assertEqual(new["diagnostics_version"], "study-insufficiency-v1")
        self.assertTrue(new["insufficiency_diagnostics"])
        args.output = str(self.root / "old-cli")
        args.study_version = "single-research-v3"
        cli_run(args, self.f.repo)
        old = json.loads((self.root / "old-cli/report.json").read_bytes())
        self.assertNotIn("diagnostics_version", old)
        self.assertNotIn("insufficiency_diagnostics", old)
        self.assertEqual(new["facts"], old["facts"])
        self.assertEqual(new["hypotheses"], old["hypotheses"])


if __name__ == "__main__":
    unittest.main()
