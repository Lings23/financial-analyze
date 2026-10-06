import json
import os
import sqlite3
import unittest
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from helpers import ts
from research_fixtures import FixtureModel, fixture
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import AccessContext, digest
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import AgentSpec, ResearchRequest
from stock_research.research.report import markdown
from stock_research.research.runtime import ResearchRuntime
from stock_research.research.tools import ToolExecutor, ToolRegistry
from stock_research.storage.postgres import PostgresRepository


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fixture(self.root)

    def runtime(self, model=None, **kwargs):
        return ResearchRuntime(self.f.service, self.f.store, model, **kwargs)

    def run_report(self, model=None, **kwargs):
        return self.runtime(model, **kwargs).run(self.f.request, self.f.access)

    def test_deterministic_overview_and_independent_formulas(self):
        report = self.run_report()
        values = {f["name"]: Decimal(f["value"]) for f in report["facts"]}
        self.assertEqual(values["observed_price_change"], Decimal("-0.1"))
        self.assertEqual(values["observed_max_drawdown"], Decimal("0.25"))
        self.assertEqual(values["revenue_yoy"], Decimal("0.25"))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["usage"]["tool_calls"], 3)
        self.assertEqual(report["coverage"], "not_verified")
        for fact in report["facts"]:
            self.assertTrue(fact["inputs"])
            for eid in fact["inputs"]:
                e = report["evidence"][eid]
                self.assertTrue(e["artifact_ids"])
                self.assertTrue(e["snapshot"])
        self.assertIn("synthetic_fixture", markdown(report))

    def test_deepseek_selection_only(self):
        model = FixtureModel()
        report = self.run_report(model)
        self.assertEqual(report["model"]["status"], "verified")
        self.assertEqual(report["model"]["highlights"], [report["facts"][0]["id"]])
        self.assertEqual(model.calls, 1)
        self.assertNotIn("source_url", str(model.messages))

    def test_invalid_model_schema_numeric_injection_and_unknown_ids_rejected(self):
        for content in ('{"highlights":["F999"],"assessment":"descriptive_only"}',
                        '{"highlights":["F1"],"assessment":"descriptive_only","profit":999}',
                        '{"highlights":["F1","F1"],"assessment":"descriptive_only"}',
                        'buy now: 999', '{"highlights":[],"assessment":"descriptive_only"}'):
            with self.subTest(content=content):
                report = self.run_report(FixtureModel(content))
                self.assertEqual(report["status"], "partial")
                self.assertEqual(report["model"]["status"], "rejected_or_failed")
                self.assertNotIn("999", markdown(report).split("## 模型重点选择")[1].split("## 数据缺口")[0])

    def test_wrong_model_and_truncated_response_rejected(self):
        for model in (FixtureModel(returned_model="other"), FixtureModel(finish="length")):
            self.assertEqual(self.run_report(model)["status"], "partial")

    def test_duplicate_model_json_keys_rejected(self):
        model = FixtureModel('{"highlights":["F999"],"highlights":["F1"],"assessment":"descriptive_only"}')
        self.assertEqual(self.run_report(model)["model"]["status"], "rejected_or_failed")

    def test_runtime_rejects_invalid_adapter_token_types_and_output_budget(self):
        for usage in ((-1, 21, 20), (True, 20, 21), (100.0, 20, 120.0), (100, 385, 485)):
            model = FixtureModel()
            result = model.complete([])
            with patch.object(model, "complete", return_value=replace(result, prompt_tokens=usage[0],
                              completion_tokens=usage[1], total_tokens=usage[2])):
                self.assertEqual(self.run_report(model)["model"]["status"], "rejected_or_failed")

    def test_expired_unfinished_resume_does_not_read_or_complete(self):
        clock = [ts("2026-10-01T00:00:00")]
        model = FixtureModel(crash=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_report(model, now=lambda: clock[0])
        with self.f.store._connection() as db:
            run = db.execute("SELECT run FROM checkpoints LIMIT 1").fetchone()[0]
        clock[0] += timedelta(seconds=60)
        model.crash = None
        with patch.object(self.f.service, "query", wraps=self.f.service.query) as query:
            report = self.runtime(model, now=lambda: clock[0]).run(self.f.request, self.f.access, resume=run)
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["facts"], [])
        self.assertEqual(query.call_count, 0)
        self.assertEqual(model.calls, 1)

    def test_late_resume_revalidation_does_not_publish_cached_facts(self):
        clock = [ts("2026-10-01T00:00:00")]
        model = FixtureModel(crash=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_report(model, now=lambda: clock[0])
        with self.f.store._connection() as db:
            run = db.execute("SELECT run FROM checkpoints LIMIT 1").fetchone()[0]
        original = self.f.service.query
        def slow(*args):
            result = original(*args)
            clock[0] += timedelta(seconds=60)
            return result
        with patch.object(self.f.service, "query", side_effect=slow):
            report = self.runtime(model, now=lambda: clock[0]).run(self.f.request, self.f.access, resume=run)
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["model"]["status"], "unknown_outcome_no_replay")
        self.assertGreater(report["usage"]["tokens_reserved"], 0)
        self.assertEqual(model.calls, 1)

    def test_completed_replay_after_deadline_remains_authorized(self):
        clock = [ts("2026-10-01T00:00:00")]
        report = self.run_report(now=lambda: clock[0])
        clock[0] += timedelta(days=1)
        replay = self.runtime(now=lambda: clock[0]).run(self.f.request, self.f.access, resume=report["run_id"])
        self.assertEqual(replay, report)

    def test_unknown_inconsistent_or_excessive_usage_rejects_model_output(self):
        for usage in ((None, None, None), (100, 20, 121), (100000, 20, 100020)):
            model = FixtureModel()
            response = model.complete([])
            with patch.object(model, "complete", return_value=replace(response, prompt_tokens=usage[0],
                              completion_tokens=usage[1], total_tokens=usage[2])):
                report = self.run_report(model)
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["model"]["total_tokens"], usage[2])

    def test_late_model_response_is_discarded_and_accounted(self):
        clock = [ts("2026-10-01T00:00:00")]
        model = FixtureModel()
        result = model.complete([])
        def late(*args, **kwargs):
            clock[0] += timedelta(seconds=60)
            return result
        with patch.object(model, "complete", side_effect=late):
            report = self.run_report(model, now=lambda: clock[0])
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["model"]["total_tokens"], 120)

    def test_negative_financial_base_does_not_produce_yoy(self):
        from stock_research.research.calculation import calculate
        from stock_research.research.tools import read_domain
        data = read_domain(self.f.service, self.f.request, self.f.access, "financial")
        for row in data["financial_income"]["records"]:
            if row["period"] == "2023-12-31":
                for m in row["metrics"]:
                    m["value"] = "-10"
        result = calculate(data)
        self.assertFalse(any(f["name"].endswith("_yoy") for f in result["facts"]))
        self.assertIn("revenue:yoy_missing_or_nonpositive_base", result["gaps"])

    def test_model_errors_sanitized_without_retry(self):
        model = FixtureModel(crash=ValueError("fake-secret-do-not-log"))
        report = self.run_report(model)
        self.assertNotIn("fake-secret", json.dumps(report))
        self.assertEqual(model.calls, 1)
        self.assertGreater(report["usage"]["tokens_reserved"], 120)

    def test_pit_future_records_never_enter_model_context(self):
        request = replace(self.f.request, as_of=ts("2020-01-01T00:00:00"))
        model = FixtureModel()
        report = self.runtime(model).run(request, self.f.access)
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(model.calls, 0)

    def test_public_and_system_separate_capture_from_release(self):
        from stock_research.models import PITMode
        public = replace(self.f.request, as_of=ts("2025-03-21T00:00:00"), mode=PITMode.PUBLIC)
        system = replace(public, mode=PITMode.SYSTEM)
        self.assertTrue(self.runtime().run(public, self.f.access)["facts"])
        self.assertFalse(self.runtime().run(system, self.f.access)["facts"])

    def test_cross_scope_and_provider_revocation_on_completed_replay(self):
        report = self.run_report()
        for access in (AccessContext("other", frozenset({"fixture"})),
                       AccessContext(self.f.access.scope, frozenset({"other"}))):
            with self.assertRaises(PermissionDenied):
                self.runtime().run(self.f.request, access, resume=report["run_id"])

    def test_tool_permission_rechecked_on_completed_replay(self):
        report = self.run_report()
        with self.assertRaises(PermissionDenied):
            self.runtime(granted_tools={"market"}).run(self.f.request, self.f.access, resume=report["run_id"])

    def test_completed_replay_never_repeats_paid_call(self):
        model = FixtureModel()
        report = self.run_report(model)
        replayed = self.runtime(model).run(self.f.request, self.f.access, resume=report["run_id"])
        self.assertEqual(report, replayed)
        self.assertEqual(model.calls, 1)

    def test_resume_rejects_changed_cutoff(self):
        report = self.run_report()
        with self.assertRaises(PermissionDenied):
            self.runtime().run(replace(self.f.request, as_of=self.f.request.as_of+timedelta(seconds=1)),
                               self.f.access, resume=report["run_id"])

    def test_changed_artifact_rejected_even_for_completed_report(self):
        report = self.run_report()
        r = self.f.records[0]
        self.f.artifacts._path(self.f.access.scope, r.artifact_id).write_bytes(b"tampered")
        with self.assertRaises(IntegrityError):
            self.runtime().run(self.f.request, self.f.access, resume=report["run_id"])

    def test_missing_artifact_never_publishes_success(self):
        r = self.f.records[0]
        self.f.artifacts._path(self.f.access.scope, r.artifact_id).unlink()
        with self.assertRaises(IntegrityError):
            self.run_report()

    def test_tool_budget_includes_interrupted_attempts(self):
        report = self.run_report(spec=AgentSpec(max_tools=1))
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "tool_budget_exceeded")
        self.assertEqual(report["usage"]["tool_calls"], 1)

    def test_token_budget_prevents_network_call(self):
        model = FixtureModel()
        report = self.run_report(model, spec=AgentSpec(max_tokens=100))
        self.assertEqual(report["stop_reason"], "model_input_budget_exceeded")
        self.assertEqual(model.calls, 0)

    def test_cancellation_returns_partial_without_tools(self):
        report = self.run_report(cancelled=lambda: True)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(report["usage"]["tool_calls"], 0)

    def test_deadline_rejects_late_local_read(self):
        clock = [ts("2026-10-01T00:00:00")]
        original = self.f.service.query
        def slow(*args):
            value = original(*args)
            clock[0] += timedelta(seconds=60)
            return value
        with patch.object(self.f.service, "query", side_effect=slow):
            report = self.run_report(now=lambda: clock[0])
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["facts"], [])

    def test_crash_before_model_response_is_not_replayed(self):
        model = FixtureModel(crash=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_report(model)
        with self.f.store._connection() as db:
            run = db.execute("SELECT run FROM checkpoints LIMIT 1").fetchone()[0]
        model.crash = None
        report = self.runtime(model).run(self.f.request, self.f.access, resume=run)
        self.assertEqual(report["model"]["status"], "unknown_outcome_no_replay")
        self.assertEqual(model.calls, 1)
        self.assertEqual(report["status"], "partial")

    def test_crash_during_tool_preserves_budget_on_resume(self):
        with patch.object(self.f.service, "query", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_report()
        with self.f.store._connection() as db:
            run = db.execute("SELECT run FROM checkpoints LIMIT 1").fetchone()[0]
        report = self.runtime().run(self.f.request, self.f.access, resume=run)
        self.assertEqual(report["usage"]["tool_calls"], 4)

    def test_checkpoint_hash_tampering_rejected(self):
        report = self.run_report()
        with self.f.store._connection() as db:
            db.execute("UPDATE checkpoints SET payload='{}' WHERE seq=0")
        with self.assertRaises(IntegrityError):
            self.runtime().run(self.f.request, self.f.access, resume=report["run_id"])

    def test_concurrent_run_lease_rejected(self):
        run = uuid.uuid4().hex
        with self.f.store.lock(self.f.access.scope, run):
            with self.assertRaises(ValidationError):
                with self.f.store.lock(self.f.access.scope, run):
                    pass

    def test_same_wave_reuse_revalidates_artifacts(self):
        executor = ToolExecutor(self.f.service, ToolRegistry(), AgentSpec(), AgentSpec().allowed_tools,
                                self.f.request, self.f.access)
        first, hit = executor.execute("market")
        self.assertFalse(hit)
        second, hit = executor.execute("market")
        self.assertTrue(hit)
        self.assertEqual(first, second)
        r = self.f.records[0]
        self.f.artifacts._path(self.f.access.scope, r.artifact_id).write_bytes(b"tamper")
        with self.assertRaises(IntegrityError):
            executor.execute("market")

    def test_missing_close_not_zero_or_silently_skipped(self):
        f = fixture(self.root / "missing", prices=("100", None, "120"))
        report = f.runtime.run(f.request, f.access)
        self.assertFalse(any(x["name"].startswith("observed_") for x in report["facts"]))
        self.assertEqual(report["status"], "partial")

    def test_strict_request_schema_dates_and_snapshot(self):
        good = self.f.request.to_dict()
        self.assertEqual(ResearchRequest.from_dict(good), self.f.request)
        for value in ({**good, "as_of": "2025-04-16"}, {**good, "arbitrary_code": "x"},
                      {**good, "bindings": good["bindings"] * 2},
                      {**good, "bindings": [{**good["bindings"][0], "snapshot": "../secret"}]}):
            with self.assertRaises(ValidationError):
                ResearchRequest.from_dict(value)

    def test_spec_visibility_cannot_expand_permission(self):
        with self.assertRaises(ValidationError):
            AgentSpec(allowed_tools=frozenset({"market"}))

    def test_report_escapes_untrusted_document_title(self):
        report = self.run_report()
        report["documents"] = [{"title": "<script>bad</script> [click](javascript:bad)", "available_at": "x",
                                "record_id": "x", "body_artifact_id": "x"}]
        rendered = markdown(report)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("[click]", rendered)

    @unittest.skipUnless(os.environ.get("STOCK_RESEARCH_TEST_DSN"), "dedicated PostgreSQL test DSN not configured")
    def test_postgres_frozen_research_and_checkpoint_replay(self):
        repo = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        repo.migrate()
        f = fixture(self.root / "postgres", scope="phase2-test-" + uuid.uuid4().hex, repo=repo)
        model = FixtureModel()
        runtime = ResearchRuntime(f.service, f.store, model)
        report = runtime.run(f.request, f.access)
        f.service.repository = PostgresRepository(os.environ["STOCK_RESEARCH_TEST_DSN"])
        restarted = ResearchRuntime(f.service, CheckpointStore(f.store.root), model)
        self.assertEqual(report, restarted.run(f.request, f.access, resume=report["run_id"]))
        self.assertEqual(model.calls, 1)


if __name__ == "__main__":
    unittest.main()
