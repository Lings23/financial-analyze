"""Explicit experimental entrance and zero-dispatch preview, synthetic only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_domain_agents_cli as legacy_cli
from test_domain_analysis_runtime import AnalysisModel
from stock_research.errors import ValidationError
from stock_research.research import cli
from stock_research.research.domain_analysis_contracts import DomainAnalysisParentSpec


class DomainAnalysisCLITests(unittest.TestCase):
    def setUp(self):
        legacy_cli.DomainAgentsCLITests.setUp(self)

    def args(self, *options):
        return legacy_cli.DomainAgentsCLITests.args(self, *options)

    def test_default_remains_legacy_and_analysis_is_explicit(self):
        args = self.args("--preview-model")
        self.assertIsNone(args.domain_analysis_mode)
        self.assertEqual(args.child_protocol_version, "v1")
        self.assertEqual(args.parallel_version, "dynamic-parent-parallel-v1")
        self.assertEqual(DomainAnalysisParentSpec(mode="child").max_decisions, 6)
        self.assertEqual(DomainAnalysisParentSpec(mode="tool").max_decisions, 8)

    def test_three_preview_routes_without_reads_model_or_checkpoint(self):
        for mode, tools in (("direct", {"financial", "market"}),
                            ("tool", {"financial_analysis_tool", "market_analysis_tool"}),
                            ("child", {"financial_child", "market_child"})):
            with self.subTest(mode=mode):
                args = self.args("--domain-analysis-mode", mode, "--preview-model")
                args.output = str(self.root / mode)
                with patch.object(cli.DataService, "query", side_effect=AssertionError("preview cannot read")), \
                        patch.object(cli, "CheckpointStore", side_effect=AssertionError("preview cannot checkpoint")), \
                        patch.object(cli, "load_model_config", side_effect=AssertionError("preview cannot load credentials")):
                    result = cli.run(args, self.f.repo)
                preview = json.loads((Path(args.output) / "preview.json").read_text(encoding="utf-8"))
                payload = json.loads(json.loads(Path(result["messages"]).read_text(encoding="utf-8"))[1]["content"])
                self.assertEqual(preview["spec_identity"], DomainAnalysisParentSpec(mode=mode).identity)
                self.assertEqual(preview["domain_analysis"]["mode"], mode)
                self.assertTrue(tools <= set(payload["available_tools"]))
                self.assertTrue(all(value == 0 for value in result["usage"].values()))

    def test_mixing_analysis_and_old_protocol_rejected_before_loading_credentials(self):
        for options in (("--domain-agents",), ("--parallel-domains",),
                        ("--child-protocol-version", "v3"),
                        ("--parallel-version", "dynamic-parent-parallel-v6")):
            with self.subTest(options=options), patch.object(cli, "load_model_config") as configuration:
                with self.assertRaises(ValidationError):
                    cli.run(self.args("--domain-analysis-mode", "child", "--with-model", *options), self.f.repo)
                configuration.assert_not_called()

    def test_actual_cli_writes_complete_domain_report_using_same_runtime(self):
        args = self.args("--domain-analysis-mode", "child", "--domain-analysis-execution", "serial", "--with-model")
        model = AnalysisModel()
        with patch.object(cli, "load_model_config", return_value=model.config), \
                patch.object(cli, "ChatModelAdapter", return_value=model):
            result = cli.run(args, self.f.repo)
        report = json.loads((Path(args.output) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(report["domain_analysis"]["mode"], "child")
        self.assertEqual(set(report["domain_analysis"]["results"]), {"financial", "market"})
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertEqual(report["usage"]["financial_provider_network_calls"], 0)


if __name__ == "__main__":
    unittest.main()
