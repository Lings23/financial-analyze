"""Synthetic serial root-budget accounting; no paid calls or financial fixtures."""
import copy
import unittest

from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import digest
from stock_research.research.root_budget import (
    consume_parent_tool, new_root_budget, reserve_child, reserve_parent_model,
    root_usage, settle_child, settle_parent_model, validate_root_budget,
)
from stock_research.research.runtime import BudgetExceeded


ROOT = "a" * 32
CHILD = "b" * 32
MESSAGE = "c" * 64
ROOT_LIMITS = {"decisions": 12, "tools": 16, "tokens": 72000}
CHILD_LIMITS = {"decisions": 3, "tools": 1, "tokens": 18000}
KNOWN_PARENT = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
KNOWN_CHILD = {"decisions": 2, "tools": 1, "tokens_accounted": 240,
               "tokens_reserved": 12000, "total_tokens": 240, "unknown_usage_calls": 0}


class RootBudgetTests(unittest.TestCase):
    def ledger(self, limits=None):
        return new_root_budget(limits or ROOT_LIMITS, ROOT)

    def child_reserved(self):
        ledger = reserve_parent_model(self.ledger(), "parent:1", 6000, MESSAGE)
        ledger = settle_parent_model(ledger, "parent:1", KNOWN_PARENT)
        ledger = consume_parent_tool(ledger, "parent-tool:1")
        return reserve_child(ledger, CHILD, CHILD_LIMITS)

    def test_parent_and_child_share_capacity_before_dispatch(self):
        initial = self.ledger()
        reserved = self.child_reserved()
        self.assertEqual(initial["events"], [])
        usage = root_usage(reserved)
        self.assertEqual(usage["decisions_accounted"], 4)
        self.assertEqual(usage["tools_accounted"], 2)
        self.assertEqual(usage["tokens_accounted"], 18120)
        self.assertEqual(usage["remaining"], {"decisions": 8, "tools": 14, "tokens": 53880})
        self.assertEqual(usage["tokens_reserved"], 24000)
        self.assertEqual(usage["unresolved_child_allocations"], 1)

    def test_known_child_releases_only_unused_capacity_and_keeps_cumulative_reservations(self):
        reserved = self.child_reserved()
        settled = settle_child(reserved, CHILD, KNOWN_CHILD)
        usage = root_usage(settled)
        self.assertEqual(usage["decisions_accounted"], 3)
        self.assertEqual(usage["tools_accounted"], 2)
        self.assertEqual(usage["tokens_accounted"], 360)
        self.assertEqual(usage["model_attempts"], 3)
        self.assertEqual(usage["tool_attempts"], 2)
        self.assertEqual(usage["tokens_reserved"], 24000)
        self.assertEqual(usage["tokens_dispatched_reserved"], 18000)
        self.assertEqual(usage["total_tokens"], 360)
        self.assertEqual(usage["unknown_usage_calls"], 0)
        self.assertEqual(usage["unresolved_child_allocations"], 0)
        self.assertEqual(root_usage(reserved)["tokens_accounted"], 18120)

    def test_partial_child_keeps_unknown_model_reservation_but_releases_unattempted_work(self):
        usage = {**KNOWN_CHILD, "tokens_accounted": 6120, "total_tokens": 120,
                 "unknown_usage_calls": 1}
        settled = settle_child(self.child_reserved(), CHILD, usage)
        final = root_usage(settled)
        self.assertEqual(final["decisions_accounted"], 3)
        self.assertEqual(final["tools_accounted"], 2)
        self.assertEqual(final["tokens_accounted"], 6240)
        self.assertEqual(final["total_tokens"], 240)
        self.assertEqual(final["unknown_usage_calls"], 1)
        self.assertEqual(final["unresolved_child_allocations"], 0)

    def test_entirely_unknown_child_retains_full_allocation_and_cannot_later_release(self):
        reserved = self.child_reserved()
        unknown = settle_child(reserved, CHILD, None)
        self.assertEqual(root_usage(unknown), root_usage(reserved))
        self.assertEqual(root_usage(unknown)["unresolved_child_allocations"], 1)
        self.assertEqual(root_usage(unknown)["model_attempts"], 1)
        with self.assertRaises(ValidationError):
            settle_child(unknown, CHILD, KNOWN_CHILD)
        with self.assertRaises(ValidationError):
            settle_child(unknown, CHILD, None)

    def test_parent_unknown_retains_reservation_and_cannot_be_reclassified_known(self):
        reserved = reserve_parent_model(self.ledger(), "parent:1", 6000, MESSAGE)
        unknown = settle_parent_model(reserved, "parent:1", None)
        self.assertEqual(root_usage(unknown)["tokens_accounted"], 6000)
        self.assertEqual(root_usage(unknown)["unknown_usage_calls"], 1)
        self.assertEqual(root_usage(unknown)["total_tokens"], 0)
        with self.assertRaises(ValidationError):
            settle_parent_model(unknown, "parent:1", KNOWN_PARENT)

    def test_attempts_do_not_refund_when_known_token_reservation_is_replaced(self):
        reserved = reserve_parent_model(self.ledger(), "parent:1", 6000, MESSAGE)
        settled = settle_parent_model(reserved, "parent:1", KNOWN_PARENT)
        self.assertEqual(root_usage(settled)["decisions_accounted"], 1)
        self.assertEqual(root_usage(settled)["tokens_accounted"], 120)
        self.assertEqual(root_usage(settled)["tokens_reserved"], 6000)
        with self.assertRaises(ValidationError):
            reserve_parent_model(settled, "parent:1", 6000, MESSAGE)
        with self.assertRaises(ValidationError):
            settle_parent_model(settled, "parent:1", KNOWN_PARENT)

    def test_insufficient_child_allocation_never_mutates_the_parent_ledger(self):
        for limits in ({"decisions": 2, "tools": 16, "tokens": 72000},
                       {"decisions": 12, "tools": 1, "tokens": 72000},
                       {"decisions": 12, "tools": 16, "tokens": 18000}):
            with self.subTest(limits=limits):
                ledger = reserve_parent_model(self.ledger(limits), "parent:1", 1000, MESSAGE)
                ledger = settle_parent_model(ledger, "parent:1", KNOWN_PARENT)
                ledger = consume_parent_tool(ledger, "parent-tool:1")
                before = copy.deepcopy(ledger)
                with self.assertRaises(BudgetExceeded):
                    reserve_child(ledger, CHILD, CHILD_LIMITS)
                self.assertEqual(ledger, before)

    def test_parent_budget_limits_apply_before_new_attempts(self):
        token_ledger = self.ledger({"decisions": 1, "tools": 1, "tokens": 100})
        before = copy.deepcopy(token_ledger)
        with self.assertRaises(BudgetExceeded):
            reserve_parent_model(token_ledger, "parent:1", 101, MESSAGE)
        self.assertEqual(token_ledger, before)
        tool_ledger = consume_parent_tool(token_ledger, "parent-tool:1")
        with self.assertRaises(BudgetExceeded):
            consume_parent_tool(tool_ledger, "parent-tool:2")
        self.assertEqual(root_usage(tool_ledger)["tools_accounted"], 1)

    def test_serial_child_prevents_parent_dispatch_and_another_child(self):
        reserved = self.child_reserved()
        with self.assertRaises(ValidationError):
            reserve_parent_model(reserved, "parent:2", 1000, MESSAGE)
        with self.assertRaises(ValidationError):
            consume_parent_tool(reserved, "parent-tool:2")
        with self.assertRaises(ValidationError):
            reserve_child(reserved, "d" * 32, CHILD_LIMITS)
        settled = settle_child(reserved, CHILD, KNOWN_CHILD)
        with self.assertRaises(ValidationError):
            reserve_child(settled, "d" * 32, CHILD_LIMITS)
        continued = reserve_parent_model(settled, "parent:2", 1000, MESSAGE)
        self.assertEqual(root_usage(continued)["model_attempts"], 4)

    def test_pending_parent_model_prevents_overlapping_parent_or_child_dispatch(self):
        pending = reserve_parent_model(self.ledger(), "parent:1", 6000, MESSAGE)
        with self.assertRaises(ValidationError):
            reserve_parent_model(pending, "parent:2", 6000, MESSAGE)
        with self.assertRaises(ValidationError):
            reserve_child(pending, CHILD, CHILD_LIMITS)

    def test_child_cannot_reserve_the_root_itself(self):
        with self.assertRaises(ValidationError):
            reserve_child(self.ledger(), ROOT, CHILD_LIMITS)

    def test_invalid_or_overstated_parent_receipts_do_not_release_capacity(self):
        pending = reserve_parent_model(self.ledger(), "parent:1", 6000, MESSAGE)
        for usage in ({**KNOWN_PARENT, "total_tokens": 121},
                      {**KNOWN_PARENT, "prompt_tokens": True},
                      {"prompt_tokens": 6001, "completion_tokens": 0, "total_tokens": 6001},
                      {**KNOWN_PARENT, "unexpected": "value"}):
            with self.subTest(usage=usage), self.assertRaises(ValidationError):
                settle_parent_model(pending, "parent:1", usage)
        self.assertEqual(root_usage(pending)["tokens_accounted"], 6000)

    def test_invalid_child_usage_cannot_release_or_understate_unknown_tokens(self):
        pending = self.child_reserved()
        cases = [{**KNOWN_CHILD, "decisions": 4}, {**KNOWN_CHILD, "tools": 2},
                 {**KNOWN_CHILD, "tokens_accounted": 241},
                 {**KNOWN_CHILD, "tokens_accounted": 239},
                 {**KNOWN_CHILD, "unknown_usage_calls": 1},
                 {**KNOWN_CHILD, "unknown_usage_calls": True},
                 {**KNOWN_CHILD, "tokens_reserved": 1},
                 {**KNOWN_CHILD, "tokens_reserved": 36001},
                 {**KNOWN_CHILD, "decisions": 0}, {**KNOWN_CHILD, "scope": "other"}]
        for usage in cases:
            with self.subTest(usage=usage), self.assertRaises(ValidationError):
                settle_child(pending, CHILD, usage)
        self.assertEqual(root_usage(pending)["tokens_accounted"], 18120)

    def test_zero_attempt_known_child_can_release_every_unused_unit(self):
        usage = dict.fromkeys(KNOWN_CHILD, 0)
        settled = settle_child(self.child_reserved(), CHILD, usage)
        self.assertEqual(root_usage(settled)["tokens_accounted"], 120)
        self.assertEqual(root_usage(settled)["decisions_accounted"], 1)
        self.assertEqual(root_usage(settled)["tools_accounted"], 1)

    def test_child_cumulative_dispatch_reservation_may_exceed_its_local_accounted_limit(self):
        usage = {**KNOWN_CHILD, "decisions": 3, "tokens_reserved": 30000}
        settled = settle_child(self.child_reserved(), CHILD, usage)
        self.assertEqual(root_usage(settled)["tokens_accounted"], 360)
        self.assertEqual(root_usage(settled)["tokens_dispatched_reserved"], 36000)
        self.assertEqual(root_usage(settled)["tokens_reserved"], 24000)

    def test_summary_schema_boolean_and_recomputed_totals_tampering_are_rejected(self):
        original = self.child_reserved()
        for change in ("accounted", "bool", "hidden", "schema", "sequence", "event_extra"):
            forged = copy.deepcopy(original)
            if change == "accounted":
                forged["summary"]["tokens_accounted"] = 0
            elif change == "bool":
                forged["summary"]["model_attempts"] = True
            elif change == "hidden":
                forged["summary"]["secret"] = 0
            elif change == "schema":
                forged["schema"] = "root-budget/v99"
            elif change == "sequence":
                forged["events"][0]["seq"] = True
            else:
                forged["events"][0]["scope"] = "other"
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                validate_root_budget(forged)

    def test_history_rejects_counter_reset_changed_limits_or_changed_intent(self):
        first = self.ledger()
        reserved = reserve_parent_model(first, "parent:1", 6000, MESSAGE)
        settled = settle_parent_model(reserved, "parent:1", KNOWN_PARENT)
        validate_root_budget(settled, [first, reserved, settled])
        reset = self.ledger()
        with self.assertRaises(IntegrityError):
            validate_root_budget(reset, [first, reserved, reset])
        enlarged = copy.deepcopy(settled)
        enlarged["limits"]["tokens"] += 1
        with self.assertRaises(IntegrityError):
            validate_root_budget(enlarged, [first, reserved, enlarged])
        altered = copy.deepcopy(settled)
        altered["events"][0]["message_sha256"] = "d" * 64
        with self.assertRaises(IntegrityError):
            validate_root_budget(altered, [first, reserved, altered])

    def test_replayed_duplicate_settlement_or_intent_is_rejected(self):
        ledger = reserve_parent_model(self.ledger(), "parent:1", 6000, MESSAGE)
        ledger = settle_parent_model(ledger, "parent:1", KNOWN_PARENT)
        for index in (0, 1):
            forged = copy.deepcopy(ledger)
            event = copy.deepcopy(forged["events"][index])
            event["seq"] = len(forged["events"])
            forged["events"].append(event)
            with self.assertRaises(IntegrityError):
                validate_root_budget(forged)

    def test_ledger_does_not_retain_caller_mutable_limit_or_receipt_objects(self):
        limits = dict(ROOT_LIMITS)
        ledger = new_root_budget(limits, ROOT)
        limits["tokens"] = 1
        usage = dict(KNOWN_PARENT)
        ledger = reserve_parent_model(ledger, "parent:1", 6000, MESSAGE)
        ledger = settle_parent_model(ledger, "parent:1", usage)
        usage["total_tokens"] = 99999
        returned = root_usage(ledger)
        returned["limits"]["tokens"] = 1
        self.assertEqual(root_usage(ledger)["tokens_accounted"], 120)
        self.assertEqual(root_usage(ledger)["limits"], ROOT_LIMITS)


