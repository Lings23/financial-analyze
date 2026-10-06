"""Synthetic versioned domain Context CLI checks, without live financial claims."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_domain_agents_cli as legacy_cli
from test_dynamic import SequenceModel, finish, tool
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.research import cli
from stock_research.research.dynamic_contracts import DomainParentSpec, FinancialChildSpec, MarketChildSpec
from stock_research.research.report import domain_context_sections, markdown


class DomainContextCLITests(unittest.TestCase):
    setUp = legacy_cli.DomainAgentsCLITests.setUp
    args = legacy_cli.DomainAgentsCLITests.args

    def test_explicit_domain_version_requires_domain_agents_before_config_or_writes(self):
        for version in ("dynamic-parent-domains-v1", "dynamic-parent-domains-v2"):
            for mode in ("single", "financial", "fixed"):
                args = self.args("--domain-version", version, "--with-model")
                if mode == "financial":
                    args.financial_child = True
                elif mode == "fixed":
                    args.workflow, args.question = "research", None
                with self.subTest(version=version, mode=mode), patch.object(cli, "load_model_config") as config, \
                        patch.object(cli, "CheckpointStore") as checkpoints, patch.object(cli, "DataService") as service:
                    with self.assertRaisesRegex(ValidationError, "--domain-version requires --domain-agents"):
                        cli.run(args, self.f.repo)
                    for mock in (config, checkpoints, service):
                        mock.assert_not_called()
                    self.assertFalse(Path(args.output).exists())

    def test_explicit_v1_preview_and_child_identities_remain_legacy(self):
        v1 = DomainParentSpec(version="dynamic-parent-domains-v1")
        v2 = DomainParentSpec(version="dynamic-parent-domains-v2")
        self.assertNotEqual(v1.identity, v2.identity)
        self.assertEqual(DomainParentSpec().identity, v1.identity)
        self.assertEqual(v2.context_bytes, 12000)
        self.assertEqual(FinancialChildSpec().version, "financial-child-v1")
        self.assertEqual(MarketChildSpec().version, "market-child-v1")
        self.assertEqual(FinancialChildSpec().context_bytes, 12000)
        self.assertEqual(MarketChildSpec().context_bytes, 12000)
        args = self.args("--domain-agents", "--domain-version", v1.version, "--preview-model")
        self.assertTrue(args.domain_version_explicit)
        result = cli.run(args, self.f.repo)
        output = Path(result["report"]).parent
        preview = json.loads((output / "preview.json").read_text(encoding="utf-8"))
        self.assertEqual(preview["spec_version"], v1.version)
        self.assertEqual(preview["spec_identity"], v1.identity)
        self.assertEqual(json.loads(json.loads((output / "model-messages.json").read_text(encoding="utf-8"))[1]["content"])
                         ["protocol_version"], v1.version)
        self.assertEqual(result["usage"]["model_attempts"], 0)

    def test_actual_v2_mixed_export_keeps_complete_evidence_and_wrong_version_resume_rejects(self):
        model = SequenceModel([tool("financial_child"), tool("financial"), finish(), tool("market"),
                               tool("calculation", ["financial", "market"]), tool("hypotheses", ["calculation"]),
                               tool("verification", ["hypotheses"]), finish()])
        args = self.args("--domain-agents", "--with-model")
        with patch.object(cli, "load_model_config", return_value=model.config), \
                patch.object(cli, "ChatModelAdapter", return_value=model):
            result = cli.run(args, self.f.repo)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.calls, 8)
        report = json.loads((Path(args.output) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertTrue(report["facts"])
        self.assertTrue(report["evidence"])
        self.assertEqual(report["verification"]["numeric_claims"], len(report["facts"]))
        rendered = (Path(args.output) / "report.md").read_text(encoding="utf-8")
        for fact in report["facts"]:
            self.assertIn(fact["id"], rendered)
        for identifier in report["evidence"]:
            self.assertIn(identifier, rendered)
        self.assertIn("Financial Child 运行", rendered)
        self.assertIn("Parent 领域路由", rendered)
        no_calls = SequenceModel([])
        wrong_args = self.args("--domain-agents", "--domain-version", "dynamic-parent-domains-v1",
                               "--with-model", "--resume", result["run_id"])
        wrong_args.output = str(self.root / "wrong-version-output")
        with patch.object(cli, "load_model_config", return_value=no_calls.config), \
                patch.object(cli, "ChatModelAdapter", return_value=no_calls):
            with self.assertRaisesRegex(PermissionDenied, "resume request or dynamic configuration differs"):
                cli.run(wrong_args, self.f.repo)
        self.assertEqual(no_calls.calls, 0)
        self.assertFalse(Path(wrong_args.output).exists())

    def test_new_context_metadata_is_audit_only_and_legacy_report_rendering_stays_unchanged(self):
        report = legacy_cli.DomainAgentsCLITests.report(self)
        legacy_context = deepcopy(report["context"])
        self.assertEqual(domain_context_sections(report), [])
        report["context"].update(strategy="lossless_catalog_lazy_disclosure/v1", catalog_ref="catalog-synthetic-ref",
                                 context_stage="verification", claims_preserved=len(report["facts"]),
                                 evidence_preserved=len(report["evidence"]), disclosed_refs=["C:claim", "E:<script> | reference"],
                                 bytes=8000, byte_budget=12000, message_sha256="synthetic-message-sha",
                                 facts_included=len(report["facts"]), evidence_included=len(report["evidence"]), omitted_claims=0,
                                 catalog={"forbidden_extra": "FORBIDDEN_CATALOG_BODY_888"})
        before = deepcopy(report)
        rendered = markdown(report)
        for label in ("无损目录与按需上下文", "catalog-synthetic-ref", "verification", "8000", "12000",
                      "Claim 保留", "Evidence 保留", "目录 Evidence 数", "本轮未展开者", "&#124; reference"):
            self.assertIn(label, rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("FORBIDDEN_CATALOG_BODY_888", rendered)
        for fact in report["facts"]:
            self.assertIn(fact["id"], rendered)
        for identifier in report["evidence"]:
            self.assertIn(identifier, rendered)
        self.assertEqual(report, before)
        report["context"] = legacy_context
        self.assertNotIn("无损目录与按需上下文", markdown(report))

    def test_v2_preview_exports_representation_metadata_without_data_or_paid_runtime(self):
        args = self.args("--domain-agents", "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as checkpoints, \
                patch.object(cli.DataService, "query") as query:
            result = cli.run(args, self.f.repo)
        for mock in (config, checkpoints, query):
            mock.assert_not_called()
        output = Path(result["report"]).parent
        preview = json.loads((output / "preview.json").read_text(encoding="utf-8"))
        messages = json.loads((output / "model-messages.json").read_text(encoding="utf-8"))
        context = json.loads(messages[1]["content"])["context"]
        self.assertEqual(preview["context_representation"]["schema"], context["schema"])
        self.assertEqual(preview["context_representation"]["catalog_ref"], context["catalog_ref"])
        self.assertEqual(preview["context_representation"]["bytes"], sum(len(message["content"].encode("utf-8")) for message in messages))
        self.assertEqual(preview["context_representation"]["byte_budget"], 12000)
        self.assertIn("上下文表示", (output / "preview.md").read_text(encoding="utf-8"))
        self.assertFalse(Path(args.runs).exists())


if __name__ == "__main__":
    unittest.main()
