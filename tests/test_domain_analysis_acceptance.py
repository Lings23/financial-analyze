"""Acceptance bookkeeping fixtures, never live model or financial certification."""
from contextlib import ExitStack, contextmanager
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
import domain_analysis_acceptance as demo
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import canonical_json, digest, utcnow


CONFIG = SimpleNamespace(model=demo.spec_for("direct").model,
    endpoint="https://example.invalid/configured-only", api_key="synthetic-domain-harness-only-key")


class SyntheticActionAdapter:
    """Choose only registered fixture actions; no synthetic values enter sources."""
    def __init__(self, config):
        self.config = config
        self.child_dispatch_barrier = Barrier(2)

    def complete(self, messages, **kwargs):
        from stock_research.research.domain_analysis_protocol import decode_model_view
        payload = json.loads(messages[1]["content"])
        view = decode_model_view(payload["analysis_context"])
        completed = {observation["tool"] for observation in view["observations"]}
        legal = payload["control"]["legal_next_actions"]
        if payload["protocol_version"].endswith("analysis-child-v1"):
            if payload["control"]["decision"] == 1:
                self.child_dispatch_barrier.wait(timeout=10)
            action = legal[0]
        else:
            action = next((action for action in legal if action["action"] == "parallel"
                or action["action"] == "tool" and action["tool"] not in completed
                    and action["tool"].removesuffix("_child").removesuffix("_analysis_tool") not in completed
                or action["action"] == "finish"), None)
            if action is None:
                raise AssertionError("Fixture has no new legal action")
        return ChatResult(self.config.model, self.config.model, canonical_json(action),
            "stop", "synthetic-domain-mechanism", 100, 20, 120, 1)


class UnknownAdapter:
    def __init__(self, config):
        self.config = config

    def complete(self, messages, **kwargs):
        raise TimeoutError("synthetic unknown outcome")


def row(identity, mode, tokens, *, passed=True, unknown=0, repair_of=None):
    return {"case_id": identity, "mode": mode, "run_id": identity + "-" + mode + ("-repair" if repair_of else ""),
        "assessment": {"functional_passed": passed}, "repair_of_run_id": repair_of,
        "token_usage": {"whole_task": {"total_tokens": tokens, "tokens_accounted": tokens,
            "unknown_calls": unknown}}}


