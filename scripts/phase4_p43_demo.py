"""Two preregistered bounded functional demonstrations on existing public snapshots.

New v2/serial-child results never overwrite M1 failures or reuse its expired budget.
No new financial Provider collection, benchmark or strategy comparison is performed.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path

import phase4_demo as old
from phase3_benchmark_v2 import CampaignSources
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, DynamicSpec, FinancialParentSpec, FinancialRequest, FinancialChildSpec
from stock_research.research.dynamic_protocol import dynamic_messages, _validate_observation
from stock_research.research.report import markdown


OUT = old.ROOT / ".artifacts/phase4/p43-20261005"


def spec_for(kind):
    return FinancialParentSpec() if kind == "serial-financial-child" else DynamicSpec(version="single-dynamic-v2")


def code_files():
    files = old.implementation_files()
    files["scripts/phase4_p43_demo.py"] = old.sha(__file__)
    return files


def prepare():
    original = old.read(old.OUT / "proposal.json")
    if old.sha(old.OUT / "proposal.json") != "c688d90f01571b10407eed7e983ab47e9d1b7cfe1e5fc81aa9d6920ce42fab45":
        raise IntegrityError("original M1 proposal changed")
    sources, cases, previews = CampaignSources(), [], []
    for kind, previous in (("serial-financial-child", "m1-complete-financial"),
                           ("m1-runtime-closure", "m1-insufficient-missing-prior")):
        case = deepcopy(next(c for c in original["tasks"] if c["id"] == previous))
        if old.sha(old.ROOT / case["input_path"]) != case["input_sha256"]:
            raise IntegrityError("original public input changed")
        case["id"], case["scope"] = kind, "phase4-p43-20261005/" + kind
        case["case_id"] = kind
        case["parent_task_id"] = previous
        if kind == "serial-financial-child":
            case["research_question"] += " 本次先调用 financial_child 委派唯一财务读取；该结果导入 financial Observation 后，再由父运行完成其他必需检验。"
        case["novelty"]["blind"] = False
        service, access = sources.context(case)
        request = DynamicRequest.from_dict({**case["request"], "question": case["research_question"]})
        spec = spec_for(kind)
        previews.append({"case_id": kind, "request": request.to_dict(), "spec_identity": spec.identity,
            "messages": DynamicRuntime(service, None, None, spec).preview(request, access),
            "input_ref": digest(sources.inputs(case)),
            "authorization_envelope": old.authorized_envelope(service, access, request)})
        cases.append(case)
    validation = validate_cases(cases, sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("P4.3 public inputs are not contract-valid")
    config = load_model_config()  # Only endpoint hash/model are retained, never the key.
    plan = {"schema": "phase4-p43-demo/v1", "cases": cases, "previews": previews,
        "contract_validation": validation, "model": config.model, "endpoint_sha256": digest(config.endpoint),
        "max_decisions": 20, "max_tokens_accounted": 120000, "max_seconds": 720,
        "code_files": code_files(), "prior_results_preserved": True, "blind": False,
        "provider_network_calls": 0, "purpose": "M1 Runtime closure and one serial Financial Child mechanism; no statistical claim."}
    old.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": old.sha(OUT / "plan.json"), "model_calls": 0,
            "financial_provider_network_calls": 0, "contract_valid": True}


def checked():
    plan = old.read(OUT / "plan.json")
    if plan["code_files"] != code_files():
        raise IntegrityError("frozen P4.3 code changed")
    sources = CampaignSources()
    if validate_cases(plan["cases"], sources.context) != plan["contract_validation"]:
        raise IntegrityError("P4.3 public input grants changed")
    for case, item in zip(plan["cases"], plan["previews"]):
        service, access = sources.context(case)
        request = DynamicRequest.from_dict(item["request"])
        if (digest(sources.inputs(case)) != item["input_ref"]
                or old.authorized_envelope(service, access, request) != item["authorization_envelope"]
                or DynamicRuntime(service, None, None, spec_for(case["id"])).preview(request, access) != item["messages"]):
            raise IntegrityError("P4.3 exact inputs or first messages changed")
    return plan, sources


class RecordingModel:
    def __init__(self, adapter, item, spec, ledger, directory, deadline):
        self.adapter, self.config, self.item, self.spec = adapter, adapter.config, item, spec
        self.ledger, self.directory, self.deadline = ledger, directory, deadline
        self.role_calls = {}

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        role = payload["protocol_version"]
        parent = DynamicRequest.from_dict(self.item["request"])
        request = FinancialRequest.from_parent(parent) if role == "financial-child-v1" else parent
        spec = FinancialChildSpec() if role == "financial-child-v1" else self.spec
        if role != spec.version:
            raise IntegrityError("outbound role differs from frozen parent or child spec")
        control = payload["control"]
        first = DynamicRuntime(None, None, None, self.spec).preview(parent,
            # Preview does not read service; scope is only a trusted grant boundary.
            self.access)
        expected_tools = ["financial"] if role == "financial-child-v1" else json.loads(first[1]["content"])["available_tools"]
        decision = self.role_calls.get(role, 0) + 1
        if payload["available_tools"] != expected_tools or decision != control["decision"] or decision > spec.max_decisions:
            raise IntegrityError("outbound role, grants or local decisions differ")
        rebuilt, _ = dynamic_messages(request, expected_tools, self._expanded(payload), payload["required_checks"],
            control["plan"], spec.context_bytes, decision=decision,
            protocol_error=control.get("previous_action_error"), version=role,
            finish_rejection=control.get("finish_rejection"))
        if rebuilt != messages or kwargs["max_tokens"] != spec.output_tokens:
            raise IntegrityError("outbound P4.3 typed payload differs")
        key = self.config.api_key
        if old.contains_secret(messages, key):
            raise IntegrityError("outbound credential reflection rejected")
        remaining = (self.deadline - utcnow()).total_seconds()
        if remaining <= 0:
            raise ValidationError("campaign deadline exceeded")
        intent = self.ledger.reserve(self.item["case_id"] + "/" + role, messages, spec.output_tokens)
        self.role_calls[role] = decision
        prefix = f"{intent['number']:02d}-{self.item['case_id']}"
        old.write_new(self.directory / (prefix + "-messages.json"), messages)
        old.write_new(self.directory / (prefix + "-intent.json"), intent)
        try:
            response = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
        except Exception as exc:
            old.write_new(self.directory / (prefix + "-receipt.json"), {"status": "unknown", "error_type": type(exc).__name__})
            old.write_new(self.directory / (prefix + "-ledger.json"), self.ledger.snapshot())
            raise
        receipt = asdict(response)
        if old.receipt_reflects_secret(receipt, key) or len(canonical_json(receipt).encode()) > 65536:
            receipt = {"status": "withheld", "reason": "oversize_or_credential_reflection"}
        self.ledger.settle(intent, response)
        old.write_new(self.directory / (prefix + "-receipt.json"), receipt)
        old.write_new(self.directory / (prefix + "-ledger.json"), self.ledger.snapshot())
        return response

    def _expanded(self, payload):
        observations, envelope = [], self.item["authorization_envelope"]
        for observed in payload["observations"]:
            if observed["kind"] == "source_read":
                if observed != envelope["source_observations"].get(observed["tool"]):
                    raise IntegrityError("outbound source differs from authorized public input")
            if observed["kind"] == "derived":
                observed = {"tool": observed["tool"], "kind": "derived", "gaps": observed["gaps"], **payload["derived_state"]}
                if observed["tool"] == "calculation":
                    observed["hypotheses"] = {}
                if (not set(old.claim_signatures(observed)) <= set(envelope["claim_signatures"])
                        or not {digest(v) for v in observed["evidence"].values()} <= set(envelope["evidence_signatures"])):
                    raise IntegrityError("outbound numeric values exceed public envelope")
            observations.append(observed)
        return observations


def live():
    plan, sources = checked()
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("configured model or endpoint changed")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    ledger = old.RootLedger(plan["max_decisions"], plan["max_tokens_accounted"])
    deadline = utcnow() + timedelta(seconds=plan["max_seconds"])
    old.write_new(directory / "campaign-intent.json", {"plan_sha256": old.sha(OUT / "plan.json"),
        "deadline": deadline.isoformat(), "max_decisions": plan["max_decisions"], "max_tokens_accounted": plan["max_tokens_accounted"]})
    results = []
    for case, item in zip(plan["cases"], plan["previews"]):
        service, access = sources.context(case)
        spec = spec_for(case["id"])
        model = RecordingModel(ChatModelAdapter(config), item, spec, ledger, directory, deadline)
        model.access = access
        request = DynamicRequest.from_dict(item["request"])
        report = DynamicRuntime(service, CheckpointStore(directory / "runs"), model, spec,
                                inherited_deadline=deadline).run(request, access)
        old.write_new(directory / (case["id"] + "-report.json"), report)
        (directory / (case["id"] + "-report.md")).write_text(markdown(report), encoding="utf-8")
        assessment = old.assess(case, report)
        if case["id"] == "serial-financial-child":
            assessment["serial_child_passed"] = (len(report["child_results"]) == 1 and
                report["child_results"][0]["status"] == "completed" and bool(report["child_evidence_links"]))
            assessment["passed"] = assessment["passed"] and assessment["serial_child_passed"]
        assessment["typed_finish_rejections"] = sum("rejection" in d for d in report["decisions"])
        results.append(assessment)
        old.write_new(directory / (case["id"] + "-assessment.json"), assessment)
    summary = {"plan_sha256": old.sha(OUT / "plan.json"), "results": results, "ledger": ledger.snapshot(),
               "root_deadline": deadline.isoformat(), "financial_provider_network_calls": 0,
               "prior_failures_preserved": True}
    old.write_new(directory / "summary.json", summary)
    return summary


def replay():
    plan, sources = checked()
    class NoNetwork:
        class config:
            model = "deepseek-v4-flash-0731"
        def complete(self, *args, **kwargs):
            raise AssertionError("replay must not dispatch any model")
    for case, item in zip(plan["cases"], plan["previews"]):
        service, access = sources.context(case)
        saved = old.read(OUT / "live" / (case["id"] + "-report.json"))
        restored = DynamicRuntime(service, CheckpointStore(OUT / "live/runs"), NoNetwork(), spec_for(case["id"])).run(
            DynamicRequest.from_dict(item["request"]), access, resume=saved["run_id"])
        if saved != restored:
            raise IntegrityError("P4.3 replay differs")
    return {"identical_reports": len(plan["cases"]), "model_calls": 0, "financial_provider_network_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true")
    group.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    print(json.dumps(live() if args.live else replay() if args.replay else prepare(), ensure_ascii=True, indent=2))
