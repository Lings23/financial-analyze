"""Freeze one independent context-remediation run on unchanged public evidence.

No old campaign is resumed, no old score is replaced, and no source is collected.
The unchanged 744-byte question and exact seven facts/twelve Evidence are retained.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import uuid

import phase4_p44_demo as prior
from phase3_benchmark_v2 import CampaignSources
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import DataRecord, canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import DOMAINS
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DynamicRequest, DomainParentSpec,
    FinancialRequest, FinancialChildSpec, MarketRequest, MarketChildSpec)
from stock_research.research.dynamic_protocol import dynamic_messages
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result


old = prior.old
OUT = old.ROOT / ".artifacts/phase4/p44-context-20261005"
VERSION = "dynamic-parent-domains-v2"
LIMITS = (16, 96000, 480)
CASE_ID = "mixed-financial-delegation"
LEGACY_HASHES = {
    ".artifacts/phase4/p44-20261005-v2/plan.json": "20ac60e47c17cfca291a27de61b7a930cd2604a5dfe081b664fcc782f72d67a7",
    ".artifacts/phase4/p44-20261005-v2/refined-mixed/plan.json": "f2aa680d7233df75544ae1fe00b3c2f660face5137262d3e7c1cd8485eeb3549",
    ".artifacts/phase4/p44-20261005-v2/live/mixed-financial-delegation-report.json": "da3d09f0e4626826c3ae8f1c6d72868e623e170f1b78d02a30083c84a756861d",
    ".artifacts/phase4/p44-20261005-v2/live/dual-domain-delegation-report.json": "d2746ca3effaa26dc9ce65b286c4a0eedb9c0c4357ef3d4d4730bbac871d2c08",
    ".artifacts/phase4/p44-20261005-v2/refined-mixed/live/report.json": "7e3df3e4a0237943d4a84bc01052727d337bb0df87ea3fcc114c7f7ff39be800",
    ".artifacts/phase4/p44-20261005-v2/live/summary.json": "aa4782915c259c860ee435650154a984861ebf655c3fb919d57a1a7effd3b96c",
    ".artifacts/phase4/p44-20261005-v2/refined-mixed/live/summary.json": "f92329aa02a6497d392180d49496b18dd4420af082eabde75c9cad9cfcea5cee",
}


def spec_for():
    # Lazy construction: preparation is only run after the new Runtime is complete.
    return DomainParentSpec(version=VERSION)


def roles():
    return {VERSION: (DynamicRequest, spec_for()), "financial-child-v1": (FinancialRequest, FinancialChildSpec()),
            "market-child-v1": (MarketRequest, MarketChildSpec())}


def code_files():
    files = old.implementation_files()
    for name in ("phase4_p43_demo.py", "phase4_p44_demo.py", "phase4_p44_context_demo.py"):
        files["scripts/" + name] = old.sha(old.ROOT / "scripts" / name)
    return files


def preserved_legacy():
    for relative, expected in LEGACY_HASHES.items():
        if old.sha(old.ROOT / relative) != expected:
            raise IntegrityError("old frozen P4.4 input or result changed")
    original = old.read(old.ROOT / next(iter(LEGACY_HASHES)))
    refinement = old.read(old.ROOT / ".artifacts/phase4/p44-20261005-v2/refined-mixed/plan.json")
    baseline = old.read(old.ROOT / ".artifacts/phase4/p44-20261005-v2/refined-mixed/live/report.json")
    case, item = deepcopy(refinement["case"]), deepcopy(refinement["item"])
    if (case["id"] != CASE_ID or case["request"] != original["cases"][0]["request"]
            or case["expected_behavior"] != original["cases"][0]["expected_behavior"]
            or len(item["request"]["question"].encode("utf-8")) != 744
            or item["request"] != {**case["request"], "question": case["research_question"]}
            or baseline["request"] != item["request"] or len(baseline["facts"]) != 7
            or len(baseline["evidence"]) != 12 or baseline["status"] != "partial"
            or baseline["stop_reason"] != "dynamic_context_budget_exceeded"):
        raise IntegrityError("original context-failure objective, question or evidence differs")
    return case, item, baseline


def record_domains(inputs):
    return {DataRecord.from_dict(row).record_id: DOMAINS[dataset]
            for dataset, output in inputs["datasets"].items() for row in output["records"]}


def context_oracle(envelope, baseline):
    """Exact existing typed objects; no value can be taken from the model's view."""
    observations = {"O:" + name: deepcopy(value) for name, value in envelope["source_observations"].items()}
    hypotheses = deepcopy(envelope["all_bound_computable_values"])
    calculation = {**deepcopy(hypotheses), "tool": "calculation", "hypotheses": {}}
    observations.update({"O:calculation": calculation, "O:hypotheses": hypotheses,
                         "O:verification": old.observe_tool("verification", baseline["verification"])})
    return observations


