"""One explicit-action mixed-route run under the original unreset P4.4 campaign.

Preserve the original 1/2 result. This new question clarifies the existing JSON
contract, not the financial objective, sources, scoring or implementation.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import json

import phase4_p44_demo as demo

OUT = demo.OUT / "refined-mixed"
ORIGINAL_SHA = "20ac60e47c17cfca291a27de61b7a930cd2604a5dfe081b664fcc782f72d67a7"


def original_known():
    plan, sources = demo.checked(ORIGINAL_SHA)
    directory = demo.OUT / "live"
    summary = demo.old.read(directory / "summary.json")
    initial = summary["ledger"]
    if (initial["unknown_usage_calls"] or initial["decisions"] != len(initial["intents"])
            or initial["max_decisions"] != plan["max_decisions"]
            or initial["max_tokens_accounted"] != plan["max_tokens_accounted"]
            or initial["tokens_accounted"] != initial["known_tokens"]
            or initial["known_tokens"] != sum(i["total_tokens"] for i in initial["intents"])):
        raise demo.IntegrityError("original campaign has unresolved or inconsistent paid usage")
    for intent in initial["intents"]:
        prefix = f"{intent['number']:02d}-{intent['task_id'].split('/')[0]}"
        messages = demo.old.read(directory / (prefix + "-messages.json"))
        receipt = demo.old.read(directory / (prefix + "-receipt.json"))
        if (intent["usage_status"] != "known" or demo.digest(messages) != intent["messages_sha256"]
                or receipt.get("total_tokens") != intent["total_tokens"]
                or receipt.get("prompt_tokens") != intent["prompt_tokens"]
                or receipt.get("completion_tokens") != intent["completion_tokens"]
                or receipt.get("requested_model") != plan["model"] or receipt.get("returned_model") != plan["model"]):
            raise demo.IntegrityError("original paid receipt differs from its known intent")
    reports = [demo.old.read(directory / (c["id"] + "-report.json")) for c in plan["cases"]]
    if (sum(r["root_budget"]["model_attempts"] for r in reports) != initial["decisions"]
            or sum(r["root_budget"]["total_tokens"] for r in reports) != initial["known_tokens"]):
        raise demo.IntegrityError("original reports and campaign usage differ")
    return plan, sources, summary


def prepare():
    plan, sources, summary = original_known()
    case = deepcopy(plan["cases"][0])
    case["scope"] += "/typed-action-refinement"
    case["research_question"] += (' 每次调用工具的 action 字段必须为 "tool"；'
        '例如 hypotheses 步骤为 {"action":"tool","tool":"hypotheses","refs":["calculation"],"plan":["检验原必需假设"]}；'
        'verification 为 action="tool", tool="verification", refs=["hypotheses"]。'
        'calculation、hypotheses、verification 都是 tool 名，不能写成 action 值。')
    case["novelty"]["used_for_case_or_prompt_tuning"] = True
    service, access = sources.context(case)
    request = demo.DynamicRequest.from_dict({**case["request"], "question": case["research_question"]})
    validation = demo.validate_cases([case], sources.context)
    if not validation["all_cases_contract_valid"]:
        raise demo.IntegrityError("refined mixed input is not legal")
    item = {"case_id": case["id"], "request": request.to_dict(), "input_ref": demo.digest(sources.inputs(case)),
        "messages": demo.DynamicRuntime(service, None, None, demo.SPEC).preview(request, access),
        "authorization_envelope": demo.old.authorized_envelope(service, access, request)}
    refinement = {"schema": "phase4-p44-typed-action-refinement/v1", "case": case, "item": item,
        "original_plan_sha256": ORIGINAL_SHA, "original_summary_sha256": demo.old.sha(demo.OUT / "live/summary.json"),
        "initial_ledger": summary["ledger"], "deadline": summary["root_deadline"],
        "script_sha256": demo.old.sha(__file__), "contract_validation": validation,
        "original_functional_passed": [r["functional_passed"] for r in summary["results"]],
        "remaining_decisions": plan["max_decisions"] - summary["ledger"]["decisions"],
        "original_result_overwritten": False, "unknown_paid_call_retry": False}
    demo.old.write_new(OUT / "plan.json", refinement)
    return {"prepared": True, "plan_sha256": demo.old.sha(OUT / "plan.json"),
        "remaining_decisions": refinement["remaining_decisions"], "deadline": refinement["deadline"], "model_calls": 0}


def checked(expected_sha):
    if not isinstance(expected_sha, str) or len(expected_sha) != 64 or demo.old.sha(OUT / "plan.json") != expected_sha:
        raise demo.IntegrityError("explicit refinement SHA differs")
    original, sources, summary = original_known()
    plan = demo.old.read(OUT / "plan.json")
    if (plan["original_plan_sha256"] != ORIGINAL_SHA or plan["script_sha256"] != demo.old.sha(__file__)
            or plan["original_summary_sha256"] != demo.old.sha(demo.OUT / "live/summary.json")
            or plan["initial_ledger"] != summary["ledger"] or plan["deadline"] != summary["root_deadline"]):
        raise demo.IntegrityError("original frozen campaign, budget or deadline changed")
    case, item = plan["case"], plan["item"]
    service, access = sources.context(case)
    request = demo.DynamicRequest.from_dict(item["request"])
    if (case["request"] != original["cases"][0]["request"]
            or case["expected_behavior"] != original["cases"][0]["expected_behavior"]
            or demo.validate_cases([case], sources.context) != plan["contract_validation"]
            or request.to_dict() != demo.DynamicRequest.from_dict({**case["request"], "question": case["research_question"]}).to_dict()
            or demo.digest(sources.inputs(case)) != item["input_ref"]
            or demo.old.authorized_envelope(service, access, request) != item["authorization_envelope"]
            or demo.DynamicRuntime(service, None, None, demo.SPEC).preview(request, access) != item["messages"]):
        raise demo.IntegrityError("refinement source, objective, scoring or messages changed")
    return plan, original, sources


def live(expected_sha):
    plan, original, sources = checked(expected_sha)
    deadline = datetime.fromisoformat(plan["deadline"])
    if demo.utcnow() >= deadline:
        raise demo.ValidationError("original campaign deadline expired")
    config = demo.load_model_config()
    if config.model != original["model"] or demo.digest(config.endpoint) != original["endpoint_sha256"]:
        raise demo.IntegrityError("configured endpoint or model changed")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    initial = plan["initial_ledger"]
    ledger = demo.old.RootLedger(original["max_decisions"], original["max_tokens_accounted"])
    ledger.intents = deepcopy(initial["intents"])
    ledger.accounted, ledger.cumulative_reserved = initial["tokens_accounted"], initial["cumulative_tokens_reserved"]
    demo.old.write_new(directory / "campaign-intent.json", {"refinement_plan_sha256": expected_sha,
        "initial_ledger": initial, "deadline": deadline.isoformat(), "new_run": True, "paid_retry": False})
    case, item = plan["case"], plan["item"]
    service, access = sources.context(case)
    model = demo.RecordingModel(demo.ChatModelAdapter(config), item, demo.SPEC, ledger, directory, deadline)
    model.access = access
    report = demo.DynamicRuntime(service, demo.CheckpointStore(directory / "runs"), model, demo.SPEC,
        inherited_deadline=deadline).run(demo.DynamicRequest.from_dict(item["request"]), access)
    demo.old.write_new(directory / "report.json", report)
    (directory / "report.md").write_text(demo.markdown(report), encoding="utf-8")
    result = {"assessment": demo.assessment(case, report), "cumulative_ledger": ledger.snapshot(),
        "original_functional_passed": plan["original_functional_passed"], "deadline": deadline.isoformat(),
        "financial_provider_network_calls": 0, "unknown_paid_retry": False, "original_result_overwritten": False}
    demo.old.write_new(directory / "summary.json", result)
    return result


def replay(expected_sha):
    plan, _, sources = checked(expected_sha)
    saved = demo.old.read(OUT / "live/report.json")
    class NoNetwork:
        class config:
            model = demo.SPEC.model
        def complete(self, *args, **kwargs):
            raise AssertionError("refinement replay cannot dispatch model")
    service, access = sources.context(plan["case"])
    restored = demo.DynamicRuntime(service, demo.CheckpointStore(OUT / "live/runs"), NoNetwork(), demo.SPEC).run(
        demo.DynamicRequest.from_dict(plan["item"]["request"]), access, resume=saved["run_id"])
    if saved != restored:
        raise demo.IntegrityError("refinement replay differs")
    return {"identical_reports": 1, "model_calls": 0, "financial_provider_network_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true")
    group.add_argument("--replay", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if (args.live or args.replay) and not args.plan_sha256:
        parser.error("--plan-sha256 is required")
    print(json.dumps(live(args.plan_sha256) if args.live else replay(args.plan_sha256) if args.replay else prepare(), ensure_ascii=True, indent=2))
