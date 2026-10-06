"""Synthetic outbound envelope check; never live financial validation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase4_p43_demo as demo
import phase4_p43_complete as completion
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel
from test_dynamic_children import parent_actions
from stock_research.errors import IntegrityError
from stock_research.models import utcnow
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, FinancialParentSpec


class P43DemoTests(unittest.TestCase):
    def test_every_parent_and_child_dispatch_validates_exact_typed_public_envelope(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            f = fixture(root)
            request = DynamicRequest.from_dict({**study_request(f, hypotheses=("financial_deterioration",)).to_dict(),
                                               "question": "SYNTHETIC: delegated financial read"})
            item = {"case_id": "synthetic", "request": request.to_dict(),
                    "authorization_envelope": demo.old.authorized_envelope(f.service, f.access, request)}
            adapter = SequenceModel(parent_actions())
            adapter.config = SimpleNamespace(model="deepseek-v4-flash-0731", api_key="synthetic-secret-do-not-retain")
            ledger = demo.old.RootLedger(20, 120000)
            model = demo.RecordingModel(adapter, item, FinancialParentSpec(), ledger, root, utcnow() + timedelta(seconds=240))
            model.access = f.access
            report = DynamicRuntime(f.service, f.store, model, FinancialParentSpec()).run(request, f.access)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(ledger.snapshot()["decisions"], 8)
            self.assertEqual(model.role_calls, {"dynamic-parent-financial-v1": 6, "financial-child-v1": 2})
            self.assertEqual(len(list(root.glob("*-messages.json"))), 8)
            self.assertEqual(len(list(root.glob("*-intent.json"))), 8)
            for path in root.glob("*.json"):
                self.assertNotIn(adapter.config.api_key, path.read_text(encoding="utf-8"))

    def test_invalid_role_never_reserves_or_dispatches(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            f = fixture(root)
            request = DynamicRequest.from_dict({**study_request(f, hypotheses=("financial_deterioration",)).to_dict(), "question": "synthetic"})
            adapter = SequenceModel([])
            ledger = demo.old.RootLedger()
            model = demo.RecordingModel(adapter, {"request": request.to_dict()}, FinancialParentSpec(), ledger, root, utcnow() + timedelta(seconds=240))
            messages = [{"role": "system", "content": "bad"}, {"role": "user", "content": json.dumps({"protocol_version": "bad"})}]
            with self.assertRaises(IntegrityError):
                model.complete(messages, max_tokens=1024, timeout=120)
            self.assertEqual(adapter.calls, 0)
            self.assertEqual(ledger.snapshot()["decisions"], 0)

    def test_known_continuation_refuses_unknown_paid_outcome_before_config_or_writes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            live = root / "live"
            live.mkdir()
            demo.old.write_new(live / "serial-financial-child-report.json", {"root_budget": {"model_attempts": 1, "total_tokens": 0}})
            demo.old.write_new(live / "01-ledger.json", {"unknown_usage_calls": 1, "decisions": 1})
            with patch.object(demo, "OUT", root), patch.object(demo, "checked", return_value=({}, None)), \
                    patch.object(demo, "load_model_config") as config, patch.object(demo, "ChatModelAdapter") as adapter:
                with self.assertRaises(IntegrityError):
                    completion.complete()
                config.assert_not_called()
                adapter.assert_not_called()
            self.assertFalse((live / "known-continuation-intent.json").exists())

    def test_assessment_preserves_preregistered_scoring_and_adds_child_check(self):
        with TemporaryDirectory() as temporary:
            f = fixture(Path(temporary))
            request = DynamicRequest.from_dict({**study_request(f, hypotheses=("financial_deterioration",)).to_dict(), "question": "synthetic"})
            report = DynamicRuntime(f.service, f.store, SequenceModel(parent_actions()), FinancialParentSpec()).run(request, f.access)
            case = {"id": "serial-financial-child", "request": request.to_dict(), "research_question": request.question,
                    "stratum": "complete-financial", "expected_behavior": {"mandatory_fact_names": ["observed_price_change"]}}
            result = completion.assessment(case, report)
            self.assertTrue(result["functional_passed"])
            self.assertTrue(result["serial_child_passed"])
            self.assertEqual(result["checks"], demo.old.assess(case, report)["checks"])