def report_semantics(report, domains):
    """Normalize run/call UUIDs through their actual domains; preserve every value."""
    local = {event["tool_call_id"]: event["tool"] for event in report["trace"]
             if event["event"] == "tool_finished" and event["tool"] in set(DOMAINS.values())}
    children = {child["child_run_id"]: child for child in report.get("child_results", [])}
    if len(children) != len(report.get("child_results", [])):
        raise IntegrityError("duplicate child identity in report")
    delegated = {}
    for child in children.values():
        for ref in child["evidence_refs"]:
            if (ref["tool_call_id"] != child["source_tool_call_id"]
                    or domains.get(ref["record_id"]) != child["domain"]):
                raise IntegrityError("child Evidence reference has another domain")
            delegated[(ref["record_id"], ref["tool_call_id"])] = child
    evidence, links = {}, []
    for key, source in report["evidence"].items():
        if key != source["id"] or key != digest({"record": source["record_id"], "metric": source["metric"]}):
            raise IntegrityError("Evidence ID does not bind its immutable record and metric")
        domain = domains.get(source["record_id"])
        child = delegated.get((source["record_id"], source["tool_call_id"]))
        mode = "delegated" if child is not None else "direct"
        if domain is None or child is None and local.get(source["tool_call_id"]) != domain:
            raise IntegrityError("Evidence read call is outside its record domain")
        evidence[key] = {**deepcopy(source), "tool_call_id": {"domain": domain, "mode": mode}}
        if child is not None:
            links.append({"evidence_id": key, "child_run_id": child["child_run_id"],
                          "record_id": source["record_id"], "tool_call_id": source["tool_call_id"]})
    if sorted(links, key=lambda link: link["evidence_id"]) != report.get("child_evidence_links", []):
        raise IntegrityError("parent Evidence links differ from imported child records")
    facts = deepcopy(report["facts"])
    for fact in facts:
        if (any(reference not in evidence for reference in fact["inputs"])
                or fact["id"] != digest({key: value for key, value in fact.items() if key != "id"})):
            raise IntegrityError("numeric fact lacks its complete original Evidence")
    return {"facts": sorted(facts, key=lambda fact: fact["name"]), "evidence": evidence,
            "hypotheses": deepcopy(report.get("hypotheses", [])), "event_anchor": deepcopy(report.get("event_anchor"))}


def prepare():
    case, original_item, baseline = preserved_legacy()
    case["scope"] = "phase4-p44-context-20261005/" + CASE_ID
    case["novelty"]["used_for_case_or_prompt_tuning"] = True
    sources = CampaignSources()
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(original_item["request"])
    inputs = sources.inputs(case)
    domains = record_domains(inputs)
    spec = spec_for()
    run_id = uuid.uuid4().hex
    validation = validate_cases([case], sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("context-remediation public input is not contract-valid")
    config = load_model_config()
    if config.model != spec.model:
        raise IntegrityError("configured model differs from frozen context-remediation spec")
    envelope = old.authorized_envelope(service, access, request)
    item = {"case_id": CASE_ID, "request": request.to_dict(), "run_id": run_id, "scope": access.scope,
            "spec_identity": spec.identity, "input_ref": digest(inputs),
            "messages": DynamicRuntime(service, None, None, spec).preview(request, access, run_id=run_id),
            "authorization_envelope": envelope, "catalog_observations": context_oracle(envelope, baseline)}
    plan = {"schema": "phase4-p44-context-demo/v1", "case": case, "item": item,
            "legacy_hashes": LEGACY_HASHES, "baseline_semantics": report_semantics(baseline, domains),
            "baseline_fact_count": 7, "baseline_evidence_count": 12, "question_bytes": 744,
            "contract_validation": validation, "code_files": code_files(),
            "parent_spec_identity": spec.identity,
            "child_spec_identities": {role: role_spec.identity for role, (_, role_spec) in roles().items() if role != VERSION},
            "model": config.model, "endpoint_sha256": digest(config.endpoint),
            "max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2],
            "expected_routes": [["financial", "delegated"], ["market", "direct"]],
            "original_functional_passes": [False, True], "original_refinement_functional_passed": False,
            "old_budget_reused": False, "prior_results_preserved": True, "blind": False,
            "purpose": "Unchanged-question context remediation; one new bounded functional demonstration, no broad quality claim."}
    old.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": old.sha(OUT / "plan.json"), "model_calls": 0,
            "financial_provider_network_calls": 0, "question_bytes": 744}


