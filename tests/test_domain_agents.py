"""Synthetic serial domain routing safety, not financial truth or live quality."""
import copy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel, completed_actions, finish, tool
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import DataRecord
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DYNAMIC_TOOLS, AGENT_TOOLS, DynamicRequest, DomainParentSpec,
    FinancialParentSpec, FinancialChildSpec, FinancialRequest, MarketChildSpec, MarketRequest)
from stock_research.research.scoped import ScopedReadService, SourceGrant


def domain_actions(order=("financial", "market"), direct=()):
    actions = []
    for domain in order:
        if domain in direct:
            actions.append(tool(domain))
        else:
            actions.extend([tool(domain + "_child"), tool(domain), finish()])
    return actions + [tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                      tool("verification", ["hypotheses"]), finish()]


class DomainAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({**study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
                                               "question": "SYNTHETIC: inspect bound market and financial domains"})

    def runtime(self, model, spec=None, service=None, **kwargs):
        return DynamicRuntime(service or self.f.service, self.f.store, model, spec or DomainParentSpec(), **kwargs)

    def test_two_serial_children_share_root_and_keep_domain_state_separate(self):
        model = SequenceModel(domain_actions())
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual([c["domain"] for c in report["child_results"]], ["financial", "market"])
        self.assertEqual(report["root_budget"]["model_attempts"], 10)
        self.assertEqual(report["root_budget"]["tool_attempts"], 7)
        self.assertEqual(report["root_budget"]["tokens_accounted"], 1200)
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 0)
        self.assertEqual(len({c["child_run_id"] for c in report["child_results"]}), 2)
        self.assertEqual([r["mode"] for r in report["routes"]], ["delegated", "delegated", "direct", "direct", "direct"])
        for child in report["child_results"]:
            state = self.f.store.read(self.f.access.scope, child["child_run_id"])
            self.assertEqual(state["requirements"], ["read:" + child["domain"]])
            self.assertEqual({b["dataset"] for b in state["request"]["bindings"]},
                             {"financial_income"} if child["domain"] == "financial" else {"market_daily"})
            self.assertEqual(state["request"]["as_of"], self.request.to_dict()["as_of"])
            self.assertLessEqual(ts(child["deadline"]), ts(self.f.store.read(self.f.access.scope, report["run_id"])["deadline"]))
            self.assertTrue(any(link["child_run_id"] == child["child_run_id"] for link in report["child_evidence_links"]))
        parent = self.f.store.read(self.f.access.scope, report["run_id"])
        self.assertEqual(parent["root_budget"]["schema"], "root-budget/v2")
        self.assertEqual(parent["root_budget"]["max_children"], 2)
        events = [e["event"] for e in parent["trace"] if e["event"].startswith("child_")]
        self.assertEqual(events, ["child_reserved", "child_finished", "child_reserved", "child_finished"])
        payload = json.loads(model.messages[3][1]["content"])
        self.assertEqual(payload["delegation_results"][0]["domain"], "financial")
        self.assertEqual(payload["delegation_results"][0]["status"], "completed")

    def test_direct_and_delegated_routes_work_in_both_orders(self):
        for direct in (("financial",), ("market",), ("financial", "market")):
            for order in (("market", "financial"), ("financial", "market")):
                with self.subTest(direct=direct, order=order):
                    report = self.runtime(SequenceModel(domain_actions(order, direct))).run(self.request, self.f.access)
                    self.assertEqual(report["status"], "completed")
                    self.assertEqual(len(report["child_results"]), 2 - len(direct))
                    self.assertEqual([r["domain"] for r in report["routes"][:2]], list(order))
                    for route in report["routes"][:2]:
                        self.assertEqual(route["mode"], "direct" if route["domain"] in direct else "delegated")

    def test_observation_drives_parent_choice_to_delegate_market(self):
        actions = domain_actions(direct=("financial",))
        def callback(call, messages):
            payload = json.loads(messages[1]["content"])
            if call == 2:
                self.assertEqual(payload["protocol_version"], "dynamic-parent-domains-v1")
                self.assertEqual(payload["observations"][0]["tool"], "financial")
                self.assertEqual(payload["observations"][0]["datasets"]["financial_income"]["records"], 2)
                return tool("market_child", plan=["财务可見，委派行情读取后再核验"])
            return actions[call - 1]
        report = self.runtime(SequenceModel([], callback=callback)).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["routes"][1]["mode"], "delegated")

    def test_two_children_completed_replay_identical_without_model_calls(self):
        report = self.runtime(SequenceModel(domain_actions(("market", "financial")))).run(self.request, self.f.access)
        model = SequenceModel([])
        replay = self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(report, replay)
        self.assertEqual(model.calls, 0)

    def test_domain_role_specs_and_old_parent_identity_cannot_change_on_resume(self):
        report = self.runtime(SequenceModel(domain_actions())).run(self.request, self.f.access)
        for kwargs in ({"spec": FinancialParentSpec()}, {"domain_child_specs": {
                "financial": FinancialChildSpec(), "market": MarketChildSpec(max_tokens=17000)}},
                      {"delegated_tools": {"financial"}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(PermissionDenied):
                self.runtime(SequenceModel([]), **kwargs).run(self.request, self.f.access, resume=report["run_id"])

    def test_role_tool_and_data_intersections_hide_unauthorized_agenttools(self):
        for kwargs in ({"granted_tools": DYNAMIC_TOOLS | {"financial_child"}},
                       {"granted_tools": (DYNAMIC_TOOLS - {"market"}) | AGENT_TOOLS},
                       {"delegated_tools": {"financial"}}, {"delegated_datasets": {"financial_income"}},
                       {"domain_child_specs": {"financial": FinancialChildSpec(), "market": MarketChildSpec(
                           allowed_tools=frozenset(), visible_tools=frozenset())}}):
            with self.subTest(kwargs=kwargs):
                model = SequenceModel([tool("market_child")])
                with self.assertRaises(PermissionDenied):
                    self.runtime(model, **kwargs).run(self.request, self.f.access)
                self.assertEqual(model.calls, 1)

    def test_market_child_cannot_read_financial_or_spawn_either_domain(self):
        for forbidden in ("financial", "financial_child", "market_child", "calculation"):
            with self.subTest(tool=forbidden):
                model = SequenceModel([tool("market_child"), tool(forbidden)])
                with self.assertRaises(PermissionDenied):
                    self.runtime(model).run(self.request, self.f.access)
                self.assertEqual(model.calls, 2)

    def test_second_child_is_denied_when_root_remaining_allocation_is_insufficient(self):
        model = SequenceModel(domain_actions())
        report = self.runtime(model, DomainParentSpec(root_max_decisions=6)).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "root_budget_exceeded")
        self.assertEqual(model.calls, 4)
        self.assertEqual([c["domain"] for c in report["child_results"]], ["financial"])
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 0)
        self.assertNotIn("market", {link["child_run_id"] for link in report["child_evidence_links"]})

    def test_repeat_domain_after_other_child_never_spawns_again(self):
        actions = domain_actions()[:6] + [tool("financial_child"), tool("financial_child")]
        model = SequenceModel(actions)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(len(report["child_results"]), 2)
        self.assertEqual(report["usage"]["tool_calls"], 2)
        self.assertEqual(len([e for e in report["trace"] if e["event"] == "child_reserved"]), 2)

    def test_partial_unknown_child_feedback_can_route_to_other_domain_and_direct_read(self):
        tail = [tool("market_child"), tool("market"), finish(), tool("financial"),
                tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                tool("verification", ["hypotheses"]), finish()]
        def callback(call, messages):
            if call == 1:
                return tool("financial_child")
            if call == 2:
                raise RuntimeError("synthetic unknown paid outcome")
            if call == 3:
                feedback = json.loads(messages[1]["content"])["delegation_results"]
                self.assertEqual(feedback[0]["status"], "partial")
                self.assertEqual(feedback[0]["domain"], "financial")
            return tail[call - 3]
        report = self.runtime(SequenceModel([], callback=callback)).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual([c["status"] for c in report["child_results"]], ["partial", "completed"])
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 1)
        self.assertGreater(report["root_budget"]["tokens_accounted"], report["root_budget"]["total_tokens"])
        replay = self.runtime(SequenceModel([])).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(report, replay)

    def test_partial_child_repeat_cannot_use_second_child_slot(self):
        def callback(call, messages):
            if call == 2:
                raise RuntimeError("synthetic unknown")
            return tool("financial_child")
        model = SequenceModel([], callback=callback)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(len(report["child_results"]), 1)
        self.assertEqual(len([e for e in report["trace"] if e["event"] == "child_reserved"]), 1)

    def test_second_child_unknown_crash_retains_first_settlement_and_never_replays_paid_call(self):
        def callback(call, messages):
            if call == 5:
                raise KeyboardInterrupt()
            return domain_actions()[call - 1]
        with self.assertRaises(KeyboardInterrupt):
            self.runtime(SequenceModel([], callback=callback)).run(self.request, self.f.access)
        with self.f.store._connection() as db:
            states = [json.loads(row[0]) for row in db.execute("SELECT payload FROM checkpoints ORDER BY rowid")]
        parent = next(s for s in reversed(states) if s.get("pending_child"))
        model = SequenceModel([])
        report = self.runtime(model).run(self.request, self.f.access, resume=parent["run_id"])
        self.assertEqual(model.calls, 0)
        self.assertEqual(report["stop_reason"], "unknown_tool_outcome_no_replay")
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 1)
        self.assertEqual(report["root_budget"]["tokens_accounted"], 18480)
        self.assertEqual(len(report["child_results"]), 1)

    def test_cancellation_in_second_child_withholds_prior_first_child_facts(self):
        cancelled = [False]
        def callback(call, messages):
            if call == 5:
                cancelled[0] = True
            return domain_actions()[call - 1]
        report = self.runtime(SequenceModel([], callback=callback), cancelled=lambda: cancelled[0]).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["child_evidence_links"], [])
        self.assertEqual(report["root_budget"]["unresolved_child_allocations"], 1)

    def test_deadline_in_second_child_discards_late_market_read(self):
        clock = [ts("2026-10-05T12:00:00")]
        def callback(call, messages):
            if call == 5:
                clock[0] += timedelta(seconds=241)
            return domain_actions()[call - 1]
        report = self.runtime(SequenceModel([], callback=callback), now=lambda: clock[0], monotonic=lambda: 0).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["facts"], [])
        self.assertEqual(len(report["child_results"]), 1)

    def test_live_market_grant_revocation_is_detected_during_child_and_completed_replay(self):
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot, self.request.data_request(b), b.provider)
                  for b in self.request.bindings]
        service = ScopedReadService(self.f.access.scope, lambda: tuple(grants))
        def callback(call, messages):
            if call == 5:
                grants[:] = [g for g in grants if g.request.dataset.value != "market_daily"]
            return domain_actions()[call - 1]
        with self.assertRaises(PermissionDenied):
            self.runtime(SequenceModel([], callback=callback), service=service).run(self.request, self.f.access)
        grants[:] = [SourceGrant(self.f.service, self.f.access, b.snapshot, self.request.data_request(b), b.provider)
                     for b in self.request.bindings]
        report = self.runtime(SequenceModel(domain_actions()), service=service).run(self.request, self.f.access)
        grants[:] = [g for g in grants if g.request.dataset.value != "market_daily"]
        with self.assertRaises(PermissionDenied):
            self.runtime(SequenceModel([]), service=service).run(self.request, self.f.access, resume=report["run_id"])

    def test_child_role_summary_origin_and_report_route_tampering_rejected(self):
        for field in ("domain", "source_origins", "routes"):
            with self.subTest(field=field):
                report = self.runtime(SequenceModel(domain_actions())).run(self.request, self.f.access)
                state = self.f.store.read(self.f.access.scope, report["run_id"])
                if field == "domain":
                    state["child_results"][1]["domain"] = "financial"
                elif field == "source_origins":
                    state["source_origins"]["market"] = state["source_origins"]["financial"]
                else:
                    state["report"]["routes"][1]["mode"] = "direct"
                self.f.store.append(self.f.access.scope, report["run_id"], state)
                with self.assertRaises(IntegrityError):
                    self.runtime(SequenceModel([])).run(self.request, self.f.access, resume=report["run_id"])

    def test_local_evidence_cannot_replay_with_another_domains_read_call(self):
        report = self.runtime(SequenceModel(domain_actions(direct=("financial", "market")))).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        financial_call = next(event["tool_call_id"] for event in state["trace"]
                              if event["event"] == "tool_finished" and event["tool"] == "financial")
        market_records = {DataRecord.from_dict(row).record_id
                          for result in state["outputs"]["market"].values() for row in result["records"]}
        evidence_id = next(key for key, evidence in state["calculated"]["evidence"].items()
                           if evidence["record_id"] in market_records)
        state["calculated"]["evidence"][evidence_id]["tool_call_id"] = financial_call
        # Match the cached report so reconstruction alone cannot detect wrong attribution.
        state["report"]["evidence"][evidence_id]["tool_call_id"] = financial_call
        self.f.store.append(self.f.access.scope, report["run_id"], state)
        model = SequenceModel([])
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(model.calls, 0)

    def test_market_child_parent_binding_prevents_cross_parent_resume(self):
        report = self.runtime(SequenceModel(domain_actions())).run(self.request, self.f.access)
        child = report["child_results"][1]
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        child_request = MarketRequest.from_parent(self.request)
        with self.assertRaises(PermissionDenied):
            DynamicRuntime(self.f.service, self.f.store, SequenceModel([]), MarketChildSpec(),
                parent_run_id="a" * 32, inherited_deadline=ts(state["deadline"])).run(child_request, self.f.access, resume=child["child_run_id"])

    def test_market_child_request_and_spec_cannot_widen_to_other_domains(self):
        child = MarketRequest.from_parent(self.request)
        self.assertEqual(child.as_of, self.request.as_of)
        self.assertEqual(child.mode, self.request.mode)
        self.assertEqual(child.bindings, (self.request.bindings[0],))
        with self.assertRaises(ValidationError):
            replace(child, bindings=self.request.bindings)
        with self.assertRaises(ValidationError):
            replace(child, as_of=child.as_of.replace(tzinfo=None))
        with self.assertRaises(ValidationError):
            MarketChildSpec(allowed_tools=frozenset({"market", "financial"}))
        with self.assertRaises(ValidationError):
            DomainParentSpec(max_children=3)


if __name__ == "__main__":
    unittest.main()
