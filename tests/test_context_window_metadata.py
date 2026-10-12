"""Synthetic v6.1 representation checks, never live financial ground truth."""
from copy import deepcopy
import unittest

import test_context_window as window_fixtures
from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research.context_window import rebuild_window
from stock_research.research.context_window_metadata import (
    WINDOW_METADATA_SCHEMA, WINDOW_METADATA_CONTRACT, encode_window_metadata_view,
    decode_window_metadata_view, encode_window_view, decode_window_view,
)


def bytes_of(value):
    return len(canonical_json(value).encode("utf-8"))


def nodes(value):
    yield value
    if type(value) is dict:
        for child in value.values():
            yield from nodes(child)
    elif type(value) is list:
        for child in value:
            yield from nodes(child)


def tagged(value, key):
    return next(item for item in nodes(value) if type(item) is dict and set(item) == {key})


def columns(wire):
    return [[wire["symbols"][value["s"]] if type(value) is dict else value for value in record]
            for record in wire["layouts"]]


class ContextWindowMetadataTests(unittest.TestCase):
    def setUp(self):
        # Composition avoids rerunning the old v6 test class as inherited tests.
        self.fixture = window_fixtures.ContextWindowTests("test_window_is_deterministic_bound_and_within_actual_messages")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.raw, self.metadata = self.fixture.compile()
        self.wire = encode_window_metadata_view(self.raw)
        self.assertEqual(self.wire["schema"], WINDOW_METADATA_SCHEMA)

    def rejects(self, wire):
        with self.assertRaises((ValidationError, IntegrityError)):
            decode_window_metadata_view(wire)

    def test_exact_roundtrip_without_mutation_or_semantic_field_loss(self):
        raw, wire = deepcopy(self.raw), deepcopy(self.wire)
        self.assertEqual(decode_window_metadata_view(self.wire), self.raw)
        self.assertEqual(self.raw, raw)
        self.assertEqual(self.wire, wire)
        self.assertLess(bytes_of(self.wire), bytes_of(self.raw))
        self.assertEqual(encode_window_metadata_view(self.raw), self.wire)
        self.assertEqual(encode_window_view(self.raw), self.wire)
        self.assertEqual(decode_window_view(self.wire), self.raw)

    def test_descriptor_cursor_selection_content_hash_and_counts_are_identical(self):
        restored = decode_window_metadata_view(self.wire)
        self.assertEqual(restored, rebuild_window(self.fixture.catalog, self.metadata["window"],
            scope=window_fixtures.SCOPE, run_id=window_fixtures.RUN))
        for key in ("window_ref", "catalog_ref", "binding_ref", "counts", "collections", "pages",
                    "range", "state_versions", "required_checks", "verification_brief"):
            self.assertEqual(restored.get(key), self.raw.get(key))
        self.assertTrue(self.wire["symbols"])
        self.assertTrue(self.wire["list_table"])
        self.assertTrue(self.wire["layouts"])

    def test_column_records_have_full_width_and_financial_cells_remain_literal(self):
        expected_columns = ["name", "value", "unit", "window", "formula", "available_at", "inputs_ref"]
        index = columns(self.wire).index(expected_columns)
        rows = [item for item in nodes(self.wire["view"]) if type(item) is dict and set(item) == {"r", "v"}
                and item["r"] == index]
        originals = [atom[3] for page in self.raw["pages"] for atom in page["atoms"]
                     if atom[2] == "summary" and atom[0].startswith("C:")]
        self.assertEqual(len(rows), len(originals))
        self.assertEqual([row["v"][1] for row in rows], [item["value"] for item in originals])
        self.assertTrue(all(type(row["v"][1]) is str for row in rows))
        self.assertTrue(all(len(row["v"]) == len(expected_columns) for row in rows))

    def test_metadata_tables_are_unique_sorted_message_local(self):
        self.assertEqual(self.wire["symbols"], sorted(set(self.wire["symbols"])))
        identities = [canonical_json(item) for item in self.wire["list_table"]]
        self.assertEqual(identities, sorted(set(identities)))
        identities = [canonical_json(item) for item in columns(self.wire)]
        self.assertEqual(identities, sorted(set(identities)))
        for table in ("symbols", "list_table", "layouts"):
            bad = deepcopy(self.wire); bad[table].append(deepcopy(bad[table][0])); self.rejects(bad)
            bad = deepcopy(self.wire); bad[table].reverse(); self.rejects(bad)

    def test_symbol_boolean_negative_overflow_and_noninteger_indices_rejected(self):
        for value in (True, False, -1, len(self.wire["symbols"]), "0", None, []):
            bad = deepcopy(self.wire); tagged(bad["view"], "s")["s"] = value; self.rejects(bad)

    def test_list_boolean_negative_overflow_and_noninteger_indices_rejected(self):
        for value in (True, -1, len(self.wire["list_table"]), "0", None, []):
            bad = deepcopy(self.wire); tagged(bad["view"], "l")["l"] = value; self.rejects(bad)

    def test_row_boolean_negative_overflow_width_and_unknown_columns_rejected(self):
        for value in (True, -1, len(self.wire["layouts"]), "0", None, []):
            bad = deepcopy(self.wire)
            row = next(item for item in nodes(bad["view"]) if type(item) is dict and set(item) == {"r", "v"})
            row["r"] = value; self.rejects(bad)
        bad = deepcopy(self.wire)
        row = next(item for item in nodes(bad["view"]) if type(item) is dict and set(item) == {"r", "v"})
        row["v"].pop(); self.rejects(bad)
        bad = deepcopy(self.wire); bad["layouts"][0][0] = "unknown_field"; self.rejects(bad)

    def test_column_symbol_aliases_are_strict_and_financial_cell_aliasing_is_noncanonical(self):
        # Layout symbols use the same table, but never accept another table's
        # references or bool/integer coercion at this schema boundary.
        for alias in ({"s": True}, {"s": -1}, {"s": len(self.wire["symbols"])}, {"l": 0}, {"s": 0, "x": 1}):
            bad = deepcopy(self.wire); bad["layouts"][0][0] = alias; self.rejects(bad)
        bad = deepcopy(self.wire)
        index = columns(bad).index(["name", "value", "unit", "window", "formula", "available_at", "inputs_ref"])
        row = next(item for item in nodes(bad["view"]) if type(item) is dict and set(item) == {"r", "v"}
                   and item["r"] == index)
        # An attempted alias in a protected financial cell cannot become an
        # accepted encoded representation, even if a symbol is plausible text.
        row["v"][1] = {"s": 0}; self.rejects(bad)

    def test_unused_symbols_lists_layouts_and_noncanonical_literal_tags_rejected(self):
        bad = deepcopy(self.wire); bad["symbols"].append("zz_unused_exact_symbol"); bad["symbols"].sort(); self.rejects(bad)
        bad = deepcopy(self.wire); bad["list_table"].append(["unused_path"])
        bad["list_table"].sort(key=canonical_json); self.rejects(bad)
        bad = deepcopy(self.wire); bad["layouts"].append(["status", "reason", "conclusion_strength", "claim_ids_ref", "counterevidence_claim_ids_ref"])
        bad["layouts"].sort(key=canonical_json); self.rejects(bad)
        bad = deepcopy(self.wire)
        ref = tagged(bad["view"], "s"); literal = bad["symbols"][ref["s"]]
        # Replace one selected reference with the same literal.  It is exact
        # JSON but violates the one canonical representation for compact wire.
        def replace(value):
            if type(value) is dict:
                for key, child in value.items():
                    if child is ref:
                        value[key] = literal; return True
                    if replace(child): return True
            elif type(value) is list:
                for index, child in enumerate(value):
                    if child is ref:
                        value[index] = literal; return True
                    if replace(child): return True
            return False
        self.assertTrue(replace(bad["view"])); self.rejects(bad)

    def test_nested_list_cycles_mixed_alias_fields_and_unknown_wrapper_keys_rejected(self):
        bad = deepcopy(self.wire); bad["list_table"][0] = [{"l": 0}]; self.rejects(bad)
        bad = deepcopy(self.wire); tagged(bad["view"], "s")["unexpected"] = True; self.rejects(bad)
        for key in ("unexpected", "authority", "cursor_overrides"):
            bad = deepcopy(self.wire); bad[key] = {}; self.rejects(bad)
        bad = deepcopy(self.wire); bad["metadata_schema"] = "unknown/v9"; self.rejects(bad)

    def test_tampered_value_or_atom_contents_fail_original_content_hash(self):
        bad = deepcopy(self.wire)
        index = columns(bad).index(["name", "value", "unit", "window", "formula", "available_at", "inputs_ref"])
        row = next(item for item in nodes(bad["view"]) if type(item) is dict and set(item) == {"r", "v"}
                   and item["r"] == index)
        row["v"][1] = "999999.0001"
        self.rejects(bad)

    def test_zeroes_nulls_empty_collections_and_complete_object_values_remain_exact(self):
        _, metadata = self.fixture.compile()
        selected = self.fixture.select(metadata["window"], refs=["O:hypotheses"])
        raw, _ = self.fixture.compile(selection=selected, max_bytes=1_000_000)
        wire = encode_window_metadata_view(raw)
        self.assertLessEqual(bytes_of(wire), bytes_of(raw))
        self.assertEqual(decode_window_metadata_view(wire), raw)
        originals = [atom[3] for page in raw["pages"] if page["kind"] == "objects"
                     for atom in page["atoms"] if atom[2] == "v"]
        for literal in originals:
            # Full object scalar values must appear literally; their JSON path,
            # kind and catalogue ref may share metadata aliases independently.
            self.assertIn(literal, list(nodes(wire)))
        self.assertIs(raw["causal_claim"], False)
        self.assertEqual(raw["state_versions"], decode_window_metadata_view(wire)["state_versions"])

    def test_unicode_exact_metadata_works_without_byte_or_order_loss(self):
        raw = deepcopy(self.raw)
        raw["range"]["objective"] = "SYNTHETIC 中文元数据、精确顺序！"
        for page in raw["pages"]:
            for atom in page["atoms"]:
                if atom[2] == "summary" and atom[0].startswith("C:"):
                    atom[3]["name"] = "中文重复精确字段"
            page["content_hash"] = digest(page["atoms"])
        wire = encode_window_metadata_view(raw)
        self.assertLessEqual(bytes_of(wire), bytes_of(raw))
        self.assertEqual(decode_window_metadata_view(wire), raw)

    def test_literal_v1_fallback_is_supported_and_never_grows_view(self):
        empty = self.fixture.make_catalog([])
        revisions = {"source": "1" * 64, "calculated": None, "hypotheses": None, "verified": None}
        from stock_research.research.context_window import compile_window
        raw, _ = compile_window(empty, scope=window_fixtures.SCOPE, run_id=window_fixtures.RUN,
            stage="before_sources", execution_revisions=revisions, verification_ready=False,
            render=self.fixture.render, read_enabled=False)
        wire = encode_window_metadata_view(raw)
        self.assertLessEqual(bytes_of(wire), bytes_of(raw))
        self.assertEqual(decode_window_metadata_view(wire), raw)
        self.assertEqual(decode_window_metadata_view(raw), raw)
        # A tiny legal decoder view pays for no wrapper or sharing table.
        raw["range"]["bound_windows"] = {}; raw["range"]["bindings"] = {}
        raw["range"]["declared_hypotheses"] = []; raw["required_checks"] = []
        raw["state_versions"] = {"digests": [], "refs": {"source": None, "calculated": None, "hypotheses": None, "verified": None}}
        wire = encode_window_metadata_view(raw)
        self.assertEqual(wire, raw)
        self.assertEqual(decode_window_metadata_view(wire), raw)

    def test_compiler_header_mode_only_and_no_header_accepted_as_paid_view(self):
        empty = self.fixture.make_catalog([])
        from stock_research.research.context_window import compile_window
        headers = []
        def render(raw):
            wire = encode_window_metadata_view(raw, header_mode="window_ref" not in raw)
            if "window_ref" not in raw:
                headers.append(wire)
            return self.fixture.render(wire)
        raw, _ = compile_window(empty, scope=window_fixtures.SCOPE, run_id=window_fixtures.RUN,
            stage="before_sources", execution_revisions={"source": "1" * 64, "calculated": None,
                "hypotheses": None, "verified": None}, verification_ready=False, render=render)
        self.assertTrue(headers)
        for wire in headers:
            self.rejects(wire)
        self.assertEqual(decode_window_metadata_view(encode_window_metadata_view(raw)), raw)
        header = deepcopy(raw); header.pop("window_ref")
        with self.assertRaises(ValidationError):
            encode_window_metadata_view(header)
        bad = deepcopy(self.raw); bad.pop("window_ref")
        with self.assertRaises(ValidationError):
            encode_window_metadata_view(bad, header_mode=True)

    def test_unknown_raw_fields_nested_reference_fields_and_invalid_values_rejected(self):
        for mutate in (
            lambda raw: raw.update(unexpected=True),
            lambda raw: raw["range"].update(unexpected=True),
            lambda raw: raw["observations"][0]["gaps_ref"].update(unexpected=True),
            lambda raw: raw["collections"]["facts"].update(unexpected=True),
            lambda raw: raw["counts"].update(claims=True),
        ):
            raw = deepcopy(self.raw); mutate(raw)
            with self.assertRaises(ValidationError):
                encode_window_metadata_view(raw)
            self.rejects(raw)

    def test_missing_tables_bad_json_types_cycles_and_cross_table_indices_rejected(self):
        for key in ("symbols", "list_table", "layouts", "view"):
            bad = deepcopy(self.wire); bad.pop(key); self.rejects(bad)
        bad = deepcopy(self.wire); bad["symbols"].append(1.25); self.rejects(bad)
        bad = deepcopy(self.wire); bad["symbols"].append("\ud800"); self.rejects(bad)
        bad = deepcopy(self.wire); bad["list_table"].append(bad); self.rejects(bad)
        bad = deepcopy(self.wire); tagged(bad["view"], "s")["s"] = {"l": 0}; self.rejects(bad)


if __name__ == "__main__":
    unittest.main()
