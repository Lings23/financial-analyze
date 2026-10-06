"""Offline repair-envelope QA; scripted replies are not live model validation."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase4_p45_child_repair_demo as demo
from stock_research.errors import IntegrityError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import digest, utcnow
from stock_research.research.dynamic_contracts import FinancialRequest
from stock_research.research.dynamic_protocol import dynamic_messages


class EnvelopeTransport:
    """A fixed action fixture for recording/replay contracts, not repair proof."""
    def __init__(self, config, *, repeated_financial=False):
        self.config, self.repeated_financial = config, repeated_financial
        self.barrier = Barrier(2, timeout=5)
        self.calls = []

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        role, turn = payload["protocol_version"], payload["control"]["decision"]
        domain = demo.ROLE_DOMAINS.get(role)
        self.calls.append((role, turn, deepcopy(messages)))
        if domain:
            if turn == 1:
                self.barrier.wait()
            action = ({"action": "tool", "tool": domain, "refs": [], "plan": ["Fixture read"]}
                      if turn == 1 or domain == "financial" and self.repeated_financial
                      else {"action": "finish", "reason": "completed", "plan": ["Fixture finish"]})
        else:
            action = [
                {"action": "parallel", "tools": ["financial_child", "market_child"], "plan": ["Fixture group"]},
                {"action": "tool", "tool": "calculation", "refs": ["financial", "market"], "plan": ["Fixture calculation"]},
                {"action": "tool", "tool": "hypotheses", "refs": ["calculation"], "plan": ["Fixture hypothesis"]},
                {"action": "tool", "tool": "verification", "refs": ["hypotheses"], "plan": ["Fixture verification"]},
                {"action": "finish", "reason": "completed", "plan": ["Fixture final"]},
            ][turn - 1]
        return ChatResult(self.config.model, self.config.model, json.dumps(action), "stop",
                          f"synthetic-envelope-{role}-{turn}", 100, 20, 120, 1)


class ChildRepairDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = SimpleNamespace(model=demo.SPEC.model,
            endpoint="https://example.invalid/configured-synthetic-test", api_key="synthetic-envelope-credential")
        self.prior = demo.original_plan()
        # Model configuration is a controlled fixture; all financial inputs and
        # original Artifact preservation checks still use the immutable case.
        self.prior["endpoint_sha256"] = digest(self.config.endpoint)
        for item in (patch.object(demo, "OUT", self.directory),
                     patch.object(demo, "original_plan", return_value=self.prior),
                     patch.object(demo, "load_model_config", return_value=self.config)):
            item.start()
            self.addCleanup(item.stop)

    def prepare(self):
        result = demo.prepare()
        return result, demo.original.old.read(self.directory / "plan.json")

    def test_freeze_is_same_case_same_scope_and_caps_with_no_new_independent_sample(self):
        before = demo.original_hashes()
        result, plan = self.prepare()
        self.assertEqual(plan["item"]["request"], self.prior["item"]["request"])
        self.assertEqual(plan["item"]["scope"], self.prior["item"]["scope"])
        self.assertEqual(plan["item"]["authorization_envelope"], self.prior["item"]["authorization_envelope"])
        self.assertEqual(plan["item"]["catalog_observations"], self.prior["item"]["catalog_observations"])
        self.assertNotEqual(plan["item"]["run_id"], self.prior["item"]["run_id"])
        self.assertEqual(plan["independent_new_task_count"], 0)
        self.assertEqual(plan["repair_retest_count"], 1)
        self.assertEqual(plan["original_functional_results"], {"passed": 0, "total": 1})
        self.assertEqual(plan["child_protocol_versions"], {"financial": "financial-child-v2", "market": "market-child-v2"})
        self.assertEqual(plan["root_limits"], {"decisions": 16, "tools": 18, "tokens": 96000})
        self.assertEqual(plan["parent_local_limits"]["max_seconds"], 240)
        for limits in plan["child_local_limits"].values():
            self.assertEqual((limits["max_decisions"], limits["max_tokens"], limits["max_seconds"]), (3, 18000, 120))
        self.assertEqual(plan["context_limit_bytes"], 12000)
        self.assertEqual(result["model_calls"], 0)
        self.assertNotIn(self.config.api_key, json.dumps(plan))
        demo.checked(result["plan_sha256"])
        self.assertEqual(before, demo.original_hashes())

    def test_prepare_is_one_shot_and_never_overwrites_plan(self):
        result, _ = self.prepare()
        with self.assertRaises((IntegrityError, FileExistsError)):
            demo.prepare()
        self.assertEqual(demo.original.old.sha(self.directory / "plan.json"), result["plan_sha256"])

    def test_frozen_request_child_protocol_budget_and_original_denominator_tamper_rejected(self):
        _, plan = self.prepare()
        changes = (
            lambda p: p["item"]["request"].update(question="Changed immutable question"),
            lambda p: p["item"].update(scope="another-recipient"),
            lambda p: p.update(max_decisions=17),
            lambda p: p.update(context_limit_bytes=14000),
            lambda p: p["child_protocol_versions"].update(financial="financial-child-v1"),
            lambda p: p.update(independent_new_task_count=1),
            lambda p: p["original_functional_results"].update(passed=1),
            lambda p: p["item"]["authorization_envelope"].update(provider_network_calls=1),
        )
        for change in changes:
            with self.subTest(change=change):
                modified = deepcopy(plan)
                change(modified)
                (self.directory / "plan.json").write_text(json.dumps(modified), encoding="utf-8")
                with self.assertRaises(IntegrityError):
                    demo.checked(demo.original.old.sha(self.directory / "plan.json"))

    def test_prepare_rejects_endpoint_or_model_substitution_without_dispatch(self):
        for config in (SimpleNamespace(model="another-model", endpoint=self.config.endpoint),
                       SimpleNamespace(model=self.config.model, endpoint="https://example.invalid/another-endpoint")):
            with self.subTest(config=config), patch.object(demo, "load_model_config", return_value=config), \
                    patch.object(demo, "ChatModelAdapter") as adapter:
                with self.assertRaises(IntegrityError):
                    demo.prepare()
                adapter.assert_not_called()
                self.assertFalse((self.directory / "plan.json").exists())

    def intervals(self, second_start="2026-10-05T00:00:01+00:00"):
        intents = []
        for number, role, start in ((1, "financial-child-v2", "2026-10-05T00:00:00+00:00"),
                                    (2, "market-child-v2", second_start)):
            prefix = f"{number:02d}"
            demo.original.old.write_new(self.directory / (prefix + "-dispatch.json"), {"role": role, "started_at": start})
            demo.original.old.write_new(self.directory / (prefix + "-interval.json"), {
                "role": role, "started_at": start, "finished_at": start[:17] + "05+00:00"})
            intents.append({"number": number, "task_id": demo.CASE_ID + "/" + role})
        return intents

    def test_overlap_matches_explicit_v2_domains_and_rejects_interval_identity_tamper(self):
        intents = self.intervals()
        self.assertTrue(demo.dispatch_overlap(self.directory, intents))
        self.assertFalse(demo.dispatch_overlap(self.directory, intents[:1]))
        intents[0]["task_id"] = demo.CASE_ID + "/market-child-v2"
        with self.assertRaises(IntegrityError):
            demo.dispatch_overlap(self.directory, intents)

    def test_sequential_domain_dispatches_do_not_count_as_parallel(self):
        self.assertFalse(demo.dispatch_overlap(self.directory, self.intervals("2026-10-05T00:01:00+00:00")))

    def test_scripted_recording_contract_full_oracle_and_no_model_replay(self):
        before = demo.original_hashes()
        result, _ = self.prepare()
        transport = EnvelopeTransport(self.config)
        with patch.object(demo, "ChatModelAdapter", return_value=transport):
            summary = demo.live(result["plan_sha256"])
        # A complete scripted result proves harness/mechanism shape only.
        self.assertTrue(summary["assessment"]["functional_passed"])
        self.assertTrue(summary["assessment"]["actual_child_model_dispatch_overlap"])
        self.assertEqual(summary["ledger"]["decisions"], 9)
        self.assertEqual(summary["ledger"]["tokens_accounted"], 1080)
        report = demo.original.old.read(self.directory / "live/report.json")
        self.assertEqual((len(report["facts"]), len(report["evidence"])), (7, 12))
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))
        self.assertTrue(all(row["total_context_bytes"] <= 12000 for row in report["context_telemetry"]))
        with patch.object(demo, "ChatModelAdapter", side_effect=AssertionError("replay dispatch")):
            replay = demo.replay(result["plan_sha256"])
        self.assertTrue(replay["replay_same"])
        self.assertEqual(replay["model_calls"], 0)
        self.assertEqual(before, demo.original_hashes())

    def test_scripted_repeated_financial_actions_preserve_new_failure_and_old_zero_of_one(self):
        before = demo.original_hashes()
        result, _ = self.prepare()
        with patch.object(demo, "ChatModelAdapter", return_value=EnvelopeTransport(self.config, repeated_financial=True)):
            summary = demo.live(result["plan_sha256"])
        self.assertFalse(summary["assessment"]["functional_passed"])
        self.assertEqual(summary["original_functional_results"], {"passed": 0, "total": 1})
        self.assertEqual(summary["independent_new_task_count"], 0)
        self.assertEqual(summary["assessment"]["status"], "partial")
        self.assertTrue(demo.replay(result["plan_sha256"])["replay_same"])
        self.assertEqual(before, demo.original_hashes())

    def test_recording_rejects_outbound_state_tamper_before_campaign_or_adapter_dispatch(self):
        _, plan = self.prepare()
        directory = self.directory / "recording"
        directory.mkdir()
        recorder = demo.RecordingModel(self.config, plan, utcnow() + timedelta(seconds=30), directory)
        request = FinancialRequest.from_parent(demo.DynamicRequest.from_dict(plan["item"]["request"]))
        messages, _ = dynamic_messages(request, ["financial"], [], ["read:financial"], [], 12000,
                                       version="financial-child-v2")
        payload = json.loads(messages[1]["content"])
        payload["completed_tools"] = ["financial"]
        messages[1]["content"] = json.dumps(payload)
        with patch.object(recorder.adapter, "complete", side_effect=AssertionError("adapter dispatch")) as adapter:
            with self.assertRaises(IntegrityError):
                recorder.complete(messages, max_tokens=1024, timeout=20)
            adapter.assert_not_called()
        self.assertEqual(recorder.ledger.snapshot()["decisions"], 0)
        self.assertEqual(list(directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