def checked(expected_sha):
    if not isinstance(expected_sha, str) or len(expected_sha) != 64 or old.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("explicit context-remediation plan SHA differs")
    plan = old.read(OUT / "plan.json")
    original_case, original_item, baseline = preserved_legacy()
    spec = spec_for()
    if (plan.get("schema") != "phase4-p44-context-demo/v1" or plan["code_files"] != code_files()
            or plan["legacy_hashes"] != LEGACY_HASHES or plan["parent_spec_identity"] != spec.identity
            or plan["child_spec_identities"] != {role: role_spec.identity for role, (_, role_spec) in roles().items() if role != VERSION}
            or (plan["max_decisions"], plan["max_tokens_accounted"], plan["max_seconds"]) != LIMITS
            or plan["question_bytes"] != 744 or plan["baseline_fact_count"] != 7 or plan["baseline_evidence_count"] != 12
            or plan["original_functional_passes"] != [False, True] or plan["original_refinement_functional_passed"] is not False
            or plan["old_budget_reused"] is not False or plan["expected_routes"] != [["financial", "delegated"], ["market", "direct"]]):
        raise IntegrityError("frozen context-remediation implementation or limits changed")
    case, item = plan["case"], plan["item"]
    original_case["scope"] = "phase4-p44-context-20261005/" + CASE_ID
    original_case["novelty"]["used_for_case_or_prompt_tuning"] = True
    sources = CampaignSources()
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(item["request"])
    inputs = sources.inputs(case)
    envelope = old.authorized_envelope(service, access, request)
    if (case != original_case or item["case_id"] != CASE_ID or item["request"] != original_item["request"]
            or item["spec_identity"] != spec.identity or digest(inputs) != item["input_ref"]
            or item["scope"] != access.scope or item["catalog_observations"] != context_oracle(envelope, baseline)
            or report_semantics(baseline, record_domains(inputs)) != plan["baseline_semantics"]
            or validate_cases([case], sources.context) != plan["contract_validation"]
            or envelope != item["authorization_envelope"]
            or DynamicRuntime(service, None, None, spec).preview(request, access, run_id=item["run_id"]) != item["messages"]):
        raise IntegrityError("frozen exact question, source grants, evidence or first messages changed")
    return plan, sources


