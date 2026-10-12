"""Synthetic durable accounting mechanisms; no financial/model validation."""
from dataclasses import asdict
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_real_pagination_acceptance as demo
from stock_research.errors import IntegrityError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.context_window import _atoms

CONFIG = SimpleNamespace(model=demo.spec_for("baseline").model,
    endpoint="https://example.invalid/configured-only", api_key="synthetic-real-page-test-key")


class ScriptedSourceMechanismAdapter:
    """Test-only choices and usage; never a real-model or financial-quality verdict."""
    targets = None
    errors = []
    discoveries = []

    def __init__(self, config):
        self.config = config

    def complete(self, messages, **kwargs):
        try:
            return self.scripted_complete(messages, **kwargs)
        except Exception as exc:
            import traceback
            self.errors.append({"type": type(exc).__name__, "frames": [(frame.name, frame.lineno) for frame in traceback.extract_tb(exc.__traceback__)]})
            raise

    def scripted_complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        if payload["protocol_version"].endswith("child-v3"):
            action = payload["child_progress"]["legal_next_actions"][0]
        elif not payload["completed_tools"]:
            action = {"action": "parallel", "tools": ["financial_child", "market_child"], "plan": ["Audit"]}
        elif "hypotheses" in payload["completed_tools"] and "verification" not in payload["completed_tools"]:
            if payload["protocol_version"] == demo.VERSIONS["baseline"]:
                context = payload["context"]
                action = {"action": "disclose", "refs": self.targets,
                    "catalog_ref": context["catalog_ref"], "plan": ["Audit"]}
            else:
                context = demo.optimized.raw_context(payload["context"])
                object_pages = [page for page in context["pages"] if page["kind"] == "objects"]
                action = {"action": "context_read", "catalog_ref": context["catalog_ref"], "plan": ["Audit"]}
                if object_pages:
                    if object_pages[-1]["has_more"]:
                        action["cursor"] = object_pages[-1]["next_cursor"]
                    else:
                        action = payload["control"]["execution"]["next_action"]
                else:
                    # Model-independent test driver may know frozen targets, but
                    # only currently issued identities are selected. Real code
                    # neither injects these targets nor replaces any response.
                    visible = {atom[0] for page in context["pages"] for atom in page["atoms"]}
                    visible |= {atom[3]["ref"] for page in context["pages"] for atom in page["atoms"]
                        if page["kind"] == "directory"}
                    self.discoveries.append({"turn": payload["control"]["decision"], "missing_targets": sorted(set(self.targets) - visible),
                        "pages": [{key: page[key] for key in ("kind", "start", "end", "total")} for page in context["pages"]]})
                    if set(self.targets) <= visible:
                        action["refs"] = self.targets
                    else:
                        action["cursor"] = next((page["next_cursor"] for page in context["pages"]
                            if page["kind"] == "directory" and page.get("has_more")), None) or context["collections"]["directory"]["cursor"]
        elif payload["control"]["execution"]["next_action"] is not None:
            action = payload["control"]["execution"]["next_action"]
        else:
            action = {"action": "finish", "reason": "completed", "plan": ["Audit"]}
        return ChatResult(self.config.model, self.config.model, canonical_json(action), "stop",
            "synthetic-source-harness-mechanism-only", 100, 20, 120, 1)


