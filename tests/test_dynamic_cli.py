"""Synthetic CLI/protocol checks; never live model or financial ground truth."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from research_fixtures import FixtureModel, fixture
from stock_research.__main__ import parser
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.research import cli
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest


class DynamicCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fixture(self.root / "synthetic")
        self.manifest = self.root / "request.json"
        self.base = {**self.f.request.to_dict(), "hypotheses": ["financial_deterioration"]}
        self.write_manifest(self.base)

    def write_manifest(self, value):
        self.manifest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def arguments(self, *options):
        return parser().parse_args([
            "research", "--request", str(self.manifest), "--scope", self.f.access.scope,
            "--allow-provider", "fixture", "--artifacts", str(self.f.artifacts.root),
            "--runs", str(self.root / "runs"), "--output", str(self.root / "output"),
            "--workflow", "dynamic", *options,
        ])

    def synthetic_report(self):
        request = StudyRequest.from_dict(self.base)
        report = StudyRuntime(self.f.service, self.f.store).run(request, self.f.access)
        report.update(schema="dynamic-research/v1", execution_strategy="dynamic",
                      plans=[{"turn": 1, "steps": ["读取利润表", "依据 Observation 调整检查"]},
                             {"turn": 2, "steps": ["校验财务引用后结束"]}],
                      decisions=[{"turn": 1, "status": "accepted", "action": {"type": "tool", "tool": "financial"},
                                  "token_reservation": 1200, "total_tokens": 120},
                                 {"turn": 2, "status": "accepted", "action": {"type": "finish"},
                                  "token_reservation": 1300, "total_tokens": None}],
                      required_checks=[{"id": "financial_deterioration", "status": "passed"}])
        report["request"]["question"] = "检查收入与利润是否同时下降"
        report["usage"].update(total_tokens=120, tokens_accounted=1420, unknown_usage_calls=1,
                               financial_provider_network_calls=0)
        report["trace"] += [{"seq": 99, "time": "2026-10-04T00:00:00+08:00", "event": "repeated_action",
                              "turn": 2, "tool": "financial", "reason": "no_new_evidence"}]
        return report

    def test_parser_keeps_legacy_default_and_accepts_dynamic_question(self):
        args = self.arguments("--question", "检查收入与利润", "--preview-model")
        self.assertEqual(args.workflow, "dynamic")
        self.assertEqual(args.question, "检查收入与利润")
        legacy = parser().parse_args(["research", "--request", "request.json", "--scope", "local",
                                     "--allow-provider", "fixture", "--artifacts", "artifacts", "--output", "new"])
        self.assertEqual(legacy.workflow, "overview")
        self.assertIsNone(legacy.question)
        self.assertEqual(legacy.study_version, "single-research-v4")

    def test_dynamic_requires_explicit_model_or_preview_without_loading_secrets(self):
        args = self.arguments("--question", "检查财务")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as checkpoints:
            with self.assertRaisesRegex(ValidationError, "requires --with-model or --preview-model"):
                cli.run(args, self.f.repo)
        config.assert_not_called()
        checkpoints.assert_not_called()
        self.assertFalse(Path(args.output).exists())

    def test_mutually_exclusive_execution_modes_and_preview_resume_rejected(self):
        for options in (("--with-model", "--preview-model"), ("--preview-model", "--resume", "a" * 32)):
            with self.subTest(options=options), patch.object(cli, "load_model_config") as config:
                with self.assertRaises(ValidationError):
                    cli.run(self.arguments("--question", "检查财务", *options), self.f.repo)
                config.assert_not_called()

    def test_question_is_only_accepted_by_dynamic_workflow(self):
        args = self.arguments("--question", "检查财务", "--preview-model")
        args.workflow = "research"
        with self.assertRaisesRegex(ValidationError, "requires --workflow dynamic"):
            cli.run(args, self.f.repo)

    def test_preview_generates_only_first_messages_without_tools_paid_runtime_or_config(self):
        from stock_research.research.dynamic import DynamicRuntime
        args = self.arguments("--question", "检查收入与利润是否同时下降", "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "ChatModelAdapter") as adapter, \
                patch.object(cli, "CheckpointStore") as checkpoints, \
                patch.object(DynamicRuntime, "run") as running, \
                patch.object(cli.DataService, "query", side_effect=AssertionError("preview executed a data tool")) as query:
            result = cli.run(args, self.f.repo)
        config.assert_not_called()
        adapter.assert_not_called()
        checkpoints.assert_not_called()
        running.assert_not_called()
        query.assert_not_called()
        self.assertEqual(result["status"], "preview")
        self.assertIsNone(result["run_id"])
        self.assertEqual(result["model"]["status"], "not_called")
        self.assertTrue(all(value == 0 for value in result["usage"].values()))
        target = Path(args.output)
        self.assertEqual({path.name for path in target.iterdir()}, {"model-messages.json", "preview.json", "preview.md"})
        preview = json.loads((target / "preview.json").read_text(encoding="utf-8"))
        messages = json.loads((target / "model-messages.json").read_text(encoding="utf-8"))
        self.assertEqual(preview["request"]["question"], args.question)
        self.assertIn(args.question, str(messages))
        self.assertNotIn("source_url", str(messages))
        self.assertNotIn("facts", preview)
        self.assertFalse(Path(args.runs).exists())
        self.assertIn("未调用模型或执行研究工具", (target / "preview.md").read_text(encoding="utf-8"))

    def test_preview_rechecks_provider_authorization_and_does_not_export_on_denial(self):
        args = self.arguments("--question", "检查财务", "--preview-model")
        args.allow_provider = ["other"]
        with patch.object(cli, "load_model_config") as config:
            with self.assertRaises(PermissionDenied):
                cli.run(args, self.f.repo)
        config.assert_not_called()
        self.assertFalse(Path(args.output).exists())
        self.assertFalse(Path(args.runs).exists())

    def test_pinned_manifest_question_is_preserved_and_inconsistent_cli_question_rejected(self):
        question = "检查收入与利润是否同时下降"
        self.write_manifest({**self.base, "question": question})
        args = self.arguments("--question", "改成另一问题", "--preview-model")
        with self.assertRaisesRegex(ValidationError, "differs from the pinned manifest question"):
            cli.run(args, self.f.repo)
        result = cli.run(self.arguments("--preview-model"), self.f.repo)
        preview = json.loads((Path(result["report"]).parent / "preview.json").read_text(encoding="utf-8"))
        self.assertEqual(preview["request"]["question"], question)
        self.assertEqual(json.loads(self.manifest.read_text(encoding="utf-8"))["question"], question)

    def test_missing_question_duplicate_keys_and_nonobject_manifest_rejected(self):
        for manifest in (json.dumps(self.base), json.dumps({**self.base, "question": ""}),
                         '{"question":"x","question":"y"}', '[]'):
            with self.subTest(manifest=manifest):
                self.manifest.write_text(manifest, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    cli.run(self.arguments("--preview-model"), self.f.repo)
                self.assertFalse((self.root / "output").exists())

    def test_dynamic_execution_routes_authorized_model_and_exports_exact_report(self):
        from stock_research.research.dynamic import DynamicRuntime
        report = self.synthetic_report()
        args = self.arguments("--question", report["request"]["question"], "--with-model", "--resume", "a" * 32)
        model = FixtureModel()
        with patch.object(cli, "load_model_config", return_value=model.config) as config, \
                patch.object(cli, "ChatModelAdapter", return_value=model) as adapter, \
                patch.object(DynamicRuntime, "run", return_value=report) as running:
            result = cli.run(args, self.f.repo)
        config.assert_called_once_with(args.config)
        adapter.assert_called_once_with(model.config)
        self.assertEqual(running.call_args.kwargs, {"resume": "a" * 32})
        self.assertEqual(running.call_args.args[0].question, args.question)
        self.assertEqual(running.call_args.args[1], self.f.access)
        exported = json.loads((Path(args.output) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(exported, report)
        self.assertEqual(result["status"], report["status"])
        self.assertIn("动态单股研究", Path(result["report"]).read_text(encoding="utf-8"))
        self.assertFalse((Path(args.output) / "model-messages.json").exists())

    def test_cli_exports_actual_synthetic_dynamic_loop_and_control_trace(self):
        actions = [
            {"action": "tool", "tool": "market", "refs": [], "plan": ["读取冻结行情"]},
            {"action": "tool", "tool": "financial", "refs": [], "plan": ["观察行情后读取利润表"]},
            {"action": "tool", "tool": "calculation", "refs": ["financial", "market"], "plan": ["计算已绑定数据"]},
            {"action": "tool", "tool": "hypotheses", "refs": ["calculation"], "plan": ["检验财务方向"]},
            {"action": "tool", "tool": "verification", "refs": ["hypotheses"], "plan": ["核验数值及引用"]},
            {"action": "finish", "reason": "completed", "plan": ["已完成必需检查"]},
        ]

        class SyntheticSequence(FixtureModel):
            def complete(self, messages, **kwargs):
                self.content = json.dumps(actions[self.calls], ensure_ascii=False)
                return super().complete(messages, **kwargs)

        model = SyntheticSequence()
        args = self.arguments("--question", "检查收入与利润是否同时下降", "--with-model")
        with patch.object(cli, "load_model_config", return_value=model.config), \
                patch.object(cli, "ChatModelAdapter", return_value=model):
            result = cli.run(args, self.f.repo)
        report = json.loads((Path(args.output) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(report["schema"], "dynamic-research/v1")
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertEqual(model.calls, len(actions))
        self.assertEqual(report["usage"]["model_attempts"], 6)
        self.assertEqual(report["usage"]["tool_calls"], 5)
        self.assertEqual(report["usage"]["financial_provider_network_calls"], 0)
        self.assertEqual(len(report["plans"]), 6)
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))
        self.assertTrue(any(event["event"] == "tool_finished" for event in report["trace"]))
        self.assertIn("synthetic_fixture", Path(result["report"]).read_text(encoding="utf-8"))
        self.assertIn("plan_updated", json.dumps(report))

    def test_existing_output_rejected_before_any_model_configuration(self):
        args = self.arguments("--question", "检查财务", "--with-model")
        Path(args.output).mkdir()
        original = Path(args.output) / "preserved.txt"
        original.write_text("preserved", encoding="utf-8")
        with patch.object(cli, "load_model_config") as config:
            with self.assertRaisesRegex(ValidationError, "already exists"):
                cli.run(args, self.f.repo)
        config.assert_not_called()
        self.assertEqual(original.read_text(encoding="utf-8"), "preserved")

    def test_markdown_shows_control_records_checks_usage_and_escapes_untrusted_plan(self):
        report = self.synthetic_report()
        report["plans"][0]["steps"][0] = "<script>bad</script> [click](javascript:bad) | plan"
        original = copy.deepcopy(report)
        rendered = markdown(report)
        for label in ("动态单股研究", "可见计划更新（控制信息）", "模型决策记录", "事前必需检查",
                      "工具与运行记录", "重复动作未重新派发", "假设检验与综合", "已知实测 Token 120",
                      "未知用量调用 1", "未完成时保留 partial / insufficient"):
            self.assertIn(label, rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("[click]", rendered)
        self.assertIn("&#124; plan", rendered)
        self.assertEqual(report, original)


if __name__ == "__main__":
    unittest.main()
