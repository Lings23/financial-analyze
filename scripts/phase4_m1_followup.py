"""One preregistered instruction repair within the original demonstration ledger.

The original three tasks/results are immutable. No new financial inputs, scoring
rules or success criteria are introduced. This is a fresh targeted known-result
attempt, never resumption or retry of an unknown paid request.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import phase4_demo as demo
from stock_research.errors import IntegrityError
from stock_research.model_adapters.chat import ChatModelAdapter, load_model_config
from stock_research.models import digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest
from stock_research.research.report import markdown


ROOT = demo.OUT / "targeted-instruction-repair"
ORIGINAL_SHA = "c688d90f01571b10407eed7e983ab47e9d1b7cfe1e5fc81aa9d6920ce42fab45"


def prepare():
    proposal, sources = demo.checked_proposal(demo.OUT, ORIGINAL_SHA)
    initial = demo.read(demo.OUT / "live/summary.json")
    case = next(c for c in proposal["tasks"] if c["stratum"] == "replan-missing-prior")
    item = deepcopy(next(p for p in proposal["previews"] if p["case_id"] == case["id"]))
    # Clarify the already frozen required execution checks, preserving research
    # goal, input bindings and success criteria. It does not supply financial facts.
    item["request"]["question"] += (
        " Even when evidence is insufficient, run hypotheses and verification before finish. "
        "After each Observation update the plan to explain the next evidence path.")
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(item["request"])
    item["messages"] = DynamicRuntime(service, None, None, demo.SPEC).preview(request, access)
    item["messages_sha256"] = digest(item["messages"])
    plan = {"schema": "phase4-m1-targeted-instruction-repair/v1", "case": case, "preview": item,
            "original_proposal_sha256": ORIGINAL_SHA, "original_summary_sha256": demo.sha(demo.OUT / "live/summary.json"),
            "original_results_preserved": True, "runtime_or_scoring_rules_changed": False,
            "input_values_unchanged": True, "original_root_deadline": initial["root_deadline"],
            "remaining_decisions": 24 - initial["ledger"]["decisions"],
            "root_max_decisions": 24, "root_max_tokens_accounted": 144000,
            "purpose": "Correct premature insufficient finish omitting predeclared checks; preserve original failures.",
            "source_files": demo.implementation_files(), "followup_script_sha256": demo.sha(__file__)}
    if initial["ledger"]["unknown_usage_calls"] or plan["remaining_decisions"] < 6:
        raise IntegrityError("no automatic retry of unknown outcomes or insufficient remaining root budget")
    if (request.to_dict() | {"question": case["research_question"]}) != {**case["request"], "question": case["research_question"]}:
        raise IntegrityError("targeted repair changed the trusted research scope")
    demo.write_new(ROOT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": demo.sha(ROOT / "plan.json"), "remaining_decisions": plan["remaining_decisions"],
            "model_calls": 0, "provider_network_calls": 0}


def checked():
    plan = demo.read(ROOT / "plan.json")
    proposal, sources = demo.checked_proposal(demo.OUT, ORIGINAL_SHA)
    initial = demo.read(demo.OUT / "live/summary.json")
    if (demo.sha(demo.OUT / "live/summary.json") != plan["original_summary_sha256"]
            or demo.implementation_files() != plan["source_files"] or demo.sha(__file__) != plan["followup_script_sha256"]):
        raise IntegrityError("targeted repair frozen code or original results changed")
    case, item = plan["case"], plan["preview"]
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(item["request"])
    if (demo.authorized_envelope(service, access, request) != item["authorization_envelope"]
            or DynamicRuntime(service, None, None, demo.SPEC).preview(request, access) != item["messages"]):
        raise IntegrityError("targeted repair source envelope or first messages changed")
    return plan, initial, service, access, request


def live():
    plan, initial, service, access, request = checked()
    deadline = datetime.fromisoformat(plan["original_root_deadline"])
    if utcnow() >= deadline:
        raise IntegrityError("original root deadline expired; no new dispatch")
    directory = ROOT / "live"
    directory.mkdir(exist_ok=False)
    ledger = demo.RootLedger()
    ledger.intents = deepcopy(initial["ledger"]["intents"])
    ledger.accounted = initial["ledger"]["tokens_accounted"]
    ledger.cumulative_reserved = initial["ledger"]["cumulative_tokens_reserved"]
    adapter = ChatModelAdapter(load_model_config())
    model = demo.RecordingModel(adapter, plan["preview"], ledger, directory, deadline)
    report = DynamicRuntime(service, CheckpointStore(directory / "runs"), model, demo.SPEC).run(request, access)
    demo.write_new(directory / "report.json", report)
    (directory / "report.md").write_text(markdown(report), encoding="utf-8")
    summary = {"plan_sha256": demo.sha(ROOT / "plan.json"), "result": demo.assess(plan["case"], report),
               "ledger": ledger.snapshot(), "root_deadline": deadline.isoformat(), "original_failures_preserved": True,
               "new_model_attempts": model.calls, "financial_provider_network_calls": 0}
    demo.write_new(directory / "summary.json", summary)
    return summary


def replay():
    plan, initial, service, access, request = checked()
    class NoNetworkModel:
        class config:
            model = demo.SPEC.model
        def complete(self, *args, **kwargs):
            raise AssertionError("paid dispatch forbidden during replay")
    saved = demo.read(ROOT / "live/report.json")
    restored = DynamicRuntime(service, CheckpointStore(ROOT / "live/runs"), NoNetworkModel(), demo.SPEC).run(
        request, access, resume=saved["run_id"])
    if saved != restored:
        raise IntegrityError("targeted repair replay differs")
    return {"identical_replay": True, "result": demo.assess(plan["case"], restored), "model_calls": 0,
            "financial_provider_network_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    print(json.dumps(live() if args.live else replay() if args.replay else prepare(), ensure_ascii=True, indent=2))