class RealPaginationAccountingTests(unittest.TestCase):
    def fixture(self, path, *, known=True):
        item = {"run_id": "f" * 32, "variant": "candidate", "parent_version": demo.VERSIONS["candidate"]}
        messages = [{"role": "system", "content": "synthetic only"},
            {"role": "user", "content": "synthetic immutable bounded input"}]
        spec = demo.spec_for("candidate")
        ledger = demo.OLD.RootLedger(demo.LIMITS[0], demo.LIMITS[1])
        intent = ledger.reserve(item["run_id"] + "/" + item["parent_version"], messages, spec.output_tokens)
        demo.OLD.write_new(path / "001-messages.json", messages)
        demo.OLD.write_new(path / "001-intent.json", dict(intent))
        demo.OLD.write_new(path / "ledger-001-reserved.json", ledger.snapshot())
        if known:
            receipt = ChatResult(spec.model, spec.model, "{}", "stop", "synthetic-only", 100, 20, 120, 1)
            demo.OLD.write_new(path / "001-receipt.json", asdict(receipt))
            ledger.accounted += receipt.total_tokens - intent["reservation"]
            intent.update(usage_status="known", prompt_tokens=100, completion_tokens=20, total_tokens=120)
            demo.OLD.write_new(path / "ledger-002-settled.json", ledger.snapshot())
        else:
            demo.OLD.write_new(path / "001-receipt.json", {"status": "unknown", "error_type": "SyntheticUnknown"})
            demo.OLD.write_new(path / "ledger-002-terminal-unknown.json", ledger.snapshot())
        return item, ledger, messages

    def test_known_cross_process_ledger_rebuild_preserves_counters_role_calls_and_exact_receipts(self):
        with TemporaryDirectory() as directory:
            item, expected, _ = self.fixture(Path(directory))
            ledger, calls, revision, unknown = demo.restored_ledger(directory, [item])
            self.assertEqual(ledger.snapshot(), expected.snapshot())
            self.assertEqual(calls, {(item["run_id"], item["parent_version"]): 1})
            self.assertEqual(revision, 2)
            self.assertFalse(unknown)
            self.assertEqual(ledger.max_decisions, 64)
            self.assertEqual(ledger.max_tokens, 384000)

    def test_unknown_outcome_preserves_full_charge_and_requires_terminal_stop(self):
        with TemporaryDirectory() as directory:
            item, expected, _ = self.fixture(Path(directory), known=False)
            ledger, _, _, unknown = demo.restored_ledger(directory, [item])
            self.assertTrue(unknown)
            self.assertEqual(ledger.snapshot(), expected.snapshot())
            self.assertEqual(ledger.accounted, ledger.intents[0]["reservation"])
            self.assertEqual(ledger.snapshot()["unknown_usage_calls"], 1)

    def test_orphan_intent_no_snapshot_or_changed_known_receipt_cannot_resume_or_release(self):
        for changed in ("orphan", "receipt", "snapshot"):
            with self.subTest(changed=changed), TemporaryDirectory() as directory:
                path = Path(directory)
                item, _, _ = self.fixture(path)
                if changed == "orphan":
                    demo.OLD.write_new(path / "002-intent.json", {"number": 2, "usage_status": "unknown"})
                elif changed == "receipt":
                    receipt = demo.OLD.read(path / "001-receipt.json")
                    receipt["total_tokens"] = 121
                    (path / "001-receipt.json").write_text(__import__("json").dumps(receipt), encoding="utf-8")
                else:
                    (path / "ledger-001-reserved.json").unlink()
                with self.assertRaises((IntegrityError, demo.ValidationError)):
                    demo.restored_ledger(path, [item])

    def test_restored_unknown_blocks_adapter_before_another_paid_intent(self):
        with TemporaryDirectory() as directory:
            item, ledger, messages = self.fixture(Path(directory), known=False)
            adapter = SimpleNamespace(complete=__import__('unittest').mock.Mock())
            with patch.object(demo, "ChatModelAdapter", return_value=adapter), \
                    patch.object(demo._helpers, "validate_outbound", return_value=(item["parent_version"], demo.spec_for("candidate"), 2)):
                model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=60), directory, [item])
                model.item = item
                with self.assertRaises(IntegrityError):
                    model.complete(messages, timeout=60, max_tokens=demo.spec_for("candidate").output_tokens)
                adapter.complete.assert_not_called()
                self.assertEqual(model.ledger.snapshot(), ledger.snapshot())

    def test_orphan_wire_before_first_snapshot_is_not_a_clean_new_campaign(self):
        with TemporaryDirectory() as directory:
            demo.OLD.write_new(Path(directory) / "001-messages.json", {"synthetic_only": True})
            with self.assertRaises(IntegrityError):
                demo.restored_ledger(directory, [])


