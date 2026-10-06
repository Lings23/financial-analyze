"""Read-only Phase 6 compatibility audit of frozen real historical reports.

No credentials are read, and model dispatch / Checkpoint append are forbidden.
Old live code-freeze gates are not claimed to match new code: exact frozen input
and source envelopes are validated, then the original Spec restores each report.
"""
import argparse
from pathlib import Path
from unittest.mock import patch

import phase5_evaluate as p5
import phase5_parent_repair as repaired
import phase4_p43_demo as p43
from phase3_benchmark_v2 import CampaignSources
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import IntegrityError
from stock_research.models import digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, DomainParentSpec


ROOT = p5.old.ROOT


def historical_hashes():
    return {path.relative_to(ROOT).as_posix(): p5.old.sha(path)
            for phase in ("phase2", "phase3", "phase4", "phase5")
            for path in sorted((ROOT / ".artifacts" / phase).rglob("*")) if path.is_file()}


class NoNetwork:
    class config:
        model = "deepseek-v4-flash-0731"

    def complete(self, *args, **kwargs):
        raise AssertionError("historical replay forbids model dispatch")


def run():
    before = historical_hashes()
    audit = p5.old.read(ROOT / ".runtime/phase5-historical-audit.json")
    sources, old_reports = CampaignSources(), []
    # Nine P4 historical records include the three P45 versions. Phase 5's
    # original replay below already checks those three; restore the other six.
    with patch.object(CheckpointStore, "append", side_effect=AssertionError("read-only replay cannot append")):
        for entry in audit["historical_trace_catalog"][:6]:
            path = ROOT / entry["plan_path"]
            if p5.old.sha(path) != entry["plan_sha256"]:
                raise IntegrityError("historical plan changed")
            plan = p5.old.read(path)
            if "cases" in plan:
                case = next(c for c in plan["cases"] if c["id"] == entry["historical_task_id"])
                item = next(i for i in plan["previews"] if i["case_id"] == case["id"])
            else:
                case, item = plan["case"], plan["item"]
            validation = validate_cases([case], sources.context)
            if validation["all_cases_contract_valid"] is not True:
                raise IntegrityError("historical source contract invalid")
            service, access = sources.context(case)
            request = DynamicRequest.from_dict(item["request"])
            if (digest(sources.inputs(case)) != item["input_ref"]
                    or p5.old.authorized_envelope(service, access, request) != item["authorization_envelope"]):
                raise IntegrityError("historical source / grant envelope changed")
            if "p43-" in entry["plan_path"]:
                spec = p43.spec_for(case["id"])
            else:
                spec = DomainParentSpec(version="dynamic-parent-domains-v2" if "p44-context-" in entry["plan_path"]
                                        else "dynamic-parent-domains-v1")
            report_path = ROOT / entry["report_path"]
            if p5.old.sha(report_path) != entry["report_sha256"]:
                raise IntegrityError("historical report changed")
            saved = p5.old.read(report_path)
            restored = DynamicRuntime(service, CheckpointStore((ROOT / entry["checkpoint_path"]).parent),
                NoNetwork(), spec).run(request, access, resume=entry["run_id"])
            if restored != saved:
                raise IntegrityError("historical report replay differs")
            old_reports.append({"label": entry["label"], "run_id": entry["run_id"],
                "same": True, "status": saved["status"], "stop_reason": saved.get("stop_reason")})
        result = repaired.replay(p5.old.sha(repaired.OUT / "plan.json"))
        campaign = result["original_campaign_replay"]
        historical = campaign["historical_replays"]
        if (len(old_reports) != 6 or result["replay_same"] is not True
                or campaign["replay_same"] is not True or campaign["identical_new_reports"] != 9
                or len(historical) != 3 or any(row["result"].get("replay_same") is not True for row in historical)
                or result["original_functional_results"] != {"passed": 8, "total": 9}
                or result["original_campaign_decision"] != "bounded_opt_in_not_supported"):
            raise IntegrityError("historical replay completeness or original results changed")
    after = historical_hashes()
    if before != after:
        raise IntegrityError("historical files or Checkpoints changed during read-only replay")
    return {"schema": "phase6-historical-read-only-replay/v1", "status": "passed",
        "audited_at": utcnow().isoformat(), "old_six_reports": old_reports,
        "phase5_and_p45_replay": result, "identical_reports": 19,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "historical_file_count": len(before), "file_sha256_before": before, "file_sha256_after": after,
        "old_live_code_freeze_gate_claimed_current": False, "independent_new_task_count": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    p5.old.write_new(args.output, result)
    print({"status": result["status"], "identical_reports": result["identical_reports"],
           "historical_file_count": result["historical_file_count"], "output": str(args.output)})


if __name__ == "__main__":
    main()
