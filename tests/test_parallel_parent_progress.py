"""Synthetic Parent progress mechanisms; no financial truth or live requests."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel, finish, tool
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.models import digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (
    AGENT_TOOLS, DYNAMIC_TOOLS, PARALLEL_VERSIONS, DynamicRequest,
    ParallelParentSpec, required_checks,
)
from stock_research.research.dynamic_protocol import (
    SYSTEM_PARENT_PARALLEL, dynamic_messages, observe_tool, parse_action,
)
from stock_research.research.study import StudyRuntime
from stock_research.research.tools import read_domain


VERSION = "dynamic-parent-parallel-v2"
QUESTION = "SYNTHETIC parent execution progress; not financial truth."


class ParallelParentProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.complete_request = DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": QUESTION})
        # Existing synthetic records, with the prior-year base outside this
        # frozen window. Missing financial evidence must remain insufficient.
        self.request = replace(self.complete_request, bindings=tuple(
            replace(binding, start=date(2024, 12, 31)) if binding.dataset == "financial_income" else binding
            for binding in self.complete_request.bindings))
        self.tools = DYNAMIC_TOOLS | AGENT_TOOLS

    def observations(self, stage="hypotheses", request=None):
        request = request or self.request
        outputs = {name: read_domain(self.f.service, request, self.f.access, name)
                   for name in ("financial", "market")}
        datasets = {key: value for output in outputs.values() for key, value in output.items()}
        computed = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, request)
        observations = [observe_tool(name, output) for name, output in outputs.items()]
        if stage in ("calculation", "hypotheses", "verification"):
            calculation = deepcopy(computed)
            calculation["hypotheses"] = []
            observations.append(observe_tool("calculation", calculation))
        if stage in ("hypotheses", "verification"):
            observations.append(observe_tool("hypotheses", computed))
        if stage == "verification":
            observations.append(observe_tool("verification", computed["verification"]))
        return observations

    def checks(self, observations=(), request=None):
        request = request or self.request
        completed = {observation["tool"] for observation in observations}
        hypotheses = next((observation["hypotheses"] for observation in observations
                           if observation["tool"] == "hypotheses"), {})
        result = []
        for identity in required_checks(request):
            if identity.startswith("read:"):
                status = "passed" if identity[5:] in completed else "not_completed"
            elif identity.startswith("hypothesis:"):
                hypothesis = hypotheses.get(identity[11:])
                status = ("not_completed" if hypothesis is None else "insufficient"
                          if hypothesis["status"] == "insufficient" else "passed")
            else:
                status = "passed" if identity in completed else "not_completed"
            result.append({"id": identity, "status": status})
        return result

    def view(self, observations=(), checks=None, request=None, tools=None, **kwargs):
        request = request or self.request
        messages, metadata = dynamic_messages(request, self.tools if tools is None else tools,
            list(observations), required_checks(request), [], 12000, version=VERSION,
            context_scope=self.f.access.scope, context_run_id="a" * 32,
            **({"parent_execution_checks": checks} if checks is not None else {}), **kwargs)
        return messages, metadata, json.loads(messages[1]["content"])

    def test_versioned_parent_preserves_defaults_legacy_identity_and_limits(self):
        legacy, revised = ParallelParentSpec(), ParallelParentSpec(version=VERSION)
        self.assertEqual(PARALLEL_VERSIONS, frozenset({"dynamic-parent-parallel-v1", VERSION, "dynamic-parent-parallel-v3"}))
        self.assertEqual(legacy.version, "dynamic-parent-parallel-v1")
        self.assertEqual(legacy.identity, "5120ebab68444745152040f21bdf1e21e65a73cc3d8da085ea1c4def453ebf00")
        self.assertNotEqual(legacy.identity, revised.identity)
        for name in ("max_decisions", "max_tools", "max_tokens", "max_seconds", "root_max_decisions",
                     "root_max_tools", "root_max_tokens", "context_bytes", "no_progress_limit"):
            self.assertEqual(getattr(legacy, name), getattr(revised, name))
        self.assertEqual((revised.context_bytes, revised.no_progress_limit), (12000, 2))

    def test_initial_preview_is_pending_and_does_not_force_parallel_routing(self):
        _, _, payload = self.view()
        execution = payload["control"]["execution"]
        self.assertFalse(execution["can_finish"])
        self.assertEqual(execution["pending_checks"], required_checks(self.request))
        candidate = execution["next_action"]
        self.assertTrue(candidate is None or candidate["action"] != "parallel")
        self.assertEqual(payload["available_tools"], sorted(self.tools))

    def test_noninitial_v2_requires_runtime_execution_checks(self):
        with self.assertRaises(ValidationError):
            self.view(self.observations("sources"))

    def test_candidates_use_exact_existing_calculation_and_hypothesis_contracts(self):
        for stage, next_tool, refs in (("sources", "calculation", ["financial", "market"]),
                                      ("calculation", "hypotheses", ["calculation"])):
            with self.subTest(stage=stage):
                observations = self.observations(stage)
                _, _, payload = self.view(observations, self.checks(observations))
                execution, candidate = payload["control"]["execution"], payload["control"]["execution"]["next_action"]
                self.assertFalse(execution["can_finish"])
                self.assertEqual((candidate["action"], candidate["tool"], candidate["refs"]), ("tool", next_tool, refs))
                self.assertEqual(parse_action(json.dumps(candidate), self.tools,
                    [observation["tool"] for observation in observations], version=VERSION), candidate)

    def test_hypothesis_insufficient_still_requires_verification_with_exact_next_json(self):
        observations = self.observations()
        self.assertEqual(observations[-1]["hypotheses"]["financial_deterioration"]["status"], "insufficient")
        checks = self.checks(observations)
        before = deepcopy((observations, checks))
        _, _, payload = self.view(observations, checks)
        execution = payload["control"]["execution"]
        self.assertEqual(execution["pending_checks"], ["verification"])
        self.assertFalse(execution["can_finish"])
        candidate = execution["next_action"]
        self.assertEqual(set(candidate), {"action", "tool", "refs", "plan"})
        self.assertEqual((candidate["action"], candidate["tool"], candidate["refs"]),
                         ("tool", "verification", ["hypotheses"]))
        self.assertEqual((observations, checks), before)
        self.assertEqual(parse_action(json.dumps(candidate), self.tools,
            [observation["tool"] for observation in observations], version=VERSION), candidate)

    def test_finish_rejection_feedback_keeps_pending_check_and_points_to_verification(self):
        observations = self.observations()
        rejection = {"code": "required_checks_pending", "pending_checks": ["verification"]}
        _, _, payload = self.view(observations, self.checks(observations), finish_rejection=rejection, decision=6)
        self.assertEqual(payload["control"]["finish_rejection"], rejection)
        self.assertEqual(payload["control"]["execution"]["next_action"]["tool"], "verification")
        self.assertFalse(payload["control"]["execution"]["can_finish"])

    def test_all_execution_done_allows_finish_and_preserves_insufficient_outcome(self):
        for request, reason in ((self.request, "insufficient"), (self.complete_request, "completed")):
            with self.subTest(reason=reason):
                observations = self.observations("verification", request)
                _, _, payload = self.view(observations, self.checks(observations, request), request=request)
                execution = payload["control"]["execution"]
                self.assertTrue(execution["can_finish"])
                self.assertEqual(execution["pending_checks"], [])
                self.assertIsNone(execution["next_action"])
                self.assertEqual(self.checks(observations, request)[-1]["status"],
                                 "insufficient" if reason == "insufficient" else "passed")

    def test_hidden_verifier_never_becomes_granted_by_guidance(self):
        observations = self.observations()
        tools = self.tools - {"verification"}
        _, _, payload = self.view(observations, self.checks(observations), tools=tools)
        execution = payload["control"]["execution"]
        self.assertFalse(execution["can_finish"])
        self.assertEqual(execution["pending_checks"], ["verification"])
        self.assertIsNone(execution["next_action"])
        with self.assertRaises(PermissionDenied):
            parse_action(json.dumps(tool("verification", ["hypotheses"])), tools,
                         [observation["tool"] for observation in observations], version=VERSION)

    def test_forged_reordered_unknown_or_missing_execution_checks_are_rejected(self):
        observations = self.observations()
        checks = self.checks(observations)
        forged = deepcopy(checks)
        forged[-2]["status"] = "passed"  # No verification Observation exists.
        stale = deepcopy(checks)
        stale[0]["status"] = "not_completed"  # Source read was actually performed.
        quality_forgery = deepcopy(checks)
        quality_forgery[-1]["status"] = "passed"  # Actual tested hypothesis is insufficient.
        for invalid in (list(reversed(checks)), checks[:-1], checks + [{"id": "unknown", "status": "passed"}],
                        forged, stale, quality_forgery):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.view(observations, invalid)

    def test_legacy_v1_system_preview_and_payload_bytes_are_unchanged(self):
        self.assertEqual(digest(SYSTEM_PARENT_PARALLEL), "9d2ec9897e7ec79a5fe1d86be6208cb578fc465d84d880e3371512b284fb8e98")
        messages = DynamicRuntime(self.f.service, None, spec=ParallelParentSpec()).preview(
            self.complete_request, self.f.access, run_id="a" * 32)
        self.assertEqual(digest(messages), "392d760d07f53068d78a255533ba6fc64d6d614f8c7cfd97cb5eeeef4daa6cfa")
        self.assertNotIn("execution", json.loads(messages[1]["content"])["control"])

    def test_new_wire_is_deterministic_lossless_and_respects_unchanged_byte_cap(self):
        observations = self.observations()
        checks = self.checks(observations)
        messages, metadata, payload = self.view(observations, checks)
        self.assertEqual(self.view(deepcopy(observations), deepcopy(checks)), (messages, metadata, payload))
        self.assertEqual(metadata["bytes"], sum(len(message["content"].encode("utf-8")) for message in messages))
        self.assertEqual(metadata["message_sha256"], digest(messages))
        self.assertLessEqual(metadata["bytes"], 12000)
        self.assertNotIn("telemetry", messages[1]["content"])
        with self.assertRaises(ValidationError):
            dynamic_messages(self.request, self.tools, observations, required_checks(self.request), [],
                metadata["bytes"] - 1, version=VERSION, parent_execution_checks=checks,
                context_scope=self.f.access.scope, context_run_id="a" * 32)

    def test_repeated_premature_insufficient_finish_still_stops_without_auto_verification(self):
        model = SequenceModel([tool("financial"), tool("market"), tool("calculation", ["financial", "market"]),
            tool("hypotheses", ["calculation"]), finish("insufficient"), finish("insufficient")])
        spec = ParallelParentSpec(version=VERSION)
        report = DynamicRuntime(self.f.service, self.f.store, model, spec).run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(model.calls, 6)
        self.assertEqual(sum(event["event"] == "finish_rejected" for event in report["trace"]), 2)
        self.assertFalse(any(event["event"] == "tool_started" and event["tool"] == "verification" for event in report["trace"]))
        self.assertEqual(report["root_budget"]["total_tokens"], 6 * 120)
        fresh = SequenceModel([])
        replay = DynamicRuntime(self.f.service, self.f.store, fresh, spec).run(
            self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(replay, report)
        self.assertEqual(fresh.calls, 0)

    def test_model_can_follow_rejection_candidate_and_finish_lawful_insufficient(self):
        actions = [tool("financial"), tool("market"), tool("calculation", ["financial", "market"]),
                   tool("hypotheses", ["calculation"]), finish("insufficient"), None, finish("insufficient")]
        def callback(turn, messages):
            if turn != 6:
                return actions[turn - 1]
            payload = json.loads(messages[1]["content"])
            self.assertEqual(payload["control"]["finish_rejection"],
                             {"code": "required_checks_pending", "pending_checks": ["verification"]})
            execution = payload["control"]["execution"]
            self.assertFalse(execution["can_finish"])
            self.assertEqual(execution["next_action"]["tool"], "verification")
            return execution["next_action"]
        model = SequenceModel([], callback=callback)
        spec = ParallelParentSpec(version=VERSION)
        report = DynamicRuntime(self.f.service, self.f.store, model, spec).run(self.request, self.f.access)
        self.assertEqual(report["status"], "insufficient")
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertEqual(report["required_checks"][-1]["status"], "insufficient")
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"][:-1]))
        self.assertEqual(model.calls, 7)
        self.assertEqual(sum(event["event"] == "finish_rejected" for event in report["trace"]), 1)
        self.assertLessEqual(max(record["total_context_bytes"] for record in report["context_telemetry"]), 12000)
        fresh = SequenceModel([])
        self.assertEqual(DynamicRuntime(self.f.service, self.f.store, fresh, spec).run(
            self.request, self.f.access, resume=report["run_id"]), report)
        self.assertEqual(fresh.calls, 0)


if __name__ == "__main__":
    unittest.main()
