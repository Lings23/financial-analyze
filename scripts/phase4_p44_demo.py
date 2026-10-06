"""Preregister two bounded serial domain demonstrations on existing public inputs.

This is functional evidence, not a benchmark or financial ground-truth assessment.
No collection, model retries, endpoint substitution or paid-call continuation.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json

import phase4_p43_demo as prior
from phase3_benchmark_v2 import CampaignSources
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DynamicRequest, DomainParentSpec,
    FinancialRequest, FinancialChildSpec, MarketRequest, MarketChildSpec)
from stock_research.research.dynamic_protocol import dynamic_messages
from stock_research.research.report import markdown

old = prior.old
OUT = old.ROOT / ".artifacts/phase4/p44-20261005-v2"
SPEC = DomainParentSpec()
ROLES = {SPEC.version: (DynamicRequest, SPEC),
         "financial-child-v1": (FinancialRequest, FinancialChildSpec()),
         "market-child-v1": (MarketRequest, MarketChildSpec())}
EXPECTED = {"mixed-financial-delegation": [("financial", "delegated"), ("market", "direct")],
            "dual-domain-delegation": [("financial", "delegated"), ("market", "delegated")]}


def code_files():
    files = old.implementation_files()
    for name in ("phase4_p43_demo.py", "phase4_p44_demo.py"):
        files["scripts/" + name] = old.sha(old.ROOT / "scripts" / name)
    return files


def prepare():
    original = old.read(old.OUT / "proposal.json")
    if old.sha(old.OUT / "proposal.json") != "c688d90f01571b10407eed7e983ab47e9d1b7cfe1e5fc81aa9d6920ce42fab45":
        raise IntegrityError("original M1 proposal changed")
    sources, cases, previews = CampaignSources(), [], []
    for kind, previous in (("mixed-financial-delegation", "m1-complete-financial"),
                           ("dual-domain-delegation", "m1-insufficient-missing-prior")):
        case = deepcopy(next(c for c in original["tasks"] if c["id"] == previous))
        if old.sha(old.ROOT / case["input_path"]) != case["input_sha256"]:
            raise IntegrityError("original public input changed")
        case.update(id=kind, case_id=kind, scope="phase4-p44-20261005/" + kind, parent_task_id=previous)
        case["research_question"] += (" 本次按 financial_child 委派财务读取、market 直接读取的顺序执行；父运行随后完成 calculation、hypotheses、verification，再 finish。"
            if kind == "mixed-financial-delegation" else
            " 本次依次委派 financial_child 和 market_child，各领域最多一个 Child、严格串行；父运行完成 calculation、hypotheses、verification 后 finish，缺上年同期证据须保留 insufficient。")
        case["novelty"]["blind"] = False
        service, access = sources.context(case)
        request = DynamicRequest.from_dict({**case["request"], "question": case["research_question"]})
        previews.append({"case_id": kind, "request": request.to_dict(), "spec_identity": SPEC.identity,
            "messages": DynamicRuntime(service, None, None, SPEC).preview(request, access),
            "input_ref": digest(sources.inputs(case)),
            "authorization_envelope": old.authorized_envelope(service, access, request),
            "expected_routes": EXPECTED[kind]})
        cases.append(case)
    validation = validate_cases(cases, sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("P4.4 public inputs are not contract-valid")
    config = load_model_config()
    plan = {"schema": "phase4-p44-demo/v1", "cases": cases, "previews": previews,
        "contract_validation": validation, "model": config.model, "endpoint_sha256": digest(config.endpoint),
        "max_decisions": 28, "max_tokens_accounted": 168000, "max_seconds": 720,
        "code_files": code_files(), "parent_spec_identity": SPEC.identity,
        "child_spec_identities": {k: v[1].identity for k, v in ROLES.items() if k != SPEC.version},
        "prior_results_preserved": True, "blind": False, "provider_network_calls": 0,
        "purpose": "Explicit mixed/direct and dual serial Financial/Market routing, safety and replay; no statistical claim."}
    old.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": old.sha(OUT / "plan.json"), "model_calls": 0,
            "financial_provider_network_calls": 0, "contract_valid": True}


def checked(expected_sha=None):
    if expected_sha is not None and old.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("explicit P4.4 plan SHA differs")
    plan = old.read(OUT / "plan.json")
    identifiers = list(EXPECTED)
    if (plan.get("schema") != "phase4-p44-demo/v1"
            or plan["code_files"] != code_files() or plan["parent_spec_identity"] != SPEC.identity
            or plan["child_spec_identities"] != {k: v[1].identity for k, v in ROLES.items() if k != SPEC.version}
            or (plan["max_decisions"], plan["max_tokens_accounted"], plan["max_seconds"]) != (28, 168000, 720)
            or [case["id"] for case in plan["cases"]] != identifiers
            or [item["case_id"] for item in plan["previews"]] != identifiers):
        raise IntegrityError("frozen P4.4 code or spec changed")
    sources = CampaignSources()
    if validate_cases(plan["cases"], sources.context) != plan["contract_validation"]:
        raise IntegrityError("P4.4 public input grants changed")
    for case, item in zip(plan["cases"], plan["previews"]):
        service, access = sources.context(case)
        request = DynamicRequest.from_dict(item["request"])
        if (request.to_dict() != DynamicRequest.from_dict({**case["request"], "question": case["research_question"]}).to_dict()
                or item["expected_routes"] != [list(route) for route in EXPECTED[case["id"]]]
                or digest(sources.inputs(case)) != item["input_ref"]
                or old.authorized_envelope(service, access, request) != item["authorization_envelope"]
                or DynamicRuntime(service, None, None, SPEC).preview(request, access) != item["messages"]):
            raise IntegrityError("P4.4 exact inputs or first messages changed")
    return plan, sources


class RecordingModel(prior.RecordingModel):
    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        role = payload["protocol_version"]
        if role not in ROLES:
            raise IntegrityError("outbound role differs from frozen parent or children")
        request_type, spec = ROLES[role]
        parent = DynamicRequest.from_dict(self.item["request"])
        request = parent if role == SPEC.version else request_type.from_parent(parent)
        expected_tools = (["financial"] if role == "financial-child-v1" else ["market"] if role == "market-child-v1"
            else json.loads(DynamicRuntime(None, None, None, SPEC).preview(parent, self.access)[1]["content"])["available_tools"])
        control = payload["control"]
        decision = self.role_calls.get(role, 0) + 1
        if payload["available_tools"] != expected_tools or decision != control["decision"] or decision > spec.max_decisions:
            raise IntegrityError("outbound role, grants or local decisions differ")
        rebuilt, _ = dynamic_messages(request, expected_tools, self._expanded(payload), payload["required_checks"],
            control["plan"], spec.context_bytes, decision=decision,
            protocol_error=control.get("previous_action_error"), version=role,
            finish_rejection=control.get("finish_rejection"), delegation_results=payload.get("delegation_results"))
        if rebuilt != messages or kwargs["max_tokens"] != spec.output_tokens:
            raise IntegrityError("outbound P4.4 typed payload differs")
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


def assessment(case, report):
    result = old.assess(case, report)
    routes = [(r["domain"], r["mode"]) for r in report["routes"] if r["domain"] in {"financial", "market"}]
    expected = EXPECTED[case["id"]]
    children = [domain for domain, mode in expected if mode == "delegated"]
    events = [e["event"] for e in report["trace"] if e["event"].startswith("child_")]
    result["routing_passed"] = (routes == expected and [c["domain"] for c in report["child_results"]] == children
        and all(c["status"] == "completed" and c["source_tool_call_id"] and c["evidence_refs"] for c in report["child_results"])
        and all(any(link["child_run_id"] == c["child_run_id"] for link in report["child_evidence_links"]) for c in report["child_results"])
        and events == [event for _ in children for event in ("child_reserved", "child_finished")])
    budget = report["root_budget"]
    result["root_budget_passed"] = (budget["model_attempts"] <= SPEC.root_max_decisions
        and budget["tool_attempts"] <= SPEC.root_max_tools and budget["tokens_accounted"] <= SPEC.root_max_tokens
        and budget["unknown_usage_calls"] == 0 and budget["unresolved_child_allocations"] == 0)
    result["functional_passed"] = result["functional_passed"] and result["routing_passed"] and result["root_budget_passed"]
    result["typed_finish_rejections"] = sum("rejection" in decision for decision in report["decisions"])
    return result


def live(expected_sha):
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValidationError("live requires an explicit frozen plan SHA")
    plan, sources = checked(expected_sha)
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
        model = RecordingModel(ChatModelAdapter(config), item, SPEC, ledger, directory, deadline)
        model.access = access
        report = DynamicRuntime(service, CheckpointStore(directory / "runs"), model, SPEC,
                                inherited_deadline=deadline).run(DynamicRequest.from_dict(item["request"]), access)
        old.write_new(directory / (case["id"] + "-report.json"), report)
        (directory / (case["id"] + "-report.md")).write_text(markdown(report), encoding="utf-8")
        results.append(assessment(case, report))
        old.write_new(directory / (case["id"] + "-assessment.json"), results[-1])
    summary = {"plan_sha256": old.sha(OUT / "plan.json"), "results": results, "ledger": ledger.snapshot(),
        "root_deadline": deadline.isoformat(), "financial_provider_network_calls": 0,
        "prior_failures_preserved": True, "paid_retry": False}
    old.write_new(directory / "summary.json", summary)
    return summary


def replay(expected_sha):
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValidationError("replay requires an explicit frozen plan SHA")
    plan, sources = checked(expected_sha)
    class NoNetwork:
        class config:
            model = "deepseek-v4-flash-0731"
        def complete(self, *args, **kwargs):
            raise AssertionError("replay must not dispatch any model")
    for case, item in zip(plan["cases"], plan["previews"]):
        service, access = sources.context(case)
        saved = old.read(OUT / "live" / (case["id"] + "-report.json"))
        restored = DynamicRuntime(service, CheckpointStore(OUT / "live/runs"), NoNetwork(), SPEC).run(
            DynamicRequest.from_dict(item["request"]), access, resume=saved["run_id"])
        if saved != restored:
            raise IntegrityError("P4.4 replay differs")
    return {"identical_reports": len(plan["cases"]), "model_calls": 0, "financial_provider_network_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true")
    group.add_argument("--replay", action="store_true")
    parser.add_argument("--plan-sha256", help="required frozen plan identity for live/replay")
    args = parser.parse_args()
    if (args.live or args.replay) and not args.plan_sha256:
        parser.error("--plan-sha256 is required for live/replay")
    print(json.dumps(live(args.plan_sha256) if args.live else replay(args.plan_sha256) if args.replay else prepare(), ensure_ascii=True, indent=2))
