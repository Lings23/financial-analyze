"""Synthetic v3 PIT, live disclosure authorization and recovery mechanisms."""
from dataclasses import replace
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from helpers import ts
import test_parallel_parent_progress as fixture_progress
from test_dynamic import SequenceModel, completed_actions, tool, finish
from stock_research.errors import PermissionDenied
from stock_research.models import PITMode, digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_context import expand_view, resolve_catalog
from stock_research.research.dynamic_context_metadata import decode_metadata_view
from stock_research.research.dynamic_contracts import ParallelParentSpec
from stock_research.research.scoped import ScopedReadService, SourceGrant


VERSION = "dynamic-parent-parallel-v3"
RUN = "c" * 32


def disclose(messages):
    view = decode_metadata_view(json.loads(messages[1]["content"])["context"])
    return {"action": "disclose", "catalog_ref": view["catalog_ref"],
            "refs": [view["catalog_ids"]["observations"][0]], "plan": ["SYNTHETIC exact authorized read"]}


class Phase6ContextSecurityTests(unittest.TestCase):
    setUp = fixture_progress.ParallelParentProgressTests.setUp

    def grant_service(self, request=None):
        request = request or self.complete_request
        grants = [SourceGrant(self.f.service, self.f.access, binding.snapshot,
                              request.data_request(binding), binding.provider) for binding in request.bindings]
        return ScopedReadService(self.f.access.scope, lambda: tuple(grants)), grants

    def runtime(self, model, service=None):
        return DynamicRuntime(service or self.f.service, self.f.store, model, ParallelParentSpec(version=VERSION))

    def test_public_available_at_and_system_ingested_at_boundaries_never_disclose_future_evidence(self):
        released, ingested = ts("2025-04-15T10:00:00"), ts("2025-04-16T10:00:00")
        records = self.f.repo.read(self.f.access.scope, self.complete_request.bindings[0].snapshot)
        financial = [replace(record, available_at=released, published_at=released,
            retrieved_at=released, ingested_at=ingested, announcement_date=released.date())
            for record in records if record.dataset.value == "financial_income"]
        snapshot = self.f.repo.commit(self.f.access.scope, (*self.f.records, *financial))
        cases = ((PITMode.PUBLIC, released - timedelta(microseconds=1), False),
                 (PITMode.PUBLIC, released, True),
                 (PITMode.SYSTEM, ingested - timedelta(microseconds=1), False),
                 (PITMode.SYSTEM, ingested, True))
        for mode, cutoff, visible in cases:
            with self.subTest(mode=mode.value, cutoff=cutoff):
                request = replace(self.complete_request, mode=mode, as_of=cutoff,
                    bindings=tuple(replace(binding, snapshot=snapshot.snapshot_id)
                                   for binding in self.complete_request.bindings))
                model = SequenceModel(completed_actions())
                report = self.runtime(model).run(request, self.f.access)
                financial_ids = {record.record_id for record in financial}
                found = {value["record_id"] for value in report["evidence"].values()} & financial_ids
                self.assertEqual(found, financial_ids if visible else set())
                self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"][:-1]))
                for value in report["evidence"].values():
                    self.assertLessEqual(ts(value["available_at"]), cutoff)
                    if mode == PITMode.SYSTEM:
                        self.assertLessEqual(ts(value["ingested_at"]), cutoff)
                    self.assertEqual(value["snapshot"], snapshot.snapshot_id)
                for messages in model.messages:
                    view = expand_view(json.loads(messages[1]["content"])["context"])
                    self.assertEqual(view["range"]["cutoff"], cutoff.isoformat())
                    self.assertEqual(view["range"]["pit_mode"], mode.value)
                    if not visible:
                        self.assertFalse(any(row[1] in {"revenue", "net_income_parent"} for row in view["evidence"]))

    def test_disclosure_rechecks_live_source_grants_after_resolve_and_commits_no_revoked_objects(self):
        service, grants = self.grant_service()
        model = SequenceModel([], callback=lambda call, messages: tool("financial") if call == 1 else disclose(messages))
        def revoke(*args, **kwargs):
            result = resolve_catalog(*args, **kwargs)
            grants.clear()
            return result
        with patch("stock_research.research.dynamic_context.resolve_catalog", side_effect=revoke):
            with self.assertRaises(PermissionDenied):
                self.runtime(model, service).run(self.complete_request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(model.calls, 2)
        self.assertEqual(state["context_store"]["disclosures"], [])
        self.assertFalse(any(event["event"] == "context_disclosed" for event in state["trace"]))

    def test_disclosure_rechecks_current_underlying_provider_permissions(self):
        service, grants = self.grant_service()
        model = SequenceModel([], callback=lambda call, messages: tool("financial") if call == 1 else disclose(messages))
        def revoke(*args, **kwargs):
            result = resolve_catalog(*args, **kwargs)
            grants[:] = [replace(grant, access=replace(grant.access, allowed_providers=frozenset({"revoked"})))
                         for grant in grants]
            return result
        with patch("stock_research.research.dynamic_context.resolve_catalog", side_effect=revoke):
            with self.assertRaises(PermissionDenied):
                self.runtime(model, service).run(self.complete_request, self.f.access, run_id=RUN)
        self.assertEqual(self.f.store.read(self.f.access.scope, RUN)["context_store"]["disclosures"], [])
        self.assertEqual(model.calls, 2)

    def test_disclosure_is_an_accounted_read_and_never_completes_business_checks(self):
        def callback(call, messages):
            return tool("financial") if call == 1 else disclose(messages) if call == 2 else finish("insufficient")
        model = SequenceModel([], callback=callback)
        report = self.runtime(model).run(self.complete_request, self.f.access)
        self.assertEqual((report["status"], report["stop_reason"]), ("partial", "no_progress"))
        self.assertEqual(model.calls, 4)
        self.assertEqual(report["usage"]["tool_calls"], 2)
        self.assertEqual(len(report["context_archive"]["disclosures"]), 1)
        self.assertTrue(all(check["status"] == "not_completed" for check in report["required_checks"]
                            if check["id"] in {"read:market", "calculation", "hypotheses", "verification"}))
        for rejection in (decision["rejection"] for decision in report["decisions"] if "rejection" in decision):
            self.assertTrue({"read:market", "calculation", "hypotheses", "verification"} <= set(rejection["pending_checks"]))

    def test_finished_context_recovery_rechecks_source_grants_before_paid_wire_or_append(self):
        service, grants = self.grant_service()
        report = self.runtime(SequenceModel(completed_actions()), service).run(self.complete_request, self.f.access)
        grants.clear()
        model = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
            with self.assertRaises(PermissionDenied):
                self.runtime(model, service).run(self.complete_request, self.f.access, resume=report["run_id"])
            append.assert_not_called()
        self.assertEqual(model.calls, 0)

    def test_verified_paid_action_recovery_reconstructs_exact_v3_wire_and_does_not_repeat_decision(self):
        original = self.f.store.append
        def crash_after_verified_action(scope, run, state):
            original(scope, run, state)
            if state["trace"] and state["trace"][-1]["event"] == "plan_updated":
                raise KeyboardInterrupt()
        first = SequenceModel([tool("financial")])
        with patch.object(self.f.store, "append", side_effect=crash_after_verified_action):
            with self.assertRaises(KeyboardInterrupt):
                self.runtime(first).run(self.complete_request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(state["context"]["message_sha256"], digest(first.messages[0]))
        model = SequenceModel(completed_actions()[1:])
        report = self.runtime(model).run(self.complete_request, self.f.access, resume=RUN)
        self.assertEqual(report["status"], "completed")
        self.assertEqual((first.calls, model.calls, report["usage"]["model_attempts"]), (1, 5, 6))
        self.assertEqual(report["context_telemetry"][0]["message_sha256"], digest(first.messages[0]))
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 0)


if __name__ == "__main__":
    unittest.main()
