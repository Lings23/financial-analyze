"""Synthetic P4.5 ledger contracts; no model or financial provider calls."""
import copy
import unittest

from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import digest
from stock_research.research.root_budget import (
    consume_parent_tool, new_root_budget, reserve_child, reserve_children,
    reserve_parent_model, root_usage, settle_child, settle_parent_model,
    validate_root_budget,
)
from stock_research.research.runtime import BudgetExceeded


ROOT = "a" * 32
FINANCIAL = "b" * 32
MARKET = "c" * 32
LIMITS = {"decisions": 16, "tools": 18, "tokens": 96000}
CHILD = {"decisions": 3, "tools": 1, "tokens": 18000}
HEADROOM = {"decisions": 7, "tools": 10, "tokens": 47880}
USAGE = {"decisions": 2, "tools": 1, "tokens_accounted": 240,
         "tokens_reserved": 6000, "total_tokens": 240, "unknown_usage_calls": 0}


class ParallelRootBudgetTests(unittest.TestCase):
    def ledger(self, limits=None):
        return new_root_budget(limits or LIMITS, ROOT, max_children=2, parallel=True)

    def allocations(self):
        return [{"child_run_id": child_id, "limits": dict(CHILD)}
                for child_id in (FINANCIAL, MARKET)]

    def reserved(self, ledger=None):
        return reserve_children(ledger or self.ledger(), "group:1", self.allocations(), HEADROOM)

    def test_legacy_default_and_v2_identity_are_unchanged(self):
        legacy = new_root_budget({"decisions": 12, "tools": 16, "tokens": 72000}, ROOT)
        legacy = reserve_parent_model(legacy, "parent:1", 6000, "c" * 64)
        legacy = settle_parent_model(legacy, "parent:1", {
            "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
        legacy = consume_parent_tool(legacy, "parent-tool:1")
        legacy = reserve_child(legacy, FINANCIAL, CHILD)
        legacy = settle_child(legacy, FINANCIAL, {**USAGE, "tokens_reserved": 12000})
        self.assertEqual(digest(legacy), "b9d7bffd40d0648cbf188bfabd23b75fb77dd6a770220dfe2ca11575fbf6375c")
        self.assertEqual(new_root_budget(LIMITS, ROOT, max_children=2)["schema"], "root-budget/v2")
        self.assertEqual(self.ledger()["schema"], "root-budget/v3")

    def test_both_children_are_one_atomic_event(self):
        before = self.ledger()
        reserved = self.reserved(before)
        self.assertEqual(before["events"], [])
        self.assertEqual(len(reserved["events"]), 1)
        self.assertEqual(reserved["events"][0], {"seq": 0, "kind": "children_reserved",
            "group_id": "group:1", "allocations": self.allocations(), "headroom": HEADROOM})
        usage = root_usage(reserved)
        self.assertEqual(usage["decisions_accounted"], 6)
        self.assertEqual(usage["tools_accounted"], 2)
        self.assertEqual(usage["tokens_accounted"], 36000)
        self.assertEqual(usage["unresolved_child_allocations"], 2)

    def test_remaining_five_cannot_reserve_three_plus_three(self):
        ledger = self.ledger({**LIMITS, "decisions": 5})
        before = copy.deepcopy(ledger)
        with self.assertRaises(BudgetExceeded):
            reserve_children(ledger, "group:1", self.allocations(), {"decisions": 1, "tools": 3, "tokens": 100})
        self.assertEqual(ledger, before)
        self.assertEqual(root_usage(ledger)["remaining"]["decisions"], 5)
        self.assertEqual(root_usage(ledger)["unresolved_child_allocations"], 0)

    def test_headroom_is_checked_for_every_budget_dimension_before_dispatch(self):
        for key in ("decisions", "tools", "tokens"):
            minimum = CHILD[key] * 2 + HEADROOM[key]
            ledger = self.ledger({**LIMITS, key: minimum - 1})
            before = copy.deepcopy(ledger)
            with self.subTest(key=key), self.assertRaises(BudgetExceeded):
                self.reserved(ledger)
            self.assertEqual(ledger, before)
            fitting = self.reserved(self.ledger({**LIMITS, key: minimum}))
            self.assertEqual(root_usage(fitting)["remaining"][key], HEADROOM[key])

    def test_parent_local_envelope_is_available_even_with_both_unknown_children(self):
        ledger = self.reserved()
        for child_id in (FINANCIAL, MARKET):
            ledger = settle_child(ledger, child_id, None)
        remaining = root_usage(ledger)["remaining"]
        self.assertTrue(all(remaining[key] >= HEADROOM[key] for key in HEADROOM))
        self.assertEqual(root_usage(ledger)["tokens_accounted"], 36000)
        self.assertEqual(root_usage(ledger)["unresolved_child_allocations"], 2)
        for child_id in (FINANCIAL, MARKET):
            with self.assertRaises(ValidationError):
                settle_child(ledger, child_id, USAGE)

    def test_each_known_receipt_releases_only_its_unused_allocation(self):
        reserved = self.reserved()
        first = settle_child(reserved, FINANCIAL, USAGE)
        self.assertEqual(root_usage(first)["tokens_accounted"], 18240)
        self.assertEqual(root_usage(first)["unresolved_child_allocations"], 1)
        final = settle_child(first, MARKET, USAGE)
        self.assertEqual(root_usage(final)["tokens_accounted"], 480)
        self.assertEqual(root_usage(final)["decisions_accounted"], 4)
        self.assertEqual(root_usage(final)["tools_accounted"], 2)
        self.assertEqual(root_usage(final)["tokens_reserved"], 36000)
        self.assertEqual(root_usage(final)["tokens_dispatched_reserved"], 12000)
        self.assertEqual(root_usage(final)["unresolved_child_allocations"], 0)

    def test_known_partial_receipt_keeps_unknown_paid_tokens(self):
        partial = {**USAGE, "tokens_accounted": 3120, "tokens_reserved": 6000,
                   "total_tokens": 120, "unknown_usage_calls": 1}
        ledger = settle_child(self.reserved(), FINANCIAL, partial)
        ledger = settle_child(ledger, MARKET, USAGE)
        self.assertEqual(root_usage(ledger)["tokens_accounted"], 3360)
        self.assertEqual(root_usage(ledger)["unknown_usage_calls"], 1)
        self.assertEqual(root_usage(ledger)["total_tokens"], 360)

    def test_child_completion_order_does_not_change_accounting(self):
        results = []
        for order in ((FINANCIAL, MARKET), (MARKET, FINANCIAL)):
            ledger = self.reserved()
            for child_id in order:
                ledger = settle_child(ledger, child_id, USAGE)
            results.append(root_usage(ledger))
        self.assertEqual(results[0], results[1])

    def test_pending_group_blocks_parent_and_every_other_child_dispatch(self):
        reserved = self.reserved()
        for ledger in (reserved, settle_child(reserved, FINANCIAL, USAGE)):
            with self.assertRaises(ValidationError):
                reserve_parent_model(ledger, "parent:1", 1000, "d" * 64)
            with self.assertRaises(ValidationError):
                consume_parent_tool(ledger, "parent:1")
            with self.assertRaises(ValidationError):
                reserve_child(ledger, "d" * 32, CHILD)
            with self.assertRaises(ValidationError):
                reserve_children(ledger, "group:2", [{"child_run_id": "d" * 32, "limits": CHILD}], HEADROOM)

    def test_parent_pending_paid_intent_prevents_group_reservation(self):
        ledger = reserve_parent_model(self.ledger(), "parent:1", 1000, "d" * 64)
        with self.assertRaises(ValidationError):
            self.reserved(ledger)

    def test_resume_keeps_group_and_known_child_prefix_without_reservation(self):
        initial = self.ledger()
        reserved = self.reserved(initial)
        first = settle_child(reserved, FINANCIAL, USAGE)
        restored = copy.deepcopy(first)
        validate_root_budget(restored, [initial, reserved, first])
        final = settle_child(restored, MARKET, USAGE)
        validate_root_budget(final, [initial, reserved, first, final])
        self.assertEqual(final["events"][:len(first["events"])], first["events"])
        self.assertEqual(sum(event["kind"] == "children_reserved" for event in final["events"]), 1)
        self.assertEqual(root_usage(final)["tokens_accounted"], 480)
        with self.assertRaises(ValidationError):
            self.reserved(restored)

    def test_reserved_not_started_crash_preserves_both_full_allocations(self):
        initial = self.ledger()
        reserved = self.reserved(initial)
        restored = copy.deepcopy(reserved)
        validate_root_budget(restored, [initial, reserved])
        self.assertEqual(root_usage(restored)["tokens_accounted"], 36000)
        self.assertEqual(root_usage(restored)["decisions_accounted"], 6)
        self.assertEqual(root_usage(restored)["unresolved_child_allocations"], 2)

    def test_duplicate_identity_group_and_settlement_are_rejected(self):
        ledger = self.reserved()
        for child_id in (FINANCIAL, MARKET):
            ledger = settle_child(ledger, child_id, USAGE)
        with self.assertRaises(ValidationError):
            self.reserved(ledger)
        with self.assertRaises(ValidationError):
            reserve_child(ledger, FINANCIAL, CHILD)
        with self.assertRaises(ValidationError):
            settle_child(ledger, FINANCIAL, USAGE)
        with self.assertRaises(ValidationError):
            settle_child(ledger, "e" * 32, USAGE)

    def test_v3_serial_child_can_retain_parent_headroom(self):
        ledger = reserve_child(self.ledger(), FINANCIAL, CHILD, headroom=HEADROOM)
        self.assertEqual(ledger["events"][0]["headroom"], HEADROOM)
        validate_root_budget(ledger)
        no_room = self.ledger({**LIMITS, "tokens": CHILD["tokens"] + HEADROOM["tokens"] - 1})
        with self.assertRaises(BudgetExceeded):
            reserve_child(no_room, FINANCIAL, CHILD, headroom=HEADROOM)
        ledger = settle_child(ledger, FINANCIAL, USAGE)
        ledger = reserve_child(ledger, MARKET, CHILD, headroom=HEADROOM)
        self.assertEqual(root_usage(ledger)["unresolved_child_allocations"], 1)

    def test_finished_reads_can_reserve_finish_with_zero_tool_headroom(self):
        ledger = reserve_children(self.ledger(), "finish-only", self.allocations(),
                                  {"decisions": 1, "tools": 0, "tokens": 1})
        validate_root_budget(ledger)

    def test_parallel_api_is_rejected_by_old_ledgers(self):
        for ledger in (new_root_budget(LIMITS, ROOT), new_root_budget(LIMITS, ROOT, max_children=2)):
            with self.assertRaises(ValidationError):
                self.reserved(ledger)
            with self.assertRaises(ValidationError):
                reserve_child(ledger, FINANCIAL, CHILD, headroom=HEADROOM)

    def test_headroom_and_group_shapes_reject_untrusted_or_invalid_values(self):
        for headroom in ({**HEADROOM, "tokens": 0}, {**HEADROOM, "decisions": 0},
                         {**HEADROOM, "tools": True}, {**HEADROOM, "tokens": -1},
                         {**HEADROOM, "hidden": 1}, None):
            with self.subTest(headroom=headroom), self.assertRaises(ValidationError):
                reserve_children(self.ledger(), "group:1", self.allocations(), headroom)
        for group in (True, "", "a secret with spaces", "x" * 161):
            with self.subTest(group=group), self.assertRaises(ValidationError):
                reserve_children(self.ledger(), group, self.allocations(), HEADROOM)

    def test_allocations_are_bounded_unique_exact_and_not_root(self):
        bad = ([], self.allocations() + [{"child_run_id": "e" * 32, "limits": CHILD}],
               [{"child_run_id": FINANCIAL, "limits": CHILD}] * 2,
               [{"child_run_id": ROOT, "limits": CHILD}],
               [{"child_run_id": FINANCIAL, "limits": {**CHILD, "tokens": True}}],
               [{"child_run_id": FINANCIAL, "limits": CHILD, "scope": "other"}])
        for allocations in bad:
            with self.subTest(allocations=allocations), self.assertRaises(ValidationError):
                reserve_children(self.ledger(), "group:1", allocations, HEADROOM)

    def test_group_replay_rejects_changed_headroom_deleted_branch_and_schema_downgrade(self):
        initial = self.ledger()
        reserved = self.reserved(initial)
        for mutation in ("headroom", "branch", "schema", "summary", "seq", "hidden"):
            altered = copy.deepcopy(reserved)
            if mutation == "headroom":
                altered["events"][0]["headroom"]["tokens"] += 1
            elif mutation == "branch":
                altered["events"][0]["allocations"].pop()
            elif mutation == "schema":
                altered["schema"] = "root-budget/v2"
            elif mutation == "summary":
                altered["summary"]["tokens_accounted"] = 0
            elif mutation == "seq":
                altered["events"][0]["seq"] = True
            else:
                altered["events"][0]["secret"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(IntegrityError):
                validate_root_budget(altered, [initial, reserved, altered])

    def test_replay_validates_parent_headroom_even_without_history(self):
        forged = self.reserved()
        forged["events"][0]["headroom"]["tokens"] = LIMITS["tokens"]
        with self.assertRaises(IntegrityError):
            validate_root_budget(forged)

    def test_no_caller_mutable_objects_are_retained(self):
        allocations, headroom = self.allocations(), dict(HEADROOM)
        ledger = reserve_children(self.ledger(), "group:1", allocations, headroom)
        allocations[0]["limits"]["tokens"] = 1
        headroom["tokens"] = 1
        self.assertEqual(ledger["events"][0]["allocations"][0]["limits"], CHILD)
        self.assertEqual(ledger["events"][0]["headroom"], HEADROOM)

    def test_v3_opt_in_boolean_and_child_cap_are_strict(self):
        for parallel in (1, "true", None):
            with self.subTest(parallel=parallel), self.assertRaises(ValidationError):
                new_root_budget(LIMITS, ROOT, max_children=2, parallel=parallel)
        for max_children in (0, True, 3, "2"):
            with self.subTest(max_children=max_children), self.assertRaises(ValidationError):
                new_root_budget(LIMITS, ROOT, max_children=max_children, parallel=True)
        self.assertEqual(new_root_budget(LIMITS, ROOT, parallel=True)["max_children"], 2)


if __name__ == "__main__":
    unittest.main()
