"""Synthetic v2 Child progression/safety contracts; never real model validation."""
import copy
import json
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import completed_actions, finish, tool
from test_parallel_runtime import parallel_action
from stock_research.errors import PermissionDenied
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (
    DynamicRequest, DomainParentSpec, FinancialChildSpec, MarketChildSpec, ParallelParentSpec,
)
from stock_research.research.scoped import ScopedReadService, SourceGrant


def progress_specs():
    return {"financial": FinancialChildSpec(version="financial-child-v2"),
            "market": MarketChildSpec(version="market-child-v2")}


class ProgressModel:
    """Protocol mechanism fixture that inspects the actual isolated Child wire.

    Selecting an advertised candidate tests Runtime contracts, not whether a real
    model will choose it. The separate frozen real validation establishes that.
    """
    config = SimpleNamespace(model="deepseek-v4-flash-0731")

    def __init__(self, callback=None, parent_actions=None):
        self.callback = callback
        self.parent_actions = parent_actions or [parallel_action(),
            tool("calculation", ["financial", "market"]),
            tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()]
        self.counts, self.messages, self.lock = Counter(), [], Lock()

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        version = payload.get("protocol_version", "")
        role = next((domain for domain in ("financial", "market")
                     if version.startswith(domain + "-child-")), "parent")
        with self.lock:
            self.counts[role] += 1
            turn = self.counts[role]
            self.messages.append((role, turn, copy.deepcopy(messages)))
        if role == "parent":
            if turn > len(self.parent_actions):
                raise AssertionError("unexpected parent model dispatch")
            action = self.parent_actions[turn - 1]
        else:
            action = payload["child_progress"]["legal_next_actions"][0]
        if self.callback is not None:
            replacement = self.callback(role, turn, payload)
            if replacement is not None:
                action = replacement
        content = json.dumps(action, ensure_ascii=False, allow_nan=False)
        return ChatResult(self.config.model, self.config.model, content, "stop",
                          f"synthetic-child-progress-{role}-{turn}", 100, 20, 120, 1)


class ChildProgressRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({**study_request(self.f,
            hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: independently read financial and market, then verify"})

    def runtime(self, model, spec=None, service=None, **kwargs):
        specs = kwargs.pop("domain_child_specs", progress_specs())
        return DynamicRuntime(service or self.f.service, self.f.store, model,
            spec or ParallelParentSpec(), domain_child_specs=specs, **kwargs)

    def parent_state(self, run_id):
        return self.f.store.read(self.f.access.scope, run_id)

    def child_state(self, report, domain):
        child = next(item for item in report["child_results"] if item["domain"] == domain)
        return self.f.store.read(self.f.access.scope, child["child_run_id"])

    def test_successful_reads_expose_passed_checks_and_finish_keep_quality_gaps(self):
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, payload):
            if role != "parent" and turn == 1:
                rendezvous.wait()
                progress = payload["child_progress"]
                self.assertEqual(progress["required_checks"], [{"id": "read:" + role,
                                                               "status": "not_completed"}])
                self.assertFalse(progress["execution"]["can_finish"])
                self.assertEqual(progress["legal_next_actions"][0]["tool"], role)
            if role != "parent" and turn == 2:
                progress = payload["child_progress"]
                self.assertEqual(payload["completed_tools"], [role])
                self.assertEqual(payload["available_tools"], [role])
                self.assertEqual(progress["required_checks"], [{"id": "read:" + role, "status": "passed"}])
                self.assertEqual(progress["execution"], {"read_completed": True,
                    "pending_checks": [], "can_finish": True, "completion_scope": "delegated_source_read"})
                self.assertEqual(progress["legal_next_actions"][0]["action"], "finish")
                observation = payload["observations"][0]
                self.assertEqual(progress["source_quality"]["gaps"], observation["gaps"])
                self.assertEqual(progress["source_quality"]["coverage"], "not_verified")
                self.assertTrue(any(gap.endswith(":coverage_not_verified") for gap in observation["gaps"]))
                self.assertNotIn("verification", payload["completed_tools"])
        model = ProgressModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(model.counts, {"parent": 5, "financial": 2, "market": 2})
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))
        self.assertEqual([child["domain"] for child in report["child_results"]], ["financial", "market"])
        for domain in ("financial", "market"):
            state = self.child_state(report, domain)
            self.assertEqual(state["spec_version"], domain + "-child-v2")
            self.assertEqual(state["tools_used"], 1)
            self.assertEqual(state["request"]["as_of"], self.request.to_dict()["as_of"])
            self.assertEqual(state["request"]["mode"], self.request.to_dict()["mode"])

    def test_premature_child_finish_rejected_then_read_and_finish_with_original_limits(self):
        def callback(role, turn, payload):
            if role != "parent" and turn == 1:
                return finish("insufficient")
            if role != "parent" and turn == 2:
                self.assertEqual(payload["control"]["finish_rejection"],
                    {"code": "required_checks_pending", "pending_checks": ["read:" + role]})
                self.assertFalse(payload["child_progress"]["execution"]["can_finish"])
                self.assertEqual(payload["child_progress"]["legal_next_actions"][0]["action"], "tool")
        model = ProgressModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(model.counts, {"parent": 5, "financial": 3, "market": 3})
        self.assertEqual(report["root_budget"]["model_attempts"], 11)
        for domain in ("financial", "market"):
            state = self.child_state(report, domain)
            self.assertEqual(state["tools_used"], 1)
            self.assertEqual(state["decisions"][0]["rejection"]["pending_checks"], ["read:" + domain])

    def test_persistent_repeated_reads_still_dispatch_once_and_stop_no_progress(self):
        for repeated_domain in ("financial", "market"):
            with self.subTest(domain=repeated_domain):
                seen_feedback = []
                def callback(role, turn, payload):
                    if role == repeated_domain:
                        if turn == 3:
                            progress = payload["child_progress"]
                            self.assertEqual(payload["control"]["previous_action_error"], "duplicate_no_progress")
                            self.assertEqual(progress["duplicate_feedback"]["next_actions"],
                                             progress["legal_next_actions"])
                            self.assertFalse(progress["duplicate_feedback"]["dispatched"])
                            self.assertTrue(progress["execution"]["can_finish"])
                            seen_feedback.append(True)
                        return tool(role)
                model = ProgressModel(callback)
                report = self.runtime(model).run(self.request, self.f.access)
                self.assertEqual(report["status"], "partial")
                self.assertEqual(report["stop_reason"], "parallel_required_branch_incomplete")
                self.assertEqual(model.counts["parent"], 1)
                state = self.child_state(report, repeated_domain)
                self.assertEqual(state["report"]["stop_reason"], "no_progress")
                self.assertEqual(state["tools_used"], 1)
                self.assertEqual(state["model_attempts"], 3)
                self.assertEqual(sum(event["event"] == "tool_started" for event in state["trace"]), 1)
                self.assertEqual(seen_feedback, [True])
                replay_model = ProgressModel()
                self.assertEqual(self.runtime(replay_model).run(self.request, self.f.access,
                    resume=report["run_id"]), report)
                self.assertFalse(replay_model.counts)

    def test_child_finish_does_not_skip_parent_calculation_hypotheses_verification(self):
        model = ProgressModel(parent_actions=[parallel_action(), finish(), finish("insufficient")])
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual([child["status"] for child in report["child_results"]], ["completed", "completed"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "no_progress")
        required = {check["id"]: check["status"] for check in report["required_checks"]}
        self.assertEqual(required["read:financial"], "passed")
        self.assertEqual(required["read:market"], "passed")
        for check in ("calculation", "hypotheses", "verification"):
            self.assertEqual(required[check], "not_completed")
        self.assertEqual(report["facts"], [])

    def test_one_duplicate_then_advertised_finish_recovers_without_another_read(self):
        def callback(role, turn, payload):
            if role != "parent" and turn == 2:
                return tool(role)
            if role != "parent" and turn == 3:
                progress = payload["child_progress"]
                self.assertEqual(progress["duplicate_feedback"]["next_actions"],
                                 progress["legal_next_actions"])
                self.assertEqual(progress["legal_next_actions"][0]["action"], "finish")
        model = ProgressModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(model.counts, {"parent": 5, "financial": 3, "market": 3})
        for domain in ("financial", "market"):
            state = self.child_state(report, domain)
            self.assertEqual(state["tools_used"], 1)
            self.assertEqual(state["report"]["required_checks"], [{"id": "read:" + domain, "status": "passed"}])
            self.assertEqual(sum(event["event"] == "repeated_action" for event in state["trace"]), 1)

    def test_empty_read_can_finish_insufficient_without_certifying_data_or_parent(self):
        # Preserve a valid immutable binding with only synthetic market rows.
        snapshot = self.f.repo.commit(self.f.access.scope, self.f.records)
        request = replace(self.request, bindings=tuple(replace(binding, snapshot=snapshot.snapshot_id)
                                                        for binding in self.request.bindings))
        model = ProgressModel()
        report = self.runtime(model).run(request, self.f.access)
        financial_wire = next(json.loads(messages[1]["content"]) for role, turn, messages in model.messages
                              if role == "financial" and turn == 2)
        progress = financial_wire["child_progress"]
        self.assertTrue(progress["execution"]["read_completed"])
        self.assertEqual(progress["required_checks"], [{"id": "read:financial", "status": "passed"}])
        self.assertEqual(progress["source_quality"]["read_result_status"], "insufficient")
        self.assertEqual(progress["source_quality"]["gaps"], financial_wire["observations"][0]["gaps"])
        self.assertEqual(progress["legal_next_actions"][0]["reason"], "insufficient")
        self.assertEqual(self.child_state(report, "financial")["report"]["status"], "insufficient")
        self.assertNotEqual(report["status"], "completed")
        self.assertFalse(any(fact["name"].startswith("financial_") for fact in report["facts"]))

    def test_new_child_specs_keep_direct_and_serial_mixed_routes_compatible(self):
        for direct in (("financial", "market"), ("financial",), ("market",), ()):
            with self.subTest(direct=direct):
                # Parent actions omit Child decisions; each Child owns its stream.
                parent_actions = []
                for domain in ("financial", "market"):
                    parent_actions.append(tool(domain if domain in direct else domain + "_child"))
                parent_actions.extend(completed_actions()[2:])
                model = ProgressModel(parent_actions=parent_actions)
                report = self.runtime(model, DomainParentSpec(version="dynamic-parent-domains-v2")).run(
                    self.request, self.f.access)
                self.assertEqual(report["status"], "completed")
                self.assertEqual(len(report["child_results"]), 2 - len(direct))
                self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))
                self.assertEqual([route["mode"] for route in report["routes"][:2]],
                                 ["direct" if domain in direct else "delegated" for domain in ("financial", "market")])

    def test_v2_paid_wire_telemetry_and_zero_model_replay_are_exact(self):
        model = ProgressModel()
        report = self.runtime(model).run(self.request, self.f.access)
        states = {"parent": self.parent_state(report["run_id"]),
                  **{domain: self.child_state(report, domain) for domain in ("financial", "market")}}
        for role, turn, messages in model.messages:
            telemetry = states[role]["context_telemetry"][turn - 1]
            size = sum(len(message["content"].encode("utf-8")) for message in messages)
            self.assertEqual(telemetry["context_after_compaction_bytes"], size)
            self.assertEqual(telemetry["total_context_bytes"], size)
            self.assertEqual(telemetry["message_sha256"], digest(messages))
            self.assertEqual(telemetry["context_limit_bytes"], 12000)
            self.assertEqual((telemetry["input_tokens"], telemetry["output_tokens"], telemetry["total_tokens"]),
                             (100, 20, 120))
            self.assertLessEqual(size, 12000)
            for name in ("context_telemetry", "root_actual_tokens", "sum_branch_execution_ms"):
                self.assertNotIn(name, messages[1]["content"])
        before = copy.deepcopy(states)
        model = ProgressModel()
        self.assertEqual(self.runtime(model).run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertFalse(model.counts)
        for state in before.values():
            self.assertEqual(self.f.store.read(self.f.access.scope, state["run_id"]), state)
        # Changing the injected protocol specs changes the immutable resume binding.
        with self.assertRaises(PermissionDenied):
            DynamicRuntime(self.f.service, self.f.store, ProgressModel(), ParallelParentSpec()).run(
                self.request, self.f.access, resume=report["run_id"])

    def test_cancel_propagates_to_running_v2_children_and_discards_late_returns(self):
        cancelled = Event()
        rendezvous = Barrier(2, timeout=5)
        entered = set()
        entered_lock = Lock()
        def callback(role, turn, payload):
            if role != "parent" and turn == 1:
                with entered_lock:
                    entered.add(role)
                rendezvous.wait()
                cancelled.set()
        model = ProgressModel(callback)
        report = self.runtime(model, cancelled=cancelled.is_set).run(self.request, self.f.access)
        self.assertEqual(entered, {"financial", "market"})
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(model.counts, {"parent": 1, "financial": 1, "market": 1})
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        self.assertEqual(self.parent_state(report["run_id"])["outputs"], {})
        self.assertEqual(report["parallel_groups"][0]["telemetry"]["late_branch_count"], 2)

    def test_deadline_on_v2_child_return_does_not_allow_finish_or_import(self):
        wall = [ts("2026-10-05T00:00:00")]
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, payload):
            if role != "parent" and turn == 1:
                rendezvous.wait()
                wall[0] = ts("2026-10-05T00:04:01")
        report = self.runtime(ProgressModel(callback), now=lambda: wall[0], monotonic=lambda: 0).run(
            self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        self.assertEqual(self.parent_state(report["run_id"])["request"], self.request.to_dict())

    def test_one_child_deadline_preserves_successful_sibling_without_completed_parent(self):
        wall = [ts("2026-10-05T00:00:00")]
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, payload):
            if role != "parent" and turn == 1:
                rendezvous.wait()
            if role == "financial" and turn == 2:
                wall[0] += timedelta(seconds=2)
        specs = progress_specs()
        specs["financial"] = FinancialChildSpec(version="financial-child-v2", max_seconds=1)
        report = self.runtime(ProgressModel(callback), domain_child_specs=specs,
            now=lambda: wall[0], monotonic=lambda: 0).run(self.request, self.f.access)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["parallel_groups"][0]["nodes"]["financial_branch"]["status"], "late_discarded")
        self.assertNotIn("financial", self.parent_state(report["run_id"])["outputs"])
        self.assertIn("market", self.parent_state(report["run_id"])["outputs"])

    def test_unknown_v2_paid_finish_intent_never_reissues_or_releases_reservation(self):
        class Crash(BaseException):
            pass
        original = self.f.store.append
        def append(scope, run, state):
            original(scope, run, state)
            if (state["spec_version"] == "financial-child-v2" and state["trace"]
                    and state["trace"][-1]["event"] == "model_started" and state["model_attempts"] == 2):
                raise Crash()
        self.f.store.append = append
        with self.assertRaises(Crash):
            self.runtime(ProgressModel()).run(self.request, self.f.access)
        with self.f.store._connection() as db:
            parent = json.loads(db.execute("SELECT payload FROM checkpoints WHERE payload LIKE ? "
                "ORDER BY rowid DESC LIMIT 1", ('%dynamic-parent-parallel-v1%',)).fetchone()[0])
        self.f.store.append = original
        fresh = ProgressModel(parent_actions=ProgressModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=parent["run_id"])
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(fresh.counts.get("financial", 0), 0)
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 1)
        self.assertGreater(report["root_budget"]["tokens_accounted"], report["root_budget"]["total_tokens"])
        events = self.parent_state(report["run_id"])["root_budget"]["events"]
        self.assertEqual(sum(event["kind"] == "children_reserved" for event in events), 1)

    def test_resume_after_known_duplicate_keeps_progress_and_does_not_repay_read(self):
        class Crash(BaseException):
            pass
        original = self.f.store.append
        sibling_accepted = Event()
        def append(scope, run, state):
            original(scope, run, state)
            if (state["spec_version"] == "dynamic-parent-parallel-v1" and state["trace"]
                    and state["trace"][-1]["event"] == "tool_finished"
                    and state["trace"][-1].get("tool") == "market_child"):
                sibling_accepted.set()
            if (state["spec_version"] == "financial-child-v2" and state["trace"]
                    and state["trace"][-1]["event"] == "repeated_action"):
                raise Crash()
        self.f.store.append = append
        def duplicate(role, turn, payload):
            if role == "financial" and turn == 2:
                self.assertTrue(sibling_accepted.wait(5))
                return tool(role)
        with self.assertRaises(Crash):
            self.runtime(ProgressModel(duplicate)).run(self.request, self.f.access)
        with self.f.store._connection() as db:
            parent = json.loads(db.execute("SELECT payload FROM checkpoints WHERE payload LIKE ? "
                "ORDER BY rowid DESC LIMIT 1", ('%dynamic-parent-parallel-v1%',)).fetchone()[0])
        self.f.store.append = original
        resumed_wires = []
        def inspect(role, turn, payload):
            if role == "financial":
                self.assertEqual(payload["control"]["decision"], 3)
                progress = payload["child_progress"]
                self.assertTrue(progress["execution"]["read_completed"])
                self.assertEqual(progress["duplicate_feedback"]["next_actions"][0]["action"], "finish")
                resumed_wires.append(copy.deepcopy(payload))
        fresh = ProgressModel(inspect, parent_actions=ProgressModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=parent["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(fresh.counts.get("financial"), 1)
        self.assertEqual(len(resumed_wires), 1)
        self.assertEqual(self.child_state(report, "financial")["tools_used"], 1)
        self.assertEqual(report["root_budget"]["model_attempts"], 10)
        self.assertEqual(report["root_budget"]["total_tokens"], 10 * 120)
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 0)
        events = self.parent_state(report["run_id"])["root_budget"]["events"]
        self.assertEqual(sum(event["kind"] == "children_reserved" for event in events), 1)

    def test_crash_after_two_v2_children_complete_before_join_replays_no_child_or_payment(self):
        class Crash(BaseException):
            pass
        original = self.f.store.append
        completed = [0]
        def append(scope, run, state):
            original(scope, run, state)
            if (state["spec_version"] == "dynamic-parent-parallel-v1" and state["trace"]
                    and state["trace"][-1]["event"] == "child_finished"):
                completed[0] += 1
                if completed[0] == 2:
                    raise Crash()
        self.f.store.append = append
        with self.assertRaises(Crash):
            self.runtime(ProgressModel()).run(self.request, self.f.access)
        with self.f.store._connection() as db:
            parent = json.loads(db.execute("SELECT payload FROM checkpoints WHERE payload LIKE ? "
                "ORDER BY rowid DESC LIMIT 1", ('%dynamic-parent-parallel-v1%',)).fetchone()[0])
        self.assertEqual(len(parent["child_results"]), 2)
        self.f.store.append = original
        fresh = ProgressModel(parent_actions=ProgressModel().parent_actions[1:])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=parent["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(fresh.counts, {"parent": 4})
        self.assertEqual(report["root_budget"]["total_tokens"], 9 * 120)
        events = self.parent_state(report["run_id"])["root_budget"]["events"]
        self.assertEqual(sum(event["kind"] == "children_reserved" for event in events), 1)
        self.assertEqual(report["child_results"], parent["child_results"])
        links = report["child_evidence_links"]
        self.assertEqual(len(links), len({(link["evidence_id"], link["record_id"]) for link in links}))

    def test_revocation_during_v2_parallel_read_and_completed_replay_cannot_use_cache(self):
        grants = [SourceGrant(self.f.service, self.f.access, binding.snapshot,
                  self.request.data_request(binding), binding.provider) for binding in self.request.bindings]
        service = ScopedReadService(self.f.access.scope, lambda: tuple(grants))
        original = service.query
        revoked = Event()
        def query(request, access):
            result = original(request, access)
            if request.dataset.value == "financial_income" and not revoked.is_set():
                grants[:] = [grant for grant in grants if grant.request.dataset.value != "financial_income"]
                revoked.set()
            return result
        service.query = query
        with self.assertRaises(PermissionDenied):
            self.runtime(ProgressModel(), service=service).run(self.request, self.f.access)
        self.assertTrue(revoked.is_set())
        grants[:] = [SourceGrant(self.f.service, self.f.access, binding.snapshot,
                    self.request.data_request(binding), binding.provider) for binding in self.request.bindings]
        service.query = original
        report = self.runtime(ProgressModel(), service=service).run(self.request, self.f.access)
        grants.clear()
        model = ProgressModel()
        with self.assertRaises(PermissionDenied):
            self.runtime(model, service=service).run(self.request, self.f.access, resume=report["run_id"])
        self.assertFalse(model.counts)

    def test_v2_cross_domain_reads_and_child_spawn_remain_permission_denied(self):
        for domain, forbidden in (("financial", "market"), ("market", "financial"),
                                   ("financial", "market_child"), ("market", "financial_child")):
            with self.subTest(domain=domain, tool=forbidden):
                def callback(role, turn, payload):
                    if role == domain and turn == 1:
                        return tool(forbidden)
                with self.assertRaises(PermissionDenied):
                    self.runtime(ProgressModel(callback)).run(self.request, self.f.access)

    def test_v2_context_overflow_retains_canonical_facts_evidence_and_replays(self):
        with patch("research_fixtures.ts", return_value=ts("2026-04-15T00:00:00")):
            self.f = fixture(Path(self.temp.name) / "large", prices=("100",) * 300)
        base = study_request(self.f, hypotheses=("financial_deterioration",)).to_dict()
        base["as_of"] = "2026-04-16T00:00:00+00:00"
        for binding in base["bindings"]:
            if binding["dataset"] == "market_daily":
                binding["end"] = str(date(2025, 4, 1) + timedelta(days=299))
        request = DynamicRequest.from_dict({**base, "question": "SYNTHETIC " + "x" * 1900})
        model = ProgressModel()
        report = self.runtime(model).run(request, self.f.access)
        self.assertEqual(report["stop_reason"], "dynamic_context_budget_exceeded")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(len(report["facts"]), 7)
        self.assertEqual(len(report["evidence"]), 305)
        self.assertEqual(len(self.parent_state(report["run_id"])["outputs"]["market"]["market_daily"]["records"]), 300)
        self.assertGreater(report["context_telemetry"][-1]["total_context_bytes"], 12000)
        self.assertFalse(report["context_telemetry"][-1]["model_dispatched"])
        model = ProgressModel()
        self.assertEqual(self.runtime(model).run(request, self.f.access, resume=report["run_id"]), report)
        self.assertFalse(model.counts)


if __name__ == "__main__":
    unittest.main()
