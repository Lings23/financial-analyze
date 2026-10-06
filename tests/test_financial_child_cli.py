"""Synthetic P4.3 entry/report checks; no Provider or real model validation."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research_fixtures import FixtureModel, fixture
from stock_research.__main__ import parser
from stock_research.errors import ValidationError
from stock_research.research import cli
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicSpec, FinancialParentSpec
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest


class FinancialChildCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fixture(self.root / "synthetic")
        self.request = {**self.f.request.to_dict(), "hypotheses": ["financial_deterioration"]}
        self.manifest = self.root / "request.json"
        self.manifest.write_text(json.dumps(self.request), encoding="utf-8")

    def args(self, *options):
        return parser().parse_args([
            "research", "--workflow", "dynamic", "--request", str(self.manifest),
            "--scope", self.f.access.scope, "--allow-provider", "fixture", "--artifacts", str(self.f.artifacts.root),
            "--runs", str(self.root / "runs"), "--output", str(self.root / "output"),
            "--question", "SYNTHETIC: inspect bound financial evidence", *options,
        ])

    def report(self):
        report = StudyRuntime(self.f.service, self.f.store).run(StudyRequest.from_dict(self.request), self.f.access)
        report.update(schema="dynamic-research/v1", execution_strategy="dynamic", plans=[], decisions=[],
                      required_checks=[{"id": "verification", "status": "passed"}])
        report["request"]["question"] = "SYNTHETIC: inspect bound financial evidence"
        return report

    def test_default_cli_version_is_v2_and_child_remains_explicit(self):
        args = self.args("--preview-model")
        self.assertEqual(args.dynamic_version, "single-dynamic-v2")
        self.assertFalse(args.financial_child)
        self.assertEqual(DynamicSpec().version, "single-dynamic-v1")
        with patch("stock_research.research.dynamic.DynamicRuntime", autospec=True) as runtime:
            runtime.return_value.run.return_value = self.report()
            with patch.object(cli, "load_model_config", return_value=FixtureModel.config), \
                    patch.object(cli, "ChatModelAdapter", return_value=FixtureModel()):
                cli.run(self.args("--with-model"), self.f.repo)
        spec = runtime.call_args.kwargs["spec"]
        self.assertIs(type(spec), DynamicSpec)
        self.assertEqual(spec.version, "single-dynamic-v2")
        self.assertNotIn("financial_child", spec.visible_tools)

    def test_financial_child_legacy_or_fixed_mode_rejected_before_runtime_config_and_output(self):
        args = self.args("--financial-child", "--dynamic-version", "single-dynamic-v1", "--with-model")
        other = self.args("--financial-child", "--with-model")
        other.workflow, other.question = "research", None
        for candidate in (args, other):
            with self.subTest(workflow=candidate.workflow), patch.object(cli, "load_model_config") as config, \
                    patch.object(cli, "CheckpointStore") as checkpoints:
                with self.assertRaisesRegex(ValidationError, "--financial-child requires"):
                    cli.run(candidate, self.f.repo)
                config.assert_not_called()
                checkpoints.assert_not_called()
                self.assertFalse(Path(candidate.output).exists())

    def test_child_preview_lists_only_opt_in_tool_without_model_data_or_child_run(self):
        args = self.args("--financial-child", "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "ChatModelAdapter") as model, \
                patch.object(cli, "CheckpointStore") as checkpoints, patch.object(DynamicRuntime, "run") as run, \
                patch.object(cli.DataService, "query", side_effect=AssertionError("preview dispatched a source read")) as query:
            result = cli.run(args, self.f.repo)
        for mock in (config, model, checkpoints, run, query):
            mock.assert_not_called()
        target = Path(args.output)
        preview = json.loads((target / "preview.json").read_text(encoding="utf-8"))
        messages = json.loads((target / "model-messages.json").read_text(encoding="utf-8"))
        payload = json.loads(messages[1]["content"])
        self.assertEqual(preview["spec_version"], "dynamic-parent-financial-v1")
        self.assertTrue(preview["financial_child_enabled"])
        self.assertIn("financial_child", payload["available_tools"])
        self.assertEqual(payload["observations"], [])
        self.assertEqual(payload["completed_tools"], [])
        self.assertTrue(all(value == 0 for value in result["usage"].values()))
        self.assertFalse(Path(args.runs).exists())
        self.assertNotIn("child_results", preview)
        self.assertIn("未启动 Financial Child", (target / "preview.md").read_text(encoding="utf-8"))

    def test_v1_explicit_preview_remains_available(self):
        result = cli.run(self.args("--dynamic-version", "single-dynamic-v1", "--preview-model"), self.f.repo)
        preview = json.loads((Path(result["report"]).parent / "preview.json").read_text(encoding="utf-8"))
        self.assertEqual(preview["spec_version"], "single-dynamic-v1")
        self.assertFalse(preview["financial_child_enabled"])

    def test_authorized_parent_routes_same_runtime_with_separate_parent_spec(self):
        model = FixtureModel()
        report = self.report()
        with patch("stock_research.research.dynamic.DynamicRuntime", autospec=True) as runtime, \
                patch.object(cli, "load_model_config", return_value=model.config), \
                patch.object(cli, "ChatModelAdapter", return_value=model):
            runtime.return_value.run.return_value = report
            result = cli.run(self.args("--financial-child", "--with-model"), self.f.repo)
        spec = runtime.call_args.kwargs["spec"]
        self.assertIsInstance(spec, FinancialParentSpec)
        self.assertNotEqual(spec.identity, DynamicSpec(version="single-dynamic-v2").identity)
        self.assertEqual(runtime.call_args.args[2], model)
        self.assertEqual(runtime.return_value.run.call_args.kwargs, {"resume": None})
        self.assertEqual(result["status"], report["status"])

    def test_report_shows_typed_rejection_child_links_and_unresolved_root_budget(self):
        report = self.report()
        report.update(status="partial", stop_reason="unknown_child_outcome")
        report["decisions"] = [{"turn": 1, "status": "verified", "token_reservation": 2000,
                                "action": {"action": "finish", "reason": "insufficient", "plan": ["control"]},
                                "rejection": {"code": "required_checks_pending", "pending_checks": ["verification"]}}]
        report["child_results"] = [{"schema": "financial-child-result/v1", "child_run_id": "child-synthetic",
            "parent_run_id": report["run_id"], "tool_call_id": "parent:child-tool", "status": "partial",
            "stop_reason": "unknown_model_outcome", "request_ref": "request-ref", "result_ref": "result-ref",
            "source_result_ref": None, "deadline": "2026-10-05T00:02:00+08:00",
            "required_checks": [{"id": "read:financial", "status": "not_completed"}],
            "usage": {"model_attempts": 1, "tool_calls": 0, "tokens_reserved": 18000, "tokens_accounted": 18000,
                      "total_tokens": 0, "unknown_usage_calls": 1},
            "evidence_refs": [{"record_id": "record-ref", "artifact_sha256": "artifact-ref", "snapshot": "snapshot-ref",
                               "tool_call_id": "child:source-read"}],
            "rows": [{"model_free_value": "FORBIDDEN_MODEL_FREE_NUMBER_999"}]}]
        report["root_budget"] = {"decisions_accounted": 4, "tools_accounted": 1, "tokens_accounted": 20000,
            "tokens_reserved": 20000, "tokens_dispatched_reserved": 2000, "model_attempts": 1, "tool_attempts": 0,
            "total_tokens": 0, "unknown_usage_calls": 0, "unresolved_child_allocations": 1}
        report["trace"] += [{"seq": 100, "time": "2026-10-05T00:00:00+08:00", "event": "finish_rejected", "turn": 1}]
        before = deepcopy(report)
        rendered = markdown(report)
        for label in ("Runtime 结束拒绝反馈", "required_checks_pending", "verification", "Financial Child 与父子证据关联",
                      "child-synthetic", "request-ref", "result-ref", "record-ref", "artifact-ref", "snapshot-ref",
                      "child:source-read", "根预算账本", "未知 Child 结果保留已占用额度", "尚未结算的 Child 额度",
                      "Runtime 拒绝提前结束"):
            self.assertIn(label, rendered)
        self.assertNotIn("FORBIDDEN_MODEL_FREE_NUMBER_999", rendered)
        self.assertEqual(report, before)

    def test_child_reference_and_rejection_text_are_escaped(self):
        report = self.report()
        report["decisions"] = [{"turn": 1, "status": "verified", "token_reservation": 1,
                                "rejection": {"code": "required_checks_pending", "pending_checks": ["<script>bad</script> | check"]}}]
        report["child_results"] = []
        report["root_budget"] = {"tokens_accounted": 1}
        rendered = markdown(report)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&#124; check", rendered)
        self.assertIn("尚无已返回的 Financial Child 结果", rendered)


if __name__ == "__main__":
    unittest.main()
