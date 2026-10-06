"""Synthetic refinement/ledger mechanisms; no live paid calls or financial truth."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase4_p44_refine as refine
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel, finish, tool
from stock_research.model_adapters.chat import ChatResult


class P44RefineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fixture(self.root / "synthetic")
        self.demo = refine.demo
        self.request = self.demo.DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: explicit typed tool actions for the bound mixed route",
        })
        self.deadline = self.demo.utcnow() + timedelta(seconds=240)
        self.case = {"id": "mixed-financial-delegation", "request": self.request.to_dict(),
                     "research_question": self.request.question, "stratum": "complete-financial",
                     "expected_behavior": {"mandatory_fact_names": ["observed_price_change", "revenue_yoy"]}}
        self.item = {"case_id": self.case["id"], "request": self.request.to_dict(),
                     "authorization_envelope": self.demo.old.authorized_envelope(self.f.service, self.f.access, self.request)}
        self.original = {"max_decisions": 28, "max_tokens_accounted": 168000,
                         "model": self.demo.SPEC.model, "endpoint_sha256": self.demo.digest("https://example.invalid/synthetic"),
                         "cases": [deepcopy(self.case), {"id": "dual-domain-delegation"}]}
        self.sources = SimpleNamespace(context=lambda case: (self.f.service, self.f.access),
                                       inputs=lambda case: {"synthetic": "same original bound inputs"})

    def initial_known(self, *, write_directory=None):
        ledger = self.demo.old.RootLedger(28, 168000)
        messages = [{"role": "system", "content": "SYNTHETIC prior known response " + "x" * 5000}]
        for number in range(1, 20):
            task_id = self.case["id"] if number <= 9 else "dual-domain-delegation"
            intent = ledger.reserve(task_id + "/" + self.demo.SPEC.version, messages, self.demo.SPEC.output_tokens)
            amount = 1500 if number <= 18 else 2913
            receipt = ChatResult(self.demo.SPEC.model, self.demo.SPEC.model, self.demo.canonical_json(finish()), "stop",
                                 "synthetic-known-" + str(number), amount - 20, 20, amount, 1)
            ledger.settle(intent, receipt)
            if write_directory is not None:
                prefix = f"{number:02d}-{task_id}"
                self.demo.old.write_new(write_directory / (prefix + "-messages.json"), messages)
                self.demo.old.write_new(write_directory / (prefix + "-receipt.json"), asdict(receipt))
        self.assertEqual(ledger.snapshot()["decisions"], 19)
        self.assertEqual(ledger.snapshot()["known_tokens"], 29913)
        return ledger.snapshot()

    def test_original_unknown_paid_ledger_blocks_before_config_and_live_directory(self):
        original_out, refined_out = self.root / "original", self.root / "refined"
        initial = self.initial_known()
        initial["unknown_usage_calls"] = 1
        self.demo.old.write_new(original_out / "live/summary.json", {"ledger": initial})
        self.demo.old.write_new(refined_out / "plan.json", {"synthetic": "unknown must block"})
        expected_sha = self.demo.old.sha(refined_out / "plan.json")
        with patch.object(self.demo, "OUT", original_out), patch.object(refine, "OUT", refined_out), \
                patch.object(self.demo, "checked", return_value=(self.original, self.sources)), \
                patch.object(self.demo, "load_model_config") as config, patch.object(self.demo, "ChatModelAdapter") as adapter:
            with self.assertRaises(self.demo.IntegrityError):
                refine.live(expected_sha)
            config.assert_not_called()
            adapter.assert_not_called()
        self.assertFalse((refined_out / "live").exists())

    def test_original_known_reconciles_receipts_and_rejects_changed_usage(self):
        original_out = self.root / "original"
        directory = original_out / "live"
        initial = self.initial_known(write_directory=directory)
        summary = {"ledger": initial}
        self.demo.old.write_new(directory / "summary.json", summary)
        for case, decisions, tokens in ((self.original["cases"][0], 9, 13500), (self.original["cases"][1], 10, 16413)):
            self.demo.old.write_new(directory / (case["id"] + "-report.json"),
                                    {"root_budget": {"model_attempts": decisions, "total_tokens": tokens}})
        with patch.object(self.demo, "OUT", original_out), \
                patch.object(self.demo, "checked", return_value=(self.original, self.sources)):
            self.assertEqual(refine.original_known()[2], summary)
            path = directory / "19-dual-domain-delegation-receipt.json"
            changed = self.demo.old.read(path)
            changed["total_tokens"] += 1
            actual_read = self.demo.old.read
            with patch.object(self.demo.old, "read", side_effect=lambda target: changed if Path(target) == path else actual_read(target)):
                with self.assertRaises(self.demo.IntegrityError):
                    refine.original_known()

    def test_expired_original_deadline_blocks_before_config_or_writes(self):
        refined_out = self.root / "expired"
        plan = {"deadline": (self.demo.utcnow() - timedelta(seconds=1)).isoformat()}
        with patch.object(refine, "OUT", refined_out), \
                patch.object(refine, "checked", return_value=(plan, self.original, self.sources)), \
                patch.object(self.demo, "load_model_config") as config, patch.object(self.demo, "ChatModelAdapter") as adapter:
            with self.assertRaisesRegex(self.demo.ValidationError, "deadline expired"):
                refine.live("a" * 64)
            config.assert_not_called()
            adapter.assert_not_called()
        self.assertFalse(refined_out.exists())

    def test_actual_mixed_eight_calls_inherit_nineteen_and_number_twenty_through_twentyseven(self):
        initial = self.initial_known()
        before = deepcopy(initial)
        plan = {"deadline": self.deadline.isoformat(), "initial_ledger": initial,
                "case": self.case, "item": self.item, "original_functional_passed": [False, True]}
        adapter = SequenceModel([tool("financial_child"), tool("financial"), finish(), tool("market"),
                                 tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                                 tool("verification", ["hypotheses"]), finish()])
        adapter.config = SimpleNamespace(model=self.demo.SPEC.model, api_key="synthetic-do-not-retain",
                                         endpoint="https://example.invalid/synthetic")
        refined_out = self.root / "actual-refined"
        refined_out.mkdir()
        with patch.object(refine, "OUT", refined_out), \
                patch.object(refine, "checked", return_value=(plan, self.original, self.sources)), \
                patch.object(self.demo, "load_model_config", return_value=adapter.config), \
                patch.object(self.demo, "ChatModelAdapter", return_value=adapter):
            result = refine.live("b" * 64)
        self.assertEqual(adapter.calls, 8)
        self.assertTrue(result["assessment"]["functional_passed"])
        self.assertTrue(result["assessment"]["routing_passed"])
        self.assertNotIn("passed", result["assessment"])
        cumulative = result["cumulative_ledger"]
        self.assertEqual(cumulative["decisions"], 27)
        self.assertEqual(cumulative["tokens_accounted"], 29913 + 960)
        self.assertEqual(cumulative["known_tokens"], 29913 + 960)
        self.assertEqual(cumulative["unknown_usage_calls"], 0)
        self.assertEqual(cumulative["intents"][:19], before["intents"])
        self.assertEqual([intent["number"] for intent in cumulative["intents"][19:]], list(range(20, 28)))
        self.assertGreater(cumulative["cumulative_tokens_reserved"], before["cumulative_tokens_reserved"])
        self.assertEqual(initial, before)
        self.assertEqual(result["original_functional_passed"], [False, True])
        self.assertFalse(result["unknown_paid_retry"])
        self.assertFalse(result["original_result_overwritten"])
        self.assertEqual(result["deadline"], self.deadline.isoformat())
        directory = refined_out / "live"
        files = sorted(directory.glob("*-messages.json"))
        self.assertEqual([int(path.name.split("-", 1)[0]) for path in files], list(range(20, 28)))
        self.assertEqual([self.demo.old.read(path) for path in files], adapter.messages)
        report = self.demo.old.read(directory / "report.json")
        self.assertEqual(report["root_budget"]["model_attempts"], 8)
        self.assertEqual(report["root_budget"]["total_tokens"], 960)
        checkpoint = self.demo.CheckpointStore(directory / "runs").read(self.f.access.scope, report["run_id"])
        self.assertEqual(checkpoint["deadline"], self.deadline.isoformat())
        for path in directory.glob("*.json"):
            self.assertNotIn(adapter.config.api_key, path.read_text(encoding="utf-8"))

    def test_wrong_external_refinement_sha_blocks_original_checks_and_config(self):
        directory = self.root / "freeze"
        self.demo.old.write_new(directory / "plan.json", {"synthetic": True})
        with patch.object(refine, "OUT", directory), patch.object(refine, "original_known") as original, \
                patch.object(self.demo, "load_model_config") as config:
            with self.assertRaises(self.demo.IntegrityError):
                refine.live("f" * 64)
            original.assert_not_called()
            config.assert_not_called()
        self.assertFalse((directory / "live").exists())


if __name__ == "__main__":
    unittest.main()