class DomainAnalysisAcceptanceTests(unittest.TestCase):
    @contextmanager
    def fixture(self, directory, adapter=SyntheticActionAdapter):
        prior, sources = demo.original_guard()
        prior = deepcopy(prior)
        prior["endpoint_sha256"] = digest(CONFIG.endpoint)
        with ExitStack() as stack:
            stack.enter_context(patch.object(demo, "OUT", Path(directory) / "campaign"))
            stack.enter_context(patch.object(demo, "original_guard", return_value=(prior, sources)))
            stack.enter_context(patch.object(demo, "load_model_config", return_value=CONFIG))
            stack.enter_context(patch.object(demo, "ChatModelAdapter", adapter))
            stack.enter_context(patch.object(demo, "history_hashes", return_value={"historical-evidence": digest("unchanged")}))
            stack.enter_context(patch.object(demo, "validate_gate", return_value=({}, {})))
            stack.enter_context(patch.object(demo, "evidence_ref", return_value={"path": "synthetic-gate.json", "sha256": digest("gate")}))
            yield prior, sources

    def test_freeze_same_goal_sources_oracles_six_fresh_runs_strong_baselines_and_freeze_deadline(self):
        with TemporaryDirectory() as directory, self.fixture(directory) as (prior, _):
            frozen = demo.prepare("offline", "preflight")
            plan, _ = demo.checked(frozen["plan_sha256"])
            self.assertEqual(plan["campaign_limits"], {"max_decisions": 128, "max_tokens_accounted": 768000, "max_seconds": 2400})
            self.assertEqual((plan["maximum_campaign_runs"], plan["scheduled_initial_run_count"], plan["reserved_repair_run_slots"]), (8, 6, 2))
            self.assertEqual(plan["acceptance"]["threshold_percent"], 10)
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertFalse(plan["old_budget_reused"])
            for mode in ("direct", "tool"):
                self.assertEqual((plan["specs"][mode]["local_limits"]["decisions"], plan["specs"][mode]["local_limits"]["tools"]), (8, 12))
            self.assertEqual((plan["specs"]["child"]["local_limits"]["decisions"], plan["specs"]["child"]["local_limits"]["tools"]), (6, 8))
            self.assertEqual(plan["specs"]["child"]["root_limits"], {"decisions": 16, "tools": 18, "tokens": 96000})
            for identity in demo.CASE_IDS:
                items = [item for item in plan["items"] if item["case_id"] == identity]
                for key in ("request", "input_ref", "authorization_envelope", "catalog_observations", "required_check_ids", "expected_outcome"):
                    self.assertTrue(all(item[key] == items[0][key] for item in items))
            self.assertFalse({item["run_id"] for item in plan["items"]} & {item["run_id"] for item in prior["items"]})
            self.assertNotIn(CONFIG.api_key, canonical_json(plan))

    def test_rehashed_plan_cannot_expand_limits_change_metric_order_or_goal(self):
        changes = (lambda plan: plan["campaign_limits"].update(max_decisions=129),
            lambda plan: plan.update(maximum_campaign_runs=9),
            lambda plan: plan["acceptance"].update(threshold_percent=5),
            lambda plan: plan["items"][0]["request"].update(question="changed goal"),
            lambda plan: plan["items"].reverse(),
            lambda plan: plan.update(deadline=(utcnow() + timedelta(seconds=2500)).isoformat()))
        for change in changes:
            with self.subTest(change=change), TemporaryDirectory() as directory, self.fixture(directory):
                demo.prepare("offline", "preflight")
                path = demo.OUT / "plan.json"
                plan = demo.OLD.read(path)
                change(plan)
                path.write_text(canonical_json(plan), encoding="utf-8")
                with self.assertRaises(IntegrityError):
                    demo.checked(demo.OLD.sha(path))

    def test_primary_metric_requires_ten_percent_vs_B_and_stronger_A(self):
        cases = demo.CASE_IDS
        rows = [row(identity, mode, tokens) for identity in cases for mode, tokens in (
            ("direct", 1000), ("tool", 1200), ("child", 950))]
        result = demo.evaluate(rows)
        self.assertTrue(result["equal_complete_accepted_quality"])
        self.assertFalse(result["efficiency_10_percent_candidate_passed"])
        self.assertEqual(result["stronger_valid_A_B_total_tokens"], 2000)
        for item in rows:
            if item["mode"] == "child":
                item["token_usage"]["whole_task"]["total_tokens"] = 900
        self.assertTrue(demo.evaluate(rows)["efficiency_10_percent_candidate_passed"])

    def test_failed_quality_unknown_usage_or_missing_run_cannot_prove_acceleration(self):
        valid = [row(identity, mode, tokens) for identity in demo.CASE_IDS
            for mode, tokens in (("direct", 1000), ("tool", 1000), ("child", 100))]
        for change in (lambda rows: rows[2]["assessment"].update(functional_passed=False),
                       lambda rows: rows[2]["token_usage"]["whole_task"].update(unknown_calls=1),
                       lambda rows: rows.pop()):
            with self.subTest(change=change):
                rows = deepcopy(valid)
                change(rows)
                self.assertFalse(demo.evaluate(rows)["efficiency_10_percent_candidate_passed"])

    def test_repair_tokens_include_original_failure_and_original_denominator(self):
        rows = [row(identity, mode, tokens) for identity in demo.CASE_IDS
            for mode, tokens in (("direct", 1000), ("tool", 1000), ("child", 800))]
        failed = rows[2]
        failed["assessment"]["functional_passed"] = False
        rows.append(row(demo.CASE_IDS[0], "child", 800, repair_of=failed["run_id"]))
        result = demo.evaluate(rows)
        self.assertTrue(result["equal_complete_accepted_quality"])
        self.assertEqual(result["initial_functional_results"], {"passed": 5, "total": 6})
        self.assertEqual(result["repair_functional_results"], {"passed": 1, "total": 1})
        self.assertEqual(result["whole_task_known_total_tokens_by_mode_including_failures_and_repairs"]["child"], 2400)
        self.assertFalse(result["efficiency_10_percent_candidate_passed"])

    def test_offline_gate_requires_current_full_suite_and_historical_zero_append_evidence(self):
        files = {"synthetic.py": digest("fixture")}
        offline = {"status": "passed", "command": "python -m unittest discover -s tests -v", "pythonpath": "src",
            "failures": 0, "errors": 0, "tests_run": 100, "code_files": files}
        probe = {"schema": "domain-analysis-readonly-preflight/v1", "status": "passed", "code_files": files,
            "history_hashes": {"fixture": "same"}, "historical_files_unchanged": True,
            "unique_historical_reports_replayed": 39, "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}
        with patch.object(demo.OLD, "read", side_effect=[offline, probe]), patch.object(demo, "code_files", return_value=files), \
                patch.object(demo, "history_hashes", return_value=probe["history_hashes"]):
            self.assertEqual(demo.validate_gate("offline", "probe"), (offline, probe))
        for field, value in (("errors", 1), ("command", "targeted tests only"), ("tests_run", 0)):
            changed = {**offline, field: value}
            with self.subTest(field=field), patch.object(demo.OLD, "read", side_effect=[changed, probe]), \
                    patch.object(demo, "code_files", return_value=files), patch.object(demo, "history_hashes", return_value=probe["history_hashes"]):
                with self.assertRaises(IntegrityError):
                    demo.validate_gate("offline", "probe")

    def test_paid_token_roles_count_parent_and_both_children_and_unknown_reservation(self):
        roles = [demo.spec_for("child").version, *(spec.version for spec in demo.child_specs().values())]
        intents = [{"task_id": "run/" + role, "usage_status": "known", "prompt_tokens": 100,
            "completion_tokens": 20, "total_tokens": 120, "reservation": 13280} for role in roles]
        totals = demo.token_usage(intents, roles[0])
        self.assertEqual(totals["whole_task"]["total_tokens"], 360)
        self.assertEqual(totals["parent"]["total_tokens"], 120)
        intents[-1].update(usage_status="unknown", total_tokens=None)
        totals = demo.token_usage(intents, roles[0])
        self.assertEqual(totals["whole_task"]["tokens_accounted"], 13520)
        self.assertEqual(totals["whole_task"]["unknown_calls"], 1)

    def test_unknown_transport_retains_intent_reservation_and_blocks_next_paid_call(self):
        spec = demo.spec_for("direct")
        item = {"run_id": "synthetic-run", "case_id": demo.CASE_IDS[0], "mode": "direct"}
        messages = [{"role": "system", "content": "synthetic"}, {"role": "user", "content": "{}"}]
        with TemporaryDirectory() as directory, patch.object(demo, "ChatModelAdapter", UnknownAdapter), \
                patch.object(demo, "validate_outbound", return_value=(spec.version, spec, 1)):
            model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=10), Path(directory))
            model.item = item
            with self.assertRaises(TimeoutError):
                model.complete(messages, max_tokens=1024, timeout=5)
            self.assertTrue(model.terminal_unknown)
            self.assertEqual(model.ledger.accounted, model.ledger.intents[0]["reservation"])
            with self.assertRaises(IntegrityError):
                model.complete(messages, max_tokens=1024, timeout=5)
            self.assertEqual(len(model.ledger.intents), 1)

    def test_actual_stage_metrics_keep_child_local_join_and_full_verifier_separate(self):
        report = {"run_id": "root", "trace": [
            {"event": "domain_join", "domain": "financial", "elapsed_ms": 4,
             "production_calculations": 0, "fraction_verifications": 0, "source_checks": 1, "execution_receipt_checks": 3},
            {"event": "tool_finished", "tool": "verification", "full_fraction_verifications": 1}]}
        child = {"run_id": "financial-child", "trace": [
            {"event": "domain_production", "elapsed_ms": 2, "production_calculations": 2, "fraction_verifications": 0},
            {"event": "domain_review_executed", "elapsed_ms": 3, "production_calculations": 0, "fraction_verifications": 1}]}
        audit = {"root_full_integrity": {"calls": 5, "elapsed_ms": 12}}
        result = demo.stage_metrics(report, [child], audit)
        self.assertEqual(result["domain_production"]["production_calculations"], 2)
        self.assertEqual(result["child_local_review"]["fraction_verifications"], 1)
        self.assertEqual(result["parent_join"]["production_calculations"], 0)
        self.assertEqual(result["parent_join"]["fraction_verifications"], 0)
        self.assertEqual(result["final_verification"]["full_fraction_verifications"], 1)
        self.assertEqual(result["runtime_verifier_audit_metrics"], audit)
        self.assertIsNone(result["parent_composition"]["elapsed_ms"])
        self.assertIsNone(result["parent_composition"]["fraction_verifications"])

    def test_stage_metrics_do_not_infer_zero_join_from_absent_measurement(self):
        result = demo.stage_metrics({"run_id": "root", "trace": []}, [], None)
        self.assertEqual(result["parent_join"]["actual_stage_events"], 0)
        self.assertIsNone(result["parent_join"]["production_calculations"])
        self.assertIsNone(result["parent_join"]["fraction_verifications"])
        self.assertIsNone(result["runtime_verifier_audit_metrics"])

    def test_original_freeze_deadline_prevents_reservation_and_transport(self):
        spec = demo.spec_for("direct")
        messages = [{"role": "system", "content": "fixture"}, {"role": "user", "content": "{}"}]
        with TemporaryDirectory() as directory, patch.object(demo, "ChatModelAdapter", SyntheticActionAdapter), \
                patch.object(demo, "validate_outbound", return_value=(spec.version, spec, 1)):
            model = demo.RecordingModel(CONFIG, utcnow() - timedelta(seconds=1), Path(directory))
            model.item = {"run_id": "expired", "case_id": demo.CASE_IDS[0], "mode": "direct"}
            with patch.object(model.adapter, "complete", side_effect=AssertionError("expired campaign must never dispatch")):
                with self.assertRaises(ValidationError):
                    model.complete(messages, max_tokens=1024, timeout=5)
            self.assertEqual(model.ledger.snapshot()["decisions"], 0)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
