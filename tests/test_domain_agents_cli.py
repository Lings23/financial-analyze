"""Synthetic P4.4 CLI/report boundaries; no live model or Provider certification."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research_fixtures import FixtureModel, fixture
from test_dynamic import SequenceModel, finish, tool
from stock_research.__main__ import parser
from stock_research.errors import ValidationError
from stock_research.research import cli
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DomainParentSpec, DynamicSpec, FinancialParentSpec
from stock_research.research.report import financial_child_sections, markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest


class DomainAgentsCLITests(unittest.TestCase):
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
            "--question", "SYNTHETIC: inspect the two bound source domains", *options,
        ])

    def report(self):
        report = StudyRuntime(self.f.service, self.f.store).run(StudyRequest.from_dict(self.request), self.f.access)
        report.update(schema="dynamic-research/v1", execution_strategy="dynamic", plans=[], decisions=[],
                      required_checks=[{"id": "verification", "status": "passed"}])
        report["request"]["question"] = "SYNTHETIC: inspect the two bound source domains"
        return report

    def test_domain_mode_is_explicit_and_does_not_change_legacy_spec_identities(self):
        args = self.args("--preview-model")
        self.assertFalse(args.domain_agents)
        self.assertFalse(args.financial_child)
        self.assertEqual(args.dynamic_version, "single-dynamic-v2")
        self.assertEqual(args.domain_version, "dynamic-parent-domains-v2")
        self.assertFalse(args.domain_version_explicit)
        self.assertEqual(DynamicSpec().version, "single-dynamic-v1")
        self.assertEqual(FinancialParentSpec().version, "dynamic-parent-financial-v1")
        self.assertNotEqual(DomainParentSpec().identity, FinancialParentSpec().identity)

    def test_conflicting_or_non_v2_domain_options_reject_before_any_execution(self):
        cases = [self.args("--domain-agents", "--financial-child", "--with-model"),
                 self.args("--domain-agents", "--dynamic-version", "single-dynamic-v1", "--with-model")]
        fixed = self.args("--domain-agents", "--with-model")
        fixed.workflow, fixed.question = "research", None
        cases.append(fixed)
        for args in cases:
            with self.subTest(workflow=args.workflow, version=args.dynamic_version), \
                    patch.object(cli, "load_model_config") as config, patch.object(cli, "ChatModelAdapter") as model, \
                    patch.object(cli, "CheckpointStore") as checkpoints, patch.object(cli, "DataService") as service:
                with self.assertRaisesRegex(ValidationError, "mutually exclusive|--domain-agents requires"):
                    cli.run(args, self.f.repo)
                for mock in (config, model, checkpoints, service):
                    mock.assert_not_called()
                self.assertFalse(Path(args.output).exists())

    def test_domain_mode_still_requires_explicit_live_or_preview_authorization(self):
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as checkpoints:
            with self.assertRaisesRegex(ValidationError, "requires --with-model or --preview-model"):
                cli.run(self.args("--domain-agents"), self.f.repo)
            config.assert_not_called()
            checkpoints.assert_not_called()
        self.assertFalse((self.root / "output").exists())

    def test_domain_preview_lists_both_children_without_reads_models_or_checkpoints(self):
        args = self.args("--domain-agents", "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "ChatModelAdapter") as model, \
                patch.object(cli, "CheckpointStore") as checkpoints, patch.object(DynamicRuntime, "run") as run, \
                patch.object(cli.DataService, "query", side_effect=AssertionError("preview source read")) as query:
            result = cli.run(args, self.f.repo)
        for mock in (config, model, checkpoints, run, query):
            mock.assert_not_called()
        target = Path(args.output)
        preview = json.loads((target / "preview.json").read_text(encoding="utf-8"))
        messages = json.loads((target / "model-messages.json").read_text(encoding="utf-8"))
        payload = json.loads(messages[1]["content"])
        self.assertEqual(preview["spec_version"], "dynamic-parent-domains-v2")
        self.assertEqual(preview["spec_identity"], DomainParentSpec(version="dynamic-parent-domains-v2").identity)
        self.assertTrue(preview["domain_agents_enabled"])
        self.assertTrue(preview["financial_child_enabled"])
        self.assertTrue({"financial_child", "market_child", "financial", "market"} <= set(payload["available_tools"]))
        self.assertEqual(payload["protocol_version"], "dynamic-parent-domains-v2")
        self.assertEqual(payload["context"]["observations"], [])
        self.assertEqual(payload["completed_tools"], [])
        self.assertEqual(payload["delegation_results"], [])
        self.assertTrue(all(value == 0 for value in result["usage"].values()))
        self.assertFalse(Path(args.runs).exists())
        self.assertNotIn("child_results", preview)
        self.assertIn("未启动 Financial / Market Child", (target / "preview.md").read_text(encoding="utf-8"))
        self.assertEqual({p.name for p in target.iterdir()}, {"model-messages.json", "preview.json", "preview.md"})

    def test_legacy_financial_preview_does_not_advertise_market_or_new_metadata(self):
        args = self.args("--financial-child", "--preview-model")
        cli.run(args, self.f.repo)
        target = Path(args.output)
        preview = json.loads((target / "preview.json").read_text(encoding="utf-8"))
        payload = json.loads(json.loads((target / "model-messages.json").read_text(encoding="utf-8"))[1]["content"])
        self.assertEqual(preview["spec_version"], FinancialParentSpec().version)
        self.assertNotIn("domain_agents_enabled", preview)
        self.assertNotIn("market_child", payload["available_tools"])
        self.assertIn("未启动 Financial Child", (target / "preview.md").read_text(encoding="utf-8"))

    def test_live_opt_in_uses_same_runtime_and_explicit_parent_identity(self):
        model = FixtureModel()
        report = self.report()
        with patch("stock_research.research.dynamic.DynamicRuntime", autospec=True) as runtime, \
                patch.object(cli, "load_model_config", return_value=model.config), \
                patch.object(cli, "ChatModelAdapter", return_value=model):
            runtime.return_value.run.return_value = report
            result = cli.run(self.args("--domain-agents", "--with-model", "--resume", "synthetic-resume"), self.f.repo)
        spec = runtime.call_args.kwargs["spec"]
        self.assertIs(type(spec), DomainParentSpec)
        self.assertEqual(spec.version, "dynamic-parent-domains-v2")
        self.assertEqual(runtime.call_args.args[2], model)
        self.assertEqual(runtime.return_value.run.call_args.kwargs, {"resume": "synthetic-resume"})
        self.assertEqual(result["status"], report["status"])

    def test_actual_two_serial_children_cli_exports_and_resumes_without_model_calls(self):
        model = SequenceModel([
            tool("financial_child"), tool("financial"), finish(),
            tool("market_child"), tool("market"), finish(),
            tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
            tool("verification", ["hypotheses"]), finish(),
        ])
        reports = {}
        actual_run = DynamicRuntime.run

        def record_actual_run(runtime, *args, **kwargs):
            report = actual_run(runtime, *args, **kwargs)
            reports[report["run_id"]] = deepcopy(report)
            return report

        args = self.args("--domain-agents", "--domain-version", "dynamic-parent-domains-v1", "--with-model")
        with patch.object(cli, "load_model_config", return_value=model.config), \
                patch.object(cli, "ChatModelAdapter", return_value=model), \
                patch.object(DynamicRuntime, "run", new=record_actual_run):
            result = cli.run(args, self.f.repo)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.calls, 10)
        protocols = [json.loads(messages[1]["content"])["protocol_version"] for messages in model.messages]
        self.assertEqual(protocols, ["dynamic-parent-domains-v1", "financial-child-v1", "financial-child-v1",
                                     "dynamic-parent-domains-v1", "market-child-v1", "market-child-v1",
                                     *["dynamic-parent-domains-v1"] * 4])
        target = Path(args.output)
        exported = json.loads((target / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(exported, reports[result["run_id"]])
        self.assertEqual(exported["verification"]["status"], "verified")
        self.assertEqual(len(exported["child_results"]), 2)
        self.assertEqual({child["domain"] for child in exported["child_results"]}, {"financial", "market"})
        delegates = [route for route in exported["routes"] if route["mode"] == "delegated"]
        self.assertEqual(len(delegates), 2)
        self.assertEqual({route["child_run_id"] for route in delegates},
                         {child["child_run_id"] for child in exported["child_results"]})
        for child in exported["child_results"]:
            self.assertEqual(child["schema"], child["domain"] + "-child-result/v1")
            self.assertEqual(child["status"], "completed")
            self.assertTrue(child["source_result_ref"])
            self.assertTrue(child["evidence_refs"])
            self.assertTrue(all(check["status"] == "passed" for check in child["required_checks"]))
        rendered = (target / "report.md").read_text(encoding="utf-8")
        self.assertEqual(rendered, markdown(exported))
        self.assertIn("Financial Child 运行", rendered)
        self.assertIn("Market Child 运行", rendered)
        self.assertIn("Parent 领域路由", rendered)
        self.assertEqual(exported["root_budget"]["model_attempts"], 10)
        self.assertEqual(exported["root_budget"]["total_tokens"], 1200)

        no_more_calls = SequenceModel([])
        resumed_args = self.args("--domain-agents", "--domain-version", "dynamic-parent-domains-v1",
                                 "--with-model", "--resume", result["run_id"])
        resumed_args.output = str(self.root / "resumed-output")
        with patch.object(cli, "load_model_config", return_value=no_more_calls.config), \
                patch.object(cli, "ChatModelAdapter", return_value=no_more_calls), \
                patch.object(DynamicRuntime, "run", new=record_actual_run):
            resumed = cli.run(resumed_args, self.f.repo)
        resumed_report = json.loads((Path(resumed_args.output) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(no_more_calls.calls, 0)
        self.assertEqual(resumed["run_id"], result["run_id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed_report, reports[result["run_id"]])
        for field in ("child_results", "root_budget", "routes", "facts", "evidence"):
            self.assertEqual(resumed_report[field], exported[field])
        self.assertEqual((Path(resumed_args.output) / "report.md").read_text(encoding="utf-8"), markdown(resumed_report))

    def test_report_displays_routes_domains_and_evidence_without_arbitrary_child_rows(self):
        report = self.report()
        report["routes"] = [
            {"turn": 1, "tool": "financial", "mode": "direct", "domain": "financial", "tool_call_id": "direct-fin"},
            {"turn": 2, "tool": "market_child", "mode": "delegated", "domain": "market", "tool_call_id": "delegate-market",
             "child_run_id": "market-synthetic"},
            {"turn": 3, "tool": "calculation", "mode": "direct", "domain": "research", "tool_call_id": "derive"},
        ]
        report["child_results"] = []
        for domain in ("financial", "market"):
            report["child_results"].append({"domain": domain, "schema": domain + "-child-result/v1",
                "child_run_id": domain + "-synthetic", "parent_run_id": report["run_id"], "tool_call_id": "delegate-" + domain,
                "status": "completed", "stop_reason": None, "request_ref": domain + "-request-ref",
                "result_ref": domain + "-result-ref", "source_result_ref": domain + "-source-ref",
                "deadline": "2026-10-05T00:02:00+08:00", "required_checks": [{"id": "read:" + domain, "status": "passed"}],
                "usage": {"model_attempts": 2, "tool_calls": 1, "tokens_accounted": 240, "total_tokens": 240},
                "evidence_refs": [{"record_id": domain + "-record", "artifact_sha256": domain + "-sha",
                                   "snapshot": domain + "-snapshot", "tool_call_id": domain + "-source-call"}],
                "rows": [{"value": "FORBIDDEN_FREE_VALUE_888"}]})
        report["root_budget"] = {"tokens_accounted": 480, "total_tokens": 480, "unresolved_child_allocations": 0}
        report["trace"] += [{"seq": 100, "time": "2026-10-05T00:00:00+08:00", "event": "child_started",
                             "turn": 2, "domain": "market"}]
        before = deepcopy(report)
        rendered = markdown(report)
        for label in ("Parent 领域路由", "Financial / 财务", "Market / 行情", "研究计算与校验", "直接工具", "AgentTool 委派",
                      "direct-fin", "delegate-market", "领域 Child 与父子证据关联", "Financial Child 运行",
                      "Market Child 运行", "financial-record", "market-record", "market-sha", "market-snapshot",
                      "market-source-call", "Market Child 开始", "根预算账本"):
            self.assertIn(label, rendered)
        self.assertNotIn("FORBIDDEN_FREE_VALUE_888", rendered)
        self.assertEqual(report, before)

    def test_new_route_fields_are_escaped_and_old_optional_sections_remain_exact(self):
        legacy = {"child_results": []}
        self.assertEqual(financial_child_sections(legacy), ["## Financial Child 与父子证据关联", "",
            "本入口允许一个串行、受限的 Financial Child。父子运行沿用绑定的证券、窗口、cutoff、PIT 和快照；"
            "Child 的状态与来源引用不替代父运行的必需检查或独立数值校验。", "",
            "尚无已返回的 Financial Child 结果。", ""])
        self.assertEqual(financial_child_sections({}), [])
        report = self.report()
        report["routes"] = [{"turn": 1, "tool": "<script>bad</script> | source", "mode": "direct",
                             "domain": "market", "tool_call_id": "<ref> | call", "child_run_id": "<child>"}]
        rendered = markdown(report)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<child>", rendered)
        self.assertIn("&#124; source", rendered)
        self.assertIn("尚无已返回的领域 Child 结果", rendered)


if __name__ == "__main__":
    unittest.main()
