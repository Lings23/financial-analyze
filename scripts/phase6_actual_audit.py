"""Post-run, read-only Phase 6 paid-state audit; no credentials or external calls."""
import argparse
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import phase6_evaluate as run
from stock_research.models import digest
from stock_research.research.checkpoints import CheckpointStore


def audit(expected_sha):
    plan, _ = run.checked(expected_sha, replay=True)  # Current grants/PIT/source envelopes.
    directory = run.OUT / "live"
    before = run.original.file_hashes(directory)
    dataset = run.OLD.read(directory / "trace-dataset.json")
    summary = run.OLD.read(directory / "summary.json")
    manifest = run.OLD.read(directory / "trace-manifest.json")
    assert manifest["files_before_manifest"] == {k: v for k, v in before.items() if k != "trace-manifest.json"}
    assert manifest["trace_dataset_sha256"] == run.OLD.sha(directory / "trace-dataset.json")
    assert manifest["summary_sha256"] == run.OLD.sha(directory / "summary.json")
    states, chains = {}, []
    for item in plan["items"]:
        database = directory / item["run_id"] / "runs/checkpoints.sqlite3"
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            records = connection.execute("SELECT scope,run,seq,previous,hash,payload FROM checkpoints "
                "ORDER BY scope,run,seq").fetchall()
        previous, seqs = {}, {}
        for scope, identity, seq, predecessor, checksum, payload in records:
            state, key = json.loads(payload), (scope, identity)
            assert seq == seqs.get(key, 0) and predecessor == previous.get(key, "")
            assert digest({"previous": predecessor, "state": state}) == checksum
            previous[key], seqs[key] = checksum, seq + 1
            states.setdefault(key, []).append(state)
        assert len(seqs) == 3
        chains.append({"run_id": item["run_id"], "rows": len(records), "runs": len(seqs),
            "integrity_and_hashchain_verified": True})
    matched = []
    rows = {row["run_id"]: row for row in dataset["rows"]}
    with patch.object(CheckpointStore, "append", side_effect=AssertionError("audit cannot append")):
        receipts = run.validate_receipts(directory / "dispatch", summary["ledger"], plan["items"], directory)
        assert receipts == summary["receipt_validation"]
        for item in plan["items"]:
            row, scope = rows[item["run_id"]], item["scope"]
            report = row["report"]
            assert states[(scope, item["run_id"])][-1]["report"] == report
            assert row["assessment"]["functional_passed"] is True and row["error_type"] is None
            assert all(value == "passed" for value in row["safety_checks"].values())
            assert report["root_budget"]["unknown_usage_calls"] == 0
            assert report["root_budget"]["unresolved_child_allocations"] == 0
            assert [c for c in report["required_checks"] if c["id"] == "verification"] == [
                {"id": "verification", "status": "passed"}]
            verified_tools = [e for e in report["trace"] if e["event"] == "tool_finished" and e["tool"] == "verification"]
            assert len(verified_tools) == 1  # Actual execution, not report-only numerical validation.
            for child in row["child_reports"]:
                assert states[(scope, child["run_id"])][-1]["report"] == child
            assert run.paid_telemetry(item, report, row["child_reports"], directory / "dispatch", row["intents"]) == row["paid_telemetry_validation"]
            for intent in row["intents"]:
                prefix = f"{intent['number']:03d}"
                messages = run.OLD.read(directory / "dispatch" / (prefix + "-messages.json"))
                payload = json.loads(messages[1]["content"])
                role, turn = payload["protocol_version"], payload["control"]["decision"]
                identity = item["run_id"] if role == item["parent_version"] else next(
                    c["child_run_id"] for c in report["child_results"] if c["domain"] == role.split("-", 1)[0])
                pending = [s for s in states[(scope, identity)] if s["phase"] == "model_pending"
                    and s["decisions"][-1]["turn"] == turn
                    and s["decisions"][-1]["message_sha256"] == digest(messages)]
                assert pending and pending[0]["decisions"][-1]["token_reservation"] == intent["reservation"]
                matched.append({"intent": intent["number"], "role": role, "turn": turn,
                    "durable_pre_dispatch_state_matched": True})
    assert len(matched) == 36 and len(set(m["intent"] for m in matched)) == 36
    assert run.evaluate_pairs(dataset["rows"]) == summary["evaluation"]
    assert summary["evaluation"]["all_quality_passed"] is True
    assert summary["evaluation"]["primary_lossless_wire_benefit_proven"] is True
    assert run.original.file_hashes(directory) == before
    assert run.history_hashes() == plan["history_hashes"]
    return {"schema": "phase6-root-read-only-actual-audit/v1", "status": "passed",
        "author_role": "root", "independent_expert_review_claimed": False,
        "plan_sha256": expected_sha, "chains": chains, "matched_paid_states": matched,
        "receipt_validation": receipts, "original_source_grants_and_oracles_revalidated": True,
        "actual_verification_tool_executions": 4, "reports": 4, "child_reports": 8,
        "immutable_live_files": len(before), "original_history_unchanged": True,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "live_file_sha256_before": before, "live_file_sha256_after": before}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.plan_sha256)
    run.OLD.write_new(args.output, result)
    print({"status": result["status"], "matched_paid_states": len(result["matched_paid_states"]),
        "reports": result["reports"], "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0})


if __name__ == "__main__":
    main()
