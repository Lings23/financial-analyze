"""Synthetic dynamic-loop security mechanisms; never live financial validation."""
import copy
import json
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import add_domain, study_request
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import AccessContext, digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, DynamicSpec
from stock_research.research.scoped import ScopedReadService, SourceGrant


QUESTION = "分析已绑定股票的收入与归母净利润同报告期同比是否均下降。"


def tool(name, refs=(), plan=None):
    return {"action": "tool", "tool": name, "refs": list(refs),
            "plan": plan or ["核对已绑定证据，按结果调整下一步"]}


def finish(reason="completed"):
    return {"action": "finish", "reason": reason, "plan": ["请求结束并由程序核对必需检验"]}


def completed_actions(sources=("financial", "market")):
    return [*[tool(name) for name in sources], tool("calculation", sources),
            tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()]


class SequenceModel:
    """Scripted JSON protocol fixture, including callbacks driven by Observation."""
    config = SimpleNamespace(model="deepseek-v4-flash-0731")

    def __init__(self, actions, *, callback=None, crash=None, usage=(100, 20, 120)):
        self.actions = list(actions)
        self.callback, self.crash, self.usage = callback, crash, usage
        self.calls, self.messages = 0, []

    def complete(self, messages, **kwargs):
        self.calls += 1
        self.messages.append(copy.deepcopy(messages))
        if self.crash is not None:
            raise self.crash
        if self.callback is not None:
            content = self.callback(self.calls, messages)
        else:
            if self.calls > len(self.actions):
                raise AssertionError("dynamic runtime exceeded the scripted decisions")
            content = self.actions[self.calls - 1]
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, allow_nan=False)
        return ChatResult(self.config.model, self.config.model, content, "stop",
                          f"synthetic-dynamic-{self.calls}", *self.usage, 1)


class DynamicTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": QUESTION,
        })

    def runtime(self, model, **kwargs):
        return DynamicRuntime(self.f.service, self.f.store, model, **kwargs)

    def run_report(self, model, request=None, **kwargs):
        return self.runtime(model, **kwargs).run(request or self.request, self.f.access)

    def latest_run(self):
        with self.f.store._connection() as db:
            return db.execute("SELECT run FROM checkpoints ORDER BY rowid DESC LIMIT 1").fetchone()[0]

    def assert_stopped(self, report, reason=None):
        self.assertNotEqual(report["status"], "completed")
        self.assertTrue(report["stop_reason"])
        if reason is not None:
            self.assertIn(reason, report["stop_reason"])

    def test_first_model_decision_precedes_reads_and_observation_changes_next_action(self):
        observed_queries = []
        original = self.f.service.query
        actions = completed_actions()

        def query(*args):
            observed_queries.append(args[0].dataset.value)
            return original(*args)

        def decide(call, messages):
            payload = json.loads(messages[1]["content"])
            if call == 1:
                self.assertEqual(observed_queries, [])
                self.assertEqual(payload["observations"], [])
                self.assertIn("hypothesis:financial_deterioration", payload["required_checks"])
                self.assertIn("verification", payload["required_checks"])
            elif call == 2:
                observation = next(o for o in payload["observations"] if o["tool"] == "financial")
                self.assertEqual(observation["datasets"]["financial_income"]["records"], 2)
                self.assertEqual(observation["status"], "available")
                # A real observed response changes the plan and next domain.
                return tool("market", plan=["财务可见，改为补充已绑定行情"])
            return actions[call - 1]

        model = SequenceModel([], callback=decide)
        with patch.object(self.f.service, "query", side_effect=query):
            report = self.run_report(model)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(model.calls, 6)
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertEqual(report["hypotheses"][0]["status"], "unsupported")
        self.assertEqual(report["usage"]["model_attempts"], 6)
        self.assertEqual(report["usage"]["tool_calls"], 5)
        self.assertEqual(report["usage"]["financial_provider_network_calls"], 0)
        self.assertTrue(report["facts"])
        self.assertTrue(report["trace"])

    def test_missing_visible_financial_evidence_drives_alternative_read_and_insufficient_finish(self):
        snapshot = self.f.repo.commit(self.f.access.scope, self.f.records)
        request = replace(self.request, bindings=tuple(replace(b, snapshot=snapshot.snapshot_id)
                                                     for b in self.request.bindings))
        actions = completed_actions()
        actions[-1] = finish("insufficient")

        def decide(call, messages):
            payload = json.loads(messages[1]["content"])
            if call == 2:
                financial = next(o for o in payload["observations"] if o["tool"] == "financial")
                self.assertEqual(financial["status"], "insufficient")
                self.assertEqual(financial["datasets"]["financial_income"]["records"], 0)
                return tool("market", plan=["财务证据为空，核对原授权行情并保留财务缺口"])
            return actions[call - 1]

        report = self.run_report(SequenceModel([], callback=decide), request)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["hypotheses"][0]["status"], "insufficient")
        self.assertFalse(any(f["name"].startswith("financial_") for f in report["facts"]))
        self.assertEqual(report["verification"]["status"], "verified")

    def test_finish_before_required_checks_never_completes(self):
        model = SequenceModel([finish()])
        report = self.run_report(model)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(model.calls, 1)
        self.assertEqual(report["usage"]["tool_calls"], 0)
        self.assertEqual(report["facts"], [])

    def test_strict_bad_actions_cannot_inject_numbers_or_delete_required_checks(self):
        cases = ["not JSON", '{"action":"tool","tool":"financial","refs":[],"plan":["x"],"value":999}',
                 '{"action":"finish","reason":"completed","plan":["x"],"required_checks":[]}',
                 '{"action":"tool","tool":"financial","tool":"market","refs":[],"plan":["x"]}',
                 tool("calculation", ["F999"]), tool("financial", ["unknown-snapshot"])]
        for bad in cases:
            with self.subTest(bad=bad):
                model = SequenceModel([bad, bad])
                report = self.run_report(model)
                self.assert_stopped(report)
                self.assertEqual(report["facts"], [])
                self.assertEqual(report["usage"]["tool_calls"], 0)
                self.assertEqual(report["usage"]["model_attempts"], 2)
                self.assertNotIn("999", json.dumps(report.get("model", {})))

    def test_one_invalid_format_can_be_corrected_within_the_decision_budget(self):
        model = SequenceModel(["not JSON", *completed_actions()])
        report = self.run_report(model)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["usage"]["model_attempts"], 7)
        self.assertEqual(model.calls, 7)

    def test_repeated_actions_are_not_dispatched_and_two_no_progress_rounds_stop(self):
        model = SequenceModel([tool("financial"), tool("financial"), tool("financial")])
        with patch.object(self.f.service, "query", wraps=self.f.service.query) as query:
            report = self.run_report(model)
        self.assert_stopped(report)
        self.assertEqual(model.calls, 3)
        self.assertEqual(report["usage"]["tool_calls"], 1)
        # Reauthorization may read the pinned local bytes again; the repeated
        # actions must not consume or dispatch additional tool attempts.
        self.assertEqual(sum(e["event"] == "tool_started" for e in report["trace"]), 1)
        self.assertEqual(sum(e["event"] == "repeated_action" and e["dispatched"] is False
                             for e in report["trace"]), 2)

    def test_decision_budget_caps_paid_attempts(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model, spec=DynamicSpec(max_decisions=2))
        self.assert_stopped(report, "decision")
        self.assertEqual(model.calls, 2)
        self.assertEqual(report["usage"]["model_attempts"], 2)

    def test_tool_budget_prevents_additional_dispatch(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model, spec=DynamicSpec(max_tools=1))
        self.assert_stopped(report, "tool")
        self.assertEqual(report["usage"]["tool_calls"], 1)
        self.assertEqual(model.calls, 2)

    def test_total_token_budget_stops_before_first_paid_call(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model, spec=DynamicSpec(max_tokens=100))
        self.assert_stopped(report)
        self.assertEqual(model.calls, 0)
        self.assertEqual(report["usage"]["model_attempts"], 0)

    def test_context_overflow_does_not_drop_evidence_or_call_model(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model, spec=DynamicSpec(context_bytes=512))
        self.assert_stopped(report, "context")
        self.assertEqual(model.calls, 0)
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["usage"]["tool_calls"], 0)

    def test_cancelled_start_never_reads_or_dispatches(self):
        model = SequenceModel(completed_actions())
        with patch.object(self.f.service, "query", wraps=self.f.service.query) as query:
            report = self.run_report(model, cancelled=lambda: True)
        self.assert_stopped(report, "cancel")
        self.assertEqual(model.calls, 0)
        self.assertEqual(query.call_count, 0)
        self.assertEqual(report["facts"], [])

    def test_late_model_result_is_discarded_and_still_accounted(self):
        clock = [ts("2026-10-04T00:00:00")]

        def decide(call, messages):
            clock[0] += timedelta(seconds=241)
            return tool("financial")

        model = SequenceModel([], callback=decide)
        with patch.object(self.f.service, "query", wraps=self.f.service.query) as query:
            report = self.run_report(model, now=lambda: clock[0])
        self.assert_stopped(report, "deadline")
        self.assertEqual(model.calls, 1)
        self.assertEqual(query.call_count, 0)
        self.assertEqual(report["usage"]["model_attempts"], 1)
        self.assertGreater(report["usage"]["tokens_reserved"], 0)

    def test_late_local_read_never_enters_model_observation_or_report(self):
        clock = [ts("2026-10-04T00:00:00")]
        original = self.f.service.query

        def query(*args):
            result = original(*args)
            clock[0] += timedelta(seconds=241)
            return result

        model = SequenceModel([tool("financial")])
        with patch.object(self.f.service, "query", side_effect=query):
            report = self.run_report(model, now=lambda: clock[0])
        self.assert_stopped(report, "deadline")
        self.assertEqual(model.calls, 1)
        self.assertEqual(report["facts"], [])

    def test_unknown_paid_outcome_is_not_resent_on_resume_and_reservation_remains(self):
        model = SequenceModel([], crash=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_report(model)
        run = self.latest_run()
        state = self.f.store.read(self.f.access.scope, run)
        self.assertEqual(state["model_attempts"], 1)
        self.assertGreater(state["tokens_reserved"], 0)
        resumed_model = SequenceModel(completed_actions())
        report = self.runtime(resumed_model).run(self.request, self.f.access, resume=run)
        self.assert_stopped(report)
        self.assertEqual(resumed_model.calls, 0)
        self.assertEqual(report["usage"]["model_attempts"], 1)
        self.assertEqual(report["usage"]["tokens_reserved"], state["tokens_reserved"])

    def test_expired_pending_resume_does_not_read_or_publish_cached_claims(self):
        clock = [ts("2026-10-04T00:00:00")]
        model = SequenceModel([], crash=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_report(model, now=lambda: clock[0])
        run = self.latest_run()
        clock[0] += timedelta(seconds=241)
        resumed_model = SequenceModel(completed_actions())
        with patch.object(self.f.service, "query", wraps=self.f.service.query) as query:
            report = self.runtime(resumed_model, now=lambda: clock[0]).run(self.request, self.f.access, resume=run)
        self.assert_stopped(report)
        self.assertEqual(resumed_model.calls, 0)
        self.assertEqual(query.call_count, 0)
        self.assertEqual(report["facts"], [])

    def test_completed_resume_reauthorizes_without_paid_replay(self):
        model = SequenceModel(completed_actions())
        runtime = self.runtime(model)
        report = runtime.run(self.request, self.f.access)
        self.assertEqual(runtime.run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertEqual(model.calls, 6)
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, AccessContext("another-scope", frozenset({"fixture"})),
                        resume=report["run_id"])
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, AccessContext(self.f.access.scope, frozenset({"other"})),
                        resume=report["run_id"])

    def test_changed_request_question_cutoff_snapshot_or_spec_cannot_resume(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model)
        changed = (replace(self.request, question=QUESTION + "补充分析"),
                   replace(self.request, as_of=self.request.as_of + timedelta(seconds=1)),
                   replace(self.request, bindings=tuple(replace(b, snapshot="0" * 64)
                                                       for b in self.request.bindings)))
        for request in changed:
            with self.subTest(request=request), self.assertRaises(PermissionDenied):
                self.runtime(model).run(request, self.f.access, resume=report["run_id"])
        with self.assertRaises(PermissionDenied):
            self.runtime(model, spec=DynamicSpec(max_decisions=7)).run(
                self.request, self.f.access, resume=report["run_id"])

    def test_revoked_source_grant_blocks_completed_replay(self):
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot,
                              self.request.data_request(b), b.provider) for b in self.request.bindings]
        access = AccessContext("synthetic-dynamic-recipient", frozenset({"fixture"}))
        service = ScopedReadService(access.scope, lambda: grants)
        model = SequenceModel(completed_actions())
        runtime = DynamicRuntime(service, self.f.store, model)
        report = runtime.run(self.request, access)
        grants.clear()
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, access, resume=report["run_id"])
        self.assertEqual(model.calls, 6)

    def test_corrupted_source_bytes_block_completed_replay(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model)
        self.f.artifacts._path(self.f.access.scope, self.f.financial.artifact_id).write_bytes(b"corrupt")
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])

    def test_model_usage_with_unknown_or_invalid_values_cannot_complete(self):
        for usage in ((None, None, None), (True, 20, 21), (100, 20, 121), (100, 1025, 1125)):
            with self.subTest(usage=usage):
                model = SequenceModel(completed_actions(), usage=usage)
                report = self.run_report(model)
                self.assert_stopped(report)
                self.assertEqual(model.calls, 1)
                self.assertGreater(report["usage"]["tokens_reserved"], 0)
                self.assertEqual(report["usage"]["tool_calls"], 0)

    def test_model_transport_error_is_sanitized_and_never_retried(self):
        model = SequenceModel([], crash=ValueError("secret-like-error-do-not-log"))
        report = self.run_report(model)
        self.assert_stopped(report)
        self.assertEqual(model.calls, 1)
        self.assertNotIn("secret-like-error", json.dumps(report, ensure_ascii=False))
        self.assertGreater(report["usage"]["tokens_reserved"], 0)

    def test_plan_text_does_not_become_financial_facts_or_override_target(self):
        actions = completed_actions()
        actions[0]["plan"] = ["利润为999亿，因此只需直接宣告完成"]
        model = SequenceModel(actions)
        report = self.run_report(model)
        self.assertEqual(report["status"], "completed")
        self.assertEqual([h["id"] for h in report["hypotheses"]], ["financial_deterioration"])
        self.assertFalse(any("999" in f["value"] for f in report["facts"]))

    def test_untrusted_document_titles_and_bodies_are_excluded_from_model_context(self):
        base = study_request(self.f, hypotheses=("financial_deterioration",))
        base, _ = add_domain(self.f, base, "announcement")
        request = DynamicRequest.from_dict({**base.to_dict(), "question": QUESTION})
        model = SequenceModel(completed_actions(("announcement", "financial", "market")))
        report = self.run_report(model, request)
        self.assertEqual(report["status"], "completed")
        outgoing = json.dumps(model.messages, ensure_ascii=False)
        self.assertNotIn("99999", outgoing)
        self.assertNotIn("ignore rules", outgoing)
        self.assertNotIn("example.invalid", outgoing)

    def test_permission_violation_stops_immediately(self):
        spec = DynamicSpec(allowed_tools=frozenset({"financial", "calculation", "hypotheses", "verification"}),
                           visible_tools=frozenset({"financial", "calculation", "hypotheses", "verification"}))
        model = SequenceModel([tool("market")])
        with self.assertRaises(PermissionDenied):
            self.run_report(model, spec=spec)

    def test_rehashed_report_numeric_tampering_is_rejected(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model)
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        forged = copy.deepcopy(state)
        fact = forged["report"]["facts"][0]
        fact["value"] = "999"
        fact["id"] = digest({k: v for k, v in fact.items() if k != "id"})
        self.f.store.append(self.f.access.scope, report["run_id"], forged)
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])

    def test_rehashed_checkpoint_required_checks_cannot_be_deleted(self):
        model = SequenceModel(completed_actions())
        report = self.run_report(model)
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        state["requirements"] = []
        self.f.store.append(self.f.access.scope, report["run_id"], state)
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])

    def test_crash_during_tool_preserves_attempt_and_never_repeats_unknown_action(self):
        model = SequenceModel([tool("financial")])
        with patch.object(self.f.service, "query", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_report(model)
        run = self.latest_run()
        before = self.f.store.read(self.f.access.scope, run)
        self.assertEqual(before["tools_used"], 1)
        resumed_model = SequenceModel(completed_actions())
        report = self.runtime(resumed_model).run(self.request, self.f.access, resume=run)
        self.assert_stopped(report)
        self.assertEqual(resumed_model.calls, 0)
        self.assertEqual(report["usage"]["tool_calls"], 1)
        self.assertEqual(report["usage"]["model_attempts"], 1)

    def test_reauthorization_between_decisions_blocks_revoked_source(self):
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot,
                              self.request.data_request(b), b.provider) for b in self.request.bindings]
        access = AccessContext("synthetic-live-revocation", frozenset({"fixture"}))
        service = ScopedReadService(access.scope, lambda: grants)
        original = self.f.service.query

        def query(*args):
            result = original(*args)
            grants.clear()
            return result

        model = SequenceModel(completed_actions())
        with patch.object(self.f.service, "query", side_effect=query):
            with self.assertRaises(PermissionDenied):
                DynamicRuntime(service, self.f.store, model).run(self.request, access)
        self.assertEqual(model.calls, 1)

    def test_cancel_after_calculation_withholds_previously_computed_facts(self):
        cancel = [False]
        actions = completed_actions()

        def decide(call, messages):
            if call == 4:
                cancel[0] = True
            return actions[call - 1]

        model = SequenceModel([], callback=decide)
        report = self.run_report(model, cancelled=lambda: cancel[0])
        self.assert_stopped(report, "cancel")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        self.assertEqual(model.calls, 4)
        self.assertGreater(report["usage"]["tokens_reserved"], 0)

    def test_cutoff_before_all_data_keeps_pit_values_out_of_model_and_report(self):
        request = replace(self.request, as_of=ts("2020-01-01T00:00:00"))
        actions = completed_actions()
        actions[-1] = finish("insufficient")
        model = SequenceModel(actions)
        report = self.run_report(model, request)
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        for messages in model.messages:
            payload = json.loads(messages[1]["content"])
            for observation in payload["observations"]:
                if observation["kind"] == "source_read":
                    self.assertTrue(all(d["records"] == 0 and d["periods"] == []
                                        for d in observation["datasets"].values()))

    def test_rehashed_pending_ledger_reset_cannot_enable_another_paid_call(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_report(SequenceModel([], crash=KeyboardInterrupt()))
        run = self.latest_run()
        state = self.f.store.read(self.f.access.scope, run)
        state.update(decisions=[], plans=[], model_attempts=0, tokens_reserved=0,
                     tokens_accounted=0, model={"status": "not_called"}, phase="planned")
        self.f.store.append(self.f.access.scope, run, state)
        model = SequenceModel(completed_actions())
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=run)
        self.assertEqual(model.calls, 0)

    def test_rehashed_absolute_deadline_extension_is_rejected(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_report(SequenceModel([], crash=KeyboardInterrupt()))
        run = self.latest_run()
        state = self.f.store.read(self.f.access.scope, run)
        from datetime import datetime
        state["deadline"] = (datetime.fromisoformat(state["deadline"]) + timedelta(days=1)).isoformat()
        self.f.store.append(self.f.access.scope, run, state)
        model = SequenceModel(completed_actions())
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=run)
        self.assertEqual(model.calls, 0)

    def test_rehashed_source_observation_cannot_forge_loaded_empty_evidence(self):
        original = self.f.service.query
        queries = [0]

        def interrupted_revalidation(*args):
            queries[0] += 1
            if queries[0] == 2:
                raise KeyboardInterrupt()
            return original(*args)

        with patch.object(self.f.service, "query", side_effect=interrupted_revalidation):
            with self.assertRaises(KeyboardInterrupt):
                self.run_report(SequenceModel([tool("financial")]))
        run = self.latest_run()
        state = self.f.store.read(self.f.access.scope, run)
        observation = state["observations"]["financial"]
        observation["status"] = "insufficient"
        observation["datasets"]["financial_income"].update(status="no_visible_data", records=0, periods=[])
        observation["gaps"] = ["financial_income:no_visible_records"]
        self.f.store.append(self.f.access.scope, run, state)
        model = SequenceModel([tool("market"), *completed_actions(("financial", "market"))[2:]])
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=run)
        self.assertEqual(model.calls, 0)

    def test_restored_pending_action_must_match_the_paid_verified_decision(self):
        original = self.f.store.append

        def crash_after_verified_action(scope, run, state):
            original(scope, run, state)
            if state["trace"] and state["trace"][-1]["event"] == "plan_updated":
                raise KeyboardInterrupt()

        with patch.object(self.f.store, "append", side_effect=crash_after_verified_action):
            with self.assertRaises(KeyboardInterrupt):
                self.run_report(SequenceModel([tool("financial")]))
        run = self.latest_run()
        state = self.f.store.read(self.f.access.scope, run)
        self.assertEqual(state["decisions"][-1]["action"]["tool"], "financial")
        state["pending_action"] = tool("market")
        self.f.store.append(self.f.access.scope, run, state)
        model = SequenceModel(completed_actions())
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=run)
        self.assertEqual(model.calls, 0)

    def test_verified_pending_action_resumes_without_repeating_its_paid_decision(self):
        original = self.f.store.append

        def crash_after_verified_action(scope, run, state):
            original(scope, run, state)
            if state["trace"] and state["trace"][-1]["event"] == "plan_updated":
                raise KeyboardInterrupt()

        first_model = SequenceModel([tool("financial")])
        with patch.object(self.f.store, "append", side_effect=crash_after_verified_action):
            with self.assertRaises(KeyboardInterrupt):
                self.run_report(first_model)
        run = self.latest_run()
        model = SequenceModel(completed_actions()[1:])
        report = self.runtime(model).run(self.request, self.f.access, resume=run)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(first_model.calls, 1)
        self.assertEqual(model.calls, 5)
        self.assertEqual(report["usage"]["model_attempts"], 6)
        self.assertEqual(report["usage"]["tool_calls"], 5)

    def test_encoded_credential_reflection_is_rejected_before_action_persistence(self):
        # Synthetic marker, never an actual credential or live model result.
        marker = "synthetic_reflection_marker"
        raw = json.dumps(tool("financial", plan=[marker])).replace("synthetic", "\\u0073ynthetic")
        self.assertNotIn(marker, raw)
        model = SequenceModel([raw])
        model.config = SimpleNamespace(model=SequenceModel.config.model, api_key=marker)
        report = self.run_report(model)
        self.assertEqual(report["stop_reason"], "credential_reflection_rejected")
        self.assertEqual(model.calls, 1)
        self.assertNotIn(marker, json.dumps(report))
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        self.assertNotIn(marker, json.dumps(state))
        self.assertNotIn("\\u0073ynthetic_reflection", json.dumps(state))