class RootBudgetV2Tests(unittest.TestCase):
    SECOND_CHILD = "d" * 32

    def ledger(self, limits=None, max_children=2):
        return new_root_budget(limits or ROOT_LIMITS, ROOT, max_children=max_children)

    def first_child_settled(self, limits=None):
        ledger = reserve_parent_model(self.ledger(limits), "parent:1", 6000, MESSAGE)
        ledger = settle_parent_model(ledger, "parent:1", KNOWN_PARENT)
        ledger = consume_parent_tool(ledger, "parent-tool:1")
        ledger = reserve_child(ledger, CHILD, CHILD_LIMITS)
        return settle_child(ledger, CHILD, KNOWN_CHILD)

    def test_default_v1_fixture_identity_and_single_child_limit_remain_exact(self):
        ledger = reserve_parent_model(new_root_budget(ROOT_LIMITS, ROOT), "parent:1", 6000, MESSAGE)
        ledger = settle_parent_model(ledger, "parent:1", KNOWN_PARENT)
        ledger = consume_parent_tool(ledger, "parent-tool:1")
        ledger = reserve_child(ledger, CHILD, CHILD_LIMITS)
        ledger = settle_child(ledger, CHILD, KNOWN_CHILD)
        self.assertEqual(ledger["schema"], "root-budget/v1")
        self.assertNotIn("max_children", ledger)
        self.assertEqual(digest(ledger), "b9d7bffd40d0648cbf188bfabd23b75fb77dd6a770220dfe2ca11575fbf6375c")
        with self.assertRaises(ValidationError):
            reserve_child(ledger, self.SECOND_CHILD, CHILD_LIMITS)

    def test_v2_two_independent_serial_children_consume_the_same_root(self):
        ledger = self.first_child_settled()
        ledger = consume_parent_tool(ledger, "parent-tool:2")
        ledger = reserve_child(ledger, self.SECOND_CHILD, CHILD_LIMITS)
        second_usage = {**KNOWN_CHILD, "decisions": 3, "tokens_accounted": 360,
                        "tokens_reserved": 18000, "total_tokens": 360}
        ledger = settle_child(ledger, self.SECOND_CHILD, second_usage)
        self.assertEqual(ledger["schema"], "root-budget/v2")
        self.assertEqual(ledger["max_children"], 2)
        usage = root_usage(ledger)
        self.assertEqual(usage["model_attempts"], 6)
        self.assertEqual(usage["decisions_accounted"], 6)
        self.assertEqual(usage["tool_attempts"], 4)
        self.assertEqual(usage["tools_accounted"], 4)
        self.assertEqual(usage["tokens_accounted"], 720)
        self.assertEqual(usage["tokens_reserved"], 42000)
        self.assertEqual(usage["tokens_dispatched_reserved"], 36000)
        self.assertEqual(usage["remaining"], {"decisions": 6, "tools": 12, "tokens": 71280})
        self.assertEqual(usage["unknown_usage_calls"], 0)
        self.assertEqual(usage["unresolved_child_allocations"], 0)

    def test_pending_first_or_second_child_blocks_every_new_dispatch(self):
        first = reserve_child(self.ledger(), CHILD, CHILD_LIMITS)
        settled = settle_child(first, CHILD, KNOWN_CHILD)
        second = reserve_child(settled, self.SECOND_CHILD, CHILD_LIMITS)
        for ledger in (first, second):
            before = copy.deepcopy(ledger)
            with self.subTest(child_count=len([e for e in ledger["events"] if e["kind"] == "child_reserved"])), \
                    self.assertRaises(ValidationError):
                reserve_parent_model(ledger, "parent:1", 6000, MESSAGE)
            with self.assertRaises(ValidationError):
                consume_parent_tool(ledger, "parent-tool:1")
            with self.assertRaises(ValidationError):
                reserve_child(ledger, "e" * 32, CHILD_LIMITS)
            self.assertEqual(ledger, before)

    def test_pending_parent_model_blocks_v2_child_dispatch(self):
        ledger = reserve_parent_model(self.ledger(), "parent:1", 6000, MESSAGE)
        with self.assertRaises(ValidationError):
            reserve_child(ledger, CHILD, CHILD_LIMITS)

    def test_second_child_cannot_reuse_first_identity_and_third_child_is_rejected(self):
        first = self.first_child_settled()
        with self.assertRaises(ValidationError):
            reserve_child(first, CHILD, CHILD_LIMITS)
        second = reserve_child(first, self.SECOND_CHILD, CHILD_LIMITS)
        second = settle_child(second, self.SECOND_CHILD, KNOWN_CHILD)
        with self.assertRaises(ValidationError):
            reserve_child(second, "e" * 32, CHILD_LIMITS)
        with self.assertRaises(ValidationError):
            reserve_child(second, ROOT, CHILD_LIMITS)
        self.assertEqual(root_usage(second)["model_attempts"], 5)

    def test_first_known_usage_stays_charged_when_second_allocation_exceeds_root(self):
        cases = ({"decisions": 5, "tools": 16, "tokens": 72000},
                 {"decisions": 12, "tools": 2, "tokens": 72000},
                 {"decisions": 12, "tools": 16, "tokens": 18359})
        for limits in cases:
            ledger = self.first_child_settled(limits)
            before = copy.deepcopy(ledger)
            with self.subTest(limits=limits), self.assertRaises(BudgetExceeded):
                reserve_child(ledger, self.SECOND_CHILD, CHILD_LIMITS)
            self.assertEqual(ledger, before)
            self.assertEqual(root_usage(ledger)["tokens_accounted"], 360)

    def test_two_unknown_children_keep_both_entire_allocations(self):
        first = reserve_child(self.ledger(), CHILD, CHILD_LIMITS)
        first = settle_child(first, CHILD, None)
        second = reserve_child(first, self.SECOND_CHILD, CHILD_LIMITS)
        self.assertEqual(root_usage(second)["unresolved_child_allocations"], 2)
        second = settle_child(second, self.SECOND_CHILD, None)
        usage = root_usage(second)
        self.assertEqual(usage["decisions_accounted"], 6)
        self.assertEqual(usage["tools_accounted"], 2)
        self.assertEqual(usage["tokens_accounted"], 36000)
        self.assertEqual(usage["tokens_reserved"], 36000)
        self.assertEqual(usage["unresolved_child_allocations"], 2)
        self.assertEqual(usage["model_attempts"], 0)
        for child_id in (CHILD, self.SECOND_CHILD):
            with self.subTest(child_id=child_id), self.assertRaises(ValidationError):
                settle_child(second, child_id, KNOWN_CHILD)

    def test_known_partial_second_child_releases_only_unattempted_work(self):
        ledger = self.first_child_settled()
        ledger = reserve_child(ledger, self.SECOND_CHILD, CHILD_LIMITS)
        partial = {**KNOWN_CHILD, "tokens_accounted": 6120,
                   "total_tokens": 120, "unknown_usage_calls": 1}
        ledger = settle_child(ledger, self.SECOND_CHILD, partial)
        usage = root_usage(ledger)
        self.assertEqual(usage["decisions_accounted"], 5)
        self.assertEqual(usage["tools_accounted"], 3)
        self.assertEqual(usage["tokens_accounted"], 6480)
        self.assertEqual(usage["total_tokens"], 480)
        self.assertEqual(usage["unknown_usage_calls"], 1)
        self.assertEqual(usage["unresolved_child_allocations"], 0)
        self.assertEqual(usage["tokens_reserved"], 42000)

    def test_second_child_settlement_must_reference_exact_reserved_child(self):
        ledger = self.first_child_settled()
        ledger = reserve_child(ledger, self.SECOND_CHILD, CHILD_LIMITS)
        with self.assertRaises(ValidationError):
            settle_child(ledger, CHILD, KNOWN_CHILD)
        with self.assertRaises(ValidationError):
            settle_child(ledger, "e" * 32, KNOWN_CHILD)
        settled = settle_child(ledger, self.SECOND_CHILD, KNOWN_CHILD)
        with self.assertRaises(ValidationError):
            settle_child(settled, self.SECOND_CHILD, KNOWN_CHILD)

    def test_v2_history_rejects_changed_max_children_even_when_standalone_valid(self):
        first = self.ledger()
        reserved = reserve_child(first, CHILD, CHILD_LIMITS)
        settled = settle_child(reserved, CHILD, KNOWN_CHILD)
        validate_root_budget(settled, [first, reserved, settled])
        narrowed = copy.deepcopy(settled)
        narrowed["max_children"] = 1
        validate_root_budget(narrowed)
        with self.assertRaises(IntegrityError):
            validate_root_budget(narrowed, [first, reserved, narrowed])
        downgraded = copy.deepcopy(settled)
        downgraded["schema"] = "root-budget/v1"
        downgraded.pop("max_children")
        validate_root_budget(downgraded)
        with self.assertRaises(IntegrityError):
            validate_root_budget(downgraded, [first, reserved, downgraded])

    def test_v2_history_rejects_deleted_prior_child_and_changed_usage(self):
        first = self.ledger()
        reserved = reserve_child(first, CHILD, CHILD_LIMITS)
        settled = settle_child(reserved, CHILD, KNOWN_CHILD)
        second = reserve_child(settled, self.SECOND_CHILD, CHILD_LIMITS)
        reset = reserve_child(self.ledger(), self.SECOND_CHILD, CHILD_LIMITS)
        with self.assertRaises(IntegrityError):
            validate_root_budget(reset, [first, reserved, settled, reset])
        altered = copy.deepcopy(second)
        altered["events"][1]["usage"]["tokens_reserved"] += 1
        with self.assertRaises(IntegrityError):
            validate_root_budget(altered, [first, reserved, settled, altered])

    def test_v2_replay_rejects_overlapping_child_and_duplicate_settlement_events(self):
        pending = reserve_child(self.ledger(), CHILD, CHILD_LIMITS)
        overlapping = copy.deepcopy(pending)
        overlapping["events"].append({"seq": 1, "kind": "child_reserved", "child_run_id": self.SECOND_CHILD,
                                      "limits": dict(CHILD_LIMITS)})
        with self.assertRaises(IntegrityError):
            validate_root_budget(overlapping)
        settled = settle_child(pending, CHILD, KNOWN_CHILD)
        duplicate = copy.deepcopy(settled)
        duplicate["events"].append({"seq": 2, "kind": "child_settled", "child_run_id": CHILD,
                                   "usage": dict(KNOWN_CHILD)})
        with self.assertRaises(IntegrityError):
            validate_root_budget(duplicate)

    def test_v2_serial_rules_are_enforced_during_event_replay(self):
        pending = reserve_child(self.ledger(), CHILD, CHILD_LIMITS)
        events = ({"seq": 1, "kind": "parent_model_reserved", "intent_id": "parent:1",
                   "token_reservation": 6000, "message_sha256": MESSAGE},
                  {"seq": 1, "kind": "parent_tool_consumed", "tool_call_id": "parent-tool:1"})
        for event in events:
            forged = copy.deepcopy(pending)
            forged["events"].append(event)
            with self.subTest(kind=event["kind"]), self.assertRaises(IntegrityError):
                validate_root_budget(forged)

    def test_v2_opt_in_is_bounded_and_cannot_be_smuggled_into_v1(self):
        for value in (True, 0, 3, 2.0, "2"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.ledger(max_children=value)
        legacy = new_root_budget(ROOT_LIMITS, ROOT)
        legacy["max_children"] = 2
        with self.assertRaises(IntegrityError):
            validate_root_budget(legacy)
        for value in (True, 3, []):
            forged = self.ledger()
            forged["max_children"] = value
            with self.subTest(value=value), self.assertRaises(IntegrityError):
                validate_root_budget(forged)

    def test_v2_uses_the_same_usage_fields_and_refunds_do_not_change_event_prefix(self):
        legacy_fields = set(root_usage(new_root_budget(ROOT_LIMITS, ROOT)))
        initial = self.ledger()
        pending = reserve_child(initial, CHILD, CHILD_LIMITS)
        settled = settle_child(pending, CHILD, KNOWN_CHILD)
        self.assertEqual(set(root_usage(settled)), legacy_fields)
        self.assertEqual(settled["events"][:len(pending["events"])], pending["events"])
        self.assertGreater(root_usage(pending)["tokens_accounted"], root_usage(settled)["tokens_accounted"])
        self.assertEqual(root_usage(pending)["tokens_reserved"], root_usage(settled)["tokens_reserved"])
        validate_root_budget(settled, [initial, pending, settled])
