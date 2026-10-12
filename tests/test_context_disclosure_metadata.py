"""Synthetic v5 revision-codec mechanisms; never financial/provider truth."""
from copy import deepcopy
import json
import unittest

import test_phase6_context as legacy_fixture
from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research.dynamic_context_metadata import (
    METADATA_VIEW_SCHEMA, decode_metadata_view, decode_state_versions,
    encode_metadata_view, encode_state_versions,
)


SLOTS = ("source", "calculated", "hypotheses", "verified")


class ContextDisclosureRevisionMetadataTests(unittest.TestCase):
    def revisions(self, **changes):
        return {"source": digest({}), "calculated": None, "hypotheses": None,
                "verified": None, **changes}

    def test_all_revision_phases_round_trip_without_mutation(self):
        source, changed = digest({}), digest({"SYNTHETIC": "changed source"})
        states = [self.revisions(),
                  self.revisions(calculated=source),
                  self.revisions(calculated=source, hypotheses=source),
                  self.revisions(calculated=source, hypotheses=source, verified=source),
                  self.revisions(source=changed, calculated=source, hypotheses=source, verified=source),
                  {slot: None for slot in SLOTS}]
        for revisions in states:
            with self.subTest(revisions=revisions):
                before = deepcopy(revisions)
                wire = encode_state_versions(revisions)
                self.assertEqual(decode_state_versions(wire), revisions)
                self.assertEqual(decode_state_versions(wire, revisions), revisions)
                self.assertEqual(wire, encode_state_versions(dict(reversed(list(revisions.items())))))
                self.assertEqual(revisions, before)

    def test_exact_empty_source_digest_is_not_read_completion_or_null(self):
        wire = encode_state_versions(self.revisions())
        self.assertEqual(wire, {"digests": [digest({})], "refs": {
            "source": {"h": 0}, "calculated": None, "hypotheses": None, "verified": None}})
        self.assertEqual(decode_state_versions(wire)["source"], digest({}))
        self.assertEqual(len(wire["digests"][0]), 64)

    def test_equal_full_digests_are_interned_once_and_nulls_stay_null(self):
        value = digest({"SYNTHETIC": "current"})
        revisions = self.revisions(source=value, calculated=value, hypotheses=value)
        wire = encode_state_versions(revisions)
        self.assertEqual(wire["digests"], [value])
        self.assertEqual([wire["refs"][slot] for slot in SLOTS],
                         [{"h": 0}, {"h": 0}, {"h": 0}, None])
        self.assertLess(len(canonical_json(wire).encode()), len(canonical_json(revisions).encode()))

    def test_distinct_digests_are_sorted_and_indices_are_message_local(self):
        revisions = {slot: character * 64 for slot, character in zip(SLOTS, "dcba")}
        wire = encode_state_versions(revisions)
        self.assertEqual(wire["digests"], [character * 64 for character in "abcd"])
        self.assertEqual([wire["refs"][slot]["h"] for slot in SLOTS], [3, 2, 1, 0])
        second = encode_state_versions({slot: "f" * 64 for slot in SLOTS})
        self.assertEqual(decode_state_versions(second), {slot: "f" * 64 for slot in SLOTS})
        self.assertNotEqual(decode_state_versions(wire), decode_state_versions(second))

    def test_malformed_authoritative_encode_input_raises_typed_validation(self):
        for revisions in (None, [], {}, {"source": digest({})},
                          self.revisions(extra="forbidden"), self.revisions(source="A" * 64),
                          self.revisions(source=True), self.revisions(calculated="a" * 63)):
            with self.subTest(revisions=revisions), self.assertRaises(ValidationError):
                encode_state_versions(revisions)

    def test_bad_table_or_slot_shapes_and_extra_keys_are_rejected(self):
        original = encode_state_versions(self.revisions())
        invalid = [None, [], {}]
        for field in ("digests", "refs"):
            bad = deepcopy(original); bad.pop(field); invalid.append(bad)
        bad = deepcopy(original); bad["schema"] = "unknown"; invalid.append(bad)
        for table in (None, {}, (), "a" * 64):
            bad = deepcopy(original); bad["digests"] = table; invalid.append(bad)
        for slots in (None, [], {}, {"source": {"h": 0}}, {**original["refs"], "extra": None}):
            bad = deepcopy(original); bad["refs"] = slots; invalid.append(bad)
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                decode_state_versions(bad)

    def test_boolean_float_literal_negative_out_of_range_and_extra_index_keys_rejected(self):
        for value in (True, False, 0, 0.0, "0", digest({}), -1, {"h": True}, {"h": False},
                      {"h": -1}, {"h": 1}, {"h": 10**100}, {"h": 0.0}, {"h": "0"},
                      {"h": None}, {"h": 0, "other": 0}, {"s": 0}, [], {}):
            bad = encode_state_versions(self.revisions()); bad["refs"]["source"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                decode_state_versions(bad)

    def test_invalid_hex_noncanonical_duplicate_unsorted_and_unreferenced_digests_rejected(self):
        invalid = []
        for table in (["A" * 64], ["g" * 64], ["a" * 63], ["a" * 65], [True], [None],
                      [{"h": 0}], ["a" * 63 + "\n"], ["ａ" * 64],
                      ["a" * 64, "a" * 64], ["b" * 64, "a" * 64],
                      [character * 64 for character in "abcde"]):
            bad = encode_state_versions(self.revisions()); bad["digests"] = table; invalid.append(bad)
        bad = encode_state_versions(self.revisions(source="a" * 64))
        bad["digests"].append("b" * 64); invalid.append(bad)
        bad = encode_state_versions(self.revisions()); bad["refs"]["source"] = None; invalid.append(bad)
        bad = encode_state_versions(self.revisions()); bad["digests"] = []; invalid.append(bad)
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                decode_state_versions(bad)

    def test_full_authoritative_comparison_rejects_stale_or_forged_slots(self):
        revisions = self.revisions(calculated=digest({}), hypotheses=digest({}))
        wire = encode_state_versions(revisions)
        for slot in SLOTS:
            stale = {**revisions, slot: digest({"SYNTHETIC": slot})}
            with self.subTest(slot=slot), self.assertRaises(IntegrityError):
                decode_state_versions(wire, stale)
        with self.assertRaises(ValidationError):
            decode_state_versions(wire, {"source": digest({})})
        self.assertEqual(decode_state_versions(json.loads(canonical_json(wire)), revisions), revisions)

    def test_state_versions_composes_without_changing_old_metadata_fields_or_decoder(self):
        fixture = legacy_fixture.MetadataContextTests(methodName="test_lists_retain_every_reference_and_order_when_shared")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = fixture.view()
        metadata = encode_metadata_view(original)
        before = canonical_json(metadata)
        state_versions = encode_state_versions(self.revisions())
        independent = {**deepcopy(metadata), "schema": "dynamic-context-disclosure-view/v2",
                       "disclosure_contract": "phase_gated_verification_brief/v1",
                       "state_versions": state_versions}
        with self.assertRaises(ValidationError):
            decode_metadata_view(independent)
        restored = deepcopy(independent)
        restored.pop("disclosure_contract"); restored.pop("state_versions")
        restored["schema"] = METADATA_VIEW_SCHEMA
        self.assertEqual(canonical_json(restored), before)
        self.assertEqual(decode_metadata_view(restored), original)
        self.assertEqual(canonical_json(metadata), before)


if __name__ == "__main__":
    unittest.main()
