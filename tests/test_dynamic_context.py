"""Synthetic lossless catalogue/disclosure mechanisms, never financial truth."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research.dynamic_context import (
    MAX_REFS, build_catalog, decode_arena, decode_catalog, encode_arena,
    encode_view, expand_view, resolve_catalog, validate_catalog, validate_view, view_catalog,
)
from stock_research.research.dynamic_contracts import DynamicRequest, FinancialRequest, MarketRequest, required_checks
from stock_research.research.dynamic_protocol import observe_tool
from stock_research.research.study import StudyRuntime
from stock_research.research.tools import read_domain


SCOPE = "SYNTHETIC/context-owner"
RUN = "a" * 32


def rehash(catalog):
    catalog["catalog_ref"] = digest({key: value for key, value in catalog.items() if key != "catalog_ref"})
    return catalog


def column_objects(view, table):
    view = expand_view(view)
    columns = view["columns"][table]
    return {row[0]: dict(zip(columns[1:], row[1:])) for row in view[table]}


class ArenaTests(unittest.TestCase):
    def test_round_trip_exact_types_nulls_order_and_unicode(self):
        original = {"empty": {}, "sequence": [None, False, True, 0, -99, [], "000.0100", "精确值"],
                    "nested": {"z": "repeated", "a": ["repeated", {"str": "1e-34"}]}}
        arena = encode_arena(original)
        restored = decode_arena(arena)
        self.assertEqual(restored, original)
        self.assertIs(restored["sequence"][0], None)
        self.assertIs(restored["sequence"][1], False)
        self.assertEqual(arena["strings"].count("repeated"), 1)
        self.assertEqual(encode_arena(restored), arena)

    def test_mapping_insertion_order_does_not_change_encoding(self):
        a = {"z": [{"b": 2, "a": "exact"}], "a": 1}
        b = {"a": 1, "z": [{"a": "exact", "b": 2}]}
        self.assertEqual(encode_arena(a), encode_arena(b))
        self.assertNotEqual(encode_arena(["a", "b"]), encode_arena(["b", "a"]))

    def test_floats_nontext_keys_invalid_unicode_and_cycles_rejected(self):
        cycle = []; cycle.append(cycle)
        for value in (1.25, float("nan"), {1: "unsupported"}, ("tuple",), "\ud800", cycle):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ValidationError):
                    encode_arena(value)

    def test_alias_boolean_out_of_bounds_unknown_tag_and_duplicate_pairs_rejected(self):
        arena = encode_arena({"key": "value"})
        invalid = []
        bad = deepcopy(arena); bad["value"] = ["s", True]; invalid.append(bad)
        bad = deepcopy(arena); bad["value"] = ["s", 100]; invalid.append(bad)
        bad = deepcopy(arena); bad["value"] = ["new-field", []]; invalid.append(bad)
        bad = deepcopy(arena); bad["value"][1].append(deepcopy(bad["value"][1][0])); invalid.append(bad)
        bad = deepcopy(arena); bad["strings"].append("unused"); bad["strings"].sort(); invalid.append(bad)
        bad = deepcopy(arena); bad["strings"].append(bad["strings"][-1]); invalid.append(bad)
        for value in invalid:
            with self.assertRaises(ValidationError):
                decode_arena(value)

    def test_depth_budget_is_bounded_without_lossy_fallback(self):
        value = "exact"
        for _ in range(40):
            value = [value]
        with self.assertRaises(ValidationError):
            encode_arena(value)


class DynamicContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: preserve exact bound evidence and all required checks",
        })
        self.outputs = {name: read_domain(self.f.service, self.request, self.f.access, name)
                        for name in ("financial", "market")}
        datasets = {key: value for output in self.outputs.values() for key, value in output.items()}
        computed = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, self.request)
        calculation = deepcopy(computed); calculation["hypotheses"] = []
        self.source = [observe_tool(name, self.outputs[name]) for name in ("financial", "market")]
        self.calculated = observe_tool("calculation", calculation)
        self.tested = observe_tool("hypotheses", computed)
        self.verified = observe_tool("verification", computed["verification"])
        self.observations = self.source + [self.calculated, self.tested, self.verified]
        self.checks = required_checks(self.request)

    def catalog(self, observations=None, request=None):
        request = request or self.request
        return build_catalog(request, self.observations if observations is None else observations,
                             required_checks(request), scope=SCOPE, run_id=RUN)

    def view(self, catalog=None, **kwargs):
        return view_catalog(catalog or self.catalog(), scope=SCOPE, run_id=RUN, **kwargs)

    def test_complete_old_observations_and_request_round_trip(self):
        catalog = self.catalog()
        original_catalog = deepcopy(catalog)
        restored = decode_catalog(catalog, scope=SCOPE, run_id=RUN, catalog_ref=catalog["catalog_ref"])
        self.assertEqual(restored, {"scope": SCOPE, "run_id": RUN, "request": self.request.to_dict(),
                                    "observations": self.observations, "required_checks": self.checks})
        self.assertEqual(catalog, self.catalog())
        restored["observations"][0]["datasets"].clear()
        self.assertEqual(catalog, original_catalog)
        self.assertEqual(validate_catalog(catalog, scope=SCOPE, run_id=RUN)["observations"], 5)

    def test_all_facts_hypotheses_and_evidence_refs_remain_without_disclosure(self):
        catalog = self.catalog(); view = self.view(catalog)
        self.assertEqual(column_objects(view, "facts"), {"C:" + k: v for k, v in self.tested["facts"].items()})
        self.assertEqual(column_objects(view, "hypotheses"), {"H:" + k: v for k, v in self.tested["hypotheses"].items()})
        self.assertEqual(view["evidence"], [])
        self.assertEqual(set(view["catalog_ids"]["evidence"]), {"E:" + k for k in self.tested["evidence"]})
        refs = view["catalog_ids"]["evidence"]
        resolved = resolve_catalog(catalog, refs, scope=SCOPE, run_id=RUN, catalog_ref=catalog["catalog_ref"])
        self.assertEqual(resolved, {"E:" + k: v for k, v in self.tested["evidence"].items()})

    def test_scope_run_and_question_not_repeated_in_model_data_view(self):
        view = self.view()
        wire = canonical_json(view)
        self.assertNotIn(SCOPE, wire)
        self.assertNotIn(RUN, wire)
        self.assertNotIn(self.request.question, wire)
        self.assertEqual(view["range"]["declared_hypotheses"], list(self.request.hypotheses))
        for binding in self.request.bindings:
            self.assertEqual(view["range"]["bindings"][binding.dataset],
                             {"provider": binding.provider, "snapshot_ref": binding.snapshot})
            self.assertEqual(view["range"]["bound_windows"][binding.dataset],
                             [binding.start.isoformat(), binding.end.isoformat()])

    def test_declared_hypothesis_closure_available_before_hypothesis_tool(self):
        catalog = self.catalog(self.source + [self.calculated])
        view = self.view(catalog, current_stage="hypotheses")
        names = {"revenue_yoy", "net_income_parent_yoy"}
        expected = {eid for fact in self.calculated["facts"].values() if fact["name"] in names
                    for eid in fact["evidence_ids"]}
        self.assertEqual({row[0][2:] for row in view["evidence"]}, expected)
        self.assertEqual(len(view["facts"]), len(self.calculated["facts"]))
        self.assertEqual(view["hypotheses"], [])

    def test_verification_discloses_all_fact_inputs_and_finish_preserves_counterevidence(self):
        view = self.view(current_stage="verification")
        expected = {eid for fact in self.tested["facts"].values() for eid in fact["evidence_ids"]}
        self.assertEqual({row[0][2:] for row in view["evidence"]}, expected)
        finished = self.view(current_stage="finish")
        hypothesis = self.tested["hypotheses"]["financial_deterioration"]
        claims = set(hypothesis["claim_ids"] + hypothesis["counterevidence_claim_ids"])
        expected_hypothesis = {eid for cid in claims for eid in self.tested["facts"][cid]["evidence_ids"]}
        self.assertEqual({row[0][2:] for row in finished["evidence"]}, expected_hypothesis)
        self.assertEqual(finished["catalog_ids"], view["catalog_ids"])

    def test_manual_refs_have_exact_claim_hypothesis_observation_input_closure(self):
        catalog = self.catalog()
        first = next(iter(self.tested["facts"]))
        view = self.view(catalog, refs=["C:" + first])
        self.assertEqual({row[0][2:] for row in view["evidence"]}, set(self.tested["facts"][first]["evidence_ids"]))
        all_evidence = self.view(catalog, refs=["O:calculation"])
        self.assertEqual(column_objects(all_evidence, "evidence"),
                         {"E:" + k: v for k, v in self.tested["evidence"].items()})
        hypothesis = self.view(catalog, refs=["H:financial_deterioration"])
        self.assertEqual(hypothesis["evidence"], self.view(catalog, current_stage="finish")["evidence"])

    def test_refs_are_bounded_unique_current_catalogue_and_known(self):
        catalog = self.catalog()
        known = next(iter(catalog["index"]))
        for refs in (known, [known, known], ["E:unknown"], [True], [known] * (MAX_REFS + 1)):
            with self.subTest(refs=refs):
                with self.assertRaises(ValidationError):
                    resolve_catalog(catalog, refs, scope=SCOPE, run_id=RUN, catalog_ref=catalog["catalog_ref"])
        with self.assertRaises(ValidationError):
            self.view(catalog, current_stage="invented_stage")

    def test_cross_scope_cross_run_stale_catalogue_and_mutated_hash_rejected(self):
        catalog = self.catalog()
        for scope, run in (("SYNTHETIC/other", RUN), (SCOPE, "b" * 32)):
            with self.assertRaises(PermissionDenied):
                decode_catalog(catalog, scope=scope, run_id=run)
        other = build_catalog(self.request, self.observations, self.checks, scope=SCOPE, run_id="b" * 32)
        self.assertNotEqual(other["catalog_ref"], catalog["catalog_ref"])
        with self.assertRaises(PermissionDenied):
            resolve_catalog(catalog, ["O:market"], scope=SCOPE, run_id=RUN, catalog_ref=other["catalog_ref"])
        altered = deepcopy(catalog); altered["request_ref"] = "0" * 64
        with self.assertRaises(IntegrityError):
            decode_catalog(altered, scope=SCOPE, run_id=RUN)

    def test_rehashed_index_tampering_unknown_keys_and_request_identity_detected(self):
        catalog = self.catalog()
        altered = deepcopy(catalog); altered["index"]["C:invented"] = deepcopy(next(iter(altered["index"].values())))
        with self.assertRaises(IntegrityError):
            decode_catalog(rehash(altered), scope=SCOPE, run_id=RUN)
        altered = deepcopy(catalog); altered["authorization"] = "all"
        with self.assertRaises(ValidationError):
            decode_catalog(altered, scope=SCOPE, run_id=RUN)
        altered = deepcopy(catalog); altered["request_ref"] = "0" * 64
        with self.assertRaises(IntegrityError):
            decode_catalog(rehash(altered), scope=SCOPE, run_id=RUN)

    def test_source_text_unknown_numeric_fields_pit_and_check_mutations_rejected(self):
        for kind in ("source_body", "fact_body", "evidence_authorization", "future", "NaN", "window"):
            observations = deepcopy(self.observations)
            if kind == "source_body":
                observations[0]["datasets"]["financial_income"]["source_text"] = "untrusted"
            elif kind == "fact_body":
                observations[2]["facts"]["F1"]["title"] = "untrusted"
            elif kind == "evidence_authorization":
                next(iter(observations[2]["evidence"].values()))["scope"] = "widened"
            elif kind in {"future", "NaN"}:
                observations[2]["facts"]["F1"]["available_at" if kind == "future" else "value"] = (
                    "2099-01-01T00:00:00+00:00" if kind == "future" else "NaN")
            else:
                observations[0]["datasets"]["financial_income"]["window"] = ["2000-01-01", "2099-01-01"]
            with self.subTest(kind=kind):
                with self.assertRaises(ValidationError):
                    self.catalog(observations)
        with self.assertRaises(ValidationError):
            build_catalog(self.request, self.observations, self.checks[:-1], scope=SCOPE, run_id=RUN)

    def test_rehashed_arena_still_validates_restored_observation_schema(self):
        altered = self.catalog()
        payload = decode_arena(altered["arena"])
        payload["observations"][0]["datasets"]["financial_income"]["body"] = "SOURCE INSTRUCTION"
        altered["arena"] = encode_arena(payload)
        with self.assertRaises(ValidationError):
            decode_catalog(rehash(altered), scope=SCOPE, run_id=RUN)

    def test_stale_derived_and_duplicate_observation_denied(self):
        altered = deepcopy(self.observations)
        altered[3]["facts"]["F1"]["value"] = "123"
        with self.assertRaises(ValidationError):
            self.catalog(altered)
        with self.assertRaises(ValidationError):
            self.catalog(self.source + [deepcopy(self.source[0])])

    def test_full_source_and_verification_objects_resolve_exactly(self):
        catalog = self.catalog()
        refs = ["O:" + item["tool"] for item in self.observations]
        resolved = resolve_catalog(catalog, refs, scope=SCOPE, run_id=RUN, catalog_ref=catalog["catalog_ref"])
        self.assertEqual(resolved, {"O:" + item["tool"]: item for item in self.observations})
        view = self.view(catalog)
        self.assertEqual(view["verification"], [["O:verification", self.verified["result"]]])
        self.assertEqual(expand_view(view)["gaps"], [["O:" + item["tool"], item["gaps"]]
                                        for item in self.observations if "gaps" in item])

    def test_source_child_catalogues_keep_exact_narrow_request_and_no_other_domain(self):
        for cls, domain in ((FinancialRequest, "financial"), (MarketRequest, "market")):
            with self.subTest(domain=domain):
                request = cls.from_parent(self.request)
                observations = [observe_tool(domain, self.outputs[domain])]
                catalog = self.catalog(observations, request)
                restored = decode_catalog(catalog, scope=SCOPE, run_id=RUN)
                self.assertEqual(restored["request"], request.to_dict())
                self.assertEqual(restored["observations"], observations)
                self.assertEqual(self.view(catalog)["catalog_ids"]["observations"], ["O:" + domain])
                with self.assertRaises(PermissionDenied):
                    self.catalog(self.source, request)

    def test_missing_data_and_nullable_evidence_remain_exactly_addressable(self):
        observations = deepcopy(self.observations)
        # An additional unused, nullable typed Evidence entry tests storage rather
        # than inventing a computed financial fact or changing a Claim input.
        evidence = deepcopy(next(iter(self.tested["evidence"].values())))
        evidence["value"] = None
        for item in observations:
            if item["kind"] == "derived":
                item["evidence"]["E999"] = evidence
        catalog = self.catalog(observations)
        view = self.view(catalog, current_stage="verification")
        self.assertIn("E:E999", view["catalog_ids"]["evidence"])
        self.assertNotIn("E:E999", {row[0] for row in view["evidence"]})
        self.assertEqual(resolve_catalog(catalog, ["E:E999"], scope=SCOPE, run_id=RUN,
                                         catalog_ref=catalog["catalog_ref"])["E:E999"]["value"], None)
        disclosed = self.view(catalog, refs=["E:E999"])
        self.assertIs(column_objects(disclosed, "evidence")["E:E999"]["value"], None)

    def test_empty_current_catalogue_no_synthetic_fact_or_evidence_added(self):
        view = self.view(self.catalog([]))
        self.assertEqual(view["facts"], [])
        self.assertEqual(view["evidence"], [])
        self.assertEqual(view["hypotheses"], [])
        self.assertEqual(view["catalog_ids"], {"claims": [], "evidence": [], "hypotheses": [], "observations": []})
        self.assertEqual(view["required_checks"], self.checks)

    def test_invalid_binding_types_and_unicode_rejected(self):
        for scope, run in (("", RUN), ("bad\nScope", RUN), ("\ud800", RUN), (SCOPE, "run"), (SCOPE, True)):
            with self.subTest(scope=repr(scope), run=run):
                with self.assertRaises(ValidationError):
                    build_catalog(self.request, [], self.checks, scope=scope, run_id=run)

    def test_wire_symbols_and_gap_table_round_trip_without_numeric_or_ref_interning(self):
        catalog = self.catalog()
        view = self.view(catalog, current_stage="verification")
        expanded = expand_view(view)
        self.assertEqual(encode_view(expanded), view)
        self.assertEqual(validate_view(view, catalog, scope=SCOPE, run_id=RUN), expanded)
        self.assertEqual(expanded["gaps"], [["O:" + item["tool"], item["gaps"]]
                                            for item in self.observations if "gaps" in item])
        self.assertLess(len(canonical_json(view).encode("utf-8")), len(canonical_json(expanded).encode("utf-8")))
        self.assertTrue(view["symbols"])
        for table in ("facts", "evidence"):
            for row in view[table]:
                self.assertIs(type(row[0]), str)
                self.assertTrue(row[2] is None or type(row[2]) is str)
        self.assertEqual(column_objects(view, "facts"), {"C:" + k: v for k, v in self.tested["facts"].items()})
        self.assertEqual(column_objects(view, "evidence"), {"E:" + k: v for k, v in self.tested["evidence"].items()})

    def test_wire_dangling_boolean_symbols_and_gap_indices_rejected(self):
        view = self.view(current_stage="verification")
        for tag in ("bool_symbol", "unknown_symbol", "bool_gap", "unknown_gap", "unused_symbol"):
            corrupted = deepcopy(view)
            if tag in {"bool_symbol", "unknown_symbol"}:
                corrupted["facts"][0][3] = {"s": True if tag == "bool_symbol" else 99999}
            elif tag in {"bool_gap", "unknown_gap"}:
                corrupted["gaps"][0][1] = [True if tag == "bool_gap" else 99999]
            else:
                corrupted["symbols"].append("zzzz_UNREGISTERED_SOURCE_INSTRUCTION")
            with self.subTest(tag=tag):
                with self.assertRaises(ValidationError):
                    expand_view(corrupted)

    def test_numeric_cells_cannot_be_aliased_and_columns_cannot_be_changed(self):
        view = self.view(current_stage="verification")
        changed = deepcopy(view); changed["facts"][0][2] = {"s": 0}
        with self.assertRaises(ValidationError):
            expand_view(changed)
        changed = deepcopy(view); changed["columns"]["facts"][2] = "free_number"
        with self.assertRaises(ValidationError):
            expand_view(changed)
        changed = deepcopy(view); changed["source_text"] = "not registered"
        with self.assertRaises(ValidationError):
            expand_view(changed)

    def test_wire_values_and_directories_must_match_authoritative_current_catalogue(self):
        catalog = self.catalog(); view = self.view(catalog, current_stage="verification")
        changed = deepcopy(view); changed["facts"][0][2] = "123456789"
        with self.assertRaises(IntegrityError):
            validate_view(changed, catalog, scope=SCOPE, run_id=RUN)
        changed = deepcopy(view); changed["catalog_ids"]["evidence"].append("E:invented")
        with self.assertRaises(IntegrityError):
            validate_view(changed, catalog, scope=SCOPE, run_id=RUN)
        with self.assertRaises(PermissionDenied):
            validate_view(view, catalog, scope=SCOPE, run_id="b" * 32)


if __name__ == "__main__":
    unittest.main()
