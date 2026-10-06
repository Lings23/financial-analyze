"""Explicit protocol compatibility checks using synthetic transports only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_domain_agents_cli as fixture_cli
from test_dynamic import SequenceModel, finish, tool
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.research import cli
from stock_research.research.dynamic_contracts import FinancialChildSpec, MarketChildSpec


class ChildProgressCLITests(unittest.TestCase):
    setUp = fixture_cli.DomainAgentsCLITests.setUp
    args = fixture_cli.DomainAgentsCLITests.args

    def test_v2_requires_child_mode_before_credentials_or_output(self):
        args = self.args("--child-protocol-version", "v2", "--with-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            with self.assertRaisesRegex(ValidationError, "requires a Child parent mode"):
                cli.run(args, self.f.repo)
            config.assert_not_called()
            store.assert_not_called()
        self.assertFalse(Path(args.output).exists())

    def test_preview_records_explicit_child_versions_without_dispatch(self):
        for mode in ("--financial-child", "--domain-agents", "--parallel-domains"):
            with self.subTest(mode=mode):
                args = self.args(mode, "--child-protocol-version", "v2", "--preview-model")
                args.output += mode
                with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
                    cli.run(args, self.f.repo)
                    config.assert_not_called()
                    store.assert_not_called()
                preview = json.loads((Path(args.output) / "preview.json").read_text(encoding="utf-8"))
                expected = {"financial": FinancialChildSpec(version="financial-child-v2").identity}
                if mode != "--financial-child":
                    expected["market"] = MarketChildSpec(version="market-child-v2").identity
                self.assertEqual(preview["child_spec_identities"], expected)
                self.assertEqual(preview["child_protocol_version"], "v2")

    def test_v2_serial_run_replays_only_with_matching_child_configuration(self):
        actions = [tool("financial_child"), tool("financial"), finish(), tool("market_child"),
                   tool("market"), finish(), tool("calculation", ["financial", "market"]),
                   tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()]
        args = self.args("--domain-agents", "--child-protocol-version", "v2", "--with-model")
        model = SequenceModel(actions)
        with patch.object(cli, "load_model_config", return_value=model.config), patch.object(cli, "ChatModelAdapter", return_value=model):
            result = cli.run(args, self.f.repo)
        self.assertEqual(result["status"], "completed")
        for version, should_pass in (("v1", False), ("v2", True)):
            retry = self.args("--domain-agents", "--child-protocol-version", version, "--with-model", "--resume", result["run_id"])
            retry.output += version
            no_calls = SequenceModel([])
            with patch.object(cli, "load_model_config", return_value=no_calls.config), patch.object(cli, "ChatModelAdapter", return_value=no_calls):
                if should_pass:
                    resumed = cli.run(retry, self.f.repo)
                    self.assertEqual(resumed["status"], "completed")
                else:
                    with self.assertRaisesRegex(PermissionDenied, "configuration differs"):
                        cli.run(retry, self.f.repo)
                    self.assertFalse(Path(retry.output).exists())
            self.assertEqual(no_calls.calls, 0)


if __name__ == "__main__":
    unittest.main()
