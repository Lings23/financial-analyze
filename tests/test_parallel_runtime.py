"""Synthetic P4.5 concurrency and safety mechanisms; no live financial truth."""
import copy
import json
import os
import uuid
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock, Thread, current_thread
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import finish, tool
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import AccessContext, digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, ParallelParentSpec
from stock_research.research.scoped import ScopedReadService, SourceGrant


def parallel_action():
    return {"action": "parallel", "tools": ["financial_child", "market_child"],
            "plan": ["Read the independent bound domains, then join their evidence"]}


class RoleModel:
    """A thread safe protocol fixture routing by the actual isolated child prompt."""
    config = SimpleNamespace(model="deepseek-v4-flash-0731")

    def __init__(self, callback=None, *, parent_actions=None):
        self.callback = callback
        self.parent_actions = parent_actions or [parallel_action(),
            tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
            tool("verification", ["hypotheses"]), finish()]
        self.counts, self.messages, self.threads = Counter(), [], {}
        self._lock = Lock()

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        role = ({"financial-child-v1": "financial", "market-child-v1": "market"}
                .get(payload.get("protocol_version"), "parent"))
        with self._lock:
            self.counts[role] += 1
            turn = self.counts[role]
            self.messages.append((role, turn, copy.deepcopy(messages)))
            self.threads.setdefault(role, set()).add(current_thread().name)
        if role == "parent":
            action = self.parent_actions[min(turn, len(self.parent_actions)) - 1]
        else:
            action = tool(role) if turn == 1 else finish()
        if self.callback is not None:
            replacement = self.callback(role, turn, messages)
            if replacement is not None:
                action = replacement
        content = action if isinstance(action, str) else json.dumps(action, ensure_ascii=False)
        return ChatResult(self.config.model, self.config.model, content, "stop",
                          f"synthetic-parallel-{role}-{turn}", 100, 20, 120, 1)


class ParallelRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({**study_request(self.f,
            hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: combine independently bound financial and market evidence"})

    def runtime(self, model, spec=None, **kwargs):
        return DynamicRuntime(self.f.service, self.f.store, model,
                              spec or ParallelParentSpec(), **kwargs)

    def parent_state(self):
        with self.f.store._connection() as db:
            row = db.execute("SELECT payload FROM checkpoints WHERE payload LIKE ? "
                "ORDER BY rowid DESC LIMIT 1", ('%dynamic-parent-parallel-v1%',)).fetchone()
        return json.loads(row[0])

    def test_independent_children_really_overlap_and_have_isolated_contexts(self):
        rendezvous = Barrier(2, timeout=5)
        observations = []
        obs_lock = Lock()
        def callback(role, turn, messages):
            if role in {"financial", "market"} and turn == 1:
                rendezvous.wait()
                parent = self.parent_state()
                with obs_lock:
                    observations.append(parent)
            if role == "parent" and turn > 1:
                self.assertEqual(len(self.parent_state()["child_results"]), 2)
        model = RoleModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(observations), 2)
        self.assertEqual(model.counts, {"parent": 5, "financial": 2, "market": 2})
        self.assertNotEqual(model.threads["financial"], model.threads["market"])
        self.assertEqual(report["root_budget"]["total_tokens"], 9 * 120)
        self.assertEqual(len(report["child_results"]), 2)
        for role, turn, messages in model.messages:
            if role == "parent":
                continue
            payload = json.loads(messages[1]["content"])
            self.assertEqual(payload["available_tools"], [role])
            self.assertEqual(payload["required_checks"], ["read:" + role])
            self.assertEqual(set(payload["bound_windows"]), {
                "financial_income" if role == "financial" else "market_daily"})
            self.assertNotIn("parallel_group", messages[1]["content"])
            self.assertNotIn("context_telemetry", messages[1]["content"])
        state = self.parent_state()
        group = state["parallel_groups"][0]
        for observed in observations:
            self.assertEqual({n["status"] for n in observed["parallel_groups"][0]["nodes"].values()
                              if n.get("domain") in {"financial", "market"}}, {"running"})
        child_runs = [c["child_run_id"] for c in report["child_results"]]
        self.assertEqual(len(set(child_runs)), 2)
        for run in child_runs:
            child = self.f.store.read(self.f.access.scope, run)
            self.assertLessEqual(ts(child["deadline"]), ts(state["deadline"]))
            self.assertEqual(child["request"]["as_of"], state["request"]["as_of"])
            self.assertEqual(child["request"]["mode"], state["request"]["mode"])

    def test_completed_replay_has_zero_model_calls_and_identical_receipts(self):
        report = self.runtime(RoleModel()).run(self.request, self.f.access)
        model = RoleModel()
        replay = self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(replay, report)
        self.assertEqual(model.counts, {})

    def test_completion_order_does_not_change_facts_evidence_or_links(self):
        reports = []
        observed_orders = []
        for first in ("financial", "market"):
            rendezvous = Barrier(2, timeout=5)
            first_returned = Event()
            actual_order = []
            order_lock = Lock()
            def callback(role, turn, messages):
                if role in {"financial", "market"} and turn == 1:
                    rendezvous.wait()
                if role in {"financial", "market"} and turn == 2:
                    if role != first:
                        self.assertTrue(first_returned.wait(5))
                    with order_lock:
                        actual_order.append(role)
                    if role == first:
                        first_returned.set()
            reports.append(self.runtime(RoleModel(callback)).run(self.request, self.f.access))
            observed_orders.append(actual_order)
        self.assertEqual(observed_orders, [["financial", "market"], ["market", "financial"]])
        self.assertEqual(reports[0]["facts"], reports[1]["facts"])
        self.assertEqual(reports[0]["hypotheses"], reports[1]["hypotheses"])
        def evidence_graph(report):
            evidence = copy.deepcopy(report["evidence"])
            for entry in evidence.values():
                entry.pop("tool_call_id", None)
            links = sorted((link["evidence_id"], link["record_id"]) for link in report["child_evidence_links"])
            return evidence, links
        self.assertEqual(evidence_graph(reports[0]), evidence_graph(reports[1]))
        for report in reports:
            self.assertEqual([c["domain"] for c in report["child_results"]], ["financial", "market"])

    def test_root_denies_group_before_any_child_model_dispatch(self):
        for spec in (ParallelParentSpec(root_max_decisions=6),
                     ParallelParentSpec(root_max_tools=3), ParallelParentSpec(root_max_tokens=35999)):
            with self.subTest(spec=spec):
                model = RoleModel()
                report = self.runtime(model, spec).run(self.request, self.f.access)
                self.assertEqual(model.counts, {"parent": 1})
                self.assertEqual(report["stop_reason"], "root_budget_exceeded")
                self.assertEqual(report["child_results"], [])

    def test_parent_followup_checks_keep_budget_after_parallel_settlement(self):
        report = self.runtime(RoleModel()).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 0)
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 0)
        self.assertEqual(report["root_budget"]["model_attempts"], 9)
        self.assertGreaterEqual(report["root_budget"]["remaining"]["decisions"], 0)

    def test_one_unknown_paid_child_and_one_success_never_become_completed(self):
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, messages):
            if role in {"financial", "market"} and turn == 1:
                rendezvous.wait()
                if role == "financial":
                    raise RuntimeError("synthetic unknown paid result")
        model = RoleModel(callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["stop_reason"], "parallel_required_branch_incomplete")
        self.assertEqual(model.counts, {"parent": 1, "financial": 1, "market": 2})
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 1)
        self.assertGreater(report["root_budget"]["tokens_accounted"], report["root_budget"]["total_tokens"])
        self.assertEqual(self.parent_state()["outputs"].keys(), {"market"})
        model = RoleModel()
        self.assertEqual(self.runtime(model).run(self.request, self.f.access,
            resume=report["run_id"]), report)
        self.assertEqual(model.counts, {})

    def test_repeated_group_never_starts_same_domain_twice(self):
        actions = [parallel_action(), parallel_action(),
            tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
            tool("verification", ["hypotheses"]), finish()]
        model = RoleModel(parent_actions=actions)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(model.counts["financial"], 2)
        self.assertEqual(model.counts["market"], 2)
        self.assertEqual(len(report["child_results"]), 2)
        self.assertTrue(any(e["event"] == "repeated_action" or
            e["event"] == "model_finished" and e.get("status") == "invalid_action" for e in report["trace"]))

    def test_child_cross_domain_read_is_rejected_while_other_branch_runs(self):
        rendezvous = Barrier(2, timeout=5)
        runtime, children = self.runtime(None), {}
        original_child_context = runtime._child_context
        def capture_child(*args, **kwargs):
            result = original_child_context(*args, **kwargs)
            children[args[4] if len(args) > 4 else kwargs.get("domain", "financial")] = result[0]
            return result
        def callback(role, turn, messages):
            if role in {"financial", "market"} and turn == 1:
                rendezvous.wait()
                if role == "financial":
                    return tool("market")
                # Keep the sibling in its paid call until the security fault
                # cancels the group. A start barrier alone also permits Market
                # to finish and be accepted before Financial's fault is handled.
                until = monotonic() + 5
                while not children["market"].cancelled() and monotonic() < until:
                    Event().wait(0.005)
                self.assertTrue(children["market"].cancelled())
        model = RoleModel(callback)
        runtime.model = model
        with patch.object(runtime, "_child_context", side_effect=capture_child), self.assertRaises(PermissionDenied):
            runtime.run(self.request, self.f.access)
        state = self.parent_state()
        self.assertTrue(state.get("security_stopped"))
        self.assertNotIn("financial", state["outputs"])
        telemetry = state["parallel_groups"][0]["telemetry"]
        self.assertEqual(telemetry["failed_branch_count"], 2)
        self.assertEqual(telemetry["unknown_usage_count"], 2)
        self.assertTrue(any(e["event"] == "parallel_telemetry" for e in state["trace"]))

    def test_cancel_after_reservation_before_start_closes_telemetry_without_dispatch(self):
        cancel = Event()
        original = self.f.store.append
        def append(scope, run, state):
            original(scope, run, state)
            if state["trace"] and state["trace"][-1]["event"] == "parallel_group_reserved":
                cancel.set()
        self.f.store.append = append
        model = RoleModel()
        report = self.runtime(model, cancelled=cancel.is_set).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(model.counts, {"parent": 1})
        telemetry = report["parallel_groups"][0]["telemetry"]
        self.assertEqual(telemetry["cancelled_branch_count"], 2)
        self.assertEqual(telemetry["root_actual_decisions"], 0)
        self.assertEqual(telemetry["unknown_usage_count"], 0)
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 2)
        cancel.clear()
        self.assertEqual(self.runtime(RoleModel()).run(self.request, self.f.access,
                         resume=report["run_id"]), report)

    def test_cancel_reaches_both_running_children_and_late_data_is_not_imported(self):
        cancel = Event()
        rendezvous = Barrier(2, timeout=5)
        entered = set()
        entered_lock = Lock()
        def callback(role, turn, messages):
            if role in {"financial", "market"} and turn == 1:
                with entered_lock:
                    entered.add(role)
                rendezvous.wait()
                cancel.set()
        model = RoleModel(callback)
        report = self.runtime(model, cancelled=cancel.is_set).run(self.request, self.f.access)
        self.assertEqual(entered, {"financial", "market"})
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        self.assertEqual(model.counts, {"parent": 1, "financial": 1, "market": 1})
        self.assertEqual(self.parent_state()["outputs"], {})
        telemetry = report["parallel_groups"][0]["telemetry"]
        self.assertEqual(telemetry["cancelled_branch_count"], 2)
        self.assertEqual(telemetry["late_branch_count"], 2)

    def test_root_deadline_rejects_both_late_results_without_changing_cutoff(self):
        wall = [ts("2026-10-05T00:00:00")]
        wall_lock = Lock()
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, messages):
            if role in {"financial", "market"} and turn == 1:
                rendezvous.wait()
                with wall_lock:
                    wall[0] = ts("2026-10-05T00:04:01")
        report = self.runtime(RoleModel(callback), now=lambda: wall[0], monotonic=lambda: 0).run(
            self.request, self.f.access)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        self.assertEqual(self.parent_state()["request"], self.request.to_dict())

    def test_revoke_grant_during_parallel_read_prevents_cached_import(self):
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot,
            self.request.data_request(b), b.provider) for b in self.request.bindings]
        revoked = Event()
        service = ScopedReadService(self.f.access.scope, lambda: list(grants))
        original = service.query
        def query(request, context):
            result = original(request, context)
            if request.dataset.value == "financial_income" and not revoked.is_set():
                grants[:] = [grant for grant in grants if grant.request.dataset.value != "financial_income"]
                revoked.set()
            return result
        service.query = query
        runtime = DynamicRuntime(service, self.f.store, RoleModel(), ParallelParentSpec())
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, self.f.access)
        self.assertTrue(revoked.is_set())
        self.assertNotIn("financial", self.parent_state()["outputs"])

    def test_completed_replay_rechecks_source_grants_and_source_bytes(self):
        report = self.runtime(RoleModel()).run(self.request, self.f.access)
        with self.assertRaises(PermissionDenied):
            self.runtime(RoleModel(), delegated_tools=frozenset({"market"})).run(
                self.request, self.f.access, resume=report["run_id"])
        source = self.f.artifacts._path(self.f.access.scope, self.f.financial.artifact_id)
        source.write_bytes(b"tampered synthetic financial artifact")
        with self.assertRaises(IntegrityError):
            self.runtime(RoleModel()).run(self.request, self.f.access, resume=report["run_id"])

    def test_context_cap_stays_frozen_and_parallel_telemetry_stays_out_of_messages(self):
        with self.assertRaises(ValidationError):
            ParallelParentSpec(context_bytes=12001)
        model = RoleModel()
        report = self.runtime(model).run(self.request, self.f.access)
        for role, turn, messages in model.messages:
            self.assertLessEqual(sum(len(m["content"].encode("utf-8")) for m in messages), 12000)
            for term in ("context_before_compaction_bytes", "sum_branch_execution_ms", "root_actual_tokens"):
                self.assertNotIn(term, messages[1]["content"])
        self.assertEqual(report["context"]["byte_budget"], 12000)

    def test_context_telemetry_matches_actual_parent_and_child_wires_and_known_tokens(self):
        model = RoleModel()
        report = self.runtime(model).run(self.request, self.f.access)
        states = {"parent": self.f.store.read(self.f.access.scope, report["run_id"])}
        for child in report["child_results"]:
            states[child["domain"]] = self.f.store.read(self.f.access.scope, child["child_run_id"])
        core = {"run_id", "parent_run_id", "child_run_id", "agent_role", "domain", "turn_id", "route_type",
            "parallel_group_id", "parallel_width", "context_limit_bytes", "context_before_compaction_bytes",
            "context_after_compaction_bytes", "total_context_bytes", "visible_fact_count", "visible_claim_count",
            "visible_evidence_count", "total_fact_count", "total_claim_count", "total_evidence_count",
            "input_tokens", "output_tokens", "total_tokens", "model_dispatched", "context_budget_exceeded",
            "status", "stop_reason"}
        for role, turn, messages in model.messages:
            records = [event for event in states[role]["trace"]
                       if event.get("schema") == "context-telemetry/v1" and event.get("turn_id") == turn]
            self.assertTrue(records, (role, turn))
            record = records[-1]
            self.assertTrue(core <= set(record), (role, turn, core - set(record)))
            size = sum(len(message["content"].encode("utf-8")) for message in messages)
            self.assertEqual(record["context_after_compaction_bytes"], size)
            self.assertEqual(record["total_context_bytes"], size)
            self.assertEqual(record["message_sha256"], digest(messages))
            # A small initial catalog has framing overhead; measure negative
            # savings honestly rather than inventing a larger baseline.
            self.assertGreater(record["context_before_compaction_bytes"], 0)
            self.assertEqual(record["context_saved_bytes"], record["context_before_compaction_bytes"] - size)
            self.assertEqual(record["context_limit_bytes"], 12000)
            self.assertEqual((record["input_tokens"], record["output_tokens"], record["total_tokens"]), (100, 20, 120))
            self.assertTrue(record["model_dispatched"])
            self.assertFalse(record["context_budget_exceeded"])
            self.assertEqual(record["agent_role"].lower(), "parent" if role == "parent" else "child")
            if role != "parent":
                self.assertEqual(record["domain"], role)
                self.assertEqual(record["parent_run_id"], report["run_id"])
                self.assertEqual(record["child_run_id"], states[role]["run_id"])
                self.assertEqual(record["parallel_width"], 2)
                self.assertTrue(record["parallel_group_id"])
        parent_records = [event for event in states["parent"]["trace"]
                          if event.get("schema") == "context-telemetry/v1"]
        full = parent_records[-1]
        self.assertEqual(full["total_fact_count"], len(report["facts"]))
        self.assertEqual(full["total_claim_count"], len(report["facts"]))
        self.assertEqual(full["total_evidence_count"], len(report["evidence"]))
        self.assertGreater(full["context_saved_bytes"], 0)
        before = copy.deepcopy(states)
        self.assertEqual(self.runtime(RoleModel()).run(self.request, self.f.access,
                         resume=report["run_id"]), report)
        for state in before.values():
            self.assertEqual(self.f.store.read(self.f.access.scope, state["run_id"]), state)

    def test_two_coordinators_cannot_reserve_the_same_stale_root_balance(self):
        ready, release, rendezvous = Event(), Event(), Barrier(2, timeout=5)
        result, errors = [], []
        run_id = uuid.uuid4().hex
        def callback(role, turn, messages):
            if role != "parent" and turn == 1:
                rendezvous.wait()
                ready.set()
                self.assertTrue(release.wait(5))
        def run_parent():
            try:
                result.append(self.runtime(RoleModel(callback)).run(self.request, self.f.access, run_id=run_id))
            except BaseException as exc:
                errors.append(exc)
        worker = Thread(target=run_parent)
        worker.start()
        try:
            self.assertTrue(ready.wait(5))
            competing = RoleModel()
            with self.assertRaisesRegex(ValidationError, "already active"):
                self.runtime(competing).run(self.request, self.f.access, resume=run_id)
            self.assertFalse(competing.counts)
        finally:
            release.set()
            worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertEqual(result[0]["status"], "completed")
        self.assertEqual(len([e for e in self.parent_state()["root_budget"]["events"]
                              if e["kind"] == "children_reserved"]), 1)

    def test_parallel_merge_overflow_preserves_canonical_facts_and_replays_exactly(self):
        # A valid bounded 300-day synthetic snapshot; no provider or financial truth.
        with patch("research_fixtures.ts", return_value=ts("2026-04-15T00:00:00")):
            self.f = fixture(Path(self.temp.name) / "large", prices=("100",) * 300)
        base = study_request(self.f, hypotheses=("financial_deterioration",)).to_dict()
        base["as_of"] = "2026-04-16T00:00:00+00:00"
        for binding in base["bindings"]:
            if binding["dataset"] == "market_daily":
                binding["end"] = str(date(2025, 4, 1) + timedelta(days=299))
        self.request = DynamicRequest.from_dict({**base, "question": "SYNTHETIC " + "x" * 1900})
        model = RoleModel()
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "dynamic_context_budget_exceeded")
        self.assertEqual(model.counts, {"parent": 2, "financial": 2, "market": 2})
        self.assertEqual(len(report["facts"]), 7)
        self.assertEqual(len(report["evidence"]), 305)
        state = self.parent_state()
        self.assertEqual(len(state["outputs"]["market"]["market_daily"]["records"]), 300)
        overflow = report["context_telemetry"][-1]
        self.assertGreater(overflow["context_after_compaction_bytes"], 12000)
        self.assertEqual(overflow["context_limit_bytes"], 12000)
        self.assertTrue(overflow["context_budget_exceeded"])
        self.assertFalse(overflow["model_dispatched"])
        replay = RoleModel()
        self.assertEqual(self.runtime(replay).run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertFalse(replay.counts)

    def test_context_receipt_telemetry_tamper_is_rejected_on_replay(self):
        report = self.runtime(RoleModel()).run(self.request, self.f.access)
        state = self.parent_state()
        state["context_telemetry"][0]["input_tokens"] = 999
        state["decisions"][0]["context_telemetry"]["input_tokens"] = 999
        self.f.store.append(self.f.access.scope, report["run_id"], state)
        with self.assertRaisesRegex(IntegrityError, "context telemetry receipt"):
            self.runtime(RoleModel()).run(self.request, self.f.access, resume=report["run_id"])

    def test_parallel_telemetry_tamper_is_rejected_on_replay(self):
        report = self.runtime(RoleModel()).run(self.request, self.f.access)
        state = self.parent_state()
        state["parallel_groups"][0]["telemetry"]["root_actual_tokens"] += 1
        self.f.store.append(self.f.access.scope, report["run_id"], state)
        with self.assertRaisesRegex(IntegrityError, "parallel telemetry"):
            self.runtime(RoleModel()).run(self.request, self.f.access, resume=report["run_id"])

    @unittest.skipUnless(os.environ.get("STOCK_RESEARCH_TEST_DSN"), "isolated PostgreSQL DSN required")
    def test_parallel_postgres_reads_and_reopened_completed_replay(self):
        from stock_research.storage.postgres import PostgresRepository
        from stock_research.research.checkpoints import CheckpointStore
        repository = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        repository.migrate()
        self.f = fixture(Path(self.temp.name) / "postgres", scope="p45-test-" + uuid.uuid4().hex,
                         repo=repository)
        self.request = DynamicRequest.from_dict({**study_request(self.f,
            hypotheses=("financial_deterioration",)).to_dict(), "question": "SYNTHETIC PostgreSQL parallel test"})
        rendezvous = Barrier(2, timeout=5)
        def callback(role, turn, messages):
            if role != "parent" and turn == 1:
                rendezvous.wait()
        report = self.runtime(RoleModel(callback)).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.f.service.repository = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        self.f.store = CheckpointStore(Path(self.temp.name) / "postgres" / "runs")
        replay_model = RoleModel()
        self.assertEqual(self.runtime(replay_model).run(self.request, self.f.access,
                         resume=report["run_id"]), report)
        self.assertEqual(sum(replay_model.counts.values()), 0)


if __name__ == "__main__":
    unittest.main()
