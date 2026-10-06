"""Offline repair harness mechanisms; synthetic actions are not model quality.

Existing frozen sources are only exercised for deterministic mechanisms. The
temporary fixture replaces endpoint identity with example.invalid and never
loads credentials, sends requests, edits historical artifacts, or counts tasks.
"""
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
import phase5_parent_repair as repair
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic_contracts import DynamicRequest


CONFIG = SimpleNamespace(model=repair.spec_for().model,
    endpoint="https://example.invalid/configured-only", api_key="synthetic-repair-mechanism-key")


class SyntheticRepairAdapter:
    """Actual Runtime controls with scripted choices, never real model proof."""
    def __init__(self, config):
        self.config = config
        self.children = Barrier(2, timeout=10)

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        if payload["protocol_version"] in {spec.version for spec in repair.CHILD_SPECS.values()}:
            self.children.wait()
            action = payload["child_progress"]["legal_next_actions"][0]
        else:
            execution = payload["control"]["execution"]
            if not payload["completed_tools"]:
                action = {"action": "parallel", "tools": ["financial_child", "market_child"],
                          "plan": ["Read the original bound sources"]}
            elif execution["next_action"] is not None:
                action = execution["next_action"]
            else:
                if not execution["can_finish"]:
                    raise AssertionError("scripted finish cannot bypass pending execution")
                action = {"action": "finish", "reason": "insufficient", "plan": ["Preserve source insufficiency"]}
        return ChatResult(self.config.model, self.config.model, canonical_json(action),
                          "stop", "synthetic-parent-v2-repair", 100, 20, 120, 1)


class UnknownRepairAdapter:
    def __init__(self, config):
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise OSError("synthetic unknown paid outcome")


