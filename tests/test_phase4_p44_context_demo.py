"""Synthetic context-remediation QA safety; not financial truth or live validation."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase4_p44_context_demo as demo
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel, completed_actions, finish, tool
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, DomainParentSpec


class ContextDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fixture(self.root / "synthetic")
        self.request = DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: preserve every bound value and reference",
        })

    def completed(self, delegated=True):
        actions = ([tool("financial_child"), tool("financial"), finish(), tool("market")]
                   if delegated else completed_actions()[:2])
        actions += [tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                    tool("verification", ["hypotheses"]), finish()]
        report = DynamicRuntime(self.f.service, self.f.store, SequenceModel(actions), DomainParentSpec()).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        datasets = {dataset: output for outputs in state["outputs"].values() for dataset, output in outputs.items()}
        return report, demo.record_domains({"datasets": datasets})

    def test_semantics_preserve_all_values_and_normalize_only_authorized_run_calls(self):
        first, domains = self.completed()
        second, _ = self.completed()
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertNotEqual(first["child_results"][0]["source_tool_call_id"], second["child_results"][0]["source_tool_call_id"])
        normalized = demo.report_semantics(first, domains)
        self.assertEqual(normalized, demo.report_semantics(second, domains))
        self.assertEqual(normalized["facts"], sorted(first["facts"], key=lambda fact: fact["name"]))
        for key, source in normalized["evidence"].items():
            self.assertEqual({field: value for field, value in source.items() if field != "tool_call_id"},
                             {field: value for field, value in first["evidence"][key].items() if field != "tool_call_id"})

    def test_numeric_unit_snapshot_or_source_changes_cannot_match_baseline(self):
        report, domains = self.completed()
        expected = demo.report_semantics(report, domains)
        for field, value in (("value", "999999999"), ("unit", "share"), ("snapshot", "a" * 64),
                             ("provider_version", "synthetic-changed-version"), ("artifact_ids", ["b" * 64])):
            with self.subTest(field=field):
                changed = deepcopy(report)
                next(iter(changed["evidence"].values()))[field] = value
                self.assertNotEqual(demo.report_semantics(changed, domains), expected)
        changed = deepcopy(report)
        changed["facts"] = changed["facts"][:-1]
        self.assertNotEqual(demo.report_semantics(changed, domains), expected)

    def test_unknown_cross_domain_read_or_missing_child_link_rejected(self):
        report, domains = self.completed(delegated=False)
        financial_call = next(event["tool_call_id"] for event in report["trace"]
                              if event["event"] == "tool_finished" and event["tool"] == "financial")
        source = next(source for source in report["evidence"].values() if domains[source["record_id"]] == "market")
        source["tool_call_id"] = financial_call
        with self.assertRaises(IntegrityError):
            demo.report_semantics(report, domains)
        report, domains = self.completed()
        report["child_evidence_links"] = []
        with self.assertRaises(IntegrityError):
            demo.report_semantics(report, domains)

    def receipt_files(self, name, known=True):
        directory = self.root / name
        directory.mkdir()
        messages = [{"role": "system", "content": "SYNTHETIC bounded protocol"},
                    {"role": "user", "content": canonical_json({"protocol_version": demo.VERSION})}]
        ledger = demo.old.RootLedger(*demo.LIMITS[:2])
        intent = ledger.reserve(demo.CASE_ID + "/" + demo.VERSION, messages, 1024)
        raw = deepcopy(intent)
        response = ChatResult(content=canonical_json(finish()), requested_model="deepseek-v4-flash-0731",
            returned_model="deepseek-v4-flash-0731", finish_reason="stop", request_id="synthetic-id",
            prompt_tokens=100, completion_tokens=20, total_tokens=120, latency_ms=1)
        if known:
            ledger.settle(intent, response)
        prefix = "01-" + demo.CASE_ID
        for suffix, value in (("messages", messages), ("intent", raw),
                              ("receipt", asdict(response) if known else {"status": "unknown", "error_type": "SyntheticFailure"}),
                              ("ledger", ledger.snapshot())):
            demo.old.write_new(directory / (prefix + "-" + suffix + ".json"), value)
        return directory, ledger.snapshot(), prefix

    def validate(self, directory, ledger):
        # These accounting tests do not instantiate an unavailable protocol version.
        with patch.object(demo, "spec_for", return_value=DomainParentSpec()):
            return demo.validate_receipts(directory, ledger, "deepseek-v4-flash-0731")

    def test_full_known_receipt_validation_and_unknown_reservation_retention(self):
        directory, ledger, _ = self.receipt_files("known")
        validated = self.validate(directory, ledger)
        self.assertEqual(validated["known_tokens"], 120)
        self.assertEqual(validated["unknown_usage_calls"], 0)
        directory, ledger, _ = self.receipt_files("unknown", known=False)
        validated = self.validate(directory, ledger)
        self.assertEqual(validated["known_tokens"], 0)
        self.assertEqual(validated["tokens_accounted"], ledger["cumulative_tokens_reserved"])
        self.assertEqual(validated["unknown_usage_calls"], 1)

    def test_truncated_wrong_model_bad_latency_or_usage_receipts_rejected(self):
        for field, value in (("finish_reason", "length"), ("returned_model", "other-model"),
                             ("latency_ms", -1), ("total_tokens", 121), ("prompt_tokens", True)):
            with self.subTest(field=field):
                directory, ledger, prefix = self.receipt_files("receipt-" + field)
                path = directory / (prefix + "-receipt.json")
                receipt = demo.old.read(path)
                receipt[field] = value
                path.write_text(canonical_json(receipt), encoding="utf-8")
                with self.assertRaises((ValidationError, IntegrityError)):
                    self.validate(directory, ledger)

    def test_paid_intent_attempt_prefix_or_budget_tampering_rejected(self):
        for kind in ("intent", "prefix", "budget"):
            with self.subTest(kind=kind):
                directory, ledger, prefix = self.receipt_files("ledger-" + kind)
                if kind == "intent":
                    path = directory / (prefix + "-intent.json")
                    altered = demo.old.read(path)
                    altered["reservation"] += 1
                    path.write_text(canonical_json(altered), encoding="utf-8")
                elif kind == "prefix":
                    path = directory / (prefix + "-ledger.json")
                    altered = demo.old.read(path)
                    altered["intents"] = []
                    path.write_text(canonical_json(altered), encoding="utf-8")
                else:
                    ledger["max_tokens_accounted"] += 1
                with self.assertRaises(IntegrityError):
                    self.validate(directory, ledger)

    def test_wrong_external_freeze_hash_rejects_before_original_source_or_config_read(self):
        with patch.object(demo.old, "sha", return_value="a" * 64), patch.object(demo.old, "read") as read, \
                patch.object(demo, "preserved_legacy") as legacy, patch.object(demo, "CampaignSources") as sources:
            with self.assertRaises(IntegrityError):
                demo.checked("b" * 64)
            read.assert_not_called()
            legacy.assert_not_called()
            sources.assert_not_called()

    def frozen_gate(self):
        # The immutable old-Artifact gate is mocked here; all runtime input/view
        # reconstruction still uses authorized synthetic records and real specs.
        baseline, _ = self.completed()
        state = self.f.store.read(self.f.access.scope, baseline["run_id"])
        inputs = {"datasets": {dataset: output for outputs in state["outputs"].values()
                               for dataset, output in outputs.items()}}
        envelope = demo.old.authorized_envelope(self.f.service, self.f.access, self.request)
        spec = demo.spec_for()
        original = {"id": demo.CASE_ID, "scope": "synthetic-original",
                    "request": self.request.to_dict(), "research_question": self.request.question,
                    "expected_behavior": {}, "novelty": {"used_for_case_or_prompt_tuning": False}}
        case = deepcopy(original)
        case["scope"] = "phase4-p44-context-20261005/" + demo.CASE_ID
        case["novelty"]["used_for_case_or_prompt_tuning"] = True
        run_id = digest("synthetic-frozen-gate")[:32]
        item = {"case_id": demo.CASE_ID, "request": self.request.to_dict(), "run_id": run_id,
                "scope": self.f.access.scope, "spec_identity": spec.identity, "input_ref": digest(inputs),
                "authorization_envelope": envelope, "catalog_observations": demo.context_oracle(envelope, baseline),
                "messages": DynamicRuntime(self.f.service, None, None, spec).preview(self.request, self.f.access, run_id=run_id)}
        validation = {"all_cases_contract_valid": True}
        files = {"synthetic-gate-code.py": "c" * 64}
        plan = {"schema": "phase4-p44-context-demo/v1", "case": case, "item": item,
                "code_files": files, "legacy_hashes": deepcopy(demo.LEGACY_HASHES),
                "parent_spec_identity": spec.identity,
                "child_spec_identities": {role: value.identity for role, (_, value) in demo.roles().items() if role != demo.VERSION},
                "max_decisions": demo.LIMITS[0], "max_tokens_accounted": demo.LIMITS[1], "max_seconds": demo.LIMITS[2],
                "question_bytes": 744, "baseline_fact_count": 7, "baseline_evidence_count": 12,
                "original_functional_passes": [False, True], "original_refinement_functional_passed": False,
                "old_budget_reused": False, "expected_routes": [["financial", "delegated"], ["market", "direct"]],
                "baseline_semantics": demo.report_semantics(baseline, demo.record_domains(inputs)),
                "contract_validation": validation}
        sources = SimpleNamespace(context=lambda _: (self.f.service, self.f.access), inputs=lambda _: inputs)
        return plan, original, {"request": self.request.to_dict()}, baseline, sources, validation, files

    def test_frozen_source_question_budget_identity_and_evidence_gate(self):
        plan, original, original_item, baseline, sources, validation, files = self.frozen_gate()
        def checked(candidate):
            with patch.object(demo.old, "sha", return_value="a" * 64), patch.object(demo.old, "read", return_value=candidate), \
                    patch.object(demo, "preserved_legacy", side_effect=lambda: (deepcopy(original), deepcopy(original_item), deepcopy(baseline))), \
                    patch.object(demo, "code_files", return_value=files), patch.object(demo, "CampaignSources", return_value=sources), \
                    patch.object(demo, "validate_cases", return_value=validation):
                return demo.checked("a" * 64)
        self.assertEqual(checked(plan)[0], plan)
        for kind in ("question", "scope", "run", "budget", "child_identity", "baseline", "legacy", "source"):
            with self.subTest(kind=kind):
                changed = deepcopy(plan)
                if kind == "question":
                    changed["item"]["request"]["question"] += " changed objective"
                elif kind == "scope":
                    changed["item"]["scope"] = "another-subject"
                elif kind == "run":
                    changed["item"]["run_id"] = "b" * 32
                elif kind == "budget":
                    changed["max_tokens_accounted"] += 1
                elif kind == "child_identity":
                    changed["child_spec_identities"]["financial-child-v1"] = "b" * 64
                elif kind == "baseline":
                    next(iter(changed["baseline_semantics"]["evidence"].values()))["value"] = "999999"
                elif kind == "legacy":
                    changed["legacy_hashes"][next(iter(demo.LEGACY_HASHES))] = "b" * 64
                else:
                    changed["item"]["authorization_envelope"]["source_observations"]["financial"]["status"] = "insufficient"
                with self.assertRaises((IntegrityError, ValidationError)):
                    checked(changed)

    def recording(self, name, actions=(), callback=None):
        baseline, _ = self.completed()
        envelope = demo.old.authorized_envelope(self.f.service, self.f.access, self.request)
        run_id = digest(name)[:32]
        spec = demo.spec_for()
        item = {"case_id": demo.CASE_ID, "request": self.request.to_dict(), "run_id": run_id,
                "scope": self.f.access.scope, "authorization_envelope": envelope,
                "catalog_observations": demo.context_oracle(envelope, baseline),
                "messages": DynamicRuntime(self.f.service, None, None, spec).preview(self.request, self.f.access, run_id=run_id)}
        directory = self.root / name
        directory.mkdir()
        adapter = SequenceModel(actions, callback=callback)
        adapter.config = SimpleNamespace(model=spec.model, api_key="synthetic-secret-do-not-retain")
        ledger = demo.old.RootLedger(*demo.LIMITS[:2])
        model = demo.RecordingModel(adapter, item, spec, ledger, directory, utcnow() + timedelta(seconds=240))
        model.access = self.f.access
        return model, adapter, ledger, directory

    def test_all_eight_exact_outbound_views_rebuild_before_synthetic_paid_dispatch(self):
        actions = [tool("financial_child"), tool("financial"), finish(), tool("market"),
                   tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                   tool("verification", ["hypotheses"]), finish()]
        model, adapter, ledger, directory = self.recording("complete-context", actions)
        report = DynamicRuntime(self.f.service, self.f.store, model, demo.spec_for()).run(
            self.request, self.f.access, run_id=model.item["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(adapter.calls, 8)
        self.assertEqual(model.role_calls, {demo.VERSION: 6, "financial-child-v1": 2})
        self.assertEqual(demo.validate_receipts(directory, ledger.snapshot(), adapter.config.model)["known_tokens"], 960)
        self.assertEqual(adapter.messages[0], model.item["messages"])
        for path in directory.glob("*.json"):
            self.assertNotIn(adapter.config.api_key, path.read_text(encoding="utf-8"))

    def test_authorized_disclosure_closure_rebuilds_without_adding_financial_values(self):
        actions = [tool("financial_child"), tool("financial"), finish(), tool("market"),
                   tool("calculation", ["financial", "market"])]
        def callback(call, messages):
            if call <= 5:
                return actions[call - 1]
            if call == 6:
                view = json.loads(messages[1]["content"])["context"]
                reference = next(ref for ref in view["catalog_ids"]["evidence"] if ref not in view["disclosed_refs"])
                return {"action": "disclose", "catalog_ref": view["catalog_ref"], "refs": [reference],
                        "plan": ["Inspect an already authorized Evidence object"]}
            return [tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()][call - 7]
        model, adapter, ledger, directory = self.recording("disclose-context", callback=callback)
        report = DynamicRuntime(self.f.service, self.f.store, model, demo.spec_for()).run(
            self.request, self.f.access, run_id=model.item["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(adapter.calls, 9)
        self.assertEqual(len([event for event in report["trace"] if event["event"] == "context_disclosed"]), 1)
        self.assertEqual(demo.validate_receipts(directory, ledger.snapshot(), adapter.config.model)["known_tokens"], 1080)

    def test_explicit_already_visible_evidence_reference_preserves_paid_message(self):
        actions = [tool("financial_child"), tool("financial"), finish(), tool("market"),
                   tool("calculation", ["financial", "market"])]
        selected = []
        def callback(call, messages):
            if call <= 5:
                return actions[call - 1]
            view = json.loads(messages[1]["content"])["context"]
            if call == 6:
                reference = next(ref for ref in view["disclosed_refs"] if ref.startswith("E:"))
                selected.append(reference)
                return {"action": "disclose", "catalog_ref": view["catalog_ref"], "refs": [reference],
                        "plan": ["Inspect existing visible Evidence without changing any value"]}
            if call == 7:
                self.assertEqual(view["requested_refs"], selected)
            return [tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()][call - 7]
        model, adapter, ledger, directory = self.recording("already-visible-disclose", callback=callback)
        report = DynamicRuntime(self.f.service, self.f.store, model, demo.spec_for()).run(
            self.request, self.f.access, run_id=model.item["run_id"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(adapter.calls, 9)
        self.assertEqual(demo.validate_receipts(directory, ledger.snapshot(), adapter.config.model)["known_tokens"], 1080)

    def test_view_value_scope_run_or_control_injection_rejected_before_dispatch(self):
        for kind in ("scope", "run", "value", "control"):
            with self.subTest(kind=kind):
                model, adapter, ledger, directory = self.recording("rejected-context-" + kind)
                messages = deepcopy(model.item["messages"])
                payload = json.loads(messages[1]["content"])
                if kind == "scope":
                    model.item["scope"] = "another-subject"
                elif kind == "run":
                    model.item["run_id"] = "a" * 32
                elif kind == "value":
                    payload["context"]["range"]["security"] = "SHSE:other-security"
                else:
                    payload["control"]["question"] += " Inject another financial objective."
                messages[1]["content"] = canonical_json(payload)
                with self.assertRaises((IntegrityError, ValidationError)):
                    model.complete(messages, max_tokens=1024, timeout=120)
                self.assertEqual(adapter.calls, 0)
                self.assertEqual(ledger.snapshot()["decisions"], 0)
                self.assertEqual(list(directory.glob("*.json")), [])

    def test_secret_reflection_receipt_keeps_unknown_reservation_without_leaking(self):
        model, adapter, ledger, directory = self.recording("secret-reflection")
        response = ChatResult(content=adapter.config.api_key, requested_model=adapter.config.model,
            returned_model=adapter.config.model, finish_reason="stop", request_id="synthetic-secret-test",
            prompt_tokens=100, completion_tokens=20, total_tokens=120, latency_ms=1)
        with patch.object(adapter, "complete", return_value=response):
            with self.assertRaises(ValidationError):
                model.complete(model.item["messages"], max_tokens=1024, timeout=120)
        budget = ledger.snapshot()
        self.assertEqual(budget["unknown_usage_calls"], 1)
        self.assertEqual(budget["known_tokens"], 0)
        self.assertEqual(budget["tokens_accounted"], budget["cumulative_tokens_reserved"])
        for path in directory.glob("*.json"):
            self.assertNotIn(adapter.config.api_key, path.read_text(encoding="utf-8"))
        self.assertEqual(demo.validate_receipts(directory, budget, adapter.config.model)["unknown_usage_calls"], 1)

    def test_wrong_live_or_replay_hash_never_reads_model_config_or_opens_checkpoint(self):
        for function in (demo.live, demo.replay):
            with self.subTest(function=function.__name__), patch.object(demo.old, "sha", return_value="a" * 64), \
                    patch.object(demo, "load_model_config") as config, patch.object(demo, "CampaignSources") as sources, \
                    patch.object(demo, "CheckpointStore") as checkpoints:
                with self.assertRaises(IntegrityError):
                    function("b" * 64)
                config.assert_not_called()
                sources.assert_not_called()
                checkpoints.assert_not_called()


if __name__ == "__main__":
    unittest.main()