class RealPaginationFreezeTests(unittest.TestCase):
    @contextmanager
    def fixture(self, directory):
        task = {"case": {"id": "synthetic-mechanism-only"}, "scope": "synthetic-only", "request": {"question": "synthetic only"},
            "request_by_variant": {variant: {"question": "synthetic only"} for variant in demo.VERSIONS},
            "source_payload_sha256": digest("synthetic-only"), "inputs": {"synthetic": True}}
        preview = [{"role": "system", "content": "synthetic only"}, {"role": "user", "content": canonical_json({"available_tools": []})}]
        source = SimpleNamespace(build_task=lambda: deepcopy(task), preview=lambda *args: deepcopy(preview))
        with ExitStack() as stack:
            stack.enter_context(patch.object(demo, "OUT", Path(directory) / "campaign"))
            stack.enter_context(patch.object(demo, "sources", return_value=source))
            stack.enter_context(patch.object(demo, "load_model_config", return_value=CONFIG))
            stack.enter_context(patch.object(demo, "history_hashes", return_value={"old": "preserved"}))
            stack.enter_context(patch.object(demo, "code_files", return_value={"synthetic.py": digest("code")}))
            stack.enter_context(patch.object(demo.prior, "test_files", return_value={"synthetic_test.py": digest("tests")}))
            stack.enter_context(patch.object(demo, "validate_gate", return_value=({}, {})))
            stack.enter_context(patch.object(demo, "evidence_ref", return_value={"path": "synthetic-only.json", "sha256": digest("gate")}))
            yield task

    def test_one_new_task_two_initial_and_two_reserved_slots_no_limit_or_deadline_reset(self):
        with TemporaryDirectory() as directory, self.fixture(directory):
            result = demo.prepare("offline", "preflight")
            plan = demo.checked(result["plan_sha256"])
            self.assertEqual(plan["independent_new_task_count"], 1)
            self.assertEqual(len(plan["items"]), 2)
            self.assertEqual(len(plan["reserved_repair_run_ids"]), 2)
            self.assertEqual(len({item["run_id"] for item in plan["items"]} | set(plan["reserved_repair_run_ids"])), 4)
            self.assertEqual(plan["campaign_limits"], {"max_decisions": 64, "max_tokens_accounted": 384000, "max_seconds": 1800})
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertFalse(plan["old_budget_reused"])
            self.assertFalse(plan["automatic_repair"])
            self.assertTrue(all(spec["version"].endswith("v3") for spec in plan["child_specs"].values()))

    def test_rehash_cannot_change_task_request_slot_count_or_original_local_limits(self):
        for mutate in (lambda p: p["campaign_limits"].update(max_decisions=65), lambda p: p.update(maximum_campaign_runs=5),
                lambda p: p["items"][0]["request"].update(question="changed"), lambda p: p.update(automatic_repair=True)):
            with self.subTest(mutate=mutate), TemporaryDirectory() as directory, self.fixture(directory):
                demo.prepare("offline", "preflight")
                plan = demo.OLD.read(demo.OUT / "plan.json")
                mutate(plan)
                (demo.OUT / "plan.json").write_text(canonical_json(plan), encoding="utf-8")
                with self.assertRaises(IntegrityError):
                    demo.checked(demo.OLD.sha(demo.OUT / "plan.json"))

    def test_cli_cannot_start_without_full_gate_and_explicit_frozen_sha(self):
        with patch.object(demo, "prepare") as prepare, patch.object(demo, "live") as live:
            for args in (["--prepare"], ["--live"], ["--worker", "--variant", "candidate"]):
                with self.assertRaises(SystemExit):
                    demo.main(args)
            prepare.assert_not_called()
            live.assert_not_called()

    def test_gate_rejects_synthetic_or_non_overlimit_page_or_failed_offline_evidence(self):
        task = {"synthetic_mechanism_only": True}
        evidence = {"path": "synthetic.log", "sha256": digest("log")}
        offline = {"schema": "real-pagination-offline-gate/v1", "status": "passed", "failures": 0, "errors": 0,
            "tests_run": 1000, "skipped": 14, "command": "PYTHONPATH=src python -m unittest discover -s tests -v",
            "code_files": {"synthetic.py": digest("code")}, "test_files": {"synthetic_test.py": digest("test")}, "log": evidence}
        probe = {"schema": "real-pagination-readonly-preflight/v1", "status": "passed", "task_sha256": digest(task),
            "baseline_requested_closure_bytes": 12001, "baseline_typed_budget_rejected": True,
            "candidate_object_page_count": 2, "candidate_total_context_reads": 3, "candidate_max_wire_bytes": 12000,
            "candidate_complete_target_atoms": True, "target_refs_hidden_in_question": True,
            "original_sources_grants_pit_oracle_revalidated": True, "historical_files_unchanged": True,
            "historical_hashes": {"old": "preserved"}, "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}
        probe["historical_completed_zero_append_replay"] = {"status": "passed", "completed_reports_replayed": 39,
            "all_identical": True, "historical_hashes": probe["historical_hashes"], "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}
        for group, delta in ((None, {}), ("offline", {"status": "failed"}), ("offline", {"skipped": 1000}),
                ("probe", {"baseline_requested_closure_bytes": 12000}), ("probe", {"candidate_total_context_reads": 4}),
                ("probe", {"candidate_complete_target_atoms": False}), ("probe", {"model_calls": 1})):
            with self.subTest(group=group, delta=delta), ExitStack() as stack:
                stack.enter_context(patch.object(demo.OLD, "read", side_effect=[{**offline, **(delta if group == "offline" else {})},
                    {**probe, **(delta if group == "probe" else {})}]))
                stack.enter_context(patch.object(demo, "evidence_ref", return_value=evidence))
                stack.enter_context(patch.object(demo, "code_files", return_value=offline["code_files"]))
                stack.enter_context(patch.object(demo.prior, "test_files", return_value=offline["test_files"]))
                stack.enter_context(patch.object(demo, "sources", return_value=SimpleNamespace(build_task=lambda: task)))
                stack.enter_context(patch.object(demo, "history_hashes", return_value=probe["historical_hashes"]))
                if group is None:
                    self.assertEqual(demo.validate_gate("offline", "preflight"), (offline, probe))
                else:
                    with self.assertRaises(IntegrityError):
                        demo.validate_gate("offline", "preflight")


class RealPaginationEvidenceTests(unittest.TestCase):
    def test_live_read_is_read_only_closes_connection_and_observes_new_committed_rows(self):
        with TemporaryDirectory() as directory:
            run, scope = "0" * 32, "synthetic-only"
            store = demo.CheckpointStore(directory)
            store.append(scope, run, {"synthetic_only": 1})
            self.assertEqual(demo.live_history(directory, scope, run), [{"synthetic_only": 1}])
            store.append(scope, run, {"synthetic_only": 2})
            self.assertEqual(demo.live_history(directory, scope, run), [{"synthetic_only": 1}, {"synthetic_only": 2}])
            with self.assertRaises(IntegrityError):
                demo.live_history(directory, "different-scope", run)
            with demo.closing(demo.sqlite3.connect(Path(directory) / "checkpoints.sqlite3")) as connection:
                connection.execute("UPDATE checkpoints SET hash=? WHERE seq=1", ("changed",))
                connection.commit()
            with self.assertRaises(IntegrityError):
                demo.live_history(directory, scope, run)

    def test_pending_or_precommit_page_interruption_cannot_be_replayed_as_committed_safe_recovery(self):
        item = {"run_id": "1" * 32, "scope": "synthetic-only"}
        receipt = {"synthetic_mechanism_only": True}
        marker = {"trace_seq": 0, "deadline": "2026-10-08T00:00:00+00:00", "turn": 1,
            "page_receipt": receipt, "pending_action": None, "pending_tool": None}
        state = {"trace": [{"seq": 0, "event": "tool_finished", "tool": "context_read"}],
            "pending_action": None, "pending_tool": None, "window_store": {"receipts": [receipt]},
            "deadline": marker["deadline"], "run_id": item["run_id"], "model_attempts": 1, "phase": "observed"}
        for change in ("pending_tool", "precommit", "deadline"):
            changed = deepcopy(state)
            if change == "pending_tool":
                changed["pending_tool"] = {"tool": "context_read", "tool_call_id": "synthetic-only"}
            elif change == "precommit":
                changed["trace"][-1]["event"] = "context_page_read"
            else:
                changed["deadline"] = "2026-10-09T00:00:00+00:00"
            with self.subTest(change=change), patch.object(demo.OLD, "read", return_value=marker), \
                    patch.object(demo.prior, "readonly_history", return_value=[changed]):
                with self.assertRaises(IntegrityError):
                    demo.recovery_boundary(item, "synthetic-only")
    def test_complete_source_wire_guard_and_typed_baseline_closure_with_scripted_test_transport(self):
        # Existing source data exercises guard interoperability. Financial/model
        # validation still requires the separately frozen real campaign.
        task = demo.sources().build_task()
        with TemporaryDirectory() as directory:
            path = Path(directory)
            item = demo.frozen_item(task, "baseline", "e" * 32)
            dispatch = path / "dispatch"
            dispatch.mkdir()
            ScriptedSourceMechanismAdapter.targets = item["goal_refs"]
            with patch.object(demo, "ChatModelAdapter", ScriptedSourceMechanismAdapter):
                model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=120), dispatch, [item])
                model.item, model.checkpoints = item, path / "runs"
                service, access = demo.sources().context(task)
                report = demo.runtime(service, demo.CheckpointStore(model.checkpoints), "baseline", model).run(
                    demo.DynamicRequest.from_dict(item["request"]), access, run_id=item["run_id"])
            self.assertEqual(report["stop_reason"], "dynamic_context_budget_exceeded", report["stop_reason"])
            result = demo.baseline_overflow(item, report, path)
            self.assertTrue(result["actual_model_disclose"])
            child_reports = demo.children(path, item, report)
            usage = demo.paid_usage(item, report, child_reports, dispatch, model.ledger.intents)
            self.assertTrue(usage["root_usage_same"])
            self.assertEqual(usage["exact_paid_turns"], 8)
            with patch.object(demo.CheckpointStore, "append", side_effect=AssertionError("no append")):
                replay = demo.runtime(service, demo.CheckpointStore(model.checkpoints), "baseline", demo.prior.original.NoNetwork()).run(
                    demo.DynamicRequest.from_dict(item["request"]), access, resume=item["run_id"])
            self.assertEqual(replay, report)

    def test_scripted_candidate_full_source_guards_exact_pages_actual_verification_and_zero_append_completion(self):
        task = demo.sources().build_task()
        with TemporaryDirectory() as directory:
            path = Path(directory)
            item = demo.frozen_item(task, "candidate", "c" * 32)
            dispatch = path / "dispatch"
            dispatch.mkdir()
            ScriptedSourceMechanismAdapter.targets = item["goal_refs"]
            with patch.object(demo, "ChatModelAdapter", ScriptedSourceMechanismAdapter):
                model = demo.RecordingModel(CONFIG, utcnow() + timedelta(seconds=120), dispatch, [item])
                model.item, model.checkpoints = item, path / "runs"
                service, access = demo.sources().context(task)
                report = demo.runtime(service, demo.CheckpointStore(model.checkpoints), "candidate", model).run(
                    demo.DynamicRequest.from_dict(item["request"]), access, run_id=item["run_id"])
            self.assertEqual(report["status"], "completed", {"stop": report["stop_reason"], "test_driver_errors": ScriptedSourceMechanismAdapter.errors,
                "last_receipt_type": demo.OLD.read(sorted(dispatch.glob("*-receipt.json"))[-1]).get("error_type"),
                "test_driver_discoveries": ScriptedSourceMechanismAdapter.discoveries})
            self.assertTrue(demo.sources().assess_complete(item, report)["functional_passed"])
            page_audit = demo.atom_coverage(item, report, model.checkpoints)
            self.assertTrue(page_audit["complete_original_target_c_objects"])
            self.assertEqual(page_audit["actual_object_page_count"], 2)
            self.assertEqual(page_audit["actual_discovery_page_count"], 1)
            self.assertEqual(page_audit["complete_claim_count"], 7)
            self.assertFalse(page_audit["full_evidence_objects_read"])
            child_reports = demo.children(path, item, report)
            self.assertTrue(demo.paid_usage(item, report, child_reports, dispatch, model.ledger.intents)["root_usage_same"])
            self.assertEqual(model.ledger.snapshot()["decisions"], 12)
            self.assertEqual(report["usage"]["model_attempts"], 8)
            before = demo.prior.original.file_hashes(path)
            with patch.object(demo.CheckpointStore, "append", side_effect=AssertionError("no append")):
                replay = demo.runtime(service, demo.CheckpointStore(model.checkpoints), "candidate", demo.prior.original.NoNetwork()).run(
                    demo.DynamicRequest.from_dict(item["request"]), access, resume=item["run_id"])
            self.assertEqual(replay, report)
            self.assertEqual(demo.prior.original.file_hashes(path), before)
    def test_actual_requested_baseline_overflow_is_typed_undispatched_and_not_an_efficiency_win(self):
        item = {"scope": "synthetic-only", "run_id": "a" * 32, "goal_refs": ["C:F1"]}
        action = {"action": "disclose", "refs": ["C:F1"]}
        state = {"context_store": {"disclosures": [{"turn": 1, "refs": ["C:F1"]}]}, "decisions": [{"action": action}]}
        report = {"status": "partial", "stop_reason": "dynamic_context_budget_exceeded", "context_telemetry": [
            {"context_budget_exceeded": True, "model_dispatched": False, "total_context_bytes": 12001}]}
        wire = [{"content": "x" * 12000}, {"content": "x"}]
        with patch.object(demo.prior, "readonly_history", return_value=[state]), \
                patch.object(demo, "sources", return_value=SimpleNamespace(baseline_disclosure=lambda *args, **kwargs: (wire, {}))):
            result = demo.baseline_overflow(item, report, "synthetic-only")
            self.assertTrue(result["oversized_attempt_not_dispatched"])
            self.assertFalse(result["default_mandatory_stage_overflow_claim"])
            for delta in ({"model_dispatched": True}, {"total_context_bytes": 12000}):
                changed = deepcopy(report)
                changed["context_telemetry"][0].update(delta)
                with self.assertRaises(IntegrityError):
                    demo.baseline_overflow(item, changed, "synthetic-only")

    def page_fixture(self):
        item = {"variant": "candidate", "scope": "synthetic-only", "run_id": "b" * 32,
            "goal_refs": ["C:F1"], "goal_objects": {"C:F1": {"formula": "synthetic-only", "inputs": ["E:E1", "E:E2"], "value": "1"}}}
        atoms = list(_atoms("C:F1", item["goal_objects"]["C:F1"]))
        middle = len(atoms) // 2
        selections = [{"kind": "objects", "refs": item["goal_refs"], "start": start, "end": end}
            for start, end in ((0, middle), (middle, len(atoms)))]
        pages = [{"selection": selection, "start": selection["start"], "end": selection["end"], "total": len(atoms),
            "has_more": index == 0, "atoms": atoms[selection["start"]:selection["end"]],
            "content_hash": digest(atoms[selection["start"]:selection["end"]])} for index, selection in enumerate(selections)]
        receipts = [{"turn": index + 1, "tool_call_id": str(index), "selection_after": selections[index],
            "content_hash": pages[index]["content_hash"]} for index in range(2)]
        windows = [{"turn": 1, "allowed_refs": item["goal_refs"], "cursors": {}, "window_ref": "first"},
            {"turn": 2, "allowed_refs": item["goal_refs"], "cursors": {"current": {**selections[1], "end": None}}, "window_ref": "second"}]
        state = {"window_store": {"receipts": receipts, "windows": windows}, "decisions": [
            {"action": {"action": "context_read", "refs": item["goal_refs"]}},
            {"action": {"action": "context_read", "cursor": "current"}}]}
        report = {"trace": [{"event": "tool_finished", "tool": "hypotheses", "seq": 1},
            {"event": "tool_finished", "tool": "context_read", "tool_call_id": "0", "seq": 2},
            {"event": "tool_finished", "tool": "context_read", "tool_call_id": "1", "seq": 3},
            {"event": "tool_started", "tool": "verification", "seq": 4}]}
        return item, state, report, pages

    def test_complete_page_atoms_current_cursor_and_hypothesis_to_verification_order_are_required(self):
        for change in (None, "stale_cursor", "after_verification", "before_hypotheses", "missing_field"):
            item, state, report, pages = self.page_fixture()
            if change == "stale_cursor":
                state["decisions"][1]["action"]["cursor"] = "old"
            elif change == "after_verification":
                report["trace"][2]["seq"] = 5
            elif change == "before_hypotheses":
                report["trace"][1]["seq"] = 0
            elif change == "missing_field":
                pages[-1]["atoms"].pop()
            with self.subTest(change=change), patch.object(demo.prior, "readonly_history", return_value=[state]), \
                    patch.object(demo._helpers, "page_audit", return_value={"exact_page_receipts": []}), \
                    patch.object(demo, "sources", return_value=SimpleNamespace(exact_goal_collection=lambda *args: ({}, {}))), \
                    patch.object(demo, "rebuild_selection", side_effect=pages):
                if change is None:
                    result = demo.atom_coverage(item, report, "synthetic-only")
                    self.assertTrue(result["complete_original_target_c_objects"])
                    self.assertFalse(result["full_evidence_objects_read"])
                else:
                    with self.assertRaises((IntegrityError, demo.ValidationError)):
                        demo.atom_coverage(item, report, "synthetic-only")

    def test_real_process_exit_only_after_committed_tool_finished_and_fresh_process_reads_same_deadline(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            run, deadline = "d" * 32, (utcnow() + timedelta(seconds=60)).isoformat()
            script = "\n".join((
                "import sys", f"sys.path.insert(0, {str(demo.OLD.ROOT / 'scripts')!r})", "import context_real_pagination_acceptance as d",
                f"item={{'run_id':{run!r},'scope':'synthetic-only'}}", f"store=d.PauseAfterCommittedRead({str(path / 'runs')!r},item,{str(path)!r})",
                f"state={{'run_id':{run!r},'deadline':{deadline!r},'model_attempts':1,'pending_action':None,'pending_tool':None,'phase':'observed',",
                "'window_store':{'receipts':[{'synthetic_mechanism_only':True}]},'trace':[{'event':'tool_finished','tool':'context_read','tool_call_id':'read1','seq':0}]}",
                "store.append('synthetic-only',item['run_id'],state)", "raise AssertionError('should have exited after commit')"))
            environment = {**os.environ, "PYTHONPATH": str(demo.OLD.ROOT / "src")}
            first = subprocess.run([sys.executable, "-c", script], cwd=demo.OLD.ROOT, env=environment, capture_output=True)
            self.assertEqual(first.returncode, demo.PAUSE_EXIT, first.stderr.decode(errors="replace"))
            marker = demo.OLD.read(path / "committed-page-process-exit.json")
            self.assertNotEqual(marker["pid"], os.getpid())
            boundary = demo.recovery_boundary({"run_id": run, "scope": "synthetic-only"}, path)
            self.assertEqual(boundary["deadline"], deadline)
            self.assertTrue(boundary["first_committed_read_before_next_paid"])
            second_script = "\n".join(("import sys", f"sys.path.insert(0, {str(demo.OLD.ROOT / 'scripts')!r})", "import context_real_pagination_acceptance as d",
                f"state=d.prior.readonly_history({str(path / 'runs')!r},'synthetic-only',{run!r})[-1]",
                f"assert state['deadline']=={deadline!r}", "assert state['pending_tool'] is None", "assert state['model_attempts']==1"))
            second = subprocess.run([sys.executable, "-c", second_script], cwd=demo.OLD.ROOT, env=environment, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
