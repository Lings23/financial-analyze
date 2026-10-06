"""Synthetic strict v3 response contracts; never proof of real model repair."""
import copy
import json
from dataclasses import replace
from threading import Barrier, Event
import unittest

import test_child_progress_runtime as v2_fixture
from test_child_progress_runtime import ProgressModel
from test_dynamic import finish, tool
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import FinancialChildSpec, MarketChildSpec, ParallelParentSpec
from stock_research.research.scoped import ScopedReadService, SourceGrant


def strict_specs():
    return {"financial": FinancialChildSpec(version="financial-child-v3"),
            "market": MarketChildSpec(version="market-child-v3")}


def malformed_finish(domain):
    # The actual repair attempt-1 response shape: finish omitted mandatory reason
    # and added refs. It remains invalid regardless of source read completion.
    return {"action": "finish", "plan": ["The required " + domain + " read is done",
            "Coverage and historical release gaps remain unchanged"], "refs": []}


class ChildProgressV3RuntimeTests(unittest.TestCase):
    setUp = v2_fixture.ChildProgressRuntimeTests.setUp
    parent_state = v2_fixture.ChildProgressRuntimeTests.parent_state
    child_state = v2_fixture.ChildProgressRuntimeTests.child_state

    def runtime(self, model, spec=None, service=None, **kwargs):
        return DynamicRuntime(service or self.f.service, self.f.store, model,
            spec or ParallelParentSpec(), domain_child_specs=strict_specs(), **kwargs)

    def assert_response_contract(self, progress, action):
        expected = ({"action": "tool", "required_keys": ["action", "tool", "refs", "plan"],
                     "forbidden_keys": ["reason"]} if action == "tool" else
                    {"action": "finish", "required_keys": ["action", "reason", "plan"],
                     "forbidden_keys": ["tool", "refs"]})
        self.assertEqual(progress["response_contract"], expected)

    def test_parallel_v3_exact_turn_specific_response_json_and_required_parent_verification(self):
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, payload):
            if role != "parent" and turn == 1:
                rendezvous.wait()
            if role != "parent":
                progress = payload["child_progress"]
                self.assert_response_contract(progress, "tool" if turn == 1 else "finish")
                self.assertEqual(progress["source_quality"]["coverage"], "not_verified")
                if turn == 2:
                    self.assertEqual(progress["source_quality"]["gaps"], payload["observations"][0]["gaps"])
                    self.assertTrue(progress["execution"]["can_finish"])
        model = ProgressModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(model.counts, {"parent": 5, "financial": 2, "market": 2})
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))
        for role, turn, messages in model.messages:
            if role == "parent":
                continue
            payload = json.loads(messages[1]["content"])
            candidate = payload["child_progress"]["legal_next_actions"][0]
            self.assertTrue(messages[0]["content"].endswith("CURRENT RESPONSE JSON: " + canonical_json(candidate)))
            if turn == 2:
                self.assertEqual(set(candidate), {"action", "reason", "plan"})
            state = self.child_state(report, role)
            self.assertEqual(state["spec_version"], role + "-child-v3")
            self.assertEqual(state["tools_used"], 1)

    def test_original_malformed_finish_remains_strictly_rejected_and_no_progress(self):
        seen_feedback = set()
        def callback(role, turn, payload):
            if role != "parent" and turn > 1:
                if turn == 3:
                    self.assertEqual(payload["control"]["previous_action_error"], "invalid_action")
                    progress = payload["child_progress"]
                    self.assert_response_contract(progress, "finish")
                    self.assertEqual(progress["invalid_action_feedback"], {"code": "invalid_action",
                        "response_contract": progress["response_contract"],
                        "next_actions": progress["legal_next_actions"]})
                    seen_feedback.add(role)
                return malformed_finish(role)
        model = ProgressModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(seen_feedback, {"financial", "market"})
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "parallel_required_branch_incomplete")
        self.assertEqual(model.counts, {"parent": 1, "financial": 3, "market": 3})
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        for domain in ("financial", "market"):
            state = self.child_state(report, domain)
            self.assertEqual(state["report"]["stop_reason"], "no_progress")
            self.assertEqual(state["tools_used"], 1)
            self.assertEqual(sum(decision["status"] == "invalid_action" for decision in state["decisions"]), 2)
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 0)
        fresh = ProgressModel()
        self.assertEqual(self.runtime(fresh).run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertFalse(fresh.counts)

    def test_one_malformed_finish_then_exact_candidate_completes_in_original_three_turn_cap(self):
        def callback(role, turn, payload):
            if role != "parent" and turn == 2:
                return malformed_finish(role)
            if role != "parent" and turn == 3:
                progress = payload["child_progress"]
                self.assertEqual(progress["invalid_action_feedback"]["code"], "invalid_action")
                self.assertEqual(progress["invalid_action_feedback"]["next_actions"],
                                 progress["legal_next_actions"])
                self.assertEqual(progress["response_contract"]["required_keys"], ["action", "reason", "plan"])
                self.assertEqual(progress["response_contract"]["forbidden_keys"], ["tool", "refs"])
                self.assertTrue(progress["execution"]["read_completed"])
        model = ProgressModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(model.counts, {"parent": 5, "financial": 3, "market": 3})
        for domain in ("financial", "market"):
            state = self.child_state(report, domain)
            self.assertEqual(state["tools_used"], 1)
            self.assertEqual(state["model_attempts"], 3)
            self.assertEqual(state["decisions"][1]["status"], "invalid_action")
            self.assertEqual(state["report"]["status"], "completed")
        self.assertEqual(report["root_budget"]["model_attempts"], 11)
        self.assertEqual(report["root_budget"]["total_tokens"], 11 * 120)

    def test_v3_does_not_accept_finish_before_required_read(self):
        def callback(role, turn, payload):
            if role != "parent":
                self.assertFalse(payload["child_progress"]["execution"]["can_finish"])
                self.assert_response_contract(payload["child_progress"], "tool")
                return finish("insufficient")
        model = ProgressModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(model.counts, {"parent": 1, "financial": 2, "market": 2})
        for domain in ("financial", "market"):
            state = self.child_state(report, domain)
            self.assertEqual(state["tools_used"], 0)
            self.assertEqual(state["report"]["required_checks"], [{"id": "read:" + domain,
                                                                   "status": "not_completed"}])
            self.assertEqual(state["decisions"][0]["rejection"]["code"], "required_checks_pending")

    def test_v3_repeated_read_still_no_progress_and_once_only_dispatch(self):
        def callback(role, turn, payload):
            if role != "parent":
                if turn == 3:
                    progress = payload["child_progress"]
                    self.assertEqual(progress["duplicate_feedback"]["code"], "duplicate_no_progress")
                    self.assertNotIn("invalid_action_feedback", progress)
                    self.assertFalse(progress["duplicate_feedback"]["dispatched"])
                    self.assert_response_contract(progress, "finish")
                return tool(role)
        report = self.runtime(ProgressModel(callback)).run(self.request, self.f.access)
        self.assertNotEqual(report["status"], "completed")
        for domain in ("financial", "market"):
            state = self.child_state(report, domain)
            self.assertEqual(state["tools_used"], 1)
            self.assertEqual(state["report"]["stop_reason"], "no_progress")

    def test_v3_empty_read_finish_preserves_quality_and_parent_insufficiency(self):
        snapshot = self.f.repo.commit(self.f.access.scope, self.f.records)
        request = replace(self.request, bindings=tuple(replace(binding, snapshot=snapshot.snapshot_id)
                                                        for binding in self.request.bindings))
        model = ProgressModel()
        report = self.runtime(model).run(request, self.f.access)
        financial = next(json.loads(messages[1]["content"]) for role, turn, messages in model.messages
                         if role == "financial" and turn == 2)
        progress = financial["child_progress"]
        self.assertTrue(progress["execution"]["read_completed"])
        self.assertEqual(progress["legal_next_actions"][0]["reason"], "insufficient")
        self.assertEqual(progress["required_checks"], [{"id": "read:financial", "status": "passed"}])
        self.assertEqual(progress["source_quality"]["read_result_status"], "insufficient")
        self.assertEqual(progress["source_quality"]["gaps"], financial["observations"][0]["gaps"])
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(self.child_state(report, "financial")["report"]["status"], "insufficient")

    def test_v3_context_telemetry_exact_replay_and_legacy_v2_binding_still_rejected(self):
        model = ProgressModel()
        report = self.runtime(model).run(self.request, self.f.access)
        states = {"parent": self.parent_state(report["run_id"]),
                  **{domain: self.child_state(report, domain) for domain in ("financial", "market")}}
        for role, turn, messages in model.messages:
            telemetry = states[role]["context_telemetry"][turn - 1]
            size = sum(len(message["content"].encode("utf-8")) for message in messages)
            self.assertEqual(telemetry["message_sha256"], digest(messages))
            self.assertEqual(telemetry["total_context_bytes"], size)
            self.assertEqual(telemetry["context_after_compaction_bytes"], size)
            self.assertEqual(telemetry["context_limit_bytes"], 12000)
            self.assertEqual(telemetry["input_tokens"], 100)
            self.assertEqual(telemetry["output_tokens"], 20)
            self.assertLessEqual(size, 12000)
            self.assertNotIn("context_telemetry", messages[1]["content"])
            self.assertNotIn("sum_branch_execution_ms", messages[1]["content"])
        before = copy.deepcopy(states)
        fresh = ProgressModel()
        self.assertEqual(self.runtime(fresh).run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertFalse(fresh.counts)
        for state in before.values():
            self.assertEqual(self.f.store.read(self.f.access.scope, state["run_id"]), state)
        with self.assertRaises(PermissionDenied):
            v2_fixture.ChildProgressRuntimeTests.runtime(self, ProgressModel()).run(
                self.request, self.f.access, resume=report["run_id"])
        with self.assertRaises(ValidationError):
            ParallelParentSpec(context_bytes=12001)

    def test_v3_revoked_source_grant_rejects_completed_cache_resume_before_model(self):
        grants = [SourceGrant(self.f.service, self.f.access, binding.snapshot,
                    self.request.data_request(binding), binding.provider) for binding in self.request.bindings]
        service = ScopedReadService(self.f.access.scope, lambda: tuple(grants))
        report = self.runtime(ProgressModel(), service=service).run(self.request, self.f.access)
        grants.clear()
        model = ProgressModel()
        with self.assertRaises(PermissionDenied):
            self.runtime(model, service=service).run(self.request, self.f.access, resume=report["run_id"])
        self.assertFalse(model.counts)

    def test_v3_cancel_running_children_discards_late_returns_and_evidence(self):
        cancelled = Event()
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, payload):
            if role != "parent" and turn == 1:
                rendezvous.wait()
                cancelled.set()
        model = ProgressModel(callback)
        report = self.runtime(model, cancelled=cancelled.is_set).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(model.counts, {"parent": 1, "financial": 1, "market": 1})
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        self.assertEqual(self.parent_state(report["run_id"])["outputs"], {})
        self.assertEqual(report["parallel_groups"][0]["telemetry"]["late_branch_count"], 2)


if __name__ == "__main__":
    unittest.main()
