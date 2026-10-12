"""Synthetic transport checks for the isolated v6/v6.1 acceptance wrapper."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_window_optimized_acceptance as demo
import context_window_acceptance as previous
from test_phase6_evaluate import SyntheticAdapter, UnknownAdapter
from stock_research.errors import IntegrityError
from stock_research.models import canonical_json, digest

CONFIG = SimpleNamespace(model=demo.spec_for("baseline").model,
    endpoint="https://example.invalid/configured-only", api_key="synthetic-optimized-only-key")


class OptimizedWindowAcceptanceTests(unittest.TestCase):
    @contextmanager
    def fixture(self, directory, adapter=SyntheticAdapter):
        prior, sources = demo._engine.original_guard()
        frozen_prior = deepcopy(prior)
        frozen_prior["endpoint_sha256"] = digest(CONFIG.endpoint)
        with ExitStack() as stack:
            stack.enter_context(patch.object(demo._engine, "OUT", Path(directory) / "new-independent-campaign"))
            stack.enter_context(patch.object(demo._engine, "original_guard", return_value=(frozen_prior, sources)))
            stack.enter_context(patch.object(demo._engine, "load_model_config", return_value=CONFIG))
            stack.enter_context(patch.object(demo._engine, "ChatModelAdapter", adapter))
            stack.enter_context(patch.object(demo._engine, "history_hashes", return_value={"unchanged-history": digest(prior["history_hashes"])}))
            stack.enter_context(patch.object(demo._engine, "validate_gate", return_value=({},
                {"real_overlimit_recovery_status": "真实超限恢复尚未验证"})))
            stack.enter_context(patch.object(demo._engine, "evidence_ref", return_value={"path": "synthetic-only.json", "sha256": digest("gate")}))
            yield prior, sources

    def test_private_helper_module_keeps_original_v6_module_and_file_identity_unchanged(self):
        self.assertIsNot(demo._engine, previous)
        self.assertEqual(previous.VERSIONS, {"baseline": "dynamic-parent-parallel-v5", "candidate": "dynamic-parent-parallel-v6"})
        self.assertEqual(demo.VERSIONS, {"baseline": "dynamic-parent-parallel-v6", "candidate": "dynamic-parent-parallel-v6.1"})
        self.assertEqual(demo._engine.live.__globals__["VERSIONS"], demo.VERSIONS)
        self.assertEqual(previous.live.__globals__["VERSIONS"], previous.VERSIONS)

    def test_freeze_reuses_two_exact_existing_cases_with_four_fresh_ids_and_all_original_limits(self):
        old_ids = {item["run_id"] for item in previous.OLD.read(previous.OUT / "plan.json")["items"]}
        with TemporaryDirectory() as directory, self.fixture(directory) as (prior, _):
            frozen = demo.prepare("offline", "preflight")
            plan, _ = demo.checked(frozen["plan_sha256"])
            self.assertEqual(plan["campaign_limits"], {"max_decisions": 64, "max_tokens_accounted": 384000, "max_seconds": 1800})
            self.assertEqual((plan["maximum_existing_cases"], plan["maximum_campaign_runs"], plan["independent_new_task_count"]), (2, 4, 0))
            self.assertEqual(plan["child_protocol_opt_in"], "v3")
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertEqual(plan["specs"]["baseline"]["version"], demo.VERSIONS["baseline"])
            self.assertEqual(plan["specs"]["candidate"]["version"], demo.VERSIONS["candidate"])
            self.assertFalse(old_ids & {item["run_id"] for item in plan["items"]})
            self.assertFalse(plan["old_budget_reused"])
            for item in plan["items"]:
                old = next(row for row in prior["items"] if row["case_id"] == item["case_id"] and row["route"] == "parallel")
                for name in ("request", "input_ref", "catalog_observations", "authorization_envelope", "required_check_ids"):
                    self.assertEqual(item[name], old[name])
            self.assertNotIn(CONFIG.api_key, canonical_json(plan))

    def test_rehashed_plan_cannot_expand_budget_versions_tasks_sources_or_reuse_old_v6_run(self):
        old_id = previous.OLD.read(previous.OUT / "plan.json")["items"][0]["run_id"]
        changes = (lambda plan: plan["campaign_limits"].update(max_decisions=96),
            lambda plan: plan.update(maximum_campaign_runs=6),
            lambda plan: plan["items"][0]["request"].update(question="changed"),
            lambda plan: plan["items"][0].update(run_id=old_id),
            lambda plan: plan["items"].reverse())
        for change in changes:
            with self.subTest(change=change), TemporaryDirectory() as directory, self.fixture(directory):
                demo.prepare("offline", "preflight")
                path = demo._engine.OUT / "plan.json"
                plan = demo.OLD.read(path)
                change(plan)
                path.write_text(canonical_json(plan), encoding="utf-8")
                with self.assertRaises(IntegrityError):
                    demo.checked(demo.OLD.sha(path))

    def test_scripted_paired_quality_codec_and_zero_append_replay_cannot_invent_token_savings(self):
        old_files = previous.original.file_hashes(previous.OUT)
        with TemporaryDirectory() as directory, self.fixture(directory):
            frozen = demo.prepare("offline", "preflight")
            summary = demo.live(frozen["plan_sha256"])
            rows = demo.OLD.read(demo._engine.OUT / "live/trace-dataset.json")["rows"]
            errors = [{"variant": row["variant"], "error": row["error_type"],
                "assessment": row["assessment"]} for row in rows]
            self.assertTrue(summary["evaluation"]["all_quality_passed"], errors)
            self.assertTrue(summary["evaluation"]["metadata_codec_exact_all_views"])
            self.assertFalse(summary["evaluation"]["new_disclosure_contract_not_reversible_old_view"])
            self.assertFalse(summary["evaluation"]["new_disclosure_contract"])
            self.assertTrue(summary["evaluation"]["exact_restores_literal_v6_window"])
            self.assertEqual(summary["ledger"]["decisions"], 36)
            self.assertEqual(summary["ledger"]["unknown_usage_calls"], 0)
            self.assertFalse(summary["evaluation"]["actual_task_token_reduction_proven"])
            for row in rows:
                self.assertEqual(row["token_usage"]["whole_task"]["total_tokens"], 1080)
                self.assertEqual(len(row["report"]["facts"]), 7 if row["case_id"] == demo.CASE_IDS[0] else 6)
                self.assertEqual(len(row["report"]["evidence"]), 12)
                self.assertEqual(len([event for event in row["report"]["trace"]
                    if event["event"] == "tool_finished" and event["tool"] == "verification"]), 1)
                for view in row["paid_telemetry_validation"]["same_state_candidate_parent_views"]:
                    self.assertTrue(view["expanded_raw_window_exact"])
                    self.assertTrue(view["same_raw_pages_and_cursor_selections_exact"])
                    self.assertLessEqual(view["candidate_total_wire_bytes"], 12000)
                    self.assertIsNone(view["counterfactual_tokens"])
                    self.assertIsNone(view["counterfactual_runtime"])
            before = previous.original.file_hashes(demo._engine.OUT / "live")
            replay = demo.readonly_replay(frozen["plan_sha256"])
            self.assertTrue(replay["quality_acceptance_passed"])
            self.assertFalse(replay["actual_task_token_reduction_proven"])
            self.assertNotEqual(replay["decision"], "limited_explicit_exact_window_metadata_token_optimization_accepted")
            self.assertEqual((replay["model_calls"], replay["provider_calls"], replay["checkpoint_appends"]), (0, 0, 0))
            self.assertEqual(previous.original.file_hashes(demo._engine.OUT / "live"), before)
        self.assertEqual(previous.original.file_hashes(previous.OUT), old_files)

    def test_same_raw_codec_probe_preserves_exact_old_paid_view_and_counts_system_overhead(self):
        frozen = previous.OLD.read(previous.OUT / "plan.json")
        item = next(row for row in frozen["items"] if row["parent_version"] == demo.VERSIONS["baseline"])
        probe = demo.codec_probe(item["messages"])
        self.assertTrue(probe["expanded_raw_window_exact"])
        self.assertTrue(probe["same_raw_pages_and_cursor_selections_exact"])
        self.assertEqual(probe["counterfactual_model_calls"], 0)
        self.assertEqual(probe["same_raw_wire_bytes_saved"], probe["same_raw_baseline_total_wire_bytes"] - probe["same_raw_candidate_total_wire_bytes"])

    def test_unknown_transport_preserves_full_reservation_and_stops_all_new_slots(self):
        with TemporaryDirectory() as directory, self.fixture(directory, UnknownAdapter):
            frozen = demo.prepare("offline", "preflight")
            summary = demo.live(frozen["plan_sha256"])
            self.assertEqual(summary["ledger"]["decisions"], 1)
            self.assertEqual(summary["ledger"]["unknown_usage_calls"], 1)
            self.assertEqual(summary["ledger"]["tokens_accounted"], summary["ledger"]["intents"][0]["reservation"])
            self.assertTrue(summary["unknown_paid_outcome_stopped_dispatch"])
            replay = demo.readonly_replay(frozen["plan_sha256"])
            self.assertTrue(replay["replay_same"])
            self.assertFalse(replay["quality_acceptance_passed"])
            self.assertFalse(replay["actual_task_token_reduction_proven"])

    def test_byte_benefit_gate_rejects_growing_stage_flat_total_or_self_reported_inconsistent_savings(self):
        files = {"synthetic-code": digest("unchanged")}
        offline = {"code_files": files}
        record = {"expanded_raw_window_exact": True, "same_raw_pages_and_cursor_selections_exact": True,
            "candidate_is_counterfactual_not_paid": True, "same_raw_baseline_total_wire_bytes": 100,
            "same_raw_candidate_total_wire_bytes": 90, "same_raw_wire_bytes_saved": 10,
            "same_raw_bytes_nonincreasing": True}
        valid = {"optimization_schema": "context-window-metadata-readonly-probe/v1", "code_files": files,
            "previous_v6_completed_zero_append_replay": {"replay_same": True, "identical_reports": 4,
                "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0},
            "paid_v6_states": [deepcopy(record) for _ in range(10)], "same_raw_codec_total_wire_bytes_saved": 100}
        with patch.object(demo, "_base_gate", return_value=(offline, valid)):
            self.assertEqual(demo.validate_gate("offline", "preflight", check_current=False), (offline, valid))
        changes = (lambda probe: probe["paid_v6_states"][0].update(same_raw_candidate_total_wire_bytes=101,
                        same_raw_wire_bytes_saved=-1, same_raw_bytes_nonincreasing=False),
            lambda probe: [entry.update(same_raw_candidate_total_wire_bytes=100, same_raw_wire_bytes_saved=0)
                for entry in probe["paid_v6_states"]],
            lambda probe: probe.update(same_raw_codec_total_wire_bytes_saved=999),
            lambda probe: probe["paid_v6_states"][0].update(same_raw_wire_bytes_saved=99),
            lambda probe: probe["paid_v6_states"][0].update(same_raw_bytes_nonincreasing=1))
        for change in changes:
            failed = deepcopy(valid)
            change(failed)
            with self.subTest(change=change), patch.object(demo, "_base_gate", return_value=(offline, failed)):
                with self.assertRaises(IntegrityError):
                    demo.validate_gate("offline", "preflight", check_current=False)


if __name__ == "__main__":
    unittest.main()
