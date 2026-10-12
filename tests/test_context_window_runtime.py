"""Synthetic v6 window/transaction safety; no live financial ground truth."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import test_context_verification_decoupling as v4
from test_dynamic import SequenceModel, completed_actions, finish, tool
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import digest
from stock_research.research.dynamic_contracts import ParallelParentSpec
from stock_research.research.context_window import rebuild_selection

VERSION = "dynamic-parent-parallel-v6"
RUN = "b" * 32


class WindowRuntimeTests(unittest.TestCase):
    runtime = v4.VerificationDisclosureTests.runtime
    inputs = v4.VerificationDisclosureTests.inputs
    grant_service = v4.VerificationDisclosureTests.grant_service
    rewrite_history = v4.VerificationDisclosureTests.rewrite_history
    research_signature = staticmethod(v4.VerificationDisclosureTests.research_signature)

    def setUp(self):
        v4.VerificationDisclosureTests.setUp(self)
        self.spec = ParallelParentSpec(version=VERSION)

    def complete(self, *, request=None, service=None, version=VERSION):
        return v4.VerificationDisclosureTests.complete(self, request=request, service=service, version=version)

    def decide_pages(self, turn, messages):
        context = json.loads(messages[1]["content"])["context"]
        if turn <= 3:
            return completed_actions()[turn - 1]
        if turn in {4, 5}:
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                    "refs": ["O:financial"] if turn == 4 else ["O:market"], "plan": ["Inspect exact bound page"]}
        return completed_actions()[turn - 3]

    def page_report(self):
        model = SequenceModel([], callback=self.decide_pages)
        report = self.runtime(model).run(self.request, self.f.access, run_id=RUN)
        self.assertEqual(report["status"], "completed")
        return report, model

    def test_two_working_set_replacements_keep_complete_verifier_and_zero_append_replay(self):
        report, model = self.page_report()
        self.assertEqual(model.calls, 8)
        self.assertEqual(report["usage"]["tool_calls"], 7)
        receipts = report["context_archive"]["page_receipts"]
        self.assertEqual(len(receipts), 2)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(state["schema"], "dynamic-window-state/v1")
        self.assertIsNone(state["window_store"]["selection"])
        for receipt in receipts:
            page = rebuild_selection(state["context_store"]["catalogs"][receipt["catalog_ref"]],
                receipt["selection_after"], scope=self.f.access.scope, run_id=RUN)
            self.assertEqual(receipt["content_hash"], page["content_hash"])
        self.assertEqual(report["verification_execution"]["turn"], 7)
        self.assertTrue(all(c["status"] == "passed" for c in report["required_checks"]))
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
            self.assertEqual(self.runtime(fresh).run(self.request, self.f.access, resume=RUN), report)
            append.assert_not_called()
        self.assertEqual(fresh.calls, 0)
        self.assertTrue(all(sum(len(m["content"].encode()) for m in wire) <= 12000 for wire in model.messages))

    def test_guessed_hidden_reference_never_dispatches_a_read(self):
        def decide(turn, messages):
            context = json.loads(messages[1]["content"])["context"]
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                    "refs": ["E:E99999"], "plan": ["Inspect"]}
        model = SequenceModel([], callback=decide)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(report["usage"]["tool_calls"], 0)
        self.assertEqual(report["context_archive"]["page_receipts"], [])

    def test_repeated_member_page_counts_attempt_and_two_no_progress_stop(self):
        def decide(turn, messages):
            if turn <= 3:
                return completed_actions()[turn - 1]
            context = json.loads(messages[1]["content"])["context"]
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                    "refs": ["O:financial"], "plan": ["Inspect"]}
        model = SequenceModel([], callback=decide)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(len(report["context_archive"]["page_receipts"]), 1)
        self.assertEqual(report["usage"]["tool_calls"], 5)
        self.assertEqual(next(c["status"] for c in report["required_checks"] if c["id"] == "verification"), "not_completed")

    def test_rehashed_page_receipt_content_or_boundary_tamper_is_rejected(self):
        for field in ("content_hash", "ordered_slice", "selection_after", "coverage"):
            with self.subTest(field=field):
                if field != "content_hash":
                    self.setUp()
                report, _ = self.page_report()
                def mutate(states):
                    for saved in states:
                        if not saved["window_store"]["receipts"]:
                            continue
                        if field == "coverage":
                            saved["window_store"]["coverage"] = []
                        else:
                            receipt = saved["window_store"]["receipts"][0]
                            if field == "content_hash":
                                receipt[field] = "0" * 64
                            elif field == "ordered_slice":
                                receipt[field][1] += 1
                            else:
                                receipt[field]["end"] += 1
                self.rewrite_history(RUN, mutate)
                model = SequenceModel([])
                with self.assertRaises((IntegrityError, PermissionDenied)):
                    self.runtime(model).run(self.request, self.f.access, resume=RUN)
                self.assertEqual(model.calls, 0)

    def test_optional_page_cannot_consume_finish_headroom(self):
        def decide(turn, messages):
            if turn <= 3:
                return completed_actions()[turn - 1]
            context = json.loads(messages[1]["content"])["context"]
            if turn == 6:
                self.assertFalse(json.loads(messages[1]["content"])["control"]["context_budget"]["context_read_available"])
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                    "refs": ["O:financial"] if turn != 5 else ["O:market"], "plan": ["Inspect"]}
        report = self.runtime(SequenceModel([], callback=decide)).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(len(report["context_archive"]["page_receipts"]), 2)

    def test_revocation_before_verification_blocks_actual_tool(self):
        service, grants = self.grant_service()
        def decide(turn, messages):
            if turn == 5:
                self.assertIn("verification_brief", json.loads(messages[1]["content"])["context"])
                grants.clear()
            return completed_actions()[turn - 1]
        model = SequenceModel([], callback=decide)
        with self.assertRaises(PermissionDenied):
            self.runtime(model, service=service).run(self.request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertNotIn("verification_execution", state)
        self.assertFalse(any(e["event"] == "tool_started" and e["tool"] == "verification" for e in state["trace"]))


for _name in (
    "test_original_verifier_rejects_rehashed_value_source_reference_time_and_omission",
    "test_lawful_insufficient_requires_actual_verification_and_preserves_all_gaps",
    "test_completed_children_do_not_replace_parent_verification_execution",
    "test_same_parent_explicit_child_v3_direct_serial_parallel_paths_preserve_quality_and_replay",
    "test_revocation_during_verifier_prevents_a_successful_execution_receipt",
    "test_revocation_during_final_revalidation_blocks_report_delivery",
    "test_completed_replay_reauthorizes_scope_provider_grants_and_unchanged_snapshot",
    "test_finished_recovery_rejects_stale_revision_or_changed_verification_receipt",
    "test_hash_valid_history_forgery_cannot_replace_actual_verification_execution",
    "test_current_recovered_calculation_cannot_omit_an_executed_source",
    "test_unknown_paid_result_never_replays_or_releases_reserved_usage",
    "test_completed_replay_refuses_underlying_artifact_tamper_without_model_or_append",
):
    setattr(WindowRuntimeTests, _name, getattr(v4.VerificationDisclosureTests, _name))


if __name__ == "__main__":
    unittest.main()
