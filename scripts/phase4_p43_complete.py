"""Finish only the unstarted preregistered case after a known QA summary-key bug.

Original plan, code, paid receipts, first report, budget and deadline stay intact.
This does not resume/retry an unknown paid call or alter Agent/scoring behavior.
"""
from copy import deepcopy
from datetime import datetime
import json

import phase4_p43_demo as demo


def assessment(case, report):
    result = demo.old.assess(case, report)
    if case["id"] == "serial-financial-child":
        result["serial_child_passed"] = (len(report["child_results"]) == 1 and
            report["child_results"][0]["status"] == "completed" and bool(report["child_evidence_links"]))
        result["functional_passed"] = result["functional_passed"] and result["serial_child_passed"]
    result["typed_finish_rejections"] = sum("rejection" in decision for decision in report["decisions"])
    return result


def complete():
    plan, sources = demo.checked()
    directory = demo.OUT / "live"
    if (directory / "summary.json").exists() or (directory / "m1-runtime-closure-report.json").exists():
        raise demo.IntegrityError("continuation is only for the single unstarted planned case")
    first = demo.old.read(directory / "serial-financial-child-report.json")
    ledger_paths = sorted(directory.glob("*-ledger.json"))
    initial = demo.old.read(ledger_paths[-1])
    if (initial["unknown_usage_calls"] or initial["decisions"] != first["root_budget"]["model_attempts"]
            or initial["known_tokens"] != first["root_budget"]["total_tokens"]
            or initial["max_decisions"] != plan["max_decisions"]
            or initial["max_tokens_accounted"] != plan["max_tokens_accounted"]):
        raise demo.IntegrityError("known paid ledger does not reconcile with the first root report")
    for intent in initial["intents"]:
        prefix = f"{intent['number']:02d}-serial-financial-child"
        messages = demo.old.read(directory / (prefix + "-messages.json"))
        receipt = demo.old.read(directory / (prefix + "-receipt.json"))
        if (demo.digest(messages) != intent["messages_sha256"] or receipt.get("total_tokens") != intent["total_tokens"]
                or receipt.get("requested_model") != plan["model"] or receipt.get("returned_model") != plan["model"]):
            raise demo.IntegrityError("first paid receipt differs from original intent")
    deadline = datetime.fromisoformat(demo.old.read(directory / "campaign-intent.json")["deadline"])
    if demo.utcnow() >= deadline:
        raise demo.IntegrityError("original campaign deadline expired")
    config = demo.load_model_config()
    if config.model != plan["model"] or demo.digest(config.endpoint) != plan["endpoint_sha256"]:
        raise demo.IntegrityError("configured endpoint or model changed")
    ledger = demo.old.RootLedger(plan["max_decisions"], plan["max_tokens_accounted"])
    ledger.intents = deepcopy(initial["intents"])
    ledger.accounted, ledger.cumulative_reserved = initial["tokens_accounted"], initial["cumulative_tokens_reserved"]
    case, item = plan["cases"][1], plan["previews"][1]
    demo.old.write_new(directory / "known-continuation-intent.json", {
        "reason": "QA summary used passed instead of functional_passed after first report completed",
        "original_plan_sha256": demo.old.sha(demo.OUT / "plan.json"),
        "continuation_script_sha256": demo.old.sha(__file__), "agent_and_scoring_code_unchanged": True,
        "first_report_sha256": demo.old.sha(directory / "serial-financial-child-report.json"),
        "initial_ledger": initial, "deadline": deadline.isoformat(), "remaining_case": case["id"],
        "paid_retry": False})
    results = [assessment(plan["cases"][0], first)]
    demo.old.write_new(directory / "serial-financial-child-assessment.json", results[0])
    service, access = sources.context(case)
    spec = demo.spec_for(case["id"])
    model = demo.RecordingModel(demo.ChatModelAdapter(config), item, spec, ledger, directory, deadline)
    model.access = access
    report = demo.DynamicRuntime(service, demo.CheckpointStore(directory / "runs"), model, spec,
        inherited_deadline=deadline).run(demo.DynamicRequest.from_dict(item["request"]), access)
    demo.old.write_new(directory / (case["id"] + "-report.json"), report)
    (directory / (case["id"] + "-report.md")).write_text(demo.markdown(report), encoding="utf-8")
    results.append(assessment(case, report))
    demo.old.write_new(directory / (case["id"] + "-assessment.json"), results[-1])
    summary = {"plan_sha256": demo.old.sha(demo.OUT / "plan.json"), "results": results,
        "ledger": ledger.snapshot(), "root_deadline": deadline.isoformat(),
        "financial_provider_network_calls": 0, "prior_failures_preserved": True,
        "known_QA_summary_failure_preserved": True, "paid_retry": False}
    demo.old.write_new(directory / "summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(complete(), ensure_ascii=True, indent=2))
