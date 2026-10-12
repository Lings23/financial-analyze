"""Independent acceptance harness mechanics; scripted choices are not model quality."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_disclosure_acceptance as demo
from test_phase6_evaluate import SyntheticAdapter, UnknownAdapter
from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import canonical_json, digest, utcnow


CONFIG = SimpleNamespace(model=demo.spec_for("baseline").model,
    endpoint="https://example.invalid/configured-only", api_key="synthetic-disclosure-only-key")


class ContextDisclosureAcceptanceTests(unittest.TestCase):
    @contextmanager
    def fixture(self, directory, adapter=SyntheticAdapter):
        prior, sources = demo.original_guard()
        fixture_prior = deepcopy(prior)
        fixture_prior["endpoint_sha256"] = digest(CONFIG.endpoint)
        with ExitStack() as stack:
            stack.enter_context(patch.object(demo, "OUT", Path(directory) / "independent-campaign"))
            stack.enter_context(patch.object(demo, "original_guard", return_value=(fixture_prior, sources)))
            stack.enter_context(patch.object(demo, "load_model_config", return_value=CONFIG))
            stack.enter_context(patch.object(demo, "ChatModelAdapter", adapter))
            stack.enter_context(patch.object(demo, "history_hashes", return_value={"unchanged-history": digest(prior["history_hashes"])}))
            stack.enter_context(patch.object(demo, "validate_gate", return_value=({},
                {"real_overlimit_recovery_status": "真实超限恢复尚未验证"})))
            stack.enter_context(patch.object(demo, "evidence_ref", return_value={"path": "synthetic-only.json", "sha256": digest("gate")}))
            yield prior, sources

    def test_freeze_uses_independent_four_runs_v4_v5_child_v3_preserving_all_original_inputs_and_limits(self):
        with TemporaryDirectory() as directory, self.fixture(directory) as (prior, _):
            frozen = demo.prepare("offline", "preflight")
            plan, _ = demo.checked(frozen["plan_sha256"])
            self.assertEqual(plan["campaign_limits"], {"max_decisions": 64, "max_tokens_accounted": 384000, "max_seconds": 1800})
            self.assertEqual(plan["maximum_campaign_runs"], 4)
            self.assertEqual(plan["reserved_repair_run_slots"], 0)
            self.assertEqual(plan["maximum_existing_cases"], 2)
            self.assertEqual(plan["independent_new_task_count"], 0)
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertEqual(plan["specs"]["baseline"]["version"], "dynamic-parent-parallel-v4")
            self.assertEqual(plan["specs"]["candidate"]["version"], "dynamic-parent-parallel-v5")
            self.assertFalse(plan["old_budget_reused"])
            self.assertFalse(plan["default_changed"])
            self.assertFalse(plan["parallel_enablement_expanded"])
            for item in plan["items"]:
                old = next(old for old in prior["items"] if old["case_id"] == item["case_id"] and old["route"] == "parallel")
                for key in ("request", "input_ref", "catalog_observations", "authorization_envelope", "required_check_ids"):
                    self.assertEqual(item[key], old[key], key)
                self.assertNotEqual(item["run_id"], old["run_id"])
            self.assertNotIn(CONFIG.api_key, canonical_json(plan))

    def test_rehash_cannot_weaken_question_source_contract_versions_limits_order_or_denominator(self):
        changes = (lambda p: p.update(maximum_campaign_runs=6),
            lambda p: p["campaign_limits"].update(max_decisions=96),
            lambda p: p.update(independent_new_task_count=4),
            lambda p: p["items"][0]["request"].update(question="changed"),
            lambda p: p["items"].reverse(),
            lambda p: p["specs"]["baseline"].update(version="dynamic-parent-parallel-v2"))
        for change in changes:
            with self.subTest(change=change), TemporaryDirectory() as directory, self.fixture(directory):
                frozen = demo.prepare("offline", "preflight")
                plan = demo.OLD.read(demo.OUT / "plan.json")
                change(plan)
                (demo.OUT / "plan.json").write_text(canonical_json(plan), encoding="utf-8")
                with self.assertRaises(IntegrityError):
                    demo.checked(demo.OLD.sha(demo.OUT / "plan.json"))

    def test_scripted_same_cases_execute_actual_verification_full_oracle_and_zero_append_replay(self):
        with TemporaryDirectory() as directory, self.fixture(directory):
            frozen = demo.prepare("offline", "preflight")
            summary = demo.live(frozen["plan_sha256"])
            data = demo.OLD.read(demo.OUT / "live/trace-dataset.json")
            errors = [{key: row[key] for key in ("case_id", "variant", "assessment", "safety_checks", "error_type")}
                for row in data["rows"] if not row["assessment"]["functional_passed"]]
            self.assertTrue(summary["evaluation"]["all_quality_passed"], errors)
            self.assertTrue(summary["evaluation"]["phase_gated_audit_disclosure_observed"])
            self.assertEqual(summary["ledger"]["decisions"], 36)
            self.assertEqual(summary["ledger"]["unknown_usage_calls"], 0)
            for row in data["rows"]:
                self.assertEqual(len([event for event in row["report"]["trace"]
                    if event["event"] == "tool_finished" and event["tool"] == "verification"]), 1)
                self.assertTrue(all(check["status"] == "passed" for check in row["report"]["required_checks"]
                    if not check["id"].startswith("hypothesis:")))
                self.assertTrue(all(check["status"] in {"passed", "insufficient"}
                    for check in row["report"]["required_checks"]))
                self.assertTrue(all(check == "passed" for check in row["safety_checks"].values()))
                self.assertEqual(len(row["report"]["facts"]), 7 if row["case_id"] == "p5-603207" else 6)
                self.assertEqual(len(row["report"]["evidence"]), 12)
                if row["variant"] == "candidate":
                    views = row["paid_telemetry_validation"]["same_state_candidate_parent_views"]
                    self.assertEqual(len(views), 5)
                    self.assertTrue(all(view["new_disclosure_contract"] and not view["candidate_context_decodes_exact_baseline"]
                        and not view["baseline_dispatched"] for view in views))
                    self.assertTrue(all(view["candidate_total_wire_bytes"] <= 12000 for view in views))
                    self.assertTrue(all(view["same_state_bytes_nonincreasing"] for view in views))
                    self.assertTrue(all(view["same_financial_projection"] and view["exact_execution_revisions_decoded"] for view in views))
                    self.assertEqual([view["stage"] for view in views if view["candidate_brief_present"]], ["verification"])
                    self.assertTrue(all(view["complete_audit_persisted_server_side"] for view in views if view["candidate_brief_present"]))
                    self.assertTrue(all(not view["candidate_manifest_present"] for view in views))
                self.assertEqual(row["token_usage"]["whole_task"]["input_tokens"], 900)
                self.assertEqual(row["token_usage"]["whole_task"]["output_tokens"], 180)
                self.assertEqual(row["token_usage"]["whole_task"]["total_tokens"], 1080)
                self.assertEqual(row["token_usage"]["parent"]["model_decisions"], 5)
                self.assertEqual(row["token_usage"]["financial_child"]["model_decisions"], 2)
                self.assertEqual(row["token_usage"]["market_child"]["model_decisions"], 2)
            self.assertTrue(summary["evaluation"]["same_state_all_stage_bytes_nonincreasing_and_total_reduced"])
            self.assertTrue(all(pair["complete_fact_claim_evidence_hypothesis_gap_lineage_equal"] for pair in summary["evaluation"]["pairs"]))
            inflated = deepcopy(data["rows"])
            first = next(row for row in inflated if row["variant"] == "candidate")
            first["paid_telemetry_validation"]["same_state_candidate_parent_views"][0]["same_state_bytes_nonincreasing"] = False
            self.assertFalse(demo.evaluate_pairs(inflated)["same_state_all_stage_bytes_nonincreasing_and_total_reduced"])
            premature = deepcopy(data["rows"])
            first = next(row for row in premature if row["variant"] == "candidate")
            first["paid_telemetry_validation"]["same_state_candidate_parent_views"][0]["candidate_brief_present"] = True
            self.assertFalse(demo.evaluate_pairs(premature)["phase_gated_audit_disclosure_observed"])
            before = demo.original.file_hashes(demo.OUT / "live")
            replay = demo.readonly_replay(frozen["plan_sha256"])
            self.assertTrue(replay["quality_acceptance_passed"], replay)
            self.assertEqual(replay["decision"], "limited_explicit_phase_gated_disclosure_accepted")
            self.assertEqual((replay["model_calls"], replay["provider_calls"], replay["checkpoint_appends"]), (0, 0, 0))
            audited = demo.audit(frozen["plan_sha256"])
            self.assertEqual(audited["status"], "passed")
            self.assertEqual(len(audited["matched_paid_states"]), 36)
            self.assertEqual(sum(chain["run_count"] for chain in audited["chains"]), 12)
            self.assertEqual(demo.original.file_hashes(demo.OUT / "live"), before)

    def test_terminal_unknown_keeps_reserved_cost_and_stops_all_remaining_runs_without_new_calls(self):
        with TemporaryDirectory() as directory, self.fixture(directory, UnknownAdapter):
            frozen = demo.prepare("offline", "preflight")
            summary = demo.live(frozen["plan_sha256"])
            self.assertEqual(summary["ledger"]["decisions"], 1)
            self.assertEqual(summary["ledger"]["unknown_usage_calls"], 1)
            self.assertEqual(summary["ledger"]["tokens_accounted"], summary["ledger"]["intents"][0]["reservation"])
            self.assertTrue(summary["unknown_paid_outcome_stopped_dispatch"])
            replay = demo.readonly_replay(frozen["plan_sha256"])
            self.assertFalse(replay["quality_acceptance_passed"])
            self.assertTrue(replay["replay_same"])
            self.assertEqual(replay["decision"], "bounded_acceptance_failed_evidence_retained")
            data = demo.OLD.read(demo.OUT / "live/trace-dataset.json")
            usage = data["rows"][0]["token_usage"]
            self.assertEqual(usage["whole_task"]["input_tokens"], 0)
            self.assertEqual(usage["whole_task"]["output_tokens"], 0)
            self.assertEqual(usage["whole_task"]["unknown_calls"], 1)
            self.assertEqual(usage["parent"]["tokens_accounted"], summary["ledger"]["tokens_accounted"])

    def test_failed_or_skipped_entirely_offline_gate_cannot_prepare_live_campaign(self):
        valid = {"schema": "context-disclosure-offline-gate/v1", "status": "passed", "failures": 0,
            "errors": 0, "tests_run": 850, "skipped": 14,
            "command": "PYTHONPATH=src python -m unittest discover -s tests -v"}
        for delta in ({"status": "failed"}, {"failures": 1}, {"errors": 1}, {"tests_run": 0},
                {"skipped": 850}, {"command": "some selective tests"}):
            with self.subTest(delta=delta), patch.object(demo.OLD, "read", side_effect=[{**valid, **delta}, {}]):
                with self.assertRaises(IntegrityError):
                    demo.validate_gate("offline", "preflight")

    def test_cli_requires_new_offline_gate_and_explicit_frozen_hash_before_external_dispatch(self):
        with patch.object(demo, "prepare") as prepare, patch.object(demo, "live") as live:
            with self.assertRaises(SystemExit):
                demo.main(["--prepare"])
            with self.assertRaises(SystemExit):
                demo.main(["--live"])
            prepare.assert_not_called()
            live.assert_not_called()

    def test_sibling_unknown_after_durable_reservation_blocks_transport_and_retains_full_cost(self):
        with TemporaryDirectory() as directory, patch.object(demo, "ChatModelAdapter", UnknownAdapter):
            model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=60), Path(directory))
            model.item = {"run_id": "f" * 32, "case_id": "synthetic-only", "variant": "candidate",
                          "parent_version": demo.VERSIONS["candidate"]}
            messages = [{"role": "system", "content": "synthetic system"}, {"role": "user", "content": "synthetic bounded input"}]
            original_write = demo.OLD.write_new

            def sibling_unknown(path, value):
                original_write(path, value)
                if Path(path).name.endswith("-dispatch.json"):
                    model.terminal_unknown = True

            with patch.object(demo, "validate_outbound", return_value=(demo.VERSIONS["candidate"], demo.spec_for("candidate"), 1)), \
                    patch.object(demo.OLD, "write_new", side_effect=sibling_unknown):
                with self.assertRaises(ValidationError):
                    model.complete(messages, timeout=60, max_tokens=demo.spec_for("candidate").output_tokens)
            self.assertEqual(model.adapter.calls, 0)
            ledger = model.ledger.snapshot()
            self.assertEqual(ledger["decisions"], 1)
            self.assertEqual(ledger["unknown_usage_calls"], 1)
            self.assertEqual(ledger["tokens_accounted"], ledger["intents"][0]["reservation"])


if __name__ == "__main__":
    unittest.main()
