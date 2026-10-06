"""Offline Phase 6 harness mechanisms; scripted choices are not model quality."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
import time
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase6_evaluate as demo
from stock_research.errors import IntegrityError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import canonical_json, digest, utcnow


CONFIG = SimpleNamespace(model=demo.spec_for("baseline").model,
    endpoint="https://example.invalid/configured-only", api_key="synthetic-phase6-only-key")


class SyntheticAdapter:
    def __init__(self, config):
        self.config = config
        self.children = Barrier(2, timeout=10)
        self.calls = 0

    def complete(self, messages, **kwargs):
        import json
        self.calls += 1
        payload = json.loads(messages[1]["content"])
        if payload["protocol_version"].endswith("child-v3"):
            self.children.wait()
            # Keep the synthetic I/O interval nonzero under coarse Windows UTC
            # clocks. The real strict overlap requirement remains unchanged.
            time.sleep(0.02)
            action = payload["child_progress"]["legal_next_actions"][0]
        elif not payload["completed_tools"]:
            action = {"action": "parallel", "tools": ["financial_child", "market_child"], "plan": ["Read original sources"]}
        elif payload["control"]["execution"]["next_action"] is not None:
            action = payload["control"]["execution"]["next_action"]
        else:
            if not payload["control"]["execution"]["can_finish"]:
                raise AssertionError("synthetic choice cannot skip required execution")
            action = {"action": "finish", "reason": "completed", "plan": ["Retain all exact facts and lawful gaps"]}
        return ChatResult(self.config.model, self.config.model, canonical_json(action), "stop",
                          "synthetic-phase6-mechanism", 100, 20, 120, 1)


class UnknownAdapter:
    def __init__(self, config):
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise OSError("synthetic unknown outcome")


class Phase6EvaluationTests(unittest.TestCase):
    @contextmanager
    def fixture(self, directory, adapter=SyntheticAdapter):
        prior, sources = demo.original_guard()
        fixture_prior = deepcopy(prior)
        fixture_prior["endpoint_sha256"] = digest(CONFIG.endpoint)
        with ExitStack() as stack:
            stack.enter_context(patch.object(demo, "OUT", Path(directory) / "campaign"))
            stack.enter_context(patch.object(demo, "original_guard", return_value=(fixture_prior, sources)))
            stack.enter_context(patch.object(demo, "load_model_config", return_value=CONFIG))
            stack.enter_context(patch.object(demo, "ChatModelAdapter", adapter))
            stack.enter_context(patch.object(demo, "history_hashes", return_value={"unchanged-synthetic-proof": digest(prior["history_hashes"])}))
            stack.enter_context(patch.object(demo, "evidence_ref", side_effect=lambda path, historical=False:
                {"path": "synthetic-historical.json" if historical else "synthetic-diagnosis.json", "sha256": digest([historical])}))
            yield prior, sources

    def test_prepare_freezes_only_four_existing_case_runs_original_questions_oracles_limits_and_zero_new_tasks(self):
        with TemporaryDirectory() as directory, self.fixture(directory) as (prior, _):
            prepared = demo.prepare("synthetic-diagnosis", "synthetic-audit")
            plan, _ = demo.checked(prepared["plan_sha256"])
            self.assertEqual(prepared["scheduled_run_count"], 4)
            self.assertEqual(plan["independent_new_task_count"], 0)
            self.assertEqual(plan["maximum_campaign_runs"], 6)
            self.assertEqual(plan["reserved_repair_run_slots"], 2)
            self.assertEqual(plan["campaign_limits"], {"max_decisions": 96, "max_tokens_accounted": 576000, "max_seconds": 1800})
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertEqual(plan["original_functional_results"], {"passed": 8, "total": 9})
            self.assertEqual(plan["parent_v2_repair_result"], {"passed": 1, "total": 1})
            self.assertEqual(plan["comparison_order"], [list(p) for p in demo.ORDER])
            self.assertFalse(plan["old_budget_reused"])
            self.assertFalse(plan["default_changed"])
            self.assertFalse(plan["automatic_routing"])
            for item in plan["items"]:
                old_item = next(i for i in prior["items"] if i["case_id"] == item["case_id"] and i["route"] == "parallel")
                for key in ("request", "input_ref", "catalog_observations", "authorization_envelope", "required_check_ids"):
                    self.assertEqual(item[key], old_item[key], key)
                self.assertNotEqual(item["run_id"], old_item["run_id"])
            self.assertNotIn(CONFIG.api_key, canonical_json(plan))

    def test_rehash_cannot_weaken_score_question_limit_order_or_task_denominator(self):
        for change in (lambda p: p["acceptance"].update(primary_benefit="delete facts until smaller"),
                       lambda p: p.update(independent_new_task_count=4),
                       lambda p: p["items"][0]["request"].update(question="changed question"),
                       lambda p: p.update(maximum_campaign_runs=8),
                       lambda p: p["items"].reverse()):
            with self.subTest(change=change), TemporaryDirectory() as directory, self.fixture(directory):
                prepared = demo.prepare("synthetic-diagnosis", "synthetic-audit")
                plan = demo.OLD.read(demo.OUT / "plan.json")
                change(plan)
                (demo.OUT / "plan.json").write_text(canonical_json(plan), encoding="utf-8")
                with self.assertRaises(IntegrityError):
                    demo.checked(demo.OLD.sha(demo.OUT / "plan.json"))

    def test_four_scripted_runtime_paths_bind_exact_parent_child_paid_wire_lossless_counterfactual_and_readonly_replay(self):
        with TemporaryDirectory() as directory, self.fixture(directory):
            prepared = demo.prepare("synthetic-diagnosis", "synthetic-audit")
            result = demo.live(prepared["plan_sha256"])
            dataset = demo.OLD.read(demo.OUT / "live/trace-dataset.json")
            failed = [{key: row[key] for key in ("case_id", "variant", "assessment", "safety_checks", "error_type")}
                      for row in dataset["rows"] if not row["assessment"]["functional_passed"]]
            self.assertTrue(result["evaluation"]["all_quality_passed"], failed)
            self.assertEqual(result["ledger"]["decisions"], 36)
            self.assertEqual(result["ledger"]["unknown_usage_calls"], 0)
            self.assertGreater(result["evaluation"]["same_state_net_total_wire_bytes_saved"], 0)
            self.assertEqual(dataset["independent_new_task_count"], 0)
            for row in dataset["rows"]:
                self.assertTrue(row["assessment"]["functional_passed"], row["assessment"])
                demo.validate_timing(row)
                self.assertGreaterEqual(row["runtime_wall_ms"], 0)
                self.assertGreaterEqual(row["harness_validation_ms"], 0)
                self.assertEqual(row["wall_clock_ms"], row["overall_measured_wall_ms"])
                self.assertTrue(all(s == "passed" for s in row["safety_checks"].values()))
                self.assertEqual(row["report"]["required_checks"][4]["status"], "passed")
                if row["variant"] == "candidate":
                    views = row["paid_telemetry_validation"]["same_state_candidate_parent_views"]
                    self.assertEqual(len(views), 5)
                    self.assertTrue(all(v["candidate_context_decodes_exact_baseline"] and not v["baseline_dispatched"] for v in views))
            before = demo.original.file_hashes(demo.OUT / "live")
            with patch.object(demo.original.NoNetwork, "complete", side_effect=AssertionError("replay attempted model")), \
                    patch.object(demo.CheckpointStore, "append", side_effect=AssertionError("replay appended checkpoint")):
                replay = demo.replay(prepared["plan_sha256"])
            self.assertTrue(replay["quality_acceptance_passed"])
            self.assertEqual(replay["decision"], "limited_explicit_lossless_representation_accepted")
            self.assertEqual((replay["model_calls"], replay["provider_calls"], replay["checkpoint_appends"]), (0, 0, 0))
            self.assertEqual(demo.original.file_hashes(demo.OUT / "live"), before)

    def test_terminal_unknown_preserves_reservation_stops_all_remaining_runs_and_replays_failure(self):
        with TemporaryDirectory() as directory, self.fixture(directory, UnknownAdapter):
            prepared = demo.prepare("synthetic-diagnosis", "synthetic-audit")
            result = demo.live(prepared["plan_sha256"])
            ledger = result["ledger"]
            self.assertEqual(ledger["decisions"], 1)
            self.assertEqual(ledger["unknown_usage_calls"], 1)
            self.assertEqual(ledger["tokens_accounted"], ledger["intents"][0]["reservation"])
            self.assertTrue(result["unknown_paid_outcome_stopped_dispatch"])
            dataset = demo.OLD.read(demo.OUT / "live/trace-dataset.json")
            self.assertEqual(dataset["started_run_count"], 1)
            self.assertEqual(sum(r["run_started"] for r in dataset["rows"]), 1)
            self.assertEqual(sum(bool(r["intents"]) for r in dataset["rows"]), 1)
            self.assertFalse(result["evaluation"]["all_quality_passed"])
            before = demo.original.file_hashes(demo.OUT / "live")
            replay = demo.replay(prepared["plan_sha256"])
            self.assertTrue(replay["replay_same"])
            self.assertFalse(replay["quality_acceptance_passed"])
            self.assertEqual(demo.original.file_hashes(demo.OUT / "live"), before)

    def test_known_response_receipt_interval_and_ledger_persistence_failure_keeps_unknown_reservation_and_stops(self):
        for suffix in ("-receipt.json", "-interval.json", "-settled.json"):
            with self.subTest(suffix=suffix), TemporaryDirectory() as directory, self.fixture(directory):
                prepared = demo.prepare("synthetic-diagnosis", "synthetic-audit")
                original_write, failed = demo.OLD.write_new, []
                def injected_write(path, value):
                    if str(path).endswith(suffix) and not failed:
                        failed.append(str(path))
                        raise OSError("synthetic durable commit failure")
                    return original_write(path, value)
                with patch.object(demo.OLD, "write_new", side_effect=injected_write):
                    result = demo.live(prepared["plan_sha256"])
                self.assertEqual(result["ledger"]["decisions"], 1)
                self.assertEqual(result["ledger"]["unknown_usage_calls"], 1)
                intent = result["ledger"]["intents"][0]
                self.assertEqual(result["ledger"]["tokens_accounted"], intent["reservation"])
                self.assertTrue(result["unknown_paid_outcome_stopped_dispatch"])
                marker = demo.OLD.read(demo.OUT / "live/dispatch/001-settlement-incomplete.json")
                self.assertEqual(marker["reservation_retained"], intent["reservation"])
                if suffix != "-receipt.json":
                    receipt = demo.OLD.read(demo.OUT / "live/dispatch/001-receipt.json")
                    self.assertEqual(receipt["total_tokens"], 120)
                before = demo.original.file_hashes(demo.OUT / "live")
                replay = demo.replay(prepared["plan_sha256"])
                self.assertTrue(replay["replay_same"])
                self.assertFalse(replay["quality_acceptance_passed"])
                self.assertEqual(demo.original.file_hashes(demo.OUT / "live"), before)

    def test_intent_persistence_failure_blocks_dispatch_and_any_following_attempt(self):
        with TemporaryDirectory() as directory, self.fixture(directory):
            prepared = demo.prepare("synthetic-diagnosis", "synthetic-audit")
            plan, _ = demo.checked(prepared["plan_sha256"])
            model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=30), Path(directory))
            model.item = plan["items"][0]
            role, spec = model.item["parent_version"], demo.spec_for("baseline")
            real_write = demo.OLD.write_new
            def injected(path, value):
                if str(path).endswith("-intent.json"):
                    raise OSError("synthetic intent failure")
                return real_write(path, value)
            with patch.object(demo, "validate_outbound", return_value=(role, spec, 1)), \
                    patch.object(demo.OLD, "write_new", side_effect=injected):
                with self.assertRaises(OSError):
                    model.complete(model.item["messages"], max_tokens=1024, timeout=30)
                self.assertTrue(model.terminal_unknown)
                with self.assertRaises(IntegrityError):
                    model.complete(model.item["messages"], max_tokens=1024, timeout=30)
            self.assertEqual(model.adapter.calls, 0)
            self.assertEqual(model.ledger.snapshot()["decisions"], 1)
            self.assertEqual(model.ledger.snapshot()["unknown_usage_calls"], 1)

    def test_timing_boundaries_validate_and_parallel_io_union_avoids_double_counting(self):
        row = {"run_started": True, "runtime_wall_ms": 150, "runtime_preparation_ms": 10,
               "harness_validation_ms": 20, "overall_measured_wall_ms": 180, "wall_clock_ms": 180}
        demo.validate_timing(row)
        for change in ({"runtime_wall_ms": -1}, {"harness_validation_ms": 30}, {"wall_clock_ms": 150}):
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                demo.validate_timing({**row, **change})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for number, start, end in ((1, ".000", ".100"), (2, ".050", ".150")):
                prefix = f"{number:03d}"
                demo.OLD.write_new(root / (prefix + "-interval.json"), {"role": "synthetic-child",
                    "started_at": "2026-10-06T00:00:00" + start + "+00:00",
                    "finished_at": "2026-10-06T00:00:00" + end + "+00:00", "outcome": "known"})
                demo.OLD.write_new(root / (prefix + "-receipt.json"), {"latency_ms": 100})
            measured = demo.latency({"trace": []}, [], root, [{"number": 1}, {"number": 2}])
            self.assertEqual(measured["known_model_transport_sum_ms"], 200)
            self.assertEqual(measured["model_dispatch_intervals_union_ms"], 150)
            self.assertEqual(measured["verification_tool_span_sum_ms"], 0)
            self.assertIsNone(measured["read_authorization_split_ms"])

    def test_missing_diagnostic_and_frozen_sha_requirements_have_no_execution_side_effect(self):
        with patch.object(demo, "prepare") as prepare, patch.object(demo, "live") as live:
            with self.assertRaises(SystemExit):
                demo.main(["--prepare"])
            with self.assertRaises(SystemExit):
                demo.main(["--live"])
            prepare.assert_not_called()
            live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
