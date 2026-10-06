"""Versioned Child execution guidance; synthetic views do not prove live quality."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.models import digest
from stock_research.research.dynamic_contracts import (
    DynamicRequest, FinancialChildSpec, FinancialRequest, MarketChildSpec, MarketRequest,
    required_checks,
)
from stock_research.research.dynamic_protocol import (
    SYSTEM_FINANCIAL_CHILD, SYSTEM_MARKET_CHILD, SYSTEM_FINANCIAL_CHILD_V2, SYSTEM_MARKET_CHILD_V2,
    dynamic_messages, observe_tool, parse_action,
)
from stock_research.research.tools import read_domain


class ChildProgressProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.parent = DynamicRequest.from_dict({**study_request(self.f).to_dict(),
                                               "question": "SYNTHETIC bound-domain mechanism"})

    def request(self, domain):
        return (FinancialRequest if domain == "financial" else MarketRequest).from_parent(self.parent)

    def view(self, domain, observations=(), *, protocol="v2", **kwargs):
        request = self.request(domain)
        messages, metadata = dynamic_messages(request, [domain], list(observations), required_checks(request), [],
                                              12000, version=domain + "-child-" + protocol, **kwargs)
        return messages, metadata, json.loads(messages[1]["content"])

    def observation(self, domain):
        request = self.request(domain)
        return observe_tool(domain, read_domain(self.f.service, request, self.f.access, domain),
                            version=domain + "-child-v2")

    def test_explicit_versions_keep_legacy_defaults_identities_and_every_limit(self):
        for cls, domain, identity in (
                (FinancialChildSpec, "financial", "6f77020ca19062634afca83e727b247534ddf8157b432aea3574c0d45412a699"),
                (MarketChildSpec, "market", "86c75ca8b138e5ff459f1b2872613b16974e6d29d76ae5b456f43abe4d401881")):
            with self.subTest(domain=domain):
                legacy = cls()
                revised = replace(legacy, version=domain + "-child-v2")
                self.assertEqual(legacy.version, domain + "-child-v1")
                self.assertEqual(legacy.identity, identity)
                self.assertNotEqual(revised.identity, legacy.identity)
                for field in ("max_decisions", "max_tools", "max_tokens", "max_seconds", "output_tokens",
                              "context_bytes", "no_progress_limit", "allowed_tools", "visible_tools"):
                    self.assertEqual(getattr(legacy, field), getattr(revised, field))
                self.assertEqual(revised.context_bytes, 12000)
                with self.assertRaises(ValidationError):
                    replace(legacy, version=("market" if domain == "financial" else "financial") + "-child-v2")

    def test_unread_execution_is_explicitly_pending_with_only_authorized_read_candidate(self):
        for domain in ("financial", "market"):
            with self.subTest(domain=domain):
                _, _, payload = self.view(domain)
                progress = payload["child_progress"]
                self.assertEqual(progress["required_checks"], [{"id": "read:" + domain, "status": "not_completed"}])
                self.assertFalse(progress["execution"]["read_completed"])
                self.assertFalse(progress["execution"]["can_finish"])
                self.assertEqual(progress["execution"]["pending_checks"], ["read:" + domain])
                self.assertEqual(progress["source_quality"]["read_result_status"], "not_read")
                self.assertEqual([a["action"] for a in progress["legal_next_actions"]], ["tool"])
                action = progress["legal_next_actions"][0]
                self.assertEqual(parse_action(json.dumps(action), [domain], [], version=domain + "-child-v2"), action)

    def test_successful_read_separates_passed_execution_from_exact_unverified_quality(self):
        for domain in ("financial", "market"):
            with self.subTest(domain=domain):
                observation = self.observation(domain)
                dataset = next(iter(observation["datasets"]))
                observation["gaps"] = sorted(set(observation["gaps"] + [dataset + ":coverage_not_verified",
                                                                       dataset + ":historical_release_not_verified"]))
                before = deepcopy(observation)
                messages, _, payload = self.view(domain, [observation], decision=2)
                progress = payload["child_progress"]
                self.assertEqual(payload["observations"], [before])
                self.assertEqual(observation, before)
                self.assertEqual(progress["required_checks"], [{"id": "read:" + domain, "status": "passed"}])
                self.assertTrue(progress["execution"]["can_finish"])
                self.assertEqual(progress["execution"]["pending_checks"], [])
                self.assertEqual(progress["execution"]["completion_scope"], "delegated_source_read")
                self.assertEqual(progress["source_quality"]["coverage"], "not_verified")
                self.assertEqual(progress["source_quality"]["historical_release"], "not_verified")
                self.assertEqual(progress["source_quality"]["gaps"], before["gaps"])
                self.assertEqual(payload["available_tools"], [domain])
                self.assertEqual(payload["completed_tools"], [domain])
                action = progress["legal_next_actions"][0]
                self.assertEqual((action["action"], action["reason"]), ("finish", "completed"))
                self.assertEqual(parse_action(json.dumps(action), [domain], [domain],
                                              version=domain + "-child-v2"), action)
                self.assertIn("Parent must still", messages[0]["content"])
                self.assertNotIn('{"action":"tool"', messages[0]["content"])

    def test_executed_empty_read_can_finish_insufficient_without_claiming_available_data(self):
        for domain in ("financial", "market"):
            observation = self.observation(domain)
            for dataset in observation["datasets"].values():
                dataset.update(status="no_visible_data", records=0, periods=[])
            observation["status"] = "insufficient"
            _, _, payload = self.view(domain, [observation])
            progress = payload["child_progress"]
            self.assertEqual(progress["required_checks"][0]["status"], "passed")
            self.assertTrue(progress["execution"]["can_finish"])
            self.assertEqual(progress["source_quality"]["read_result_status"], "insufficient")
            self.assertEqual(progress["legal_next_actions"][0]["reason"], "insufficient")

    def test_mixed_dataset_availability_uses_same_nonempty_criterion_as_child_finish(self):
        domain = "financial"
        observation = self.observation(domain)
        observation["datasets"]["financial_income"].update(records=0, periods=[])
        _, _, payload = self.view(domain, [observation])
        self.assertEqual(payload["child_progress"]["legal_next_actions"][0]["reason"], "insufficient")

    def test_duplicate_feedback_preserves_observation_and_points_to_finish_without_dispatch(self):
        for domain in ("financial", "market"):
            observation = self.observation(domain)
            _, _, payload = self.view(domain, [observation], decision=3, protocol_error="duplicate_no_progress")
            progress = payload["child_progress"]
            self.assertEqual(payload["observations"], [observation])
            self.assertEqual(payload["control"]["previous_action_error"], "duplicate_no_progress")
            self.assertFalse(progress["duplicate_feedback"]["dispatched"])
            self.assertTrue(progress["duplicate_feedback"]["read_completed"])
            self.assertEqual(progress["duplicate_feedback"]["next_actions"], progress["legal_next_actions"])
            self.assertEqual(progress["legal_next_actions"][0]["action"], "finish")
            # The Runtime retains authority over duplicate detection and no_progress.
            duplicate = {"action": "tool", "tool": domain, "refs": [], "plan": ["Repeat"]}
            self.assertEqual(parse_action(json.dumps(duplicate), [domain], [domain],
                                          version=domain + "-child-v2"), duplicate)

    def test_pending_finish_rejection_remains_exact_and_never_grants_finish(self):
        for domain in ("financial", "market"):
            rejection = {"code": "required_checks_pending", "pending_checks": ["read:" + domain]}
            _, _, payload = self.view(domain, decision=2, finish_rejection=rejection)
            self.assertEqual(payload["control"]["finish_rejection"], rejection)
            self.assertFalse(payload["child_progress"]["execution"]["can_finish"])
            self.assertEqual(payload["child_progress"]["legal_next_actions"][0]["action"], "tool")

    def test_new_views_reject_wrong_request_type_cross_domain_tools_and_observations(self):
        for domain, opposite in (("financial", "market"), ("market", "financial")):
            version = domain + "-child-v2"
            for request in (self.parent, self.request(opposite)):
                with self.assertRaises(ValidationError):
                    dynamic_messages(request, [domain], [], required_checks(request), [], 12000, version=version)
            with self.assertRaises(PermissionDenied):
                dynamic_messages(self.request(domain), [opposite], [], ["read:" + domain], [], 12000, version=version)
            with self.assertRaises(PermissionDenied):
                self.view(domain, [self.observation(opposite)])
            for forbidden in (opposite, opposite + "_child", domain + "_child", "calculation"):
                with self.assertRaises(PermissionDenied):
                    parse_action(json.dumps({"action": "tool", "tool": forbidden, "refs": [], "plan": ["Read"]}),
                                 [domain], [], version=version)

    def test_new_guidance_cannot_override_required_checks_or_forge_observation_schema(self):
        for domain in ("financial", "market"):
            request = self.request(domain)
            with self.assertRaises(ValidationError):
                dynamic_messages(request, [domain], [], [], [], 12000, version=domain + "-child-v2")
            observation = self.observation(domain)
            observation["execution_status"] = "passed"
            with self.assertRaises(ValidationError):
                self.view(domain, [observation])
            observation = self.observation(domain)
            observation["datasets"] = {}
            with self.assertRaises(ValidationError):
                self.view(domain, [observation])

    def test_guidance_wire_is_deterministic_bounded_and_contains_no_telemetry(self):
        for domain in ("financial", "market"):
            observations = [self.observation(domain)]
            first = self.view(domain, observations, decision=2)
            second = self.view(domain, deepcopy(observations), decision=2)
            self.assertEqual(first, second)
            messages, metadata, _ = first
            self.assertEqual(metadata["message_sha256"], digest(messages))
            self.assertEqual(metadata["bytes"], sum(len(m["content"].encode("utf-8")) for m in messages))
            self.assertLessEqual(metadata["bytes"], 12000)
            self.assertNotIn("telemetry", messages[1]["content"])
            with self.assertRaises(ValidationError):
                dynamic_messages(self.request(domain), [domain], observations, ["read:" + domain], [],
                                 metadata["bytes"] - 1, version=domain + "-child-v2", decision=2)

    def test_legacy_prompts_and_progress_absence_keep_exact_historical_contract(self):
        self.assertEqual(digest(SYSTEM_FINANCIAL_CHILD), "534371bd66a1d1b59267e872858a7a96f6851d4f2ceba37bda8c47c51c5195bd")
        self.assertEqual(digest(SYSTEM_MARKET_CHILD), "f21d30f5fc55b68857b9352c97a555a85570e6d19823b7df15a50af9b2852494")
        for domain in ("financial", "market"):
            request = self.request(domain)
            observation = self.observation(domain)
            messages, _ = dynamic_messages(request, [domain], [observation], ["read:" + domain], [],
                                           12000, version=domain + "-child-v1", decision=2)
            self.assertNotIn("child_progress", messages[1]["content"])

    def test_v2_paid_prompts_and_feedback_shape_remain_immutable_after_v3(self):
        self.assertEqual(digest(SYSTEM_FINANCIAL_CHILD_V2), "ce2a9475b6d3449104b61b2a3eb806ef0c51551636810cfe287604e9bc21d992")
        self.assertEqual(digest(SYSTEM_MARKET_CHILD_V2), "80d82db5a53beafb2f9ae57eac2391a133aa5c4ca2d43adc3d3e3ca7075574e1")
        for domain in ("financial", "market"):
            _, _, payload = self.view(domain, [self.observation(domain)], protocol_error="invalid_action")
            self.assertNotIn("response_contract", payload["child_progress"])
            self.assertNotIn("invalid_action_feedback", payload["child_progress"])

    def test_v3_system_current_response_is_exact_valid_action_for_each_execution_stage(self):
        for domain in ("financial", "market"):
            for observations in ([], [self.observation(domain)]):
                with self.subTest(domain=domain, read_completed=bool(observations)):
                    messages, metadata, payload = self.view(domain, observations, protocol="v3")
                    progress = payload["child_progress"]
                    current_json = messages[0]["content"].split("CURRENT RESPONSE JSON: ", 1)[1]
                    action = json.loads(current_json)
                    self.assertEqual(action, progress["legal_next_actions"][0])
                    self.assertEqual(parse_action(current_json, [domain], [domain] if observations else [],
                                                  version=domain + "-child-v3"), action)
                    self.assertEqual(set(action), set(progress["response_contract"]["required_keys"]))
                    self.assertFalse(set(action) & set(progress["response_contract"]["forbidden_keys"]))
                    self.assertEqual(len(action["plan"]), 1)
                    self.assertIn("Return the current JSON object below VERBATIM", messages[0]["content"])
                    self.assertIn("reason is REQUIRED", messages[0]["content"])
                    self.assertIn("tool and refs are FORBIDDEN", messages[0]["content"])
                    self.assertEqual(metadata["message_sha256"], digest(messages))
                    self.assertLessEqual(metadata["bytes"], 12000)

    def test_v3_invalid_action_feedback_gives_required_keys_and_candidate_without_raw_reply(self):
        for domain in ("financial", "market"):
            for observations in ([], [self.observation(domain)]):
                messages, _, payload = self.view(domain, observations, protocol="v3", protocol_error="invalid_action")
                progress = payload["child_progress"]
                self.assertEqual(progress["invalid_action_feedback"], {
                    "code": "invalid_action", "response_contract": progress["response_contract"],
                    "next_actions": progress["legal_next_actions"],
                })
                self.assertEqual(progress["response_contract"]["required_keys"],
                                 ["action", "reason", "plan"] if observations else ["action", "tool", "refs", "plan"])
                self.assertEqual(progress["execution"]["can_finish"], bool(observations))
                self.assertNotIn("raw_response", messages[1]["content"])
                self.assertNotIn("completion_tokens", messages[1]["content"])
                self.assertEqual(self.view(domain, observations, protocol="v3", protocol_error="invalid_action"),
                                 (messages, self.view(domain, observations, protocol="v3", protocol_error="invalid_action")[1], payload))

    def test_v3_preserves_v2_execution_quality_and_observations_without_state_transition(self):
        for domain in ("financial", "market"):
            observation = self.observation(domain)
            for absent in (False, True):
                chosen = deepcopy(observation)
                if absent:
                    for dataset in chosen["datasets"].values():
                        dataset.update(status="no_visible_data", records=0, periods=[])
                    chosen["status"] = "insufficient"
                _, _, prior = self.view(domain, [chosen])
                _, _, revised = self.view(domain, [chosen], protocol="v3")
                self.assertEqual(revised["observations"], prior["observations"])
                self.assertEqual({k: v for k, v in revised["child_progress"].items() if k != "response_contract"},
                                 prior["child_progress"])
                self.assertEqual(revised["child_progress"]["legal_next_actions"][0]["reason"],
                                 "insufficient" if absent else "completed")

    def test_v3_rejects_actual_v2_malformed_finish_patterns_without_adapter_or_rewrite(self):
        malformed = [
            {"action": "finish", "plan": ["Read is done", "Coverage gaps remain", "Available records",
                                          "No further read", "Parent still verifies"], "refs": []},
            {"action": "finish", "plan": ["Read is done"]},
            {"action": "finish", "reason": "completed", "plan": ["Read is done"], "refs": []},
            {"action": "finish", "reason": "completed", "plan": ["Read is done"], "tool": "financial"},
        ]
        for domain in ("financial", "market"):
            for protocol in ("v1", "v2", "v3"):
                for action in malformed:
                    with self.subTest(domain=domain, protocol=protocol, action=action), self.assertRaises(ValidationError):
                        parse_action(json.dumps(action), [domain], [domain], version=domain + "-child-" + protocol)

    def test_v3_versions_keep_limits_depth_and_cross_domain_rejections(self):
        for cls, domain, opposite in ((FinancialChildSpec, "financial", "market"), (MarketChildSpec, "market", "financial")):
            old, revised = cls(), cls(version=domain + "-child-v3")
            self.assertNotEqual(old.identity, revised.identity)
            self.assertNotEqual(revised.identity, cls(version=domain + "-child-v2").identity)
            for field in ("max_decisions", "max_tools", "max_tokens", "max_seconds", "output_tokens",
                          "context_bytes", "no_progress_limit", "allowed_tools", "visible_tools"):
                self.assertEqual(getattr(old, field), getattr(revised, field))
            with self.assertRaises(ValidationError):
                dynamic_messages(self.request(opposite), [domain], [], ["read:" + domain], [], 12000,
                                 version=domain + "-child-v3")
            with self.assertRaises(PermissionDenied):
                self.view(domain, [self.observation(opposite)], protocol="v3")
            for forbidden in (opposite, opposite + "_child", domain + "_child", "calculation"):
                with self.assertRaises(PermissionDenied):
                    parse_action(json.dumps({"action": "tool", "tool": forbidden, "refs": [], "plan": ["Read"]}),
                                 [domain], [], version=domain + "-child-v3")


if __name__ == "__main__":
    unittest.main()