def validate_receipts(directory, ledger, configured_model):
    """Full receipt validation and recomputed campaign accounting; unknown is retained."""
    known, accounted, reserved, settled = 0, 0, 0, []
    for number, intent in enumerate(ledger["intents"], 1):
        if intent["number"] != number:
            raise IntegrityError("campaign intent order differs")
        prefix = f"{number:02d}-{intent['task_id'].split('/')[0]}"
        messages = old.read(directory / (prefix + "-messages.json"))
        receipt = old.read(directory / (prefix + "-receipt.json"))
        raw_intent = old.read(directory / (prefix + "-intent.json"))
        expected_intent = {key: value for key, value in intent.items() if key not in {"prompt_tokens", "completion_tokens"}}
        expected_intent.update(usage_status="unknown", total_tokens=None)
        if raw_intent != expected_intent:
            raise IntegrityError("persisted paid intent differs from campaign history")
        role = intent["task_id"].split("/")[1]
        if (role not in roles() or digest(messages) != intent["messages_sha256"]
                or json.loads(messages[1]["content"])["protocol_version"] != role):
            raise IntegrityError("campaign role or paid intent messages differ")
        role_spec = roles()[role][1]
        amount = sum(len(message["content"].encode("utf-8")) for message in messages) + 256 + role_spec.output_tokens
        if amount != intent["reservation"] or role_spec.model != configured_model:
            raise IntegrityError("campaign reservation or fixed model differs")
        reserved += amount
        if intent["usage_status"] == "known":
            result = ChatResult(**receipt)
            validate_model_result(result, role_spec, amount)
            if any(getattr(result, key) != intent[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("known campaign receipt differs from its settlement")
            known += result.total_tokens
            accounted += result.total_tokens
        elif intent["usage_status"] == "unknown" and intent["total_tokens"] is None:
            accounted += amount
        else:
            raise IntegrityError("campaign settlement status differs")
        settled.append(intent)
        current = {"decisions": number, "tokens_accounted": accounted,
                   "known_tokens": known, "cumulative_tokens_reserved": reserved,
                   "unknown_usage_calls": sum(item["usage_status"] == "unknown" for item in settled),
                   "max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "intents": settled}
        if old.read(directory / (prefix + "-ledger.json")) != current:
            raise IntegrityError("campaign attempt prefix or accounting differs")
    expected = {"decisions": len(ledger["intents"]), "tokens_accounted": accounted,
                "known_tokens": known, "cumulative_tokens_reserved": reserved,
                "unknown_usage_calls": sum(intent["usage_status"] == "unknown" for intent in ledger["intents"])}
    if (any(ledger[key] != value for key, value in expected.items())
            or ledger["max_decisions"] != LIMITS[0] or ledger["max_tokens_accounted"] != LIMITS[1]
            or expected["decisions"] > LIMITS[0] or accounted > LIMITS[1]):
        raise IntegrityError("campaign receipt accounting or limits differ")
    return expected


def _parent_observations(payload, item):
    from stock_research.research.dynamic_context import build_catalog, validate_view, OBSERVATION_COLUMNS
    from stock_research.research.dynamic_protocol import context_next_stage
    request = DynamicRequest.from_dict(item["request"])
    view = payload["context"]
    columns = list(OBSERVATION_COLUMNS)
    if view["columns"]["observations"] != columns:
        raise IntegrityError("outbound context Observation columns differ from the frozen codec")
    observations = []
    for row in view["observations"]:
        if type(row) is not list or len(row) != len(columns):
            raise IntegrityError("outbound context Observation is outside the frozen source oracle")
        named = dict(zip(columns, row))
        if named["ref"] not in item["catalog_observations"]:
            raise IntegrityError("outbound context Observation is outside the frozen source oracle")
        exact = item["catalog_observations"][named["ref"]]
        if named["kind"] != exact["kind"] or named["sha256"] != digest(exact):
            raise IntegrityError("outbound context Observation hash differs from its exact original value")
        observations.append(deepcopy(exact))
    catalog = build_catalog(request, observations, view["required_checks"], scope=item["scope"], run_id=item["run_id"])
    if catalog["catalog_ref"] != view["catalog_ref"]:
        raise IntegrityError("outbound catalogue belongs to another scope, run or source revision")
    stage = context_next_stage(observations, view["required_checks"])
    if view["stage"] != stage:
        raise IntegrityError("outbound lazy disclosure stage differs from completed bound checks")
    refs = view["requested_refs"]
    validate_view(view, catalog, scope=item["scope"], run_id=item["run_id"])
    return request, observations, refs, stage


class RecordingModel(prior.RecordingModel):
    """Before every paid dispatch, reconstruct the exact public-source payload."""
    def complete(self, messages, **kwargs):
        try:
            payload = json.loads(messages[1]["content"])
            role = payload["protocol_version"]
            request_type, spec = roles()[role]
            parent = DynamicRequest.from_dict(self.item["request"])
            control = payload["control"]
            decision = self.role_calls.get(role, 0) + 1
            if (control["decision"] != decision or decision > spec.max_decisions
                    or kwargs["max_tokens"] != spec.output_tokens):
                raise IntegrityError("outbound role decision or output budget differs")
            context_args = {}
            if role == VERSION:
                request, observations, refs, stage = _parent_observations(payload, self.item)
                tools = json.loads(self.item["messages"][1]["content"])["available_tools"]
                required = payload["context"]["required_checks"]
                context_args = {"context_scope": self.item["scope"], "context_run_id": self.item["run_id"],
                                "context_refs": refs, "context_stage": stage}
                if decision == 1 and messages != self.item["messages"]:
                    raise IntegrityError("first outbound context decision differs from its frozen run")
            else:
                request = request_type.from_parent(parent)
                tools = ["financial"] if role == "financial-child-v1" else ["market"]
                required, observations = payload["required_checks"], self._expanded(payload)
            if payload["available_tools"] != tools:
                raise IntegrityError("outbound tool visibility differs from the trusted role")
            rebuilt, _ = dynamic_messages(request, tools, observations, required, control["plan"],
                spec.context_bytes, decision=decision, protocol_error=control.get("previous_action_error"),
                version=role, finish_rejection=control.get("finish_rejection"),
                delegation_results=payload.get("delegation_results"), **context_args)
            if rebuilt != messages:
                raise IntegrityError("outbound context/control values differ from their exact frozen reconstruction")
        except (KeyError, TypeError, ValueError, RecursionError):
            raise IntegrityError("outbound context-remediation message schema differs") from None
        secret = self.config.api_key
        if old.contains_secret(messages, secret):
            raise IntegrityError("outbound credential reflection rejected")
        remaining = (self.deadline - utcnow()).total_seconds()
        if remaining <= 0:
            raise ValidationError("independent context-remediation campaign deadline exceeded")
        intent = self.ledger.reserve(self.item["case_id"] + "/" + role, messages, spec.output_tokens)
        self.role_calls[role] = decision
        prefix = f"{intent['number']:02d}-{self.item['case_id']}"
        old.write_new(self.directory / (prefix + "-messages.json"), messages)
        old.write_new(self.directory / (prefix + "-intent.json"), intent)
        try:
            response = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
        except BaseException as exc:
            old.write_new(self.directory / (prefix + "-receipt.json"), {"status": "unknown", "error_type": type(exc).__name__})
            old.write_new(self.directory / (prefix + "-ledger.json"), self.ledger.snapshot())
            raise
        receipt = asdict(response)
        if old.receipt_reflects_secret(receipt, secret) or len(canonical_json(receipt).encode("utf-8")) > 65536:
            old.write_new(self.directory / (prefix + "-receipt.json"), {"status": "withheld", "reason": "oversize_or_credential_reflection"})
            old.write_new(self.directory / (prefix + "-ledger.json"), self.ledger.snapshot())
            raise ValidationError("receipt withheld; paid outcome remains accounted as unknown")
        try:
            validate_model_result(response, spec, intent["reservation"])
        except (ValidationError, TypeError, ValueError, AttributeError):
            old.write_new(self.directory / (prefix + "-receipt.json"), receipt)
            old.write_new(self.directory / (prefix + "-ledger.json"), self.ledger.snapshot())
            raise ValidationError("invalid complete receipt; paid outcome remains accounted as unknown") from None
        self.ledger.settle(intent, response)
        old.write_new(self.directory / (prefix + "-receipt.json"), receipt)
        old.write_new(self.directory / (prefix + "-ledger.json"), self.ledger.snapshot())
        return response


def assessment(case, report, plan, inputs):
    result = old.assess(case, report)
    routes = [(route["domain"], route["mode"]) for route in report["routes"] if route["domain"] in {"financial", "market"}]
    events = [event["event"] for event in report["trace"] if event["event"].startswith("child_")]
    children = report["child_results"]
    result["routing_passed"] = (routes == [("financial", "delegated"), ("market", "direct")]
        and len(children) == 1 and children[0]["domain"] == "financial" and children[0]["status"] == "completed"
        and bool(report["child_evidence_links"]) and events == ["child_reserved", "child_finished"])
    try:
        exact = report_semantics(report, record_domains(inputs))
        same = exact == plan["baseline_semantics"] and len(report["facts"]) == 7 and len(report["evidence"]) == 12
    except (IntegrityError, ValidationError, KeyError, TypeError, ValueError):
        same = False
    result["same_seven_facts_twelve_evidence"] = same
    budget, spec = report["root_budget"], spec_for()
    result["root_budget_passed"] = (budget["model_attempts"] <= spec.root_max_decisions
        and budget["tool_attempts"] <= spec.root_max_tools and budget["tokens_accounted"] <= spec.root_max_tokens
        and budget["unknown_usage_calls"] == 0 and budget["unresolved_child_allocations"] == 0)
    result["functional_passed"] = all((result["functional_passed"], result["routing_passed"], same, result["root_budget_passed"]))
    return result


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("configured endpoint or model changed")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    ledger = old.RootLedger(LIMITS[0], LIMITS[1])
    deadline = utcnow() + timedelta(seconds=LIMITS[2])
    old.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha, "deadline": deadline.isoformat(),
        "max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "independent_new_budget": True,
        "initial_ledger": ledger.snapshot(), "run_id": plan["item"]["run_id"]})
    service, access = sources.context(plan["case"])
    model = RecordingModel(ChatModelAdapter(config), plan["item"], spec_for(), ledger, directory, deadline)
    model.access = access
    try:
        report = DynamicRuntime(service, CheckpointStore(directory / "runs"), model, spec_for(), inherited_deadline=deadline).run(
            DynamicRequest.from_dict(plan["item"]["request"]), access, run_id=plan["item"]["run_id"])
    except BaseException as exc:
        old.write_new(directory / "failure.json", {"error_type": type(exc).__name__, "ledger": ledger.snapshot(),
                                                   "paid_retry": False, "deadline": deadline.isoformat()})
        raise
    old.write_new(directory / "report.json", report)
    (directory / "report.md").write_text(markdown(report), encoding="utf-8")
    usage = validate_receipts(directory, ledger.snapshot(), config.model)
    result = assessment(plan["case"], report, plan, sources.inputs(plan["case"]))
    summary = {"plan_sha256": expected_sha, "assessment": result, "ledger": ledger.snapshot(), "receipt_validation": usage,
        "deadline": deadline.isoformat(), "financial_provider_network_calls": 0, "independent_new_budget": True,
        "original_functional_passes": [False, True], "original_refinement_functional_passed": False,
        "prior_results_preserved": True, "paid_retry": False}
    old.write_new(directory / "summary.json", summary)
    preserved_legacy()
    return summary


def replay(expected_sha):
    plan, sources = checked(expected_sha)
    summary = old.read(OUT / "live/summary.json")
    if validate_receipts(OUT / "live", summary["ledger"], plan["model"]) != summary["receipt_validation"]:
        raise IntegrityError("saved campaign receipt validation differs")
    class NoNetwork:
        class config:
            model = spec_for().model
        def complete(self, *args, **kwargs):
            raise AssertionError("context-remediation replay cannot dispatch a model")
    service, access = sources.context(plan["case"])
    saved = old.read(OUT / "live/report.json")
    restored = DynamicRuntime(service, CheckpointStore(OUT / "live/runs"), NoNetwork(), spec_for()).run(
        DynamicRequest.from_dict(plan["item"]["request"]), access, resume=saved["run_id"])
    if (saved != restored or saved["run_id"] != plan["item"]["run_id"]
            or assessment(plan["case"], restored, plan, sources.inputs(plan["case"])) != summary["assessment"]):
        raise IntegrityError("context-remediation exact report or assessment replay differs")
    preserved_legacy()
    return {"identical_reports": 1, "model_calls": 0, "financial_provider_network_calls": 0,
            "prior_results_preserved": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if (args.live or args.replay) and not args.plan_sha256:
        parser.error("--plan-sha256 is required for live/replay")
    print(json.dumps(live(args.plan_sha256) if args.live else replay(args.plan_sha256) if args.replay else prepare(), ensure_ascii=True, indent=2))
