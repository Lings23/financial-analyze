"""Synthetic exact paging mechanisms; these tests do not establish financial truth."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research.context_window import (
    ContextMinimumViewExceeded, compile_window, coverage_progress, expand_window_view,
    merge_coverage, rebuild_selection, rebuild_window, restore_object_atoms,
    select_next, validate_window_descriptor,
)
from stock_research.research.dynamic_context import build_catalog, resolve_catalog
from stock_research.research.dynamic_contracts import DynamicRequest, required_checks
from stock_research.research.dynamic_protocol import observe_tool
from stock_research.research.study import StudyRuntime
from stock_research.research.tools import read_domain


SCOPE = "SYNTHETIC/context-window-owner"
RUN = "c" * 32
REVISIONS = {"source": "1" * 64, "calculated": "1" * 64,
             "hypotheses": "1" * 64, "verified": None}


class ContextWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: exact pages preserve all authorized original objects",
        })
        self.outputs = {name: read_domain(self.f.service, self.request, self.f.access, name)
                        for name in ("financial", "market")}
        datasets = {key: value for output in self.outputs.values() for key, value in output.items()}
        computed = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, self.request)
        self.observations = [observe_tool(name, self.outputs[name]) for name in ("financial", "market")]
        self.observations.append(observe_tool("hypotheses", computed))
        self.catalog = self.make_catalog(self.observations)

    def make_catalog(self, observations):
        return build_catalog(self.request, observations, required_checks(self.request), scope=SCOPE, run_id=RUN)

    def render(self, view, padding=""):
        return [{"role": "system", "content": "SYNTHETIC exact page protocol"},
                {"role": "user", "content": canonical_json({"question": self.request.question,
                    "plan": ["检查当前确切片段"], "padding": padding, "context": view})}]

    def compile(self, catalog=None, **kwargs):
        return compile_window(catalog or self.catalog, scope=SCOPE, run_id=RUN,
            stage="verification", execution_revisions=REVISIONS, verification_ready=True,
            render=self.render, **kwargs)

    def action(self, catalog, **kwargs):
        return {"action": "context_read", "catalog_ref": catalog["catalog_ref"],
                "plan": ["读取已绑定的确切对象"], **kwargs}

    def select(self, window, catalog=None, **kwargs):
        catalog = catalog or self.catalog
        return select_next(catalog, self.action(catalog, **kwargs), window, scope=SCOPE, run_id=RUN)

    def test_window_is_deterministic_bound_and_within_actual_messages(self):
        original = deepcopy(self.catalog)
        view, metadata = self.compile()
        self.assertEqual((view, metadata), self.compile())
        self.assertEqual(self.catalog, original)
        self.assertLessEqual(sum(len(item["content"].encode("utf-8")) for item in self.render(view)), 12000)
        self.assertEqual(rebuild_window(self.catalog, metadata["window"], scope=SCOPE, run_id=RUN), view)
        self.assertEqual(validate_window_descriptor(self.catalog, metadata["window"], scope=SCOPE, run_id=RUN),
                         metadata["window"])
        self.assertEqual(expand_window_view(view)["state_versions"], REVISIONS)
        self.assertFalse(view["causal_claim"])
        self.assertEqual(view["coverage"], "not_verified")

    def test_claim_scalars_retained_and_inputs_exact_entry(self):
        view, metadata = self.compile()
        facts = [atom for page in view["pages"] if page["kind"] == "facts" for atom in page["atoms"]]
        for ref, path, kind, synopsis in facts:
            original = resolve_catalog(self.catalog, [ref], scope=SCOPE, run_id=RUN,
                                       catalog_ref=self.catalog["catalog_ref"])[ref]
            self.assertEqual({key: value for key, value in synopsis.items() if key != "inputs_ref"},
                             {key: value for key, value in original.items() if key != "evidence_ids"})
            self.assertEqual(synopsis["inputs_ref"], {"object_ref": ref, "path": ["evidence_ids"],
                "count": len(original["evidence_ids"]), "content_hash": digest(original["evidence_ids"])})
        self.assertTrue(facts)

    def test_directory_larger_than_window_does_not_send_full_known_ids(self):
        observations = deepcopy(self.observations)
        derived = observations[-1]
        original = deepcopy(next(iter(derived["evidence"].values())))
        derived["evidence"].update({"E" + str(index): deepcopy(original) for index in range(100, 1200)})
        catalog = self.make_catalog(observations)
        view, metadata = self.compile(catalog)
        directory = next(page for page in view["pages"] if page["kind"] == "directory")
        self.assertGreater(directory["total"], directory["end"])
        self.assertTrue(directory["has_more"])
        self.assertNotIn("E:E1199", metadata["window"]["allowed_refs"])
        with self.assertRaises(ValidationError):
            self.select(metadata["window"], catalog, refs=["E:E1199"])
        selection = self.select(metadata["window"], catalog, cursor=directory["next_cursor"])
        self.assertEqual(selection["start"], directory["end"])

    def test_claim_long_inputs_traverse_three_replacements_and_restore_exact_object(self):
        observations = deepcopy(self.observations)
        claim = observations[-1]["facts"]["F1"]
        claim["evidence_ids"] = [next(iter(observations[-1]["evidence"]))] * 1500
        catalog = self.make_catalog(observations)
        view, metadata = self.compile(catalog)
        pending = self.select(metadata["window"], catalog, refs=["C:F1"])
        atoms, windows = [], []
        while True:
            view, metadata = self.compile(catalog, selection=pending)
            windows.append(metadata["window"]["window_ref"])
            selection = metadata["window_selection"]
            page = rebuild_selection(catalog, selection, scope=SCOPE, run_id=RUN)
            atoms.extend(page["atoms"])
            self.assertEqual(page["atoms"], view["pages"][0]["atoms"])
            if not page["has_more"]:
                break
            pending = self.select(metadata["window"], catalog, cursor=view["pages"][0]["next_cursor"])
            self.assertLess(len(windows), 100)
        self.assertGreaterEqual(len(windows), 3)
        self.assertEqual(len(set(windows)), len(windows))
        self.assertEqual(restore_object_atoms(atoms), resolve_catalog(catalog, ["C:F1"],
            scope=SCOPE, run_id=RUN, catalog_ref=catalog["catalog_ref"]))

    def test_period_collection_traversal_matches_source_list_order(self):
        observations = deepcopy(self.observations)
        source = observations[0]
        dataset = next(iter(source["datasets"]))
        item = source["datasets"][dataset]
        item["periods"] = [item["periods"][0]] * 1000
        item["records"] = 1000
        catalog = self.make_catalog(observations)
        view, metadata = self.compile(catalog)
        pending = self.select(metadata["window"], catalog, cursor=view["collections"]["periods"]["cursor"])
        seen = []
        for _ in range(100):
            view, metadata = self.compile(catalog, selection=pending)
            page = view["pages"][0]
            seen.extend(atom[3] for atom in page["atoms"] if atom[0] == "O:" + source["tool"]
                        and atom[1][:-1] == ["datasets", dataset, "periods"] and atom[2] == "v")
            if not page["has_more"]:
                break
            pending = self.select(metadata["window"], catalog, cursor=page["next_cursor"])
        else:
            self.fail("bounded period traversal did not terminate")
        self.assertEqual(seen, item["periods"])

    def test_current_paid_window_only_cursors_and_scope_run_catalog_binding(self):
        view, metadata = self.compile()
        window = metadata["window"]
        with self.assertRaises(ValidationError):
            self.select(window, cursor="f" * 64)
        for args in ({"scope": "OTHER/owner", "run_id": RUN}, {"scope": SCOPE, "run_id": "d" * 32}):
            with self.assertRaises(PermissionDenied):
                validate_window_descriptor(self.catalog, window, **args)
        selection = self.select(window, refs=["C:F1"])
        newer_view, newer = self.compile(selection=selection)
        token = view["collections"]["periods"]["cursor"]
        with self.assertRaises(ValidationError):
            self.select(newer["window"], cursor=token)
        observations = deepcopy(self.observations)
        observations[-1]["facts"]["F1"]["value"] = "999.00"
        changed = self.make_catalog(observations)
        with self.assertRaises(PermissionDenied):
            rebuild_window(changed, window, scope=SCOPE, run_id=RUN)
        with self.assertRaises(PermissionDenied):
            self.compile(changed, selection=selection)

    def test_same_catalog_different_paid_control_invalidates_all_old_cursors(self):
        _, original = self.compile()
        tokens = set(original["window"]["allowed_cursors"])
        self.assertTrue(tokens)
        for label in ("decision=8", "plan=重新检查", "remaining_tools=2", "error=invalid_action"):
            view, changed = compile_window(self.catalog, scope=SCOPE, run_id=RUN,
                stage="verification", execution_revisions=REVISIONS, verification_ready=True,
                render=lambda value: self.render(value, label))
            self.assertNotEqual(changed["window"]["dispatch_ref"], original["window"]["dispatch_ref"])
            self.assertFalse(tokens & set(changed["window"]["allowed_cursors"]))
            for token in tokens:
                with self.assertRaises(ValidationError):
                    self.select(changed["window"], cursor=token)
            with self.assertRaises(IntegrityError):
                rebuild_window(self.catalog, changed["window"], scope=SCOPE, run_id=RUN, render=self.render)
            self.assertEqual(rebuild_window(self.catalog, changed["window"], scope=SCOPE, run_id=RUN,
                render=lambda value: self.render(value, label)), view)

    def test_descriptor_tampering_of_members_ranges_cursors_or_revisions_rejected(self):
        _, metadata = self.compile()
        mutations = []
        bad = deepcopy(metadata["window"]); bad["allowed_refs"].append("E:GUESS"); mutations.append(bad)
        bad = deepcopy(metadata["window"]); bad["pages"][0]["selection"]["end"] = 1; mutations.append(bad)
        bad = deepcopy(metadata["window"]); bad["pages"][0]["content_hash"] = "2" * 64; mutations.append(bad)
        bad = deepcopy(metadata["window"]); bad["window_ref"] = "2" * 64; mutations.append(bad)
        bad = deepcopy(metadata["window"]); bad["execution_revisions"]["calculated"] = "2" * 64; mutations.append(bad)
        bad = deepcopy(metadata["window"]); token = bad["allowed_cursors"][0]; bad["cursors"][token]["start"] += 1; mutations.append(bad)
        for bad in mutations:
            with self.subTest(kind=bad):
                with self.assertRaises((IntegrityError, ValidationError)):
                    rebuild_window(self.catalog, bad, scope=SCOPE, run_id=RUN)

    def test_committed_end_cannot_shrink_when_control_header_grows(self):
        _, metadata = self.compile()
        pending = self.select(metadata["window"], refs=["O:hypotheses"])
        _, committed = self.compile(selection=pending)
        selection = committed["window_selection"]
        with self.assertRaises(ContextMinimumViewExceeded):
            compile_window(self.catalog, scope=SCOPE, run_id=RUN, stage="verification",
                execution_revisions=REVISIONS, verification_ready=True, selection=selection,
                render=lambda view: self.render(view, "膨胀" * 1200))
        self.assertEqual(selection, committed["window_selection"])

    def test_exact_12000_and_12001_actual_header_boundary(self):
        empty = self.make_catalog([])
        revisions = {"source": "1" * 64, "calculated": None, "hypotheses": None, "verified": None}
        options = {"scope": SCOPE, "run_id": RUN, "stage": "before_sources", "execution_revisions": revisions,
                   "verification_ready": False, "read_enabled": False}
        view, metadata = compile_window(empty, render=self.render, **options)
        padding = "x" * (12000 - metadata["bytes"])
        view, metadata = compile_window(empty, render=lambda value: self.render(value, padding), **options)
        self.assertEqual(metadata["bytes"], 12000)
        with self.assertRaises(ContextMinimumViewExceeded):
            compile_window(empty, render=lambda value: self.render(value, padding + "x"), **options)

    def test_headroom_disables_all_issued_read_entries_without_changing_checks(self):
        view, metadata = self.compile(read_enabled=False)
        self.assertEqual(metadata["window"]["allowed_refs"], [])
        self.assertEqual(metadata["window"]["allowed_cursors"], [])
        self.assertEqual(metadata["window"]["cursors"], {})
        self.assertEqual(view["required_checks"], required_checks(self.request))
        with self.assertRaises(ValidationError):
            self.select(metadata["window"], refs=["C:F1"])

    def test_member_coverage_reordered_combined_pages_do_not_create_progress(self):
        _, metadata = self.compile()
        known = [ref for ref in metadata["window"]["allowed_refs"] if ref.startswith("C:")][:2]
        coverage = []
        for ref in known:
            _, result = self.compile(selection=self.select(metadata["window"], refs=[ref]))
            selection = result["window_selection"]
            self.assertTrue(coverage_progress(self.catalog, selection, coverage, scope=SCOPE, run_id=RUN))
            coverage = merge_coverage(self.catalog, selection, coverage, scope=SCOPE, run_id=RUN)
        pending = self.select(metadata["window"], refs=list(reversed(known)))
        _, result = self.compile(selection=pending)
        self.assertFalse(coverage_progress(self.catalog, result["window_selection"], coverage, scope=SCOPE, run_id=RUN))
        self.assertEqual(merge_coverage(self.catalog, result["window_selection"], coverage, scope=SCOPE, run_id=RUN), coverage)

    def test_observation_nested_claim_coverage_matches_direct_claim_members(self):
        _, metadata = self.compile()
        _, direct = self.compile(selection=self.select(metadata["window"], refs=["C:F1"]))
        coverage = merge_coverage(self.catalog, direct["window_selection"], [], scope=SCOPE, run_id=RUN)
        _, observation = self.compile(selection=self.select(metadata["window"], refs=["O:hypotheses"]), max_bytes=1_000_000)
        page = rebuild_selection(self.catalog, observation["window_selection"], scope=SCOPE, run_id=RUN)
        paths = [index for index, atom in enumerate(page["atoms"])
                 if len(atom[1]) >= 2 and atom[1][:2] == ["facts", "F1"]]
        selection = {**observation["window_selection"], "start": min(paths), "end": max(paths) + 1}
        self.assertFalse(coverage_progress(self.catalog, selection, coverage, scope=SCOPE, run_id=RUN))
        self.assertEqual(observation["visible_fact_count"], len(self.observations[-1]["facts"]))
        self.assertEqual(observation["visible_evidence_count"], len(self.observations[-1]["evidence"]))

    def test_decoder_rejects_deleted_reordered_duplicate_and_orphan_atoms(self):
        _, metadata = self.compile()
        _, result = self.compile(selection=self.select(metadata["window"], refs=["C:F1"]))
        atoms = rebuild_selection(self.catalog, result["window_selection"], scope=SCOPE, run_id=RUN)["atoms"]
        for bad in (atoms[1:], atoms[:-1], list(reversed(atoms)), [*atoms, atoms[-1]],
                    [*atoms, ["C:F1", ["orphan", "child"], "v", "unknown"]]):
            with self.assertRaises((ValidationError, IntegrityError)):
                restore_object_atoms(bad)

    def test_complete_evidence_hypothesis_and_observation_streams_restore_originals(self):
        _, metadata = self.compile()
        for ref in ("O:financial", "O:market", "O:hypotheses", "H:financial_deterioration"):
            pending = self.select(metadata["window"], refs=[ref])
            _, result = self.compile(selection=pending, max_bytes=1_000_000)
            page = rebuild_selection(self.catalog, result["window_selection"], scope=SCOPE, run_id=RUN)
            self.assertFalse(page["has_more"])
            self.assertEqual(restore_object_atoms(page["atoms"]), resolve_catalog(self.catalog, [ref],
                scope=SCOPE, run_id=RUN, catalog_ref=self.catalog["catalog_ref"]))
        # A complete Observation exposes exact E aliases without guessing.
        _, observation = self.compile(selection=self.select(metadata["window"], refs=["O:hypotheses"]), max_bytes=1_000_000)
        ref = next(ref for ref in observation["window"]["allowed_refs"] if ref.startswith("E:"))
        _, evidence = self.compile(selection=self.select(observation["window"], refs=[ref]))
        page = rebuild_selection(self.catalog, evidence["window_selection"], scope=SCOPE, run_id=RUN)
        self.assertEqual(restore_object_atoms(page["atoms"]), resolve_catalog(self.catalog, [ref],
            scope=SCOPE, run_id=RUN, catalog_ref=self.catalog["catalog_ref"]))

    def test_window_decoder_rejects_unknown_keys_bad_ranges_deleted_or_changed_atoms(self):
        view, _ = self.compile()
        mutations = []
        bad = deepcopy(view); bad["unexpected"] = True; mutations.append(bad)
        bad = deepcopy(view); bad["pages"][0]["start"] = True; mutations.append(bad)
        bad = deepcopy(view); bad["pages"][0]["atoms"].pop(); mutations.append(bad)
        bad = deepcopy(view); bad["pages"][0]["atoms"][0][3] = "changed"; mutations.append(bad)
        for bad in mutations:
            with self.assertRaises((ValidationError, IntegrityError)):
                expand_window_view(bad)

    def test_scalar_is_not_split_and_minimum_scalar_failure_is_bounded(self):
        observations = deepcopy(self.observations)
        observations[-1]["facts"]["F1"]["value"] = "1" * 13000
        catalog = self.make_catalog(observations)
        with self.assertRaises(ContextMinimumViewExceeded):
            self.compile(catalog)

    def test_cancellation_callback_raises_during_compilation(self):
        calls = []
        def check():
            calls.append(1)
            if len(calls) == 3:
                raise TimeoutError("SYNTHETIC cancelled compilation")
        _, metadata = self.compile()
        pending = self.select(metadata["window"], refs=["O:hypotheses"])
        with self.assertRaises(TimeoutError):
            self.compile(selection=pending, check=check)
        self.assertEqual(len(calls), 3)

    def test_ref_limit_unknown_selection_boolean_offsets_and_action_shape_rejected(self):
        _, metadata = self.compile()
        for kwargs in ({"refs": ["C:F1", "C:F1"]}, {"refs": []}, {"refs": ["C:unissued"]},
                       {"refs": ["C:F1"], "cursor": "0" * 64}, {"cursor": True}):
            with self.assertRaises(ValidationError):
                self.select(metadata["window"], **kwargs)
        selected = self.select(metadata["window"], refs=["C:F1"])
        for key in ("start", "end"):
            bad = {**selected, key: True}
            with self.assertRaises(ValidationError):
                self.compile(selection=bad)


if __name__ == "__main__":
    unittest.main()
