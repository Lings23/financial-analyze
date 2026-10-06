"""Synthetic M1 closure and serial Financial Child safety; no live financial truth."""
import copy
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel, completed_actions, finish, tool
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DYNAMIC_TOOLS, DynamicRequest, DynamicSpec,
    FinancialChildSpec, FinancialParentSpec, FinancialRequest)
from stock_research.research.root_budget import new_root_budget
from stock_research.research.scoped import ScopedReadService, SourceGrant


def parent_actions(child=None):
    return [tool("financial_child"), *(child or [tool("financial"), finish()]),
            *completed_actions(("market",))[0:1], tool("calculation", ["financial", "market"]),
            tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()]


class DynamicChildrenTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({**study_request(self.f,
            hypotheses=("financial_deterioration",)).to_dict(), "question": "SYNTHETIC: delegate bound financial read"})

    def runtime(self, model, spec=None, **kwargs):
        return DynamicRuntime(self.f.service, self.f.store, model, spec or FinancialParentSpec(), **kwargs)

    def test_v2_rejects_premature_insufficient_then_continues_same_budget(self):
        actions = completed_actions()
        actions.insert(3, finish("insufficient"))
        model = SequenceModel(actions)
        report = self.runtime(model, DynamicSpec(version="single-dynamic-v2")).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        rejected = report["decisions"][3]["rejection"]
        self.assertEqual(rejected["code"], "required_checks_pending")
        self.assertIn("hypotheses", rejected["pending_checks"])
        self.assertIn("verification", rejected["pending_checks"])
        self.assertEqual(json.loads(model.messages[4][1]["content"])["control"]["finish_rejection"], rejected)
        self.assertEqual(report["usage"]["model_attempts"], 7)
        self.assertEqual(report["usage"]["total_tokens"], 840)
        self.assertEqual(report["usage"]["tool_calls"], 5)

    def test_two_premature_finishes_stop_without_unbounded_repair_or_reads(self):
        model = SequenceModel([finish(), finish("insufficient")])
        with patch.object(self.f.service, "query", side_effect=AssertionError("premature finish reads")):
            report = self.runtime(model, DynamicSpec(version="single-dynamic-v2")).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(report["usage"]["model_attempts"], 2)
        self.assertEqual(len([e for e in report["trace"] if e["event"] == "finish_rejected"]), 2)

    def test_v1_still_stops_at_first_premature_finish(self):
        model = SequenceModel([finish("insufficient")])
        report = self.runtime(model, DynamicSpec()).run(self.request, self.f.access)
        self.assertEqual(report["status"], "insufficient")
        self.assertNotIn("rejection", report["decisions"][0])
        self.assertEqual(model.calls, 1)

    def test_parent_child_use_same_loop_separate_state_and_structured_evidence(self):
        model = SequenceModel(parent_actions())
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        child = report["child_results"][0]
        self.assertNotEqual(child["child_run_id"], report["run_id"])
        self.assertEqual(child["parent_run_id"], report["run_id"])
        self.assertNotIn("source_results", child)
        self.assertEqual(child["status"], "completed")
        self.assertEqual(child["usage"]["model_attempts"], 2)
        self.assertTrue(report["child_evidence_links"])
        for link in report["child_evidence_links"]:
            self.assertEqual(link["tool_call_id"], child["source_tool_call_id"])
            self.assertTrue(any(ref["record_id"] == link["record_id"] for ref in child["evidence_refs"]))
        self.assertEqual(report["root_budget"]["model_attempts"], 8)
        self.assertEqual(report["root_budget"]["tool_attempts"], 6)
        self.assertEqual(report["root_budget"]["tokens_accounted"], 960)
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 0)
        payload = json.loads(model.messages[1][1]["content"])
        self.assertEqual(payload["available_tools"], ["financial"])
        self.assertEqual(set(payload["bound_windows"]), {"financial_income"})
        self.assertEqual(payload["required_checks"], ["read:financial"])
        child_state = self.f.store.read(self.f.access.scope, child["child_run_id"])
        self.assertLessEqual(ts(child_state["deadline"]), ts(self.f.store.read(self.f.access.scope, report["run_id"])["deadline"]))
        self.assertEqual(child_state["request"]["as_of"], self.request.to_dict()["as_of"])
        self.assertEqual(child_state["request"]["mode"], self.request.mode.value)

    def test_root_allocation_persisted_before_first_child_model_dispatch(self):
        def callback(call, messages):
            if call == 2:
                with self.f.store._connection() as db:
                    states = [json.loads(row[0]) for row in db.execute("SELECT payload FROM checkpoints")]
                parent = next(s for s in reversed(states) if s.get("pending_child"))
                self.assertEqual(parent["root_budget"]["summary"]["tokens_accounted"], 18120)
                self.assertEqual(parent["root_budget"]["summary"]["decisions_accounted"], 4)
                self.assertEqual(parent["trace"][-1]["event"], "child_reserved")
            return parent_actions()[call - 1]
        self.assertEqual(self.runtime(SequenceModel([], callback=callback)).run(self.request, self.f.access)["status"], "completed")

    def test_root_capacity_denies_child_before_any_child_model_or_read(self):
        for spec in (FinancialParentSpec(root_max_decisions=3), FinancialParentSpec(root_max_tools=1),
                     FinancialParentSpec(root_max_tokens=17999)):
            with self.subTest(spec=spec):
                model = SequenceModel([tool("financial_child")])
                with patch.object(self.f.service, "query", side_effect=AssertionError("child dispatched")):
                    report = self.runtime(model, spec).run(self.request, self.f.access)
                self.assertEqual(model.calls, 1)
                self.assertEqual(report["stop_reason"], "root_budget_exceeded")
                self.assertEqual(report["child_results"], [])

    def test_parent_financial_grant_and_delegated_grant_both_required(self):
        policies = ({"granted_tools": DYNAMIC_TOOLS - {"financial"} | {"financial_child"}},
                    {"delegated_tools": frozenset()}, {"delegated_datasets": frozenset()})
        for kwargs in policies:
            with self.subTest(kwargs=kwargs):
                model = SequenceModel([tool("financial_child")])
                with self.assertRaises(PermissionDenied):
                    self.runtime(model, **kwargs).run(self.request, self.f.access)
                self.assertEqual(model.calls, 1)

    def test_child_cannot_spawn_or_read_market(self):
        for forbidden in ("financial_child", "market", "calculation"):
            with self.subTest(tool=forbidden):
                model = SequenceModel([tool("financial_child"), tool(forbidden)])
                with self.assertRaises(PermissionDenied):
                    self.runtime(model).run(self.request, self.f.access)
                self.assertEqual(model.calls, 2)

    def test_cancel_in_child_propagates_and_withholds_all_late_evidence(self):
        cancelled = [False]
        def callback(call, messages):
            if call == 3:
                cancelled[0] = True
            return parent_actions()[call - 1]
        model = SequenceModel([], callback=callback)
        report = self.runtime(model, cancelled=lambda: cancelled[0]).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["child_results"], [])
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 1)
        self.assertEqual(model.calls, 3)

    def test_deadline_in_child_is_nested_and_late_results_not_imported(self):
        clock = [ts("2026-10-05T00:00:00")]
        def callback(call, messages):
            if call == 2:
                clock[0] += timedelta(seconds=241)
            return parent_actions()[call - 1]
        report = self.runtime(SequenceModel([], callback=callback), now=lambda: clock[0], monotonic=lambda: 0).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["child_results"], [])
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 1)

    def test_child_crash_keeps_full_root_allocation_and_resume_never_repays(self):
        def callback(call, messages):
            if call == 2:
                raise KeyboardInterrupt()
            return tool("financial_child")
        model = SequenceModel([], callback=callback)
        runtime = self.runtime(model)
        with self.assertRaises(KeyboardInterrupt):
            runtime.run(self.request, self.f.access)
        with self.f.store._connection() as db:
            parent = json.loads(db.execute("SELECT payload FROM checkpoints WHERE payload LIKE '%pending_child%' ORDER BY rowid DESC LIMIT 1").fetchone()[0])
        replacement = SequenceModel([])
        report = self.runtime(replacement).run(self.request, self.f.access, resume=parent["run_id"])
        self.assertEqual(replacement.calls, 0)
        self.assertEqual(report["stop_reason"], "unknown_tool_outcome_no_replay")
        self.assertEqual(report["root_budget"]["tokens_accounted"], 18120)
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 1)

    def test_completed_replay_revalidates_child_and_parent_without_model_calls(self):
        report = self.runtime(SequenceModel(parent_actions())).run(self.request, self.f.access)
        model = SequenceModel([])
        replay = self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(report, replay)
        self.assertEqual(model.calls, 0)

    def test_completed_child_result_and_root_ledger_tampering_are_rejected(self):
        report = self.runtime(SequenceModel(parent_actions())).run(self.request, self.f.access)
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        original = copy.deepcopy(state)
        state["child_results"][0]["result_ref"] = "a" * 64
        self.f.store.append(self.f.access.scope, report["run_id"], state)
        with self.assertRaises(IntegrityError):
            self.runtime(SequenceModel([])).run(self.request, self.f.access, resume=report["run_id"])
        original["root_budget"] = new_root_budget(original["root_budget"]["limits"], report["run_id"])
        self.f.store.append(self.f.access.scope, report["run_id"], original)
        with self.assertRaises(IntegrityError):
            self.runtime(SequenceModel([])).run(self.request, self.f.access, resume=report["run_id"])

    def test_completed_replay_checks_parent_tool_revocation_and_artifact_hash(self):
        report = self.runtime(SequenceModel(parent_actions())).run(self.request, self.f.access)
        with self.assertRaises(PermissionDenied):
            self.runtime(SequenceModel([]), delegated_tools=()).run(self.request, self.f.access, resume=report["run_id"])
        artifact = self.f.artifacts._path(self.f.access.scope, self.f.financial.artifact_id)
        artifact.write_bytes(b"changed synthetic artifact")
        with self.assertRaises(IntegrityError):
            self.runtime(SequenceModel([])).run(self.request, self.f.access, resume=report["run_id"])

    def test_financial_request_cannot_change_cutoff_snapshot_or_add_nonfinancial_data(self):
        child = FinancialRequest.from_parent(self.request)
        self.assertEqual(child.bindings, tuple(b for b in self.request.bindings if b.dataset.startswith("financial_")))
        self.assertEqual(child.as_of, self.request.as_of)
        with self.assertRaises(ValidationError):
            replace(child, bindings=self.request.bindings)
        with self.assertRaises(ValidationError):
            FinancialChildSpec(allowed_tools=frozenset({"financial", "financial_child"}))
        with self.assertRaises(ValidationError):
            DynamicSpec(version="financial-child-v1")

    def test_live_data_grant_revocation_during_child_read_and_completed_replay(self):
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot, self.request.data_request(b), b.provider)
                  for b in self.request.bindings]
        service = ScopedReadService(self.f.access.scope, lambda: tuple(grants))
        def callback(call, messages):
            if call == 3:
                grants.clear()
            return parent_actions()[call - 1]
        with self.assertRaises(PermissionDenied):
            DynamicRuntime(service, self.f.store, SequenceModel([], callback=callback), FinancialParentSpec()).run(self.request, self.f.access)
        grants[:] = [SourceGrant(self.f.service, self.f.access, b.snapshot, self.request.data_request(b), b.provider)
                     for b in self.request.bindings]
        report = DynamicRuntime(service, self.f.store, SequenceModel(parent_actions()), FinancialParentSpec()).run(self.request, self.f.access)
        grants.clear()
        with self.assertRaises(PermissionDenied):
            DynamicRuntime(service, self.f.store, SequenceModel([]), FinancialParentSpec()).run(self.request, self.f.access, resume=report["run_id"])

    def test_live_parent_tool_revocation_is_seen_by_active_child(self):
        runtime = None
        def callback(call, messages):
            if call == 2:
                runtime.granted = runtime.granted - {"financial_child"}
            return parent_actions()[call - 1]
        runtime = self.runtime(SequenceModel([], callback=callback))
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, self.f.access)

    def test_child_unknown_model_usage_is_kept_when_parent_can_use_direct_tool(self):
        def callback(call, messages):
            if call == 2:
                raise RuntimeError("synthetic transport outcome unknown")
            if call == 1:
                return tool("financial_child")
            return completed_actions()[call - 3]
        model = SequenceModel([], callback=callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["child_results"][0]["status"], "partial")
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 1)
        self.assertGreater(report["root_budget"]["tokens_accounted"], report["root_budget"]["total_tokens"])
        self.assertEqual(report["child_evidence_links"], [])
        replay = self.runtime(SequenceModel([])).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(report, replay)

    def test_child_early_finish_is_rejected_within_its_reserved_local_limit(self):
        model = SequenceModel(parent_actions([finish(), tool("financial"), finish()]))
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        child = self.f.store.read(self.f.access.scope, report["child_results"][0]["child_run_id"])
        self.assertEqual(child["decisions"][0]["rejection"]["pending_checks"], ["read:financial"])
        self.assertEqual(report["root_budget"]["model_attempts"], 9)

    def test_delegated_subset_never_imports_additional_parent_financial_dataset(self):
        model = SequenceModel(parent_actions())
        report = self.runtime(model, delegated_datasets={"financial_income"}).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        saved = self.f.store.read(self.f.access.scope, report["child_results"][0]["child_run_id"])
        self.assertEqual({b["dataset"] for b in saved["request"]["bindings"]}, {"financial_income"})


if __name__ == "__main__":
    unittest.main()
