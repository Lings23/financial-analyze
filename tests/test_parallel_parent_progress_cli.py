"""Synthetic Parent v2 CLI compatibility tests; no live model or financial truth."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_domain_agents_cli as fixture_cli
from stock_research.errors import ValidationError
from stock_research.research import cli


class ParallelParentProgressCLITests(unittest.TestCase):
    setUp = fixture_cli.DomainAgentsCLITests.setUp
    args = fixture_cli.DomainAgentsCLITests.args

    def test_explicit_v2_preview_contains_pending_execution_without_credentials(self):
        args = self.args("--parallel-domains", "--parallel-version", "dynamic-parent-parallel-v2", "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            result = cli.run(args, self.f.repo)
            config.assert_not_called()
            store.assert_not_called()
        messages = json.loads((Path(args.output) / "model-messages.json").read_text(encoding="utf-8"))
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["protocol_version"], "dynamic-parent-parallel-v2")
        self.assertFalse(payload["control"]["execution"]["can_finish"])
        self.assertIn("verification", payload["control"]["execution"]["pending_checks"])
        self.assertIsNone(payload["control"]["execution"]["next_action"])
        self.assertEqual(result["usage"]["model_attempts"], 0)

    def test_version_option_requires_parallel_mode_before_credential_load(self):
        for mode in ((), ("--financial-child",), ("--domain-agents",)):
            with self.subTest(mode=mode), patch.object(cli, "load_model_config") as config:
                args = self.args(*mode, "--parallel-version", "dynamic-parent-parallel-v2", "--with-model")
                with self.assertRaises(ValidationError):
                    cli.run(args, self.f.repo)
                config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