class Phase5ParentRepairTests(unittest.TestCase):
    @contextmanager
    def campaign_fixture(self, directory, adapter=SyntheticRepairAdapter):
        prior, item, report, sources = repair.original_guard()
        # Endpoint replacement belongs only to this no-network test fixture.
        # Every request, oracle, limit, historical result and source SHA stays.
        fixture_prior = deepcopy(prior)
        fixture_prior["endpoint_sha256"] = digest(CONFIG.endpoint)
        with ExitStack() as stack:
            stack.enter_context(patch.object(repair, "OUT", Path(directory) / "campaign"))
            stack.enter_context(patch.object(repair, "original_guard", return_value=(fixture_prior, item, report, sources)))
            stack.enter_context(patch.object(repair, "load_model_config", return_value=CONFIG))
            stack.enter_context(patch.object(repair, "ChatModelAdapter", adapter))
            stack.enter_context(patch.object(repair.original, "ChatModelAdapter", adapter))
            yield prior, item, report, sources

    def test_prepare_changes_only_explicit_parent_protocol_and_run_with_original_score_and_sources_retained(self):
        before = repair.original.file_hashes(repair.ORIGINAL)
        frozen = repair.original.file_hashes(repair.FROZEN_ORIGINAL_SOURCE)
        with TemporaryDirectory() as directory, self.campaign_fixture(directory) as fixture:
            prior, old_item, _, _ = fixture
            prepared = repair.prepare()
            plan, _ = repair.checked(prepared["plan_sha256"])
            self.assertEqual((prepared["model_calls"], prepared["financial_provider_network_calls"]), (0, 0))
            self.assertEqual(plan["original_functional_results"], {"passed": 8, "total": 9})
            self.assertEqual(plan["original_failed_route_results"], {"passed": 0, "total": 1})
            self.assertEqual(plan["independent_new_task_count"], 0)
            self.assertTrue(plan["same_case_repair_retest"])
            self.assertEqual(plan["parent_version"], "dynamic-parent-parallel-v2")
            self.assertTrue(all(spec["version"].endswith("-child-v3") for spec in plan["child_specs"].values()))
            self.assertEqual(plan["campaign_limits"], {"max_decisions": 16, "max_tokens_accounted": 96000, "max_seconds": 480})
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertFalse(plan["old_budget_reused"])
            for key, value in old_item.items():
                if key not in {"run_id", "spec_identity", "messages"}:
                    self.assertEqual(plan["item"][key], value, key)
            self.assertNotEqual(plan["item"]["run_id"], old_item["run_id"])
            self.assertEqual(plan["original_campaign_file_hashes"], before)
            self.assertEqual(plan["original_frozen_source_hashes"], frozen)
            for name, checksum in prior["code_files"].items():
                self.assertEqual(repair.OLD.sha(repair.FROZEN_ORIGINAL_SOURCE / name), checksum)
            self.assertNotIn(CONFIG.api_key, json.dumps(plan))
        self.assertEqual(repair.original.file_hashes(repair.ORIGINAL), before)
        self.assertEqual(repair.original.file_hashes(repair.FROZEN_ORIGINAL_SOURCE), frozen)

    def test_changed_original_oracle_cannot_be_approved_by_rehashing_plan(self):
        with TemporaryDirectory() as directory, self.campaign_fixture(directory):
            prepared = repair.prepare()
            plan, _ = repair.checked(prepared["plan_sha256"])
            plan["item"]["expected_outcome"]["required_check_statuses"]["verification"] = "not_completed"
            path = repair.OUT / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaises(IntegrityError):
                repair.checked(repair.OLD.sha(path))

    def test_synthetic_v2_parallel_closed_loop_preserves_six_facts_twelve_evidence_paid_wires_and_readonly_replay(self):
        with TemporaryDirectory() as directory, self.campaign_fixture(directory):
            prepared = repair.prepare()
            summary = repair.live(prepared["plan_sha256"])
            self.assertTrue(summary["assessment"]["functional_passed"], summary)
            self.assertEqual(summary["assessment"]["status"], "insufficient")
            self.assertEqual(summary["ledger"]["unknown_usage_calls"], 0)
            self.assertEqual(summary["original_functional_results"], {"passed": 8, "total": 9})
            self.assertEqual(summary["independent_new_task_count"], 0)
            self.assertFalse(summary["original_nine_run_gate_repaired"])
            self.assertTrue(all(status == "passed" for status in summary["safety_checks"].values()))
            report = repair.OLD.read(repair.OUT / "live/report.json")
            self.assertEqual((len(report["facts"]), len(report["evidence"])), (6, 12))
            checks = {check["id"]: check["status"] for check in report["required_checks"]}
            self.assertEqual(checks["verification"], "passed")
            self.assertEqual(checks["hypothesis:financial_deterioration"], "insufficient")
            self.assertEqual(summary["paid_telemetry_validation"]["bound_paid_turns"], summary["ledger"]["decisions"])
            plan, _ = repair.checked(prepared["plan_sha256"])
            message_file = repair.OUT / "live/dispatch/001-messages.json"
            messages = repair.OLD.read(message_file)
            repair.validate_outbound(messages, plan["item"], {"max_tokens": 1024}, repair.OUT / "live/runs")
            tampered = deepcopy(messages)
            payload = json.loads(tampered[1]["content"])
            payload["control"]["execution"].update(pending_checks=[], can_finish=True)
            tampered[1]["content"] = canonical_json(payload)
            with self.assertRaises(IntegrityError):
                repair.validate_outbound(tampered, plan["item"], {"max_tokens": 1024}, repair.OUT / "live/runs")
            before = repair.original.file_hashes(repair.OUT / "live")
            result = repair.replay(prepared["plan_sha256"])
            self.assertTrue(result["replay_same"])
            self.assertEqual((result["model_calls"], result["financial_provider_network_calls"], result["checkpoint_appends"]), (0, 0, 0))
            self.assertEqual(repair.original.file_hashes(repair.OUT / "live"), before)

    def test_unknown_paid_result_remains_reserved_and_same_intent_is_not_resent(self):
        with TemporaryDirectory() as directory, self.campaign_fixture(directory, UnknownRepairAdapter) as fixture:
            prepared = repair.prepare()
            plan, sources = repair.checked(prepared["plan_sha256"])
            item = plan["item"]
            root = Path(directory) / "unknown-run"
            dispatch = root / "dispatch"
            dispatch.mkdir(parents=True)
            checkpoints = root / "runs"
            model = repair.RecordingModel(CONFIG, utcnow() + timedelta(seconds=30), dispatch, item, checkpoints)
            service, access = sources.context(plan["case"])
            report = repair.runtime(service, CheckpointStore(checkpoints), model).run(
                DynamicRequest.from_dict(item["request"]), access, run_id=item["run_id"])
            ledger = model.ledger.snapshot()
            self.assertEqual(ledger["decisions"], 1)
            self.assertEqual(ledger["unknown_usage_calls"], 1)
            self.assertEqual(ledger["tokens_accounted"], ledger["intents"][0]["reservation"])
            self.assertEqual(report["root_budget"]["unknown_usage_calls"], 1)
            self.assertEqual(repair.validate_receipts(dispatch, ledger, item, checkpoints)["unknown_usage_calls"], 1)
            messages = repair.OLD.read(dispatch / "001-messages.json")
            with self.assertRaises((IntegrityError, ValidationError)):
                model.complete(messages, max_tokens=1024, timeout=30)
            self.assertEqual(model.adapter.calls, 1)
            self.assertEqual(model.ledger.snapshot(), ledger)


if __name__ == "__main__":
    unittest.main()
