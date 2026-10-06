"""Explicit v3 selection and checkpoint compatibility; synthetic calls only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_domain_agents_cli as fixture_cli
from test_dynamic import SequenceModel, finish, tool
from stock_research.errors import PermissionDenied
from stock_research.research import cli
from stock_research.research.dynamic_contracts import FinancialChildSpec, MarketChildSpec


class ChildProgressV3CLITests(unittest.TestCase):
    setUp = fixture_cli.DomainAgentsCLITests.setUp
    args = fixture_cli.DomainAgentsCLITests.args

    def test_preview_explicit_v3_preserves_limits_and_has_no_model_call(self):
        args = self.args("--parallel-domains", "--child-protocol-version", "v3", "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            cli.run(args, self.f.repo)
            config.assert_not_called()
            store.assert_not_called()
        preview = json.loads((Path(args.output) / "preview.json").read_text(encoding="utf-8"))
        self.assertEqual(preview["child_protocol_version"], "v3")
        self.assertEqual(preview["child_spec_identities"], {
            "financial": FinancialChildSpec(version="financial-child-v3").identity,
            "market": MarketChildSpec(version="market-child-v3").identity})
        self.assertEqual(preview["context_representation"]["byte_budget"], 12000)

    def test_completed_v3_requires_matching_protocol_for_zero_call_resume(self):
        actions = [tool("financial_child"), tool("financial"), finish(), tool("market"),
                   tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                   tool("verification", ["hypotheses"]), finish()]
        args = self.args("--domain-agents", "--child-protocol-version", "v3", "--with-model")
        model = SequenceModel(actions)
        with patch.object(cli, "load_model_config", return_value=model.config), patch.object(cli, "ChatModelAdapter", return_value=model):
            result = cli.run(args, self.f.repo)
        self.assertEqual(result["status"], "completed")
        for version in ("v1", "v2", "v3"):
            retry = self.args("--domain-agents", "--child-protocol-version", version,
                              "--with-model", "--resume", result["run_id"])
            retry.output += version
            no_calls = SequenceModel([])
            with patch.object(cli, "load_model_config", return_value=no_calls.config), patch.object(cli, "ChatModelAdapter", return_value=no_calls):
                if version == "v3":
                    self.assertEqual(cli.run(retry, self.f.repo)["status"], "completed")
                else:
                    with self.assertRaisesRegex(PermissionDenied, "configuration differs"):
                        cli.run(retry, self.f.repo)
                    self.assertFalse(Path(retry.output).exists())
            self.assertEqual(no_calls.calls, 0)
