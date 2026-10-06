"""Synthetic opt-in CLI regression; no paid calls or live Providers."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_domain_agents_cli as fixture_cli
from test_parallel_runtime import RoleModel
from test_dynamic import tool, finish
from stock_research.research import cli
from stock_research.errors import ValidationError


class ParallelCLITests(unittest.TestCase):
    setUp = fixture_cli.DomainAgentsCLITests.setUp
    args = fixture_cli.DomainAgentsCLITests.args

    def test_preview_is_opt_in_and_has_zero_reads_credentials_or_child(self):
        args = self.args("--parallel-domains", "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            result = cli.run(args, self.f.repo)
            config.assert_not_called()
            store.assert_not_called()
        payload = json.loads((Path(args.output) / "preview.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["spec_version"], "dynamic-parent-parallel-v1")
        self.assertTrue(payload["parallel_domains_enabled"])
        self.assertEqual(result["usage"]["model_attempts"], 0)
        self.assertEqual(payload["context_representation"]["byte_budget"], 12000)

    def test_parallel_cli_export_contains_real_shared_runtime_group_trace(self):
        args, model = self.args("--parallel-domains", "--with-model"), RoleModel()
        with patch.object(cli, "load_model_config", return_value=model.config), \
             patch.object(cli, "ChatModelAdapter", return_value=model):
            result = cli.run(args, self.f.repo)
        self.assertEqual(result["status"], "completed")
        report = json.loads((Path(args.output) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["trace_stratum"], "parallel_2_child")
        self.assertEqual(len(report["parallel_groups"]), 1)
        self.assertTrue(report["context_telemetry"])

    def test_parallel_mode_rejects_mixed_or_legacy_options_before_config(self):
        options = (("--financial-child",), ("--domain-agents",), ("--dynamic-version", "single-dynamic-v1"),
                   ("--domain-version", "dynamic-parent-domains-v2"))
        for extra in options:
            with self.subTest(extra=extra), patch.object(cli, "load_model_config") as config:
                with self.assertRaises(ValidationError):
                    cli.run(self.args("--parallel-domains", "--with-model", *extra), self.f.repo)
                config.assert_not_called()

    def test_new_parent_preserves_direct_and_serial_delegated_paths(self):
        for sources, expected in ((("financial", "market"), "parent_direct"),
            (("financial_child", "market"), "parent_1_child"),
            (("financial_child", "market_child"), "parent_2_child")):
            with self.subTest(sources=sources):
                args = self.args("--parallel-domains", "--with-model")
                args.output += expected
                model = RoleModel(parent_actions=[*[tool(n) for n in sources],
                    tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                    tool("verification", ["hypotheses"]), finish()])
                with patch.object(cli, "load_model_config", return_value=model.config), \
                     patch.object(cli, "ChatModelAdapter", return_value=model):
                    result = cli.run(args, self.f.repo)
                self.assertEqual(result["status"], "completed")
                report = json.loads((Path(args.output) / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["trace_stratum"], expected)
                self.assertEqual(report["parallel_groups"], [])
