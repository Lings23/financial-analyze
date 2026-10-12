"""Synthetic contract/protocol mechanisms; not live financial ground truth."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research.calculation import calculate_financial
from stock_research.research.dynamic_contracts import (
    DynamicRequest, FinancialChildSpec, FinancialRequest, MarketChildSpec,
    ParallelParentSpec, FINANCIAL_DATASETS, MARKET_DATASETS,
)
from stock_research.research.domain_analysis_contracts import (
    DomainAnalysisParentSpec, FinancialAnalysisChildSpec, MarketAnalysisChildSpec,
    FinancialAnalysisRequest, MarketAnalysisRequest, TASK_VERSION, domain_task,
    required_checks, required_operators, review_checks, task_refs, ownership,
    validate_receipt,
)
from stock_research.research.domain_analysis_protocol import (
    parse_action, messages, observe_tool, expand_observation_tables,
    _exact_observation_tables, encode_model_view, decode_model_view,
    _result_view,
)
from stock_research.research.tools import read_domain


def action(name, refs=()):
    return json.dumps({"action": "tool", "tool": name, "refs": list(refs), "plan": ["Execute frozen check"]})


class _FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.parent = DynamicRequest.from_dict({**study_request(self.f).to_dict(), "question": "核对原财务及行情目标"})
        self.financial = FinancialAnalysisRequest.from_parent(self.parent)
        self.market = MarketAnalysisRequest.from_parent(self.parent)


class DomainAnalysisContractTests(_FixtureCase):
    def test_requests_preserve_root_projection_and_scope(self):
        for child, cls, datasets in ((self.financial, FinancialAnalysisRequest, FINANCIAL_DATASETS),
                                     (self.market, MarketAnalysisRequest, MARKET_DATASETS)):
            self.assertEqual(cls.from_dict(child.to_dict()), child)
            self.assertEqual(child.security, self.parent.security)
            self.assertEqual(child.as_of, self.parent.as_of)
            self.assertEqual(child.mode, self.parent.mode)
            self.assertEqual(child.question, self.parent.question)
            self.assertEqual(child.parent_request_ref, digest(self.parent.to_dict()))
            self.assertEqual(child.bindings, tuple(b for b in self.parent.bindings if b.dataset in datasets))
        self.assertEqual(self.financial.hypotheses, ("financial_deterioration", "cashflow_divergence"))
        self.assertEqual(self.market.hypotheses, ("mechanical_adjustment",))
        self.assertNotEqual(self.financial.to_dict(), FinancialRequest.from_parent(self.parent).to_dict())

    def test_profiles_cannot_add_or_remove_amount_goal(self):
        with self.assertRaises(ValidationError):
            FinancialAnalysisRequest.from_parent(self.parent, profile_id="financial-profit-amount/v1")
        amount = replace(self.parent, hypotheses=self.parent.hypotheses + ("absolute_profit_change",),
                         hypothesis_version="profit-change/v1")
        child = FinancialAnalysisRequest.from_parent(amount)
        self.assertEqual(child.profile_id, "financial-profit-amount/v1")
        self.assertIn("profit_amount_change", required_operators(child))
        self.assertIn("income_yoy", required_operators(child))
        self.assertIn("absolute_profit_change", review_checks(child))
        with self.assertRaises(ValidationError):
            task_refs(amount)
        self.assertEqual(set(task_refs(amount, profile_id="profit-amount/v1")), {"financial", "market"})

    def test_request_rejects_unknown_fields_and_domain_widening(self):
        for changes in ({"profile_id": []}, {"parent_request_ref": ""}, {"question": "   "},
                        {"hypotheses": ("mechanical_adjustment",)}, {"event_record_id": "0" * 64},
                        {"bindings": self.parent.bindings}, {"as_of": self.parent.as_of.replace(tzinfo=None)}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    replace(self.financial, **changes)
        for changes in ({"hypotheses": ("financial_deterioration",)}, {"bindings": self.parent.bindings}):
            with self.assertRaises(ValidationError):
                replace(self.market, **changes)
        with self.assertRaises(ValidationError):
            FinancialAnalysisRequest.from_dict({**self.financial.to_dict(), "grant": "model"})
        with self.assertRaises(ValidationError):
            FinancialAnalysisRequest.from_parent(self.parent, datasets=FINANCIAL_DATASETS | MARKET_DATASETS)
        with self.assertRaises(ValidationError):
            FinancialAnalysisRequest.from_parent(self.financial)

    def test_independent_specs_preserve_legacy_and_strong_baselines(self):
        old = (FinancialChildSpec(), MarketChildSpec(), ParallelParentSpec())
        self.assertEqual((old[0].max_decisions, old[0].max_tools), (3, 1))
        for cls, legacy in ((FinancialAnalysisChildSpec, old[0]), (MarketAnalysisChildSpec, old[1])):
            spec = cls()
            self.assertNotEqual(spec.identity, legacy.identity)
            self.assertEqual((spec.max_decisions, spec.max_tools, spec.max_tokens, spec.max_seconds), (5, 4, 18000, 120))
            self.assertIn("domain_review", spec.allowed_tools)
            for changes in ({"max_tools": 5}, {"max_decisions": 6}, {"context_bytes": 12001},
                            {"context_bytes": 11999}, {"no_progress_limit": 1}, {"max_tokens": 18001},
                            {"allowed_tools": frozenset({"financial_child"})}, {"max_tools": True}):
                with self.assertRaises(ValidationError):
                    replace(spec, **changes)
        for mode, limits in (("direct", (8, 12)), ("tool", (8, 12)), ("child", (6, 8))):
            spec = DomainAnalysisParentSpec(mode=mode)
            self.assertEqual((spec.max_decisions, spec.max_tools), limits)
            self.assertEqual((spec.root_max_decisions, spec.root_max_tools, spec.root_max_tokens), (16, 18, 96000))
            self.assertNotEqual(spec.identity, old[2].identity)
        with self.assertRaises(ValidationError):
            DomainAnalysisParentSpec(max_decisions=8)
        with self.assertRaises(ValidationError):
            DomainAnalysisParentSpec(mode="unknown")

    def test_frozen_checks_ownership_and_task_identity(self):
        checks = required_checks(self.financial)
        self.assertIn("calculation", checks)
        self.assertIn("domain_review", checks)
        self.assertIn("operator:income_yoy", checks)
        self.assertEqual(ownership(self.parent)["check_ownership"]["event_chronology"], "parent")
        self.assertEqual(ownership(self.parent)["check_ownership"]["mechanical_adjustment"], "market")
        refs = task_refs(self.parent)
        self.assertNotEqual(refs["financial"], refs["market"])
        self.assertNotEqual(refs, task_refs(replace(self.parent, question="另一固定问题")))
        task = domain_task(self.financial, root_run_id="root", parent_run_id="parent",
                           spec=FinancialAnalysisChildSpec(), source_envelope={"snapshot": "a" * 64},
                           allocation_id="allocation", deadline=self.parent.as_of, authorization_ref="b" * 64)
        self.assertEqual(task["schema"], TASK_VERSION)
        self.assertEqual(task["task_ref"], digest({k: v for k, v in task.items() if k != "task_ref"}))
        self.assertEqual(task["limits"]["tools"], 4)
        with self.assertRaises(ValidationError):
            domain_task(self.financial, root_run_id="root", parent_run_id="parent", spec=MarketAnalysisChildSpec(),
                        source_envelope={}, allocation_id="a", deadline=self.parent.as_of, authorization_ref="b" * 64)

    def test_receipts_bind_source_separately_from_production(self):
        receipt = {"tool": "financial", "call_id": "actual-read", "input_revision": "a" * 64,
                   "output_revision": "b" * 64, "started_ref": "c" * 64, "finished_ref": "d" * 64}
        self.assertEqual(validate_receipt(receipt, tool="financial", input_revision="a" * 64), receipt)
        for changes in ({"tool": "calculation"}, {"call_id": ""}, {"input_revision": "e" * 64},
                        {"started_ref": "not-executed"}):
            with self.assertRaises(ValidationError):
                validate_receipt({**receipt, **changes}, tool="financial", input_revision="a" * 64)


class DomainAnalysisProtocolTests(_FixtureCase):
    def parse(self, content, *, completed=(), state=None, request=None, spec=None, available=None):
        request = request or self.financial
        spec = spec or FinancialAnalysisChildSpec()
        return parse_action(content, available or spec.visible_tools, completed,
                            request=request, spec=spec, state=state or {})

    def test_child_calculation_catalogue_and_complete_review_revision(self):
        self.assertEqual(self.parse(action("financial"))["refs"], [])
        calculated = self.parse(action("calculation", ["financial", "operator:income_yoy"]), completed=["financial"])
        self.assertIn("operator:income_yoy", calculated["refs"])
        state = {"analysis_operations": required_operators(self.financial), "calculated_revision": "a" * 64}
        refs = ["revision:" + "a" * 64, *("check:" + check for check in review_checks(self.financial))]
        self.assertEqual(self.parse(action("domain_review", refs), completed=["financial", "calculation"], state=state)["tool"], "domain_review")
        for invalid in (["revision:" + "b" * 64, *refs[1:]], refs[:-1], refs + ["check:market_direction"]):
            with self.assertRaises(ValidationError):
                self.parse(action("domain_review", invalid), completed=["financial", "calculation"], state=state)
        with self.assertRaises(ValidationError):
            self.parse(action("domain_review", refs), completed=["financial", "calculation"], state={**state, "analysis_operations": ["income_yoy"]})

    def test_child_rejects_unknown_or_cross_domain_and_not_read_inputs(self):
        for tool, refs, completed in (("financial", ["financial"], ()),
                                     ("calculation", ["financial", "operator:income_yoy"], ()),
                                     ("calculation", ["financial", "operator:market_price_window"], ("financial",)),
                                     ("calculation", ["financial"], ("financial",)),
                                     ("calculation", ["financial", "operator:income_yoy", "operator:income_yoy"], ("financial",))):
            with self.assertRaises(ValidationError):
                self.parse(action(tool, refs), completed=completed)
        with self.assertRaises(PermissionDenied):
            self.parse(action("market"))
        with self.assertRaises(PermissionDenied):
            self.parse(action("financial_child"))
        with self.assertRaises(ValidationError):
            self.parse(action("arbitrary_formula"))

    def test_market_has_same_strict_operator_contract(self):
        request, spec = self.market, MarketAnalysisChildSpec()
        refs = ["market", "operator:market_price_window", "operator:factor_adjusted_window"]
        self.assertEqual(self.parse(action("calculation", refs), request=request, spec=spec, completed=["market"])["refs"], sorted(refs))
        with self.assertRaises(ValidationError):
            self.parse(action("calculation", ["market", "operator:income_yoy"]), request=request, spec=spec, completed=["market"])

    def test_parent_task_and_parallel_bind_exact_frozen_goal(self):
        spec = DomainAnalysisParentSpec()
        refs = task_refs(self.parent)
        serial_spec = replace(spec, execution="serial")
        self.parse(action("financial_child", [refs["financial"]]), request=self.parent, spec=serial_spec)
        with self.assertRaises(ValidationError):
            self.parse(action("financial_child", [refs["financial"]]), request=self.parent, spec=spec)
        with self.assertRaises(ValidationError):
            self.parse(action("financial_child"), request=self.parent, spec=serial_spec)
        with self.assertRaises(ValidationError):
            self.parse(action("financial_child", [refs["market"]]), request=self.parent, spec=serial_spec)
        parallel = {"action": "parallel", "tools": ["market_child", "financial_child"], "refs": list(refs.values()), "plan": ["Analyze both frozen tasks"]}
        self.assertEqual(self.parse(json.dumps(parallel), request=self.parent, spec=spec)["tools"], ["financial_child", "market_child"])
        with self.assertRaises(ValidationError):
            self.parse(json.dumps(parallel), request=self.parent, spec=replace(spec, execution="serial"))
        with self.assertRaises(ValidationError):
            self.parse(json.dumps(parallel), request=self.parent, spec=spec, completed=["financial"])
        tool_spec = DomainAnalysisParentSpec(mode="tool")
        self.parse(action("financial_analysis_tool", [refs["financial"]]), request=self.parent, spec=tool_spec)
        with self.assertRaises(ValidationError):
            self.parse(action("financial_child", [refs["financial"]]), request=self.parent, spec=tool_spec)

    def test_parent_composition_and_final_verification_preserve_checks(self):
        spec = DomainAnalysisParentSpec(mode="direct")
        self.parse(action("calculation", ["financial", "market"]), completed=["financial", "market"], request=self.parent, spec=spec)
        self.parse(action("verification", ["hypotheses"]), completed=["hypotheses"], request=self.parent, spec=spec)
        with self.assertRaises(ValidationError):
            self.parse(action("calculation", ["financial"]), completed=["financial", "market"], request=self.parent, spec=spec)
        with self.assertRaises(ValidationError):
            self.parse(action("verification", ["hypotheses"]), request=self.parent, spec=spec)

    def test_finish_and_json_keys_values_strict(self):
        valid = {"action": "finish", "reason": "insufficient", "plan": ["Retain legitimate insufficiency"]}
        self.assertEqual(self.parse(json.dumps(valid))["reason"], "insufficient")
        for extra in ({"refs": []}, {"tool": "financial"}, {"value": "9"}, {"checks": []}):
            with self.assertRaises(ValidationError):
                self.parse(json.dumps({**valid, **extra}))
        for content in ('{"action":"tool","action":"finish","tool":"financial","refs":[],"plan":["read"]}',
                        action("financial").replace('"refs": []', '"refs": [1]'),
                        action("financial").replace('"refs": []', '"refs": [NaN]'),
                        "```json\n" + action("financial") + "\n```", action("financial") + "x"):
            with self.assertRaises(ValidationError):
                self.parse(content)

    def test_exact_view_legal_actions_and_wire_identity(self):
        state = {"observations": {}, "requirements": required_checks(self.financial), "plans": [], "analysis_operations": []}
        wire, metadata = messages(state, self.financial, FinancialAnalysisChildSpec().visible_tools, 12000,
                                  spec=FinancialAnalysisChildSpec(), decision=3)
        payload = json.loads(wire[1]["content"])
        self.assertEqual(payload["control"]["decision"], 3)
        self.assertEqual(payload["control"]["legal_next_actions"][0]["tool"], "financial")
        self.assertEqual(payload["analysis_context"]["required_checks"], required_checks(self.financial))
        self.assertEqual(metadata["bytes"], sum(len(m["content"].encode("utf-8")) for m in wire))
        self.assertEqual(metadata["message_sha256"], digest(wire))
        self.assertNotIn("context", payload)
        source = read_domain(self.f.service, self.financial, self.f.access, "financial")
        state["observations"]["financial"] = observe_tool("financial", source)
        wire, _ = messages(state, self.financial, FinancialAnalysisChildSpec().visible_tools, 12000,
                           spec=FinancialAnalysisChildSpec())
        candidates = json.loads(wire[1]["content"])["control"]["legal_next_actions"]
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(candidate["tool"] == "calculation" for candidate in candidates))
        for candidate in candidates:
            self.parse(json.dumps(candidate), completed=["financial"], state=state)

    def test_precise_observations_and_lossless_interning(self):
        source = read_domain(self.f.service, self.financial, self.f.access, "financial")
        computed = calculate_financial(source)
        first = observe_tool("calculation", computed)
        second = observe_tool("domain_review", computed)
        compact, table = _exact_observation_tables([first, second])
        self.assertTrue(table)
        self.assertEqual(expand_observation_tables(compact, table), [first, second])
        with self.assertRaises(ValidationError):
            expand_observation_tables([{**first, "facts": {"table_ref": True}}], table)
        state = {"observations": {"financial": observe_tool("financial", source), "calculation": first},
                 "analysis_operations": required_operators(self.financial), "calculated_revision": "a" * 64}
        wire, _ = messages(state, self.financial, FinancialAnalysisChildSpec().visible_tools, 12000,
                           spec=FinancialAnalysisChildSpec())
        context = decode_model_view(json.loads(wire[1]["content"])["analysis_context"])
        self.assertEqual(expand_observation_tables(context["observations"], context["exact_tables"]), [value for _, value in sorted(state["observations"].items())])
        self.assertEqual(set(first["facts"]), {"F" + str(i+1) for i in range(len(computed["facts"]))})

    def test_context_rejects_scope_source_text_and_changed_requirements(self):
        source = read_domain(self.f.service, self.financial, self.f.access, "financial")
        observed = observe_tool("financial", source)
        for mutation in ({"body": "source instruction"}, {"tool": "market"}):
            state = {"observations": {"financial": {**observed, **mutation}}, "analysis_operations": []}
            with self.assertRaises((ValidationError, PermissionDenied)):
                messages(state, self.financial, FinancialAnalysisChildSpec().visible_tools, 12000, spec=FinancialAnalysisChildSpec())
        with self.assertRaises(ValidationError):
            messages({"observations": {}, "requirements": ["read:financial"]}, self.financial,
                     FinancialAnalysisChildSpec().visible_tools, 12000, spec=FinancialAnalysisChildSpec())

    def test_context_overflow_preserves_content_for_runtime_typed_stop(self):
        source = read_domain(self.f.service, self.financial, self.f.access, "financial")
        observed = observe_tool("financial", source)
        bound = next(binding for binding in self.parent.bindings if binding.dataset == "financial_income")
        start = bound.start
        parent = replace(self.parent, bindings=(*self.parent.bindings,
                         replace(bound, dataset="financial_balance"), replace(bound, dataset="financial_cashflow")))
        child = FinancialAnalysisRequest.from_parent(parent)
        for dataset in FINANCIAL_DATASETS:
            observed["datasets"][dataset] = {"status": "available", "records": 1000,
                "periods": [(start + timedelta(days=i % 366)).isoformat() for i in range(1000)],
                "window": [bound.start.isoformat(), bound.end.isoformat()], "source_result_ref": digest(dataset)}
        wire, metadata = messages({"observations": {"financial": observed}}, child,
                                  FinancialAnalysisChildSpec().visible_tools, 12000, spec=FinancialAnalysisChildSpec())
        self.assertGreater(metadata["bytes"], 12000)
        context = decode_model_view(json.loads(wire[1]["content"])["analysis_context"])
        self.assertEqual(len(context["observations"][0]["datasets"]["financial_income"]["periods"]), 1000)


class ExactDomainModelViewTests(_FixtureCase):
    def result_state(self):
        from stock_research.research.domain_operators import calculate_domain, review_domain
        from stock_research.research.study import calculate_study_claims
        from stock_research.research.hypotheses import test_hypotheses
        parent = replace(self.parent, hypotheses=("financial_deterioration",))
        outputs, results = {}, {}
        for domain, cls in (("financial", FinancialAnalysisRequest), ("market", MarketAnalysisRequest)):
            child = cls.from_parent(parent)
            source = read_domain(self.f.service, child, self.f.access, domain)
            outputs[domain] = source
            computed = review_domain(calculate_domain(source, child, domain), source, child, domain)
            attestation = {"schema": "synthetic-local-attestation", "domain": domain,
                           "ownership_ref": digest({"domain": domain, "checks": child.hypotheses}),
                           "computed_ref": digest(computed), "source_result_ref": digest(source)}
            attestation["attestation_ref"] = digest(attestation)
            results[domain] = {"schema": "domain-analysis-tool-result/v1", "domain": domain,
                "status": "completed", "request_ref": digest(child.to_dict()), "profile_id": child.profile_id,
                "spec_ref": FinancialAnalysisChildSpec().identity if domain == "financial" else MarketAnalysisChildSpec().identity,
                "task_ref": task_refs(parent)[domain], "computed": computed, "source_result_ref": digest(source),
                "source_tool_call_id": "synthetic-source-call-" + domain, "input_revision": digest(source),
                "receipts": [], "local_verification": computed["local_verification"],
                "executed_operators": required_operators(child), "local_attestation": attestation,
                "local_attestation_ref": attestation["attestation_ref"]}
        datasets = {key: value for source in outputs.values() for key, value in source.items()}
        computed = calculate_study_claims(datasets, parent)
        computed["hypotheses"] = test_hypotheses(computed, datasets, parent)
        observations = {domain: observe_tool(domain, source) for domain, source in outputs.items()}
        observations.update(calculation=observe_tool("calculation", computed),
                            hypotheses=observe_tool("hypotheses", computed))
        revision = digest({"sources": outputs, "domain_results": {domain: digest(result)
                           for domain, result in sorted(results.items())}})
        state = {"observations": observations, "outputs": outputs, "domain_results": results,
                 "calculated_revision": revision, "hypotheses_revision": revision,
                 "analysis_ownership": ownership(parent), "requirements": required_checks(parent), "plans": []}
        return parent, state

    def test_complete_parent_model_view_restores_canonical_facts_evidence_and_checks(self):
        parent, state = self.result_state()
        frozen = deepcopy(state)
        spec = DomainAnalysisParentSpec(mode="tool")
        available = {"financial_analysis_tool", "market_analysis_tool", "calculation", "hypotheses", "verification"}
        wire, metadata = messages(state, parent, available, 12000, spec=spec)
        packed = json.loads(wire[1]["content"])["analysis_context"]
        self.assertEqual(packed["schema"], "domain-analysis-model-view/v2")
        restored = decode_model_view(packed)
        self.assertEqual(restored["request"], parent.to_dict())
        self.assertEqual(restored["required_checks"], required_checks(parent))
        self.assertEqual(restored["accepted_domain_results"], [_result_view(state["domain_results"][domain]) for domain in ("financial", "market")])
        self.assertEqual(restored["ownership"], state["analysis_ownership"])
        self.assertEqual(restored["ownership_ref"], digest(state["analysis_ownership"]))
        observed = expand_observation_tables(restored["observations"], restored["exact_tables"])
        self.assertEqual(observed, [value for _, value in sorted(state["observations"].items())])
        for result in restored["accepted_domain_results"]:
            original = state["domain_results"][result["domain"]]
            self.assertEqual(result["facts"], original["computed"]["facts"])
            self.assertEqual(result["gaps"], original["computed"]["gaps"])
            self.assertEqual(result["hypotheses"], original["computed"]["hypotheses"])
            self.assertEqual(result["evidence_refs"], sorted(original["computed"]["evidence"]))
            self.assertEqual(result["local_attestation_ref"], original["local_attestation_ref"])
        self.assertLess(metadata["bytes"], metadata["literal_bytes"])
        self.assertEqual(state, frozen)
        self.assertEqual(encode_model_view(restored), packed)

    def test_metadata_numeric_cells_remain_literal_and_wrapper_is_exact(self):
        parent, state = self.result_state()
        wire, _ = messages(state, parent, DomainAnalysisParentSpec(mode="tool").visible_tools,
                           12000, spec=DomainAnalysisParentSpec(mode="tool"))
        packed = json.loads(wire[1]["content"])["analysis_context"]
        symbols = packed["symbols"]
        columns = [[symbols[key] if type(key) is int else key for key in row] for row in packed["columns"]]
        value_cells = []
        def visit(value):
            if type(value) is dict:
                if set(value) == {"r", "v"} and "value" in columns[value["r"]]:
                    cell = value["v"][columns[value["r"]].index("value")]
                    self.assertIsInstance(cell, str)
                    value_cells.append(cell)
                for child in value.values():
                    visit(child)
            elif type(value) is list:
                for child in value:
                    visit(child)
        visit(packed["view"])
        self.assertTrue(value_cells)
        self.assertIn("100", value_cells)
        self.assertIn("80", value_cells)
        self.assertEqual(decode_model_view(packed)["request"], parent.to_dict())

    def test_codec_rejects_dangling_columns_values_and_attestation_tampering(self):
        parent, state = self.result_state()
        wire, _ = messages(state, parent, DomainAnalysisParentSpec(mode="tool").visible_tools,
                           12000, spec=DomainAnalysisParentSpec(mode="tool"))
        packed = json.loads(wire[1]["content"])["analysis_context"]
        for bad_column in (True, 999999, "invented_column"):
            damaged = deepcopy(packed)
            damaged["columns"][0][0] = bad_column
            with self.assertRaises(ValidationError):
                decode_model_view(damaged)
        damaged = deepcopy(packed)
        damaged["view_ref"] = "a" * 64
        with self.assertRaises(IntegrityError):
            decode_model_view(damaged)
        damaged = deepcopy(packed)
        damaged["view"]["request"]["as_of"] = "2099-01-01T00:00:00+08:00"
        with self.assertRaises(IntegrityError):
            decode_model_view(damaged)
        result = deepcopy(state["domain_results"]["financial"])
        result["local_attestation"]["computed_ref"] = "a" * 64
        with self.assertRaises(IntegrityError):
            _result_view(result)

    def test_checkpoint_key_order_cannot_change_prepared_paid_wire(self):
        parent, state = self.result_state()
        spec = DomainAnalysisParentSpec(mode="tool")
        available = spec.visible_tools
        original = messages(state, parent, available, 12000, spec=spec, decision=4)
        restored = json.loads(canonical_json(state))
        self.assertEqual(messages(restored, parent, available, 12000, spec=spec, decision=4), original)

    def test_small_literal_fallback_and_invalid_numeric_source(self):
        small = {"schema": "domain-analysis-model-view/v1", "facts": [], "source_records": 3}
        self.assertEqual(encode_model_view(small), small)
        self.assertEqual(decode_model_view(small), small)
        for invalid in ({**small, "source_records": 1.5}, {**small, "facts": ()},
                        {**small, "other": {"n": 1}}):
            with self.assertRaises(ValidationError):
                encode_model_view(invalid)


if __name__ == "__main__":
    unittest.main()
