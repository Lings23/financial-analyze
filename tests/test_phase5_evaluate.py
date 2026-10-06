"""Offline Phase 5 harness mechanisms; synthetic model actions are not truth."""
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
import phase5_evaluate as demo
from stock_research.errors import IntegrityError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic_contracts import DynamicRequest


CONFIG = SimpleNamespace(model=demo.SPECS["direct"].model,
                         endpoint="https://example.invalid/configured-only", api_key="synthetic-only-test-key")


class SyntheticActionAdapter:
    """Deterministic schema fixture, never a real model or quality result."""
    def __init__(self, config):
        self.config = config
        self.parallel = False
        self.child_dispatch_barrier = Barrier(2)

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        role = payload["protocol_version"]
        if role.endswith("child-v3"):
            if self.parallel:
                # Both real worker calls must enter the synthetic adapter before
                # either returns; this proves scheduling overlap deterministically.
                self.child_dispatch_barrier.wait(timeout=10)
            action = payload["child_progress"]["legal_next_actions"][0]
        else:
            completed = set(payload["completed_tools"])
            plan = ["读取来源并执行全部核验。"]
            if role == demo.SPECS["parallel"].version and not completed:
                self.parallel = True
                action = {"action": "parallel", "tools": ["financial_child", "market_child"], "plan": plan}
            else:
                delegated = "financial_child" in payload["available_tools"]
                tool = next((name for name in ("financial", "market", "calculation", "hypotheses", "verification")
                             if name not in completed), None)
                if tool is None:
                    # Source-known controlled insufficiency is exercised as a mechanism.
                    reason = "insufficient" if "688184" in payload["context"]["range"]["security"] else "completed"
                    action = {"action": "finish", "reason": reason, "plan": plan}
                else:
                    refs = [] if tool in {"financial", "market"} else ["financial", "market"] if tool == "calculation" else [
                        "calculation" if tool == "hypotheses" else "hypotheses"]
                    action = {"action": "tool", "tool": tool + "_child" if delegated and tool in {"financial", "market"} else tool,
                              "refs": refs, "plan": plan}
        return ChatResult(self.config.model, self.config.model, json.dumps(action, ensure_ascii=False),
                          "stop", "synthetic-mechanism", 100, 20, 120, 1)


