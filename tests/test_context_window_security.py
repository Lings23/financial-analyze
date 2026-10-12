"""Independent synthetic v6 transaction/restore attacks; no external requests."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_context_verification_decoupling as v4
from test_dynamic import SequenceModel, completed_actions
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.research import context_window
from stock_research.research.dynamic_contracts import ParallelParentSpec


VERSION = "dynamic-parent-parallel-v6"
RUN = "c" * 32


class WindowSecurityTests(unittest.TestCase):
    runtime = v4.VerificationDisclosureTests.runtime
    inputs = v4.VerificationDisclosureTests.inputs
    grant_service = v4.VerificationDisclosureTests.grant_service
    rewrite_history = v4.VerificationDisclosureTests.rewrite_history

    def setUp(self):
        v4.VerificationDisclosureTests.setUp(self)
        self.spec = ParallelParentSpec(version=VERSION)

    def decide_one_page(self, turn, messages):
        if turn <= 3:
            return completed_actions()[turn - 1]
        context = json.loads(messages[1]["content"])["context"]
        if turn == 4:
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                "refs": ["O:financial"], "plan": ["Inspect exact bound financial page"]}
        return completed_actions()[turn - 2]

    def complete_page(self, *, service=None):
        model = SequenceModel([], callback=self.decide_one_page)
        report = self.runtime(model, service=service).run(self.request, self.f.access, run_id=RUN)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(report["context_archive"]["page_receipts"]), 1)
        return report, model

    def fault_run(self, *, point, service=None):
        original = self.f.store.append
        def crash(scope, run, state):
            last = state["trace"][-1] if state["trace"] else {}
            matches = (last.get("event") == "tool_started" and last.get("tool") == "context_read"
                if point == "started" else last.get("event") == "context_page_read"
                if point in {"before_receipt", "after_receipt"} else
                last.get("event") == "tool_finished" and last.get("tool") == "context_read")
            if matches and point == "before_receipt":
                raise KeyboardInterrupt()
            original(scope, run, state)
            if matches:
                raise KeyboardInterrupt()
        model = SequenceModel([], callback=self.decide_one_page)
        with patch.object(self.f.store, "append", side_effect=crash), self.assertRaises(KeyboardInterrupt):
            self.runtime(model, service=service).run(self.request, self.f.access, run_id=RUN)
        self.assertEqual(model.calls, 4)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(state["schema"], "dynamic-window-state/v1")
        return state

    def test_started_and_pre_receipt_faults_stop_unknown_without_model_or_read_replay(self):
        for point in ("started", "before_receipt"):
            with self.subTest(point=point):
                if point != "started":
                    self.setUp()
                saved = self.fault_run(point=point)
                self.assertEqual(saved["window_store"]["receipts"], [])
                self.assertEqual(saved["window_store"]["coverage"], [])
                self.assertEqual(saved["pending_tool"]["tool"], "context_read")
                fresh = SequenceModel([])
                with patch.object(context_window, "select_next", wraps=context_window.select_next) as select:
                    report = self.runtime(fresh).run(self.request, self.f.access, resume=RUN)
                self.assertEqual(report["stop_reason"], "unknown_tool_outcome_no_replay")
                self.assertEqual(fresh.calls, 0)
                self.assertEqual(report["usage"]["tool_calls"], saved["tools_used"])
                self.assertEqual(report["usage"]["tokens_reserved"], saved["tokens_reserved"])
                self.assertEqual(report["context_archive"]["page_receipts"], [])
                select.assert_not_called()  # There was no completed read to rebuild.

    def test_after_receipt_fault_retains_atomic_selection_coverage_and_stops_without_replay(self):
        saved = self.fault_run(point="after_receipt")
        receipts = saved["window_store"]["receipts"]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(saved["window_store"]["selection"], receipts[0]["selection_after"])
        self.assertTrue(saved["window_store"]["coverage"])
        self.assertEqual(saved["pending_tool"]["tool"], "context_read")
        fresh = SequenceModel([])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(report["stop_reason"], "unknown_tool_outcome_no_replay")
        self.assertEqual(fresh.calls, 0)
        self.assertEqual(report["context_archive"]["page_receipts"], receipts)
        self.assertEqual(report["context_archive"]["read_coverage"], saved["window_store"]["coverage"])
        self.assertEqual(report["usage"]["tool_calls"], saved["tools_used"])

    def test_completed_receipt_fault_resumes_business_only_with_no_second_read(self):
        saved = self.fault_run(point="finished")
        self.assertIsNone(saved["pending_tool"])
        fresh = SequenceModel(completed_actions()[3:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(fresh.calls, 3)
        self.assertEqual(len(report["context_archive"]["page_receipts"]), 1)
        self.assertEqual(sum(event["event"] == "tool_started" and event["tool"] == "context_read"
                             for event in report["trace"]), 1)
        self.assertEqual(report["usage"]["tool_calls"], 6)

    def test_revocation_before_read_dispatch_prevents_intent_and_page_receipt(self):
        service, grants = self.grant_service()
        def decide(turn, messages):
            if turn == 4:
                grants.clear()
            return self.decide_one_page(turn, messages)
        model = SequenceModel([], callback=decide)
        with self.assertRaises(PermissionDenied):
            self.runtime(model, service=service).run(self.request, self.f.access, run_id=RUN)
        saved = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(model.calls, 4)
        self.assertEqual(saved["window_store"]["receipts"], [])
        self.assertFalse(any(event["event"] == "tool_started" and event["tool"] == "context_read"
                             for event in saved["trace"]))

    def test_revocation_during_page_read_blocks_selection_receipt_and_next_model(self):
        service, grants = self.grant_service()
        original = context_window.rebuild_selection
        revoked = []
        def revoke(catalog, selection, **kwargs):
            result = original(catalog, selection, **kwargs)
            state = self.f.store.read(self.f.access.scope, RUN)
            if (state.get("pending_tool") or {}).get("tool") == "context_read" and not revoked:
                revoked.append(True)
                grants.clear()
            return result
        model = SequenceModel([], callback=self.decide_one_page)
        with patch.object(context_window, "rebuild_selection", side_effect=revoke), self.assertRaises(PermissionDenied):
            self.runtime(model, service=service).run(self.request, self.f.access, run_id=RUN)
        saved = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(model.calls, 4)
        self.assertTrue(revoked)
        self.assertEqual(saved["window_store"]["receipts"], [])
        self.assertEqual(saved["window_store"]["coverage"], [])
        self.assertIsNone(saved["window_store"]["selection"])
        self.assertTrue(any(event["event"] == "tool_started" and event["tool"] == "context_read"
                            for event in saved["trace"]))
        self.assertFalse(any(event["event"] == "tool_finished" and event["tool"] == "context_read"
                             for event in saved["trace"]))

    def test_restore_page_intent_reauthorizes_before_unknown_stop_and_appends_nothing(self):
        service, grants = self.grant_service()
        self.fault_run(point="started", service=service)
        grants.clear()
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append, self.assertRaises(PermissionDenied):
            self.runtime(fresh, service=service).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(fresh.calls, 0)
        self.assertEqual(append.call_count, 1)
        persisted = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(persisted["trace"][-1]["event"], "security_stopped")
        self.assertEqual(persisted["window_store"]["receipts"], [])

    def test_coordinated_rehash_cannot_change_committed_receipt_boundary_before_next_paid_turn(self):
        saved = self.fault_run(point="after_receipt")
        self.assertGreater(saved["window_store"]["selection"]["end"], 1)
        def mutate(states):
            for state in states:
                store = state["window_store"]
                if not store["receipts"]:
                    continue
                receipt = store["receipts"][0]
                selected = {**receipt["selection_after"], "end": receipt["selection_after"]["end"] - 1}
                catalog = state["context_store"]["catalogs"][receipt["catalog_ref"]]
                page = context_window.rebuild_selection(catalog, selected,
                    scope=self.f.access.scope, run_id=RUN)
                receipt.update(selection_after=selected, ordered_slice=[page["start"], page["end"]],
                               content_hash=page["content_hash"])
                store["selection"] = deepcopy(selected)
                store["coverage"] = context_window.merge_coverage(catalog, selected, [],
                    scope=self.f.access.scope, run_id=RUN)
                for event in state["trace"]:
                    if event["event"] == "context_page_read":
                        event["receipt"] = deepcopy(receipt)
        self.rewrite_history(RUN, mutate)
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
            with self.assertRaises((IntegrityError, PermissionDenied, ValidationError)):
                self.runtime(fresh).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(fresh.calls, 0)
        self.assertEqual(append.call_count, 1)
        persisted = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(persisted["trace"][-1]["event"], "security_stopped")

    def test_precommit_intent_budget_must_match_its_already_charged_tool_trace(self):
        self.fault_run(point="after_receipt")
        def mutate(states):
            for state in states:
                if (state["trace"] and state["trace"][-1]["event"] == "tool_started"
                        and state["trace"][-1]["tool"] == "context_read"):
                    # Earlier three business calls and the later read receipt
                    # preserve monotonic totals; only the compile intent lies.
                    state["tools_used"] -= 1
        self.rewrite_history(RUN, mutate)
        fresh = SequenceModel([])
        with self.assertRaises((IntegrityError, PermissionDenied, ValidationError)):
            self.runtime(fresh).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(fresh.calls, 0)

    def test_rehashed_history_rejects_deleted_reordered_or_forged_paid_pages_and_coverage(self):
        for tamper in ("delete_page", "reorder_pages", "delete_window", "paid_descriptor", "duplicate_coverage", "invent_coverage"):
            with self.subTest(tamper=tamper):
                if tamper != "delete_page":
                    self.setUp()
                self.complete_page()
                def mutate(states):
                    for state in states:
                        store = state["window_store"]
                        for window in store["windows"]:
                            if tamper == "delete_page" and window["pages"]:
                                window["pages"] = window["pages"][:-1]
                            elif tamper == "reorder_pages" and len(window["pages"]) > 1:
                                window["pages"] = list(reversed(window["pages"]))
                            elif tamper == "paid_descriptor":
                                window["dispatch_ref"] = "0" * 64
                        if tamper == "delete_window" and store["windows"]:
                            store["windows"] = store["windows"][:-1]
                        if store["coverage"]:
                            if tamper == "duplicate_coverage":
                                store["coverage"].append(deepcopy(store["coverage"][0]))
                            elif tamper == "invent_coverage":
                                store["coverage"][0]["paths"].append(["never_read"])
                self.rewrite_history(RUN, mutate)
                fresh = SequenceModel([])
                with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
                    with self.assertRaises((IntegrityError, PermissionDenied, ValidationError)):
                        self.runtime(fresh).run(self.request, self.f.access, resume=RUN)
                self.assertEqual(fresh.calls, 0)
                append.assert_not_called()

    def test_cursor_from_prior_paid_window_is_stale_even_without_business_catalog_change(self):
        old = {}
        def decide(turn, messages):
            if turn <= 3:
                return completed_actions()[turn - 1]
            context = json.loads(messages[1]["content"])["context"]
            saved = self.f.store.read(self.f.access.scope, RUN)
            issued = saved["window_store"]["windows"][-1]
            if turn == 4:
                self.assertTrue(issued["allowed_cursors"])
                old.update(cursor=issued["allowed_cursors"][0], catalog=context["catalog_ref"])
                return self.decide_one_page(turn, messages)
            self.assertEqual(context["catalog_ref"], old["catalog"])
            self.assertNotIn(old["cursor"], issued["allowed_cursors"])
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                "cursor": old["cursor"], "plan": ["Inspect prior continuation"]}
        model = SequenceModel([], callback=decide)
        report = self.runtime(model).run(self.request, self.f.access, run_id=RUN)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(model.calls, 6)
        self.assertEqual(len(report["context_archive"]["page_receipts"]), 1)
        self.assertEqual(report["usage"]["tool_calls"], 4)

    def test_recombining_fully_read_members_does_not_create_progress(self):
        def decide(turn, messages):
            if turn <= 3:
                return completed_actions()[turn - 1]
            context = json.loads(messages[1]["content"])["context"]
            refs = ["O:financial", "O:market"] if turn == 4 else ["O:market", "O:financial"] if turn == 5 else ["O:financial"]
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                "refs": refs, "plan": ["Inspect exact bound members"]}
        model = SequenceModel([], callback=decide)
        report = self.runtime(model).run(self.request, self.f.access, run_id=RUN)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(len(report["context_archive"]["page_receipts"]), 1)
        # The reordered combination executes a charged duplicate. Its following
        # subset is rejected at the remaining business/finish headroom boundary.
        self.assertEqual(report["usage"]["tool_calls"], 5)
        self.assertEqual(sum(event["event"] == "tool_failed" and event["tool"] == "context_read"
                             for event in report["trace"]), 1)
        self.assertEqual(self.f.store.read(self.f.access.scope, RUN)["decisions"][-1]["status"], "invalid_action")
        self.assertFalse(any(check["id"] == "verification" and check["status"] == "passed"
                             for check in report["required_checks"]))


if __name__ == "__main__":
    unittest.main()
