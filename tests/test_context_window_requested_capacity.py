"""Synthetic requested-page capacity checks, never financial ground truth."""
from copy import deepcopy
import unittest

import test_context_window as fixtures
from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import canonical_json
from stock_research.research.context_window import (
    ContextMinimumViewExceeded, _assemble, _base_view, _collection, _prepared, _selection,
    compile_window, rebuild_selection, rebuild_window, restore_object_atoms, select_next,
)
from stock_research.research.context_window_metadata import (
    decode_window_metadata_view, encode_window_metadata_view,
)
from stock_research.research.dynamic_context import resolve_catalog


def message_bytes(messages):
    return sum(len(message["content"].encode("utf-8")) for message in messages)


class ContextWindowRequestedCapacityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContextWindowTests("test_window_is_deterministic_bound_and_within_actual_messages")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        observations = deepcopy(self.f.observations)
        fact = deepcopy(next(iter(observations[-1]["facts"].values())))
        observations[-1]["facts"] = {
            "F" + str(index): {**deepcopy(fact), "value": str(index)} for index in range(1, 41)
        }
        self.catalog = self.f.make_catalog(observations)

    def actual(self, view, padding=""):
        wire = encode_window_metadata_view(view, header_mode="window_ref" not in view)
        return self.f.render(wire, padding)

    def compile(self, catalog=None, **kwargs):
        options = dict(scope=fixtures.SCOPE, run_id=fixtures.RUN, stage="verification",
            execution_revisions=fixtures.REVISIONS, verification_ready=True,
            render=self.actual, admission_render=self.f.render)
        options.update(kwargs)
        return compile_window(self.catalog if catalog is None else catalog, **options)

    def select(self, metadata, catalog=None, **kwargs):
        catalog = self.catalog if catalog is None else catalog
        return select_next(catalog, {"action": "context_read", "catalog_ref": catalog["catalog_ref"],
            "plan": ["SYNTHETIC: inspect only the current exact requested page"], **kwargs},
            metadata["window"], scope=fixtures.SCOPE, run_id=fixtures.RUN)

    def facts_selection(self):
        view, metadata = self.compile()
        page = next(page for page in view["pages"] if page["kind"] == "facts")
        self.assertTrue(page["has_more"])
        return self.select(metadata, cursor=page["next_cursor"])

    def selected_frame(self, view, metadata):
        base, collections = _base_view(self.catalog, _prepared(self.catalog, fixtures.SCOPE, fixtures.RUN),
            scope=fixtures.SCOPE, run_id=fixtures.RUN, stage="verification",
            revisions=fixtures.REVISIONS, verification_ready=True)
        frame, _ = _assemble(self.catalog, base, view["pages"][:1], collections,
            scope=fixtures.SCOPE, run_id=fixtures.RUN, revisions=fixtures.REVISIONS,
            verification_ready=True, read_enabled=True, dispatch_ref=metadata["window"]["dispatch_ref"])
        return frame

    def test_policy_is_explicit_and_strict(self):
        for invalid in (False, True, 0, 1, "encoded", {}, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.compile(requested_capacity=invalid)

    def test_no_selection_preserves_both_legacy_rendering_paths(self):
        for render, admission in ((self.f.render, None), (self.actual, self.f.render)):
            with self.subTest(encoded=admission is not None):
                original = self.compile(render=render, admission_render=admission)
                self.assertEqual(original, self.compile(render=render, admission_render=admission,
                    requested_capacity=None))
                self.assertEqual(original, self.compile(render=render, admission_render=admission,
                    requested_capacity="actual"))
                view, metadata = original
                self.assertEqual(view, rebuild_window(self.catalog, metadata["window"],
                    scope=fixtures.SCOPE, run_id=fixtures.RUN, render=render))

    def test_default_selected_capacity_retains_legacy_boundaries(self):
        selection = self.facts_selection()
        for render, admission in ((self.f.render, None), (self.actual, self.f.render)):
            with self.subTest(encoded=admission is not None):
                original = self.compile(selection=selection, render=render, admission_render=admission)
                self.assertEqual(original, self.compile(selection=selection, render=render,
                    admission_render=admission, requested_capacity=None))
                self.assertLess(original[0]["pages"][0]["end"], original[0]["pages"][0]["total"])

    def test_requested_facts_use_saved_capacity_and_preserve_every_cell(self):
        selection = self.facts_selection()
        old_view, _ = self.compile(selection=selection)
        view, metadata = self.compile(selection=selection, requested_capacity="actual")
        requested = view["pages"][0]
        self.assertGreater(requested["end"], old_view["pages"][0]["end"])
        self.assertEqual(requested["end"], requested["total"])
        self.assertFalse(requested["has_more"])
        page = rebuild_selection(self.catalog, metadata["window_selection"],
            scope=fixtures.SCOPE, run_id=fixtures.RUN)
        self.assertEqual(page["atoms"], requested["atoms"])
        self.assertEqual(metadata["bytes"], message_bytes(self.actual(view)))
        self.assertLessEqual(metadata["bytes"], 12000)
        self.assertEqual(decode_window_metadata_view(encode_window_metadata_view(view)), view)
        objects = _prepared(self.catalog, fixtures.SCOPE, fixtures.RUN)[2]
        for ref, _, _, synopsis in requested["atoms"]:
            self.assertEqual({key: value for key, value in synopsis.items() if key != "inputs_ref"},
                {key: value for key, value in objects[ref].items() if key != "evidence_ids"})

    def test_requested_object_completes_exact_inputs_without_changing_scalar_values(self):
        observations = deepcopy(self.f.observations)
        claim = observations[-1]["facts"]["F1"]
        claim["evidence_ids"] = [claim["evidence_ids"][0]] * 180
        catalog = self.f.make_catalog(observations)
        _, issued = self.compile(catalog)
        selection = self.select(issued, catalog, refs=["C:F1"])
        old_view, _ = self.compile(catalog, selection=selection)
        view, metadata = self.compile(catalog, selection=selection, requested_capacity="actual")
        self.assertTrue(old_view["pages"][0]["has_more"])
        self.assertFalse(view["pages"][0]["has_more"])
        self.assertEqual(restore_object_atoms(view["pages"][0]["atoms"]), resolve_catalog(catalog,
            ["C:F1"], scope=fixtures.SCOPE, run_id=fixtures.RUN, catalog_ref=catalog["catalog_ref"]))
        self.assertEqual(view, rebuild_window(catalog, metadata["window"],
            scope=fixtures.SCOPE, run_id=fixtures.RUN, render=self.actual))
        self.assertLessEqual(metadata["bytes"], 12000)

    def test_automatic_previews_keep_legacy_increment_and_cannot_shrink_request(self):
        selection = self.facts_selection()
        view, metadata = self.compile(selection=selection, requested_capacity="actual")
        filled, filled_metadata = self.compile(selection=selection, requested_capacity="actual",
            admission_render=None)
        self.assertEqual(view["pages"][0]["selection"], filled["pages"][0]["selection"])
        self.assertEqual(metadata["window_selection"], filled_metadata["window_selection"])
        directory = next(page for page in view["pages"] if page["kind"] == "directory")
        filled_directory = next(page for page in filled["pages"] if page["kind"] == "directory")
        self.assertLess(directory["end"], filled_directory["end"])
        selected = self.selected_frame(view, metadata)
        admitted = max(message_bytes(self.actual(view)), message_bytes(self.actual(selected))
            + max(0, message_bytes(self.f.render(view)) - message_bytes(self.f.render(selected))))
        self.assertLessEqual(admitted, 12000)
        self.assertGreater(message_bytes(self.f.render(view)), 12000)

    def test_requested_page_can_fit_when_only_legacy_header_exceeds_cap(self):
        selection = self.facts_selection()
        legacy = lambda view: self.f.render(view, "SYNTHETIC legacy representation overhead" * 400)
        with self.assertRaises(ContextMinimumViewExceeded):
            self.compile(selection=selection, admission_render=legacy)
        view, metadata = self.compile(selection=selection, admission_render=legacy, requested_capacity="actual")
        self.assertFalse(view["pages"][0]["has_more"])
        self.assertLessEqual(metadata["bytes"], 12000)

    def test_committed_boundary_is_immutable_at_12000_and_fails_at_12001(self):
        view, metadata = self.compile(selection=self.facts_selection(), requested_capacity="actual")
        selection = deepcopy(metadata["window_selection"])
        selected = self.selected_frame(view, metadata)
        padding = "x" * (12000 - message_bytes(self.actual(selected)))
        exact, result = self.compile(selection=selection, requested_capacity="actual",
            render=lambda value: self.actual(value, padding))
        self.assertEqual(result["bytes"], 12000)
        self.assertEqual(exact["pages"][0]["selection"], selection)
        with self.assertRaises(ContextMinimumViewExceeded):
            self.compile(selection=selection, requested_capacity="actual",
                render=lambda value: self.actual(value, padding + "x"))
        self.assertEqual(selection, metadata["window_selection"])

    def test_indivisible_requested_scalar_failure_stops_within_fixed_probe_count(self):
        observations = deepcopy(self.f.observations)
        observations[-1]["facts"]["F1"]["value"] = "1" * 13000
        catalog = self.f.make_catalog(observations)
        prepared = _prepared(catalog, fixtures.SCOPE, fixtures.RUN)
        pending = _selection(catalog, _collection(catalog, prepared, "facts"))
        probes = []
        def render(view):
            probes.append(1)
            return self.actual(view)
        with self.assertRaises(ContextMinimumViewExceeded):
            self.compile(catalog, selection=pending, requested_capacity="actual", render=render)
        self.assertLessEqual(len(probes), 4)

    def test_cancellation_and_invalid_render_are_not_capacity_fallbacks(self):
        selection = self.facts_selection()
        calls = []
        def check():
            calls.append(1)
            if len(calls) == 3:
                raise TimeoutError("SYNTHETIC cancelled requested capacity compile")
        with self.assertRaises(TimeoutError):
            self.compile(selection=selection, requested_capacity="actual", check=check)
        self.assertEqual(len(calls), 3)
        with self.assertRaises(ValidationError):
            self.compile(selection=selection, requested_capacity="actual", admission_render=lambda view: {})

    def test_dispatch_and_current_window_cursor_binding_remain_exact(self):
        selection = self.facts_selection()
        view, metadata = self.compile(selection=selection, requested_capacity="actual")
        tokens = set(metadata["window"]["allowed_cursors"])
        self.assertTrue(tokens)
        _, changed = self.compile(selection=selection, requested_capacity="actual",
            render=lambda value: self.actual(value, "SYNTHETIC next paid decision"))
        self.assertNotEqual(metadata["window"]["dispatch_ref"], changed["window"]["dispatch_ref"])
        self.assertFalse(tokens & set(changed["window"]["allowed_cursors"]))
        for token in tokens:
            with self.assertRaises(ValidationError):
                self.select(changed, cursor=token)
        with self.assertRaises(IntegrityError):
            rebuild_window(self.catalog, metadata["window"], scope=fixtures.SCOPE, run_id=fixtures.RUN,
                render=lambda value: self.actual(value, "SYNTHETIC next paid decision"))
        self.assertEqual(canonical_json(view), canonical_json(rebuild_window(self.catalog, metadata["window"],
            scope=fixtures.SCOPE, run_id=fixtures.RUN, render=self.actual)))


if __name__ == "__main__":
    unittest.main()