class Phase5EvaluationTests(unittest.TestCase):
    def prepare_fixture(self, directory):
        with patch.object(demo, "OUT", Path(directory) / "campaign"), \
                patch.object(demo, "load_model_config", return_value=CONFIG):
            result = demo.prepare()
            plan, _ = demo.checked(result["plan_sha256"])
            return result, plan

    def test_plan_freezes_three_known_validation_tasks_nine_rotated_runs_and_legacy_hashes(self):
        with TemporaryDirectory() as directory:
            result, plan = self.prepare_fixture(directory)
            self.assertEqual((result["model_calls"], result["financial_provider_network_calls"]), (0, 0))
            self.assertEqual(len(plan["cases"]), 3)
            self.assertEqual(len(plan["items"]), 9)
            self.assertEqual(plan["independent_test_task_count"], 0)
            self.assertFalse(plan["blind"])
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertEqual(plan["campaign_limits"], {"max_decisions": 120, "max_tokens_accounted": 720000, "max_seconds": 2400})
            self.assertEqual([i["route"] for i in plan["items"]],
                             ["direct", "serial", "parallel", "serial", "parallel", "direct", "parallel", "direct", "serial"])
            self.assertEqual(len(plan["historical_index"]["historical_trace_catalog"]), 9)
            self.assertNotIn(CONFIG.api_key, json.dumps(plan))
            for case in plan["cases"]:
                self.assertEqual({b["dataset"] for b in case["request"]["bindings"]}, {"financial_income", "market_daily"})
                self.assertTrue(case["novelty"]["underlying_sources_known_validation"])
            self.assertEqual(plan["expected_statuses"], {"p5-603207": "completed", "p5-920110": "completed", "p5-688184": "insufficient"})
            self.assertEqual(plan["specs"]["direct"]["root_limits"], {"decisions": 8, "tools": 12, "tokens": 48000})
            self.assertFalse(plan["decision_rule"]["default_changed"])

    def test_plan_and_oracle_tamper_rejected_before_any_dispatch(self):
        with TemporaryDirectory() as directory:
            result, plan = self.prepare_fixture(directory)
            path = Path(directory) / "campaign/plan.json"
            plan["items"][0]["expected_outcome"]["status"] = "insufficient"
            path.write_text(json.dumps(plan), encoding="utf-8")
            with patch.object(demo, "OUT", path.parent), self.assertRaises(IntegrityError):
                demo.checked(demo.old.sha(path))

    def test_route_directives_match_exact_schema_and_v1_defaults_stay_legacy(self):
        self.assertIn("refs", demo.COMMON_DIRECTIVE)
        self.assertNotIn("references", demo.COMMON_DIRECTIVE)
        self.assertNotIn("focus_claim_ids", demo.COMMON_DIRECTIVE)
        self.assertIn("1至5", demo.COMMON_DIRECTIVE)
        self.assertEqual(demo.repair_v3.original.FinancialChildSpec().version, "financial-child-v1")
        self.assertEqual(demo.repair_v3.original.MarketChildSpec().version, "market-child-v1")
        self.assertEqual({s.version for s in demo.CHILD_SPECS.values()}, {"financial-child-v3", "market-child-v3"})

    def test_exact_outbound_reconstruction_rejects_question_permission_and_context_tamper(self):
        sources = demo.CampaignSources()
        item = demo.frozen_item(demo.build_cases()[0], "direct", sources)
        demo.validate_outbound(item["messages"], item, {"max_tokens": 1024})
        for field in ("question", "available_tools", "required_checks"):
            messages = deepcopy(item["messages"])
            payload = json.loads(messages[1]["content"])
            if field == "question":
                payload["control"][field] = "altered immutable question"
            elif field == "available_tools":
                payload[field].append("financial_child")
            else:
                payload["context"][field] = []
            messages[1]["content"] = demo.canonical_json(payload)
            with self.assertRaises((IntegrityError, demo.ValidationError)):
                demo.validate_outbound(messages, item, {"max_tokens": 1024})

    def test_unknown_paid_outcome_is_durable_accounted_once_and_never_resent(self):
        sources = demo.CampaignSources()
        item = demo.frozen_item(demo.build_cases()[0], "direct", sources)
        class UnknownAdapter:
            def complete(self, *args, **kwargs):
                raise OSError("synthetic outage")
        with TemporaryDirectory() as directory, patch.object(demo, "ChatModelAdapter", return_value=UnknownAdapter()):
            model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=30), directory)
            model.item = item
            with self.assertRaises(OSError):
                model.complete(item["messages"], max_tokens=1024, timeout=30)
            ledger = model.ledger.snapshot()
            self.assertEqual(ledger["unknown_usage_calls"], 1)
            self.assertEqual(ledger["tokens_accounted"], ledger["intents"][0]["reservation"])
            self.assertEqual(demo.validate_receipts(directory, ledger, [item])["unknown_usage_calls"], 1)
            with self.assertRaises(IntegrityError):
                model.complete(item["messages"], max_tokens=1024, timeout=30)
            self.assertEqual(model.ledger.snapshot()["decisions"], 1)

    def test_synthetic_actions_exercise_all_nine_frozen_runtime_paths_without_network(self):
        sources, cases = demo.CampaignSources(), demo.build_cases()
        for case in cases:
            for route in demo.ROUTES:
                with self.subTest(case=case["id"], route=route), TemporaryDirectory() as directory, \
                        patch.object(demo, "ChatModelAdapter", SyntheticActionAdapter):
                    root = Path(directory)
                    dispatch = root / "dispatch"
                    dispatch.mkdir()
                    item = demo.frozen_item(case, route, sources)
                    model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=60), dispatch)
                    model.item = item
                    service, access = sources.context(case)
                    report = demo.runtime(service, CheckpointStore(root / "runs"), route, model,
                        inherited_deadline=model.deadline).run(DynamicRequest.from_dict(item["request"]), access, run_id=item["run_id"])
                    intents = model.ledger.snapshot()["intents"]
                    assessed = demo.assess(item, report, dispatch, intents)
                    self.assertTrue(assessed["functional_passed"], assessed)
                    child_reports = demo.children_from_checkpoints(root, item, report)
                    paid = demo.validate_paid_telemetry(item, report, child_reports, dispatch, intents)
                    self.assertEqual(paid["bound_paid_turns"], len(intents))
                    self.assertTrue(all(value == "passed" for value in demo.safety_checks(item, report, sources, assessed).values()))
                    self.assertEqual(demo.validate_receipts(dispatch, model.ledger.snapshot(), [item])["unknown_usage_calls"], 0)
                    before = demo.file_hashes(root)
                    restored = demo.runtime(service, CheckpointStore(root / "runs"), route, demo.NoNetwork()).run(
                        DynamicRequest.from_dict(item["request"]), access, resume=item["run_id"])
                    self.assertEqual(restored, report)
                    self.assertEqual(before, demo.file_hashes(root))
                    tampered = deepcopy(report)
                    next(iter(tampered["evidence"].values()))["tool_call_id"] = "unbound-call"
                    self.assertEqual(demo.safety_checks(item, tampered, sources, assessed)["lineage"], "failed")
                    tampered = deepcopy(report)
                    tampered["context_telemetry"][0]["total_context_bytes"] += 1
                    with self.assertRaises(IntegrityError):
                        demo.validate_paid_telemetry(item, tampered, child_reports, dispatch, intents)


if __name__ == "__main__":
    unittest.main()
