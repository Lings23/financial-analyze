"""Synthetic metric mechanisms only; no financial truth or live validation."""
from copy import deepcopy
import unittest

from stock_research.errors import ValidationError
from stock_research.research.trace_evaluation import evaluate_traces, SAFETY_CHECKS


def row(case="case-a", route="direct", *, success=True, kind="new_validation", run_id=None):
    identity = run_id or case + "-" + route
    return {"case_id": case, "route": route, "run_id": identity, "sample_kind": kind,
            "report": {"run_id": identity, "status": "completed" if success else "partial",
                       "required_checks": [{"id": "read:financial", "status": "passed"},
                                           {"id": "verification", "status": "passed" if success else "not_completed"}],
                       "usage": {"total_tokens": 100, "tokens_accounted": 100,
                                 "tokens_reserved": 500, "model_attempts": 2,
                                 "tool_calls": 1, "unknown_usage_calls": 0},
                       "context_telemetry": [{"run_id": identity, "turn_id": turn,
                            "total_context_bytes": 5000, "context_limit_bytes": 12000,
                            "context_budget_exceeded": False, "model_dispatched": True} for turn in (1, 2)]},
            "summary": {"success": success, "wall_ms": 1000,
                        "expected_status": "completed",
                        "expected_required_checks": [{"id": "read:financial", "status": "passed"},
                                                     {"id": "verification", "status": "passed"}],
                        "safety_checks": {name: "passed" for name in SAFETY_CHECKS}}}


