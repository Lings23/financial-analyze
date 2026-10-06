"""Synthetic exact context accounting; neither live-provider nor financial truth."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research.context_telemetry import (
    build_context_telemetry, overflow_context_telemetry, telemetry_result,
)
from stock_research.research.dynamic_contracts import DynamicRequest, required_checks
from stock_research.research.dynamic_protocol import dynamic_messages, observe_tool
from stock_research.research.study import StudyRuntime
from stock_research.research.tools import read_domain


class ContextTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({**study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC 完整数值和字节测量"})
        outputs = {name: read_domain(self.f.service, self.request, self.f.access, name) for name in ("financial", "market")}
        datasets = {key: value for output in outputs.values() for key, value in output.items()}
        computed = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, self.request)
        self.observations = [observe_tool(name, output) for name, output in outputs.items()]
        self.observations.append(observe_tool("hypotheses", computed))
        self.tools = {"financial", "market", "calculation", "hypotheses", "verification"}
        self.kwargs = {"version": "dynamic-parent-parallel-v1", "context_scope": self.f.access.scope,
                       "context_run_id": "a" * 32, "context_stage": "finish", "decision": 4}

    def wire(self, observations=None, **changes):
        return dynamic_messages(self.request, self.tools, self.observations if observations is None else observations,
                                required_checks(self.request), ["Preserve exact data"], 12000,
                                **{**self.kwargs, **changes})

    def record(self, messages, metadata, **changes):
        return build_context_telemetry(messages, metadata, self.observations, self.request, run_id="a" * 32,
                                      turn_id=4, agent_role="parent", route_type="parallel_2_child", **changes)

    def test_after_bytes_sha_and_utf8_are_exact_and_measurement_has_no_mutations(self):
        messages, metadata = self.wire()
        before = deepcopy((messages, metadata, self.observations, self.request.to_dict()))
        record = self.record(messages, metadata)
        actual = sum(len(message["content"].encode("utf-8")) for message in messages)
        self.assertEqual(record["context_after_compaction_bytes"], actual)
        self.assertEqual(record["total_context_bytes"], actual)
        self.assertEqual(record["message_sha256"], digest(messages))
        self.assertEqual(record["context_limit_bytes"], 12000)
        self.assertEqual(record["system_bytes"], len(messages[0]["content"].encode("utf-8")))
        self.assertEqual((messages, metadata, self.observations, self.request.to_dict()), before)
        self.assertNotIn("context_telemetry", canonical_json(messages))
        self.assertNotIn("message_sha256", messages[1]["content"])

    def test_before_baseline_is_exact_complete_typed_payload_with_same_control_system(self):
        messages, metadata = self.wire()
        record = self.record(messages, metadata)
        payload = json.loads(messages[1]["content"])
        payload["context"] = {"request": self.request.to_dict(), "observations": self.observations,
                              "required_checks": required_checks(self.request)}
        expected = len(messages[0]["content"].encode("utf-8")) + len(canonical_json(payload).encode("utf-8"))
        self.assertEqual(record["context_before_compaction_bytes"], expected)
        self.assertEqual(record["context_saved_bytes"], expected - record["total_context_bytes"])
        self.assertEqual(record["context_saved_ratio"], record["context_saved_bytes"] / expected)
        self.assertEqual(record["before_compaction_baseline"], "same_system_control_full_typed_catalog_payload/v1")

    def test_lazy_disclosure_keeps_all_canonical_facts_claims_and_evidence(self):
        messages, metadata = self.wire()
        record = self.record(messages, metadata)
        full_messages, full_meta = self.wire(context_stage="verification")
        full = self.record(full_messages, full_meta)
        self.assertEqual(record["total_fact_count"], len(self.observations[-1]["facts"]))
        self.assertEqual(record["total_claim_count"], record["total_fact_count"])
        self.assertEqual(record["visible_fact_count"], record["total_fact_count"])
        self.assertEqual(record["total_evidence_count"], len(self.observations[-1]["evidence"]))
        self.assertLess(record["visible_evidence_count"], record["total_evidence_count"])
        self.assertEqual(full["visible_evidence_count"], full["total_evidence_count"])
        self.assertGreater(record["lazy_disclosure_saved_bytes"], 0)
        self.assertGreaterEqual(record["dedup_saved_bytes"], 0)
        self.assertIsNone(record["reference_compaction_saved_bytes"])

    def test_receipt_update_keeps_prepared_measurement_and_unknown_tokens_null(self):
        messages, metadata = self.wire()
        record = self.record(messages, metadata)
        result = telemetry_result(record, model_dispatched=True, status="verified",
                                  input_tokens=100, output_tokens=20, total_tokens=120)
        for key in ("context_before_compaction_bytes", "context_after_compaction_bytes", "message_sha256"):
            self.assertEqual(result[key], record[key])
        self.assertEqual((result["input_tokens"], result["output_tokens"], result["total_tokens"]), (100, 20, 120))
        self.assertIsNone(record["input_tokens"])
        unknown = telemetry_result(record, model_dispatched=True, status="unknown",
                                   stop_reason="unknown_model_outcome_no_replay")
        self.assertIsNone(unknown["total_tokens"])
        self.assertEqual(record["status"], "prepared")

    def test_measurement_reconstruction_and_replay_are_byte_identical(self):
        one, two = self.wire(), self.wire()
        self.assertEqual(one, two)
        self.assertEqual(self.record(*one), self.record(*two))

    def test_legacy_wire_is_measured_without_new_prompt_or_invented_savings(self):
        for version in ("single-dynamic-v1", "single-dynamic-v2", "dynamic-parent-domains-v1"):
            messages, metadata = dynamic_messages(self.request, self.tools, self.observations,
                required_checks(self.request), ["Preserve"], 12000, version=version)
            original = deepcopy(messages)
            record = self.record(messages, metadata)
            self.assertEqual(record["context_before_compaction_bytes"], record["total_context_bytes"])
            self.assertEqual(record["context_saved_bytes"], 0)
            self.assertEqual(record["before_compaction_baseline"], "legacy_exact_wire/v1")
            self.assertEqual(messages, original)

    def test_overflow_is_measured_without_returning_dispatchable_messages(self):
        messages, metadata = self.wire()
        cap = metadata["bytes"] - 1
        with self.assertRaisesRegex(ValidationError, "lossless byte budget"):
            dynamic_messages(self.request, self.tools, self.observations, required_checks(self.request),
                             ["Preserve exact data"], cap, **self.kwargs)
        record = overflow_context_telemetry(self.request, self.tools, self.observations,
            required_checks(self.request), ["Preserve exact data"], max_bytes=cap, message_kwargs=self.kwargs,
            run_id="a" * 32, turn_id=4)
        self.assertEqual(record["total_context_bytes"], metadata["bytes"])
        self.assertTrue(record["context_budget_exceeded"])
        self.assertFalse(record["model_dispatched"])
        self.assertEqual(record["stop_reason"], "dynamic_context_budget_exceeded")
        self.assertNotIn("messages", record)
        with self.assertRaises(ValidationError):
            telemetry_result(record, model_dispatched=True, status="verified")

    def test_invalid_usage_framing_and_overflow_flags_are_rejected(self):
        messages, metadata = self.wire()
        for changes in ({"input_tokens": True}, {"input_tokens": -1},
                        {"input_tokens": 10, "output_tokens": 20, "total_tokens": 31},
                        {"context_budget_exceeded": True}, {"limit_bytes": 14000},
                        {"status": "unsafe secret/free text"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.record(messages, metadata, **changes)
        bad = {**metadata, "bytes": metadata["bytes"] + 1}
        with self.assertRaises(ValidationError):
            self.record(messages, bad)


if __name__ == "__main__":
    unittest.main()
