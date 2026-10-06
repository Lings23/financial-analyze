"""Synthetic M3 crash injection; fixtures are not financial ground truth."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
import unittest

import test_parallel_runtime as fixtures
RoleModel = fixtures.RoleModel
from stock_research.research.dynamic_contracts import FinancialChildSpec, MarketChildSpec
from stock_research.research.parallel import gate_stage, runnable
from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import digest


class Crash(BaseException):
    pass


class ParallelRecoveryTests(fixtures.ParallelRuntimeTests):
    # Reuse only fixture helpers, not inherited test execution.
    def crash_at(self, kind, *, count=1, child=False):
        original = self.f.store.append
        seen = [0]
        def append(scope, run, state):
            original(scope, run, state)
            is_child = state["spec_version"] == "financial-child-v1"
            if is_child == child and state["trace"] and state["trace"][-1]["event"] == kind:
                seen[0] += 1
                if seen[0] == count:
                    raise Crash()
        self.f.store.append = append
        return original

    def test_crash_after_both_reserved_resumes_without_second_allocation(self):
        original = self.crash_at("parallel_group_reserved")
        model = RoleModel()
        with self.assertRaises(Crash):
            self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(model.counts, {"parent": 1})
        before = self.parent_state()
        self.assertEqual({before["parallel_groups"][0]["nodes"][d + "_branch"]["status"]
                          for d in ("financial", "market")}, {"reserved"})
        self.f.store.append = original
        fresh = RoleModel(parent_actions=RoleModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=before["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(fresh.counts, {"parent": 4, "financial": 2, "market": 2})
        events = self.parent_state()["root_budget"]["events"]
        self.assertEqual(sum(e["kind"] == "children_reserved" for e in events), 1)

    def test_crash_after_one_known_receipt_does_not_repeat_child_or_settlement(self):
        original = self.crash_at("child_finished")
        with self.assertRaises(Crash):
            self.runtime(RoleModel()).run(self.request, self.f.access)
        before = self.parent_state()
        known = deepcopy(before["child_results"])
        self.assertEqual(len(known), 1)
        self.f.store.append = original
        fresh = RoleModel(parent_actions=RoleModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=before["run_id"])
        self.assertNotEqual(report["status"], "completed" if report["stop_reason"] else "partial")
        self.assertEqual(fresh.counts.get(known[0]["domain"], 0), 0)
        self.assertIn(known[0], report["child_results"])
        self.assertEqual(sum(e["kind"] == "child_settled" and e["child_run_id"] == known[0]["child_run_id"]
            for e in self.parent_state()["root_budget"]["events"]), 1)
        self.assertEqual(len(report["evidence"]), len(set(report["evidence"])))

    def test_crash_on_unknown_paid_child_intent_never_dispatches_it_again(self):
        original = self.crash_at("model_started", child=True)
        with self.assertRaises(Crash):
            self.runtime(RoleModel()).run(self.request, self.f.access)
        before = self.parent_state()
        self.f.store.append = original
        fresh = RoleModel(parent_actions=RoleModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=before["run_id"])
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(fresh.counts.get("financial", 0), 0)
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 1)
        self.assertGreater(report["root_budget"]["tokens_accounted"], report["root_budget"]["total_tokens"])

    def test_crash_two_complete_receipts_before_group_join_is_idempotent(self):
        original = self.crash_at("child_finished", count=2)
        with self.assertRaises(Crash):
            self.runtime(RoleModel()).run(self.request, self.f.access)
        before = self.parent_state()
        self.assertEqual(len(before["child_results"]), 2)
        self.f.store.append = original
        fresh = RoleModel(parent_actions=RoleModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=before["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(fresh.counts, {"parent": 4})
        self.assertEqual(report["root_budget"]["total_tokens"], 9 * 120)
        self.assertEqual(sum(e["kind"] == "children_reserved" for e in self.parent_state()["root_budget"]["events"]), 1)

    def test_crash_after_group_ready_retains_original_section_telemetry_and_no_child_call(self):
        original = self.crash_at("parallel_group_ready_to_join")
        with self.assertRaises(Crash):
            self.runtime(RoleModel()).run(self.request, self.f.access)
        before = self.parent_state()
        self.f.store.append = original
        fresh = RoleModel(parent_actions=RoleModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=before["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(fresh.counts, {"parent": 4})
        self.assertEqual(report["parallel_groups"][0]["group_finished_at"], before["parallel_groups"][0]["group_finished_at"])

    def test_dependency_gate_rejects_each_pending_predecessor(self):
        original = self.crash_at("parallel_group_reserved")
        with self.assertRaises(Crash):
            self.runtime(RoleModel()).run(self.request, self.f.access)
        state = self.parent_state()
        for name in ("calculation", "hypotheses", "verification"):
            with self.assertRaises(ValidationError):
                gate_stage(state, name)
        self.assertTrue(runnable(state["parallel_groups"][0]["nodes"], "financial_branch"))
        self.assertFalse(runnable(state["parallel_groups"][0]["nodes"], "calculation"))
        self.f.store.append = original

    def test_single_child_deadline_leaves_successful_sibling_without_false_completion(self):
        from helpers import ts
        wall = [ts("2026-10-05T00:00:00")]
        ready = Barrier(2, timeout=5)
        def callback(role, turn, messages):
            if role in {"financial", "market"} and turn == 1:
                ready.wait()
            if role == "financial" and turn == 2:
                wall[0] += timedelta(seconds=2)
        specs = {"financial": FinancialChildSpec(max_seconds=1), "market": MarketChildSpec()}
        report = self.runtime(RoleModel(callback), domain_child_specs=specs,
            now=lambda: wall[0], monotonic=lambda: 0).run(self.request, self.f.access)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["parallel_groups"][0]["nodes"]["financial_branch"]["status"], "late_discarded")
        self.assertNotIn("financial", self.parent_state()["outputs"])
        self.assertIn("market", self.parent_state()["outputs"])

    def test_cancel_after_accepted_a_keeps_checkpoint_and_stops_b(self):
        cancel, accepted = Event(), Event()
        original = self.f.store.append
        def append(scope, run, state):
            original(scope, run, state)
            if state["spec_version"] == "dynamic-parent-parallel-v1" and state["trace"]:
                last = state["trace"][-1]
                if last["event"] == "tool_finished" and last.get("tool") == "financial_child":
                    accepted.set()
        self.f.store.append = append
        def callback(role, turn, messages):
            if role == "market" and turn == 2:
                self.assertTrue(accepted.wait(5))
                cancel.set()
        report = self.runtime(RoleModel(callback), cancelled=cancel.is_set).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertIn("financial", self.parent_state()["outputs"])
        self.assertNotIn("market", self.parent_state()["outputs"])
        self.assertTrue(self.parent_state()["parallel_groups"][0]["nodes"]["financial_branch"]["submitted"])


# Avoid duplicating the mechanism baseline inherited solely for fixtures.
for _name in list(fixtures.ParallelRuntimeTests.__dict__):
    if _name.startswith("test_") and _name not in ParallelRecoveryTests.__dict__:
        setattr(ParallelRecoveryTests, _name, None)