class TraceEvaluationTests(unittest.TestCase):
    def test_denominators_count_cases_and_runs_separately_and_exclude_old_repair_synthetic(self):
        inputs = [row(case, route) for case in ("a", "b", "c") for route in ("direct", "serial", "parallel")]
        inputs += [row("old", "parallel", success=False, kind="historical"),
                   row("old", "parallel", kind="retest", run_id="repaired-old"),
                   row("mechanism", kind="synthetic")]
        inputs.append(deepcopy(inputs[0]))
        result = evaluate_traces(inputs)
        self.assertEqual(result["denominators"], {"independent_new_task_count": 3,
            "new_run_count": 9, "all_unique_run_count": 12, "duplicate_rows_ignored": 1,
            "excluded_run_counts": {"historical": 1, "repair": 1, "synthetic": 1}})
        for route in result["routes"].values():
            self.assertEqual(route["independent_task_count"], 3)
            self.assertEqual(route["run_count"], 3)
            self.assertEqual(route["success"]["rate"], 1)
        self.assertFalse(next(r for r in result["excluded_runs"] if r["sample_kind"] == "historical")["success"])

    def test_unknown_usage_is_not_zero_and_known_receipts_are_subtotal(self):
        first, missing = row("a"), row("b")
        first["report"]["usage"].update(total_tokens=10, tokens_accounted=510, unknown_usage_calls=1)
        missing["report"].pop("usage")
        result = evaluate_traces([first, missing])
        usage = result["routes"]["direct"]["root_usage"]
        self.assertEqual(usage["known_receipt_tokens"]["known_subtotal"], 10)
        self.assertIsNone(usage["known_receipt_tokens"]["total"])
        self.assertEqual(usage["tokens_accounted"]["known_subtotal"], 510)
        self.assertIsNone(usage["tokens_accounted"]["total"])
        self.assertEqual(usage["unknown_usage_calls"]["unknown_count"], 1)
        self.assertIsNone(result["runs"][0]["root_usage"]["complete_receipt_tokens"])
        self.assertEqual(result["runs"][0]["root_usage"]["tokens_reserved"], 500)

    def test_root_ledger_already_includes_children_and_reservations_are_separate(self):
        input_row = row(route="parallel")
        input_row["report"]["child_results"] = [{"child_run_id": "financial-child", "domain": "financial", "usage": {"total_tokens": 200}}]
        input_row["report"]["root_budget"] = {"total_tokens": 300, "tokens_accounted": 700,
             "tokens_reserved": 1500, "tokens_dispatched_reserved": 900,
             "model_attempts": 4, "tool_attempts": 3, "unknown_usage_calls": 1,
             "unresolved_child_allocations": 1}
        result = evaluate_traces([input_row])["runs"][0]["root_usage"]
        self.assertEqual(result["known_receipt_tokens"], 300)
        self.assertEqual(result["tokens_accounted"], 700)
        self.assertEqual(result["tokens_reserved"], 1500)
        self.assertEqual(result["tokens_dispatched_reserved"], 900)
        self.assertEqual(result["unresolved_child_allocations"], 1)
        self.assertIsNone(result["complete_receipt_tokens"])

    def test_direct_without_root_uses_parent_usage_and_does_not_invent_child_use(self):
        usage = evaluate_traces([row()])["runs"][0]["root_usage"]
        self.assertEqual(usage["origin"], "parent_no_child")
        self.assertEqual(usage["known_receipt_tokens"], 100)
        self.assertEqual(usage["tool_attempts"], 1)
        self.assertEqual(usage["unresolved_child_allocations"], 0)
        self.assertEqual(usage["tokens_dispatched_reserved"], 500)

    def test_missing_root_with_child_cannot_use_parent_as_root(self):
        input_row = row(route="serial")
        input_row["report"]["child_results"] = [{"child_run_id": "child"}]
        usage = evaluate_traces([input_row])["runs"][0]["root_usage"]
        self.assertEqual(usage["origin"], "missing_root_with_children")
        self.assertIsNone(usage["tokens_accounted"])
        self.assertIsNone(usage["unknown_usage_calls"])

    def test_pairing_preserves_failures_and_unknown_cost_delta(self):
        direct, parallel = row(), row(route="parallel", success=False)
        parallel["summary"]["wall_ms"] = 500
        parallel["report"]["usage"].update(unknown_usage_calls=1, tokens_accounted=550, total_tokens=50)
        result = evaluate_traces([direct, parallel])
        pair = result["paired_cases"][0]
        self.assertTrue(pair["left_success"])
        self.assertFalse(pair["right_success"])
        self.assertFalse(pair["both_successful"])
        self.assertEqual(pair["deltas"]["wall_ms"], -500)
        self.assertEqual(pair["deltas"]["tokens_accounted"], 450)
        self.assertIsNone(pair["deltas"]["complete_receipt_tokens"])
        self.assertEqual(pair["deltas"]["required_check_completion"], -.5)
        self.assertEqual(result["routes"]["parallel"]["success"]["denominator"], 1)
        self.assertEqual(result["routes"]["parallel"]["success"]["rate"], 0)

    def test_percentiles_are_small_sample_descriptions_with_unknown_count(self):
        rows = [row(case) for case in ("a", "b", "c")]
        for value, sample in zip((10, 50, None), rows):
            sample["summary"]["wall_ms"] = value
        measured = evaluate_traces(rows)["routes"]["direct"]["wall_ms"]
        self.assertEqual(measured["p50"], 10)
        self.assertEqual(measured["p95"], 50)
        self.assertEqual(measured["sample_count"], 2)
        self.assertEqual(measured["unknown_count"], 1)
        self.assertIsNone(measured["total"])
        self.assertTrue(measured["small_sample"])
        self.assertTrue(measured["descriptive_only"])
        self.assertEqual(measured["percentile_method"], "nearest_rank")

    def test_missing_safety_and_not_assessable_are_never_passed(self):
        input_row = row()
        input_row["summary"]["safety_checks"] = {"authorization": "failed", "lineage": "not_assessable"}
        safety = evaluate_traces([input_row])["routes"]["direct"]["safety"]
        self.assertEqual(safety["observed_validation_failures"], 1)
        self.assertEqual(safety["unknown_checks"], 3)
        self.assertEqual(safety["not_assessable_checks"], 1)
        self.assertEqual(safety["checks"]["point_in_time"]["passed"], 0)
        self.assertEqual(safety["checks"]["lineage"]["not_assessable"], 1)

    def test_missing_success_does_not_promote_model_finish_to_validated_success(self):
        input_row = row()
        input_row["summary"].pop("success")
        success = evaluate_traces([input_row])["routes"]["direct"]["success"]
        self.assertEqual(success["unknown"], 1)
        self.assertIsNone(success["rate"])

    def test_incomplete_required_checks_reject_claimed_success(self):
        input_row = row()
        input_row["report"]["required_checks"][1]["status"] = "not_completed"
        result = evaluate_traces([input_row])["runs"][0]
        self.assertFalse(result["success"])
        self.assertTrue(result["success_inconsistent"])
        self.assertEqual(result["required_checks"]["completion_rate"], .5)

    def test_context_collects_parent_and_actual_child_without_double_counting(self):
        input_row = row(route="parallel")
        input_row["report"]["child_results"] = [{"child_run_id": "child", "domain": "financial", "usage": {"model_attempts": 1}}]
        measurement = {"run_id": "child", "turn_id": 1, "total_context_bytes": 12001,
                       "context_limit_bytes": 12000, "context_budget_exceeded": True, "model_dispatched": False}
        input_row["child_reports"] = [{"run_id": "child", "context_telemetry": [measurement]}]
        input_row["summary"]["child_context_telemetry"] = [deepcopy(measurement)]
        measured = evaluate_traces([input_row])["runs"][0]["context"]
        self.assertEqual(measured["measured_turns"], 3)
        self.assertEqual(measured["maximum_bytes"], 12001)
        self.assertEqual(measured["overflow_turns"], 1)
        self.assertEqual(measured["dispatched_over_limit_turns"], 0)
        self.assertEqual(measured["fixed_limit_bytes"], 12000)
        self.assertTrue(measured["measurement_complete"])

    def test_missing_child_context_and_missing_context_are_explicit_unknowns(self):
        input_row = row(route="serial")
        input_row["report"]["child_results"] = [{"child_run_id": "child"}]
        context = evaluate_traces([input_row])["runs"][0]["context"]
        self.assertFalse(context["measurement_complete"])
        self.assertEqual(context["missing_run_ids"], ["child"])
        input_row["report"].pop("context_telemetry")
        context = evaluate_traces([input_row])["runs"][0]["context"]
        self.assertIsNone(context["overflow_turns"])
        self.assertIsNone(context["maximum_bytes"])

    def test_legitimate_insufficient_requires_frozen_outcome_and_completed_execution(self):
        input_row = row()
        checks = [{"id": name, "status": "passed"} for name in
                  ("read:financial", "read:market", "calculation", "hypotheses", "verification")]
        checks.append({"id": "hypothesis:financial_deterioration", "status": "insufficient"})
        input_row["report"].update(status="insufficient", required_checks=checks)
        input_row["summary"].update(expected_status="insufficient", expected_required_checks=deepcopy(checks))
        result = evaluate_traces([input_row])
        self.assertTrue(result["runs"][0]["success"])
        self.assertTrue(result["runs"][0]["frozen_outcome_oracle_match"])
        metrics = result["routes"]["direct"]["required_checks"]
        self.assertEqual(metrics["execution_passed"], 5)
        self.assertEqual(metrics["execution_required"], 5)
        self.assertEqual(metrics["execution_completion_rate"], 1)
        self.assertEqual(metrics["executed"], 6)
        self.assertEqual(metrics["evaluated_completion_rate"], 1)
        self.assertEqual(metrics["fully_decisive_completion_rate"], 5 / 6)
        input_row["summary"].pop("expected_status")
        input_row["summary"].pop("expected_required_checks")
        self.assertIsNone(evaluate_traces([input_row])["runs"][0]["success"])

    def test_insufficient_cannot_excuse_nonexecuted_required_check_or_replace_oracle(self):
        input_row = row()
        input_row["report"].update(status="insufficient")
        self.assertFalse(evaluate_traces([input_row])["runs"][0]["success"])
        input_row["summary"]["expected_status"] = "insufficient"
        input_row["summary"]["expected_required_checks"][0]["status"] = "insufficient"
        with self.assertRaises(ValidationError):
            evaluate_traces([input_row])

    def test_context_run_coverage_does_not_hide_missing_paid_turns(self):
        input_row = row()
        input_row["report"]["context_telemetry"].pop()
        context = evaluate_traces([input_row])["runs"][0]["context"]
        self.assertEqual(context["missing_run_ids"], [])
        self.assertEqual(context["missing_attempt_turn_counts"], {input_row["run_id"]: 1})
        self.assertFalse(context["measurement_complete"])
        input_row["report"]["context_telemetry"][0]["turn_id"] = 0
        with self.assertRaises(ValidationError):
            evaluate_traces([input_row])

    def test_context_foreign_child_measurements_are_rejected(self):
        input_row = row()
        input_row["summary"]["child_context_telemetry"] = [
            {**input_row["report"]["context_telemetry"][0], "run_id": "unbound-child"}]
        with self.assertRaises(ValidationError):
            evaluate_traces([input_row])

    def test_context_missing_dispatch_flag_keeps_measurement_unknown(self):
        input_row = row()
        input_row["report"]["context_telemetry"][0].pop("model_dispatched")
        context = evaluate_traces([input_row])["runs"][0]["context"]
        self.assertEqual(context["unknown_measurements"], 1)
        self.assertEqual(context["maximum_bytes"], 5000)
        self.assertFalse(context["measurement_complete"])

    def test_extra_paid_dispatch_is_inconsistent_but_unpaid_overflow_remains_measured(self):
        input_row = row()
        extra = {**input_row["report"]["context_telemetry"][0], "turn_id": 3}
        input_row["report"]["context_telemetry"].append(extra)
        context = evaluate_traces([input_row])["runs"][0]["context"]
        self.assertEqual(context["dispatch_attempt_inconsistencies"], 1)
        self.assertFalse(context["measurement_complete"])
        extra.update(model_dispatched=False, total_context_bytes=12001, context_budget_exceeded=True)
        context = evaluate_traces([input_row])["runs"][0]["context"]
        self.assertEqual(context["dispatch_attempt_inconsistencies"], 0)
        self.assertEqual(context["overflow_turns"], 1)
        self.assertTrue(context["measurement_complete"])

    def test_parallel_section_and_children_measurements_use_actual_telemetry(self):
        input_row = row(route="parallel", success=False)
        input_row["report"]["parallel_groups"] = [{"telemetry": {"wall_clock_ms": 800,
            "branches": [{"domain": "financial", "child_run_id": "f", "execution_ms": 700},
                         {"domain": "market", "child_run_id": "m", "execution_ms": None}]}}]
        route = evaluate_traces([input_row])["routes"]["parallel"]
        self.assertEqual(route["parallel_section_ms"]["total"], 800)
        self.assertEqual(route["child_execution_ms"]["known_subtotal"], 700)
        self.assertIsNone(route["child_execution_ms"]["total"])
        self.assertEqual(route["child_execution_ms"]["unknown_count"], 1)

    def test_no_composite_quality_financial_truth_superiority_or_tuning_claim(self):
        result = evaluate_traces([row()])
        limits = result["assessment_limits"]
        self.assertEqual(limits["financial_ground_truth"], "not_assessed")
        self.assertEqual(limits["composite_quality_score"], "not_defined")
        self.assertEqual(limits["statistical_route_superiority"], "not_established")
        self.assertEqual(limits["threshold_tuning"], "not_performed")
        self.assertEqual(limits["context_limit_bytes"], 12000)
        self.assertNotIn("quality_score", result)

    def test_evaluation_is_pure_deterministic_and_preserves_state(self):
        inputs = [row("b", "parallel", success=False), row("a")]
        original = deepcopy(inputs)
        result = evaluate_traces(inputs)
        self.assertEqual(inputs, original)
        self.assertEqual(evaluate_traces(list(reversed(inputs))), result)
        result["runs"][0]["safety_checks"]["authorization"] = "failed"
        self.assertEqual(inputs, original)

    def test_same_case_new_rerun_and_conflicting_replay_cannot_hide_failure(self):
        first, retry = row(success=False), row(run_id="retry")
        with self.assertRaises(ValidationError):
            evaluate_traces([first, retry])
        conflict = deepcopy(first)
        conflict["summary"]["wall_ms"] = 1
        with self.assertRaises(ValidationError):
            evaluate_traces([first, conflict])
        retry["sample_kind"] = "retest"
        result = evaluate_traces([first, retry])
        self.assertEqual(result["routes"]["direct"]["success"]["rate"], 0)
        self.assertEqual(result["denominators"]["independent_new_task_count"], 1)

    def test_historical_lawful_insufficient_preserves_original_score_without_new_oracle(self):
        input_row = row(kind="historical")
        input_row["report"]["status"] = "insufficient"
        input_row["report"]["required_checks"].append({"id": "hypothesis:legacy", "status": "insufficient"})
        input_row["summary"].pop("expected_status")
        input_row["summary"].pop("expected_required_checks")
        result = evaluate_traces([input_row])
        history = result["excluded_runs"][0]
        self.assertTrue(history["success"])
        self.assertTrue(history["observed_validation_success"])
        self.assertIsNone(history["frozen_outcome_oracle_match"])
        self.assertEqual(history["assessment_scope"], "historical_or_mechanism_observation_only")
        self.assertEqual(result["denominators"]["independent_new_task_count"], 0)
        self.assertEqual(result["routes"]["direct"]["success"]["denominator"], 0)


if __name__ == "__main__":
    unittest.main()
