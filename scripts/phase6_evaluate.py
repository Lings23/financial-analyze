"""Frozen Phase 6 lossless Parent representation comparison on existing cases.

No new financial sources, defaults, task denominator, retry, or routing change.
Each configured endpoint/model call requires a durable exact-wire paid intent.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
from threading import Lock
import time
import uuid

import phase5_evaluate as original
import phase5_parent_repair as repair
from stock_research.errors import DataError, IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, FinancialRequest, MarketRequest, ParallelParentSpec
from stock_research.research.dynamic_protocol import dynamic_messages
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result


OLD = original.old
OUT = OLD.ROOT / ".artifacts/phase6/first-round-20261006"
VERSIONS = {"baseline": "dynamic-parent-parallel-v2", "candidate": "dynamic-parent-parallel-v3"}
CASE_IDS = ("p5-603207", "p5-688184")
ORDER = ((CASE_IDS[0], "baseline"), (CASE_IDS[0], "candidate"),
         (CASE_IDS[1], "candidate"), (CASE_IDS[1], "baseline"))
LIMITS = (96, 576000, 1800)
MAX_RUNS = 6
CHILD_SPECS = original.CHILD_SPECS
SAFETY = ("point_in_time", "authorization", "immutable_snapshots", "lineage", "numeric_verification")
ACCEPTANCE = {"quality": "all scheduled runs match complete original oracle and mandatory execution checks",
    "lossless": "every candidate paid state decodes to the exact v2 baseline state, values and Evidence",
    "primary_benefit": "aggregate same-state full paid wire bytes, including changed system instruction, saved > 0",
    "replay": "zero model/provider/checkpoint appends; exact original report and paid-state reconstruction",
    "secondary": "actual accepted case-paired known/accounted Token and wall/model I/O changes described with signs",
    "scope": "limited explicit context representation only; no overall Token/latency advantage or parallel expansion",
    "no_provable_benefit": "retain original defaults"}
TIMING_DEFINITIONS = {
    "runtime_wall_ms": "monotonic elapsed around Runtime.run only, including a raised call",
    "runtime_preparation_ms": "source context authorization and Runtime/request setup before Runtime.run",
    "harness_validation_ms": "after Runtime.run returns/raises through report writes and per-run oracle/safety/paid/timing validation, before row write",
    "overall_measured_wall_ms": "per-run preparation + Runtime.run + post-run harness validation; excludes run-intent, summary write and final campaign validation",
    "wall_clock_ms": "legacy alias of overall_measured_wall_ms; never Runtime latency",
    "model_dispatch_intervals_union_ms": "union of aware paid dispatch intervals; includes wrapper receipt/persistence overhead and excludes parallel double counting",
    "unavailable_splits": "local source read/authentication and persistence internal costs remain unknown; nested tool spans cannot be added to model union"}


def spec_for(variant):
    if variant not in VERSIONS:
        raise IntegrityError("Phase 6 protocol variant outside frozen comparison")
    return ParallelParentSpec(version=VERSIONS[variant])


def runtime(service, checkpoints, variant, model=None, **kwargs):
    return DynamicRuntime(service, checkpoints, model, spec_for(variant), domain_child_specs=CHILD_SPECS, **kwargs)


def code_files():
    return {**repair.code_files(), "scripts/phase6_evaluate.py": OLD.sha(Path(__file__))}


def history_hashes():
    # All prior frozen financial/model evidence is immutable, including failures.
    return {"phase" + str(phase): original.file_hashes(OLD.ROOT / ".artifacts" / ("phase" + str(phase)))
            for phase in range(2, 6)}


def original_guard():
    plan, _, _, sources = repair.original_guard()
    repaired = OLD.read(repair.OUT / "live/summary.json")
    if (repaired["assessment"]["functional_passed"] is not True
            or repaired["original_functional_results"] != {"passed": 8, "total": 9}
            or repaired["independent_new_task_count"] != 0):
        raise IntegrityError("Phase 5 original failure and separately accepted repair differ")
    return plan, sources


def evidence_ref(path, *, historical=False):
    path = Path(path).resolve()
    try:
        name = path.relative_to(OLD.ROOT.resolve()).as_posix()
    except ValueError:
        raise IntegrityError("Phase 6 diagnostic evidence must be workspace-local") from None
    value = OLD.read(path)
    if historical and (any(value.get(k) != 0 for k in ("model_calls", "provider_calls", "checkpoint_appends"))
                       or value.get("status") != "passed"):
        raise IntegrityError("Phase 6 historical replay must prove zero calls and checkpoint appends")
    return {"path": name, "sha256": OLD.sha(path)}


def spec_document():
    return {variant: {"identity": spec_for(variant).identity, "version": version,
        "local_limits": original.local_limits(spec_for(variant)),
        "root_limits": {"decisions": 16, "tools": 18, "tokens": 96000}}
        for variant, version in VERSIONS.items()}


def frozen_item(prior, case_id, variant, sources, *, run_id=None):
    prior_item = next(i for i in prior["items"] if i["case_id"] == case_id and i["route"] == "parallel")
    case = next(c for c in prior["cases"] if c["id"] == case_id)
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(prior_item["request"])
    item = deepcopy(prior_item)
    item.update(run_id=run_id or uuid.uuid4().hex, variant=variant,
                spec_identity=spec_for(variant).identity, parent_version=VERSIONS[variant],
                original_run_id=prior_item["run_id"], independent_new_task_count=0)
    item["messages"] = runtime(service, None, variant).preview(request, access, run_id=item["run_id"])
    # The original question, source binding and oracle are inherited byte for byte.
    if (item["catalog_observations"] != original.parallel.catalog_oracle(service, access, request)
            or item["authorization_envelope"] != OLD.authorized_envelope(service, access, request)
            or item["input_ref"] != digest(sources.inputs(case))):
        raise IntegrityError("Phase 6 original immutable request/source/oracle differs")
    return item


def prepare(diagnosis, historical_audit, wire_preflight=None):
    if OUT.exists():
        raise IntegrityError("Phase 6 frozen campaign already exists")
    prior, sources = original_guard()
    cases = [deepcopy(next(c for c in prior["cases"] if c["id"] == identity)) for identity in CASE_IDS]
    validation = original.validate_cases(cases, sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("Phase 6 existing case contracts are invalid")
    items = [frozen_item(prior, case_id, variant, sources) for case_id, variant in ORDER]
    config = load_model_config()
    if config.model != prior["model"] or digest(config.endpoint) != prior["endpoint_sha256"]:
        raise IntegrityError("Phase 6 configured endpoint/model differs from frozen original")
    plan = {"schema": "phase6-first-round-plan/v1", "cases": cases, "items": items,
        "contract_validation": validation, "model": config.model, "endpoint_sha256": digest(config.endpoint),
        "diagnosis": evidence_ref(diagnosis), "historical_audit": evidence_ref(historical_audit, historical=True),
        "wire_preflight": evidence_ref(wire_preflight or OLD.ROOT / ".runtime/phase6-candidate-wire-preflight-final.json"),
        "code_files": code_files(), "history_hashes": history_hashes(), "specs": spec_document(),
        "child_specs": {d: {"identity": s.identity, "version": s.version, "limits": original.local_limits(s)}
                        for d, s in CHILD_SPECS.items()},
        "campaign_limits": {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]},
        "maximum_existing_cases": 3, "maximum_campaign_runs": MAX_RUNS, "scheduled_run_count": len(items),
        "reserved_repair_run_slots": MAX_RUNS - len(items), "existing_case_count": len(cases),
        "independent_new_task_count": 0, "independent_test_task_count": 0,
        "comparison_order": [list(pair) for pair in ORDER], "context_limit_bytes": 12000,
        "child_protocol_opt_in": "v3", "provider_network_calls": 0, "old_budget_reused": False,
        "original_functional_results": {"passed": 8, "total": 9}, "parent_v2_repair_result": {"passed": 1, "total": 1},
        "score": "exact original source oracle, execution checks, safety, paid/root budgets and read-only replay",
        "failure_retained": True, "unknown_paid_outcomes_stop_external_dispatch": True,
        "default_changed": False, "automatic_routing": False, "threshold_tuning": False,
        "confounds": ["two existing known-source nonblind cases", "rotated pair order without randomization or cache reset",
                      "endpoint service time uncontrolled; no statistical or P95 improvement claim"],
        "acceptance": ACCEPTANCE, "timing_definitions": TIMING_DEFINITIONS}
    OLD.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": OLD.sha(OUT / "plan.json"), "scheduled_run_count": len(items),
            "independent_new_task_count": 0, "model_calls": 0, "provider_calls": 0}


def checked(expected_sha, *, replay=False):
    if not isinstance(expected_sha, str) or OLD.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("Phase 6 explicit frozen plan hash differs")
    plan, (prior, sources) = OLD.read(OUT / "plan.json"), original_guard()
    expected_cases = [next(c for c in prior["cases"] if c["id"] == identity) for identity in CASE_IDS]
    if (plan["schema"] != "phase6-first-round-plan/v1" or plan["cases"] != expected_cases
            or plan["specs"] != spec_document() or plan["history_hashes"] != history_hashes()
            or plan["campaign_limits"] != {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]}
            or plan["context_limit_bytes"] != 12000 or plan["comparison_order"] != [list(p) for p in ORDER]
            or plan["scheduled_run_count"] != 4 or len(plan["items"]) != 4 or len(plan["cases"]) != 2
            or plan["maximum_campaign_runs"] != 6 or plan["maximum_existing_cases"] != 3
            or plan["reserved_repair_run_slots"] != 2 or plan["independent_new_task_count"] != 0
            or plan["old_budget_reused"] is not False or plan["default_changed"] is not False
            or plan["automatic_routing"] is not False or plan["threshold_tuning"] is not False
            or plan["original_functional_results"] != {"passed": 8, "total": 9}
            or plan["parent_v2_repair_result"] != {"passed": 1, "total": 1}
            or plan["acceptance"] != ACCEPTANCE
            or plan["timing_definitions"] != TIMING_DEFINITIONS
            or plan["child_specs"] != {d: {"identity": s.identity, "version": s.version, "limits": original.local_limits(s)}
                                       for d, s in CHILD_SPECS.items()}
            or not replay and plan["code_files"] != code_files()):
        raise IntegrityError("Phase 6 frozen history, counts, protocols, code or limits differ")
    if original.validate_cases(plan["cases"], sources.context) != plan["contract_validation"]:
        raise IntegrityError("Phase 6 source contract changed")
    for key in ("diagnosis", "historical_audit", "wire_preflight"):
        if evidence_ref(OLD.ROOT / plan[key]["path"], historical=key == "historical_audit") != plan[key]:
            raise IntegrityError("Phase 6 frozen diagnostic or historical replay evidence changed")
    if [(i["case_id"], i["variant"]) for i in plan["items"]] != list(ORDER):
        raise IntegrityError("Phase 6 frozen comparison order differs")
    runs = [i["run_id"] for i in plan["items"]]
    if len(set(runs)) != len(runs) or set(runs) & {i["run_id"] for i in prior["items"]}:
        raise IntegrityError("Phase 6 must use independent new run identities")
    for item in plan["items"]:
        if frozen_item(prior, item["case_id"], item["variant"], sources, run_id=item["run_id"]) != item:
            raise IntegrityError("Phase 6 immutable request, preview, permissions or source oracle changed")
    return plan, sources


def role_spec(item, role):
    if role == item["parent_version"]:
        return spec_for(item["variant"])
    for spec in CHILD_SPECS.values():
        if role == spec.version:
            return spec
    raise IntegrityError("Phase 6 outbound role exceeds exact frozen parent/Child versions")


def validate_outbound(messages, item, kwargs, checkpoints):
    payload = json.loads(messages[1]["content"])
    role, control = payload["protocol_version"], payload["control"]
    spec, args = role_spec(item, role), {}
    if role == item["parent_version"]:
        parent_payload = deepcopy(payload)
        if item["variant"] == "candidate":
            from stock_research.research.dynamic_context_metadata import decode_metadata_view
            parent_payload["context"] = decode_metadata_view(payload["context"])
        request, observations, refs, stage = original.compact._parent_observations(parent_payload, item)
        tools = json.loads(item["messages"][1]["content"])["available_tools"]
        checks = parent_payload["context"]["required_checks"]
        # The revision-sensitive original execution checks come from matching
        # durable model_pending state, never model-provided progress or facts.
        execution = repair.paid_parent_checks(checkpoints, item, messages)
        args = {"context_scope": item["scope"], "context_run_id": item["run_id"], "context_refs": refs,
                "context_stage": stage, "parent_execution_checks": execution}
    else:
        domain = next(d for d, s in CHILD_SPECS.items() if s.version == role)
        parent = DynamicRequest.from_dict(item["request"])
        request = (FinancialRequest if domain == "financial" else MarketRequest).from_parent(parent)
        tools, observations, checks = [domain], payload["observations"], payload["required_checks"]
        if any(o != item["authorization_envelope"]["source_observations"][domain] for o in observations):
            raise IntegrityError("Phase 6 Child disclosure exceeds original authorized immutable source")
    rebuilt, _ = dynamic_messages(request, tools, observations, checks, control["plan"], 12000,
        decision=control["decision"], protocol_error=control.get("previous_action_error"), version=role,
        finish_rejection=control.get("finish_rejection"), delegation_results=payload.get("delegation_results"), **args)
    if rebuilt != messages or payload["available_tools"] != tools or kwargs.get("max_tokens") != spec.output_tokens:
        raise IntegrityError("Phase 6 outbound wire differs from authoritative source/execution view")
    return role, spec, control["decision"]


def same_state_wire(messages, item, checkpoints):
    """Rebuild baseline on this exact candidate paid state; never dispatch it."""
    from stock_research.research.dynamic_context import expand_view
    from stock_research.research.dynamic_context_metadata import decode_metadata_view
    payload = json.loads(messages[1]["content"])
    if payload["protocol_version"] != VERSIONS["candidate"]:
        return None
    old_payload = deepcopy(payload)
    old_payload["context"] = decode_metadata_view(payload["context"])
    request, observations, refs, stage = original.compact._parent_observations(old_payload, item)
    control = payload["control"]
    tools = json.loads(item["messages"][1]["content"])["available_tools"]
    baseline, _ = dynamic_messages(request, tools, observations, old_payload["context"]["required_checks"],
        control["plan"], 12000, decision=control["decision"], protocol_error=control.get("previous_action_error"),
        version=VERSIONS["baseline"], finish_rejection=control.get("finish_rejection"),
        delegation_results=payload.get("delegation_results"), context_scope=item["scope"], context_run_id=item["run_id"],
        context_refs=refs, context_stage=stage, parent_execution_checks=repair.paid_parent_checks(checkpoints, item, messages))
    baseline_payload = json.loads(baseline[1]["content"])
    old_payload["protocol_version"] = VERSIONS["baseline"]
    if (baseline_payload != old_payload or expand_view(payload["context"]) != expand_view(baseline_payload["context"])):
        raise IntegrityError("Phase 6 candidate cannot decode to same complete baseline state")
    actual = sum(len(m["content"].encode("utf-8")) for m in messages)
    prior = sum(len(m["content"].encode("utf-8")) for m in baseline)
    return {"turn": control["decision"], "candidate_message_sha256": digest(messages), "baseline_message_sha256": digest(baseline),
        "candidate_total_wire_bytes": actual, "baseline_same_state_total_wire_bytes": prior,
        "net_wire_bytes_saved": prior - actual, "same_state_scope_controls_values_and_evidence": True,
        "candidate_context_decodes_exact_baseline": True, "system_bytes_candidate": len(messages[0]["content"].encode("utf-8")),
        "system_bytes_baseline": len(baseline[0]["content"].encode("utf-8")), "baseline_dispatched": False}


class RecordingModel:
    """Durable campaign accounting and terminal-unknown stop, excluding I/O locks."""
    def __init__(self, config, deadline, directory):
        self.config, self.adapter = config, ChatModelAdapter(config)
        self.deadline, self.directory = deadline, Path(directory)
        self.ledger, self.lock = OLD.RootLedger(LIMITS[0], LIMITS[1]), Lock()
        self.item, self.checkpoints = None, None
        self.role_calls, self.revision, self.terminal_unknown = {}, 0, False

    def snapshot(self, kind):
        self.revision += 1
        OLD.write_new(self.directory / f"ledger-{self.revision:03d}-{kind}.json", self.ledger.snapshot())

    def complete(self, messages, **kwargs):
        item = self.item
        role, spec, decision = validate_outbound(messages, item, kwargs, self.checkpoints)
        if OLD.contains_secret(messages, self.config.api_key):
            raise IntegrityError("Phase 6 outbound credential reflection rejected")
        with self.lock:
            key = (item["run_id"], role)
            count = self.role_calls.get(key, 0) + 1
            if self.terminal_unknown or count != decision or count > spec.max_decisions:
                raise IntegrityError("Phase 6 unknown paid outcome or repeated/local bound blocks dispatch")
            if (self.deadline - utcnow()).total_seconds() <= 0:
                raise ValidationError("Phase 6 campaign deadline exceeded")
            intent = self.ledger.reserve(item["run_id"] + "/" + role, messages, spec.output_tokens)
            self.role_calls[key] = count
            prefix = f"{intent['number']:03d}"
            try:
                OLD.write_new(self.directory / (prefix + "-messages.json"), messages)
                OLD.write_new(self.directory / (prefix + "-intent.json"), deepcopy(intent))
                self.snapshot("reserved")
                started = utcnow().isoformat()
                OLD.write_new(self.directory / (prefix + "-dispatch.json"), {"run_id": item["run_id"],
                    "case_id": item["case_id"], "variant": item["variant"], "role": role, "started_at": started})
            except Exception:
                # An incomplete durable intent cannot be safely sent or retried.
                self.terminal_unknown = True
                raise
        try:
            remaining = (self.deadline - utcnow()).total_seconds()
            if remaining <= 0:
                raise ValidationError("Phase 6 deadline exceeded after durable intent")
            response = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
            receipt = asdict(response)
            if OLD.receipt_reflects_secret(receipt, self.config.api_key) or len(canonical_json(receipt).encode("utf-8")) > 65536:
                raise ValidationError("Phase 6 receipt reflected credentials or exceeded bound")
            validate_model_result(response, spec, intent["reservation"])
        except Exception as exc:
            with self.lock:
                self.terminal_unknown = True
                OLD.write_new(self.directory / (prefix + "-receipt.json"), {"status": "unknown", "error_type": type(exc).__name__})
                OLD.write_new(self.directory / (prefix + "-interval.json"), {"run_id": item["run_id"], "role": role,
                    "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "unknown"})
                self.snapshot("terminal-unknown")
            raise
        with self.lock:
            original_intent, original_accounted = deepcopy(intent), self.ledger.accounted
            try:
                OLD.write_new(self.directory / (prefix + "-receipt.json"), receipt)
                OLD.write_new(self.directory / (prefix + "-interval.json"), {"run_id": item["run_id"], "role": role,
                    "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "known"})
                self.ledger.accounted += response.total_tokens - intent["reservation"]
                intent.update(usage_status="known", prompt_tokens=response.prompt_tokens,
                              completion_tokens=response.completion_tokens, total_tokens=response.total_tokens)
                self.snapshot("settled")
            except Exception as exc:
                # A validated response is not a durable settlement until all
                # receipt/interval/ledger records are committed. Keep any saved
                # receipt unchanged; conservative accounting retains reservation.
                intent.clear()
                intent.update(original_intent)
                self.ledger.accounted = original_accounted
                self.terminal_unknown = True
                OLD.write_new(self.directory / (prefix + "-settlement-incomplete.json"), {
                    "status": "unknown", "error_type": type(exc).__name__, "paid_retry": False,
                    "reservation_retained": intent["reservation"], "receipt_preserved": (self.directory / (prefix + "-receipt.json")).exists()})
                self.snapshot("terminal-unknown")
                raise
        return response


def validate_receipts(directory, ledger, items, live_directory):
    by_run = {i["run_id"]: i for i in items}
    known, reserved, accounted, unknown, counts = 0, 0, 0, 0, {}
    for number, intent in enumerate(ledger["intents"], 1):
        prefix = f"{number:03d}"
        messages, raw = [OLD.read(Path(directory) / (prefix + "-" + kind + ".json")) for kind in ("messages", "intent")]
        incomplete_path = Path(directory) / (prefix + "-settlement-incomplete.json")
        incomplete = OLD.read(incomplete_path) if incomplete_path.exists() else None
        receipt_path = Path(directory) / (prefix + "-receipt.json")
        receipt = OLD.read(receipt_path) if receipt_path.exists() else {"status": "unknown"} if incomplete else None
        run, role = intent["task_id"].split("/")
        item, spec = by_run[run], role_spec(by_run[run], role)
        actual_role, _, turn = validate_outbound(messages, item, {"max_tokens": spec.output_tokens}, Path(live_directory) / run / "runs")
        counts[(run, role)] = counts.get((run, role), 0) + 1
        initial = {k: v for k, v in intent.items() if k not in {"prompt_tokens", "completion_tokens"}}
        initial.update(usage_status="unknown", total_tokens=None)
        amount = sum(len(m["content"].encode("utf-8")) for m in messages) + 256 + spec.output_tokens
        if (intent["number"] != number or raw != initial or actual_role != role
                or digest(messages) != intent["messages_sha256"] or amount != intent["reservation"]
                or turn != counts[(run, role)] or turn > spec.max_decisions):
            raise IntegrityError("Phase 6 paid intent/wire/local count changed")
        reserved += amount
        if intent["usage_status"] == "known":
            result = ChatResult(**receipt)
            validate_model_result(result, spec, amount)
            if any(getattr(result, k) != intent[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("Phase 6 paid receipt differs from durable ledger")
            known += result.total_tokens
            accounted += result.total_tokens
        elif intent["usage_status"] == "unknown" and (receipt.get("status") == "unknown" or incomplete):
            if incomplete and (incomplete.get("status") != "unknown" or incomplete.get("paid_retry") is not False
                               or incomplete.get("reservation_retained") != amount):
                raise IntegrityError("Phase 6 incomplete durable settlement does not retain original reservation")
            unknown += 1
            accounted += amount
        else:
            raise IntegrityError("Phase 6 unknown paid result released or forged")
    if (known != ledger["known_tokens"] or accounted != ledger["tokens_accounted"]
            or reserved != ledger["cumulative_tokens_reserved"] or unknown != ledger["unknown_usage_calls"]
            or len(ledger["intents"]) != ledger["decisions"] or len(ledger["intents"]) > LIMITS[0]
            or accounted > LIMITS[1] or ledger["max_decisions"] != LIMITS[0] or ledger["max_tokens_accounted"] != LIMITS[1]):
        raise IntegrityError("Phase 6 receipt accounting exceeds or differs from frozen campaign")
    return {"known_tokens": known, "tokens_accounted": accounted, "cumulative_dispatch_tokens_reserved": reserved,
            "unknown_usage_calls": unknown, "decisions": len(ledger["intents"])}


def paid_telemetry(item, report, children, directory, intents):
    # The original exact-wire validator is version-neutral except its Parent map.
    reports = {item["parent_version"]: report}
    reports.update({CHILD_SPECS[c.get("domain", "financial")].version: c for c in children})
    bound, counterfactual = set(), []
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        messages = OLD.read(Path(directory) / (prefix + "-messages.json"))
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        payload = json.loads(messages[1]["content"])
        role, turn = payload["protocol_version"], payload["control"]["decision"]
        telemetry = reports[role]["context_telemetry"][turn - 1]
        actual = sum(len(m["content"].encode("utf-8")) for m in messages)
        if ((role, turn) in bound or telemetry["message_sha256"] != digest(messages)
                or telemetry["total_context_bytes"] != actual or telemetry["context_after_compaction_bytes"] != actual
                or actual > 12000 or telemetry["context_limit_bytes"] != 12000
                or not telemetry["model_dispatched"] or telemetry["context_budget_exceeded"]):
            raise IntegrityError("Phase 6 telemetry differs from exact bounded paid wire")
        bound.add((role, turn))
        if role == VERSIONS["candidate"]:
            checkpoint_dir = Path(directory).parent / item["run_id"] / "runs"
            counterfactual.append(same_state_wire(messages, item, checkpoint_dir))
        if intent["usage_status"] == "known" and any(telemetry[a] != receipt[b] for a, b in
                (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens"))):
            raise IntegrityError("Phase 6 telemetry Token usage differs from receipt")
    dispatched = {(role, index + 1) for role, value in reports.items()
                  for index, t in enumerate(value.get("context_telemetry", [])) if t["model_dispatched"]}
    root, known = report["root_budget"], sum(i["total_tokens"] or 0 for i in intents)
    unknown = sum(i["usage_status"] == "unknown" for i in intents)
    if (dispatched != bound or root["model_attempts"] != len(intents) or root["total_tokens"] != known
            or root["tokens_accounted"] != known + sum(i["reservation"] for i in intents if i["usage_status"] == "unknown")
            or root["unknown_usage_calls"] != unknown or root["tokens_dispatched_reserved"] != sum(i["reservation"] for i in intents)):
        raise IntegrityError("Phase 6 root/paid telemetry accounting differs")
    return {"bound_paid_turns": len(bound), "actual_wire_cap": 12000, "root_paid_usage_same": True,
        "same_state_candidate_parent_views": counterfactual,
        "net_same_state_wire_bytes_saved": sum(c["net_wire_bytes_saved"] for c in counterfactual) if counterfactual else None}


def assess(item, report, dispatch, intents):
    return original.assess(item, report, dispatch, intents)


def latency(report, children, directory, intents):
    """Nested spans stay separate; missing read/authentication subcosts stay unknown."""
    models, adapter_ms, tools, intervals = [], 0, [], []
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        interval = OLD.read(Path(directory) / (prefix + "-interval.json"))
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        start, end = (datetime.fromisoformat(interval[k]) for k in ("started_at", "finished_at"))
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise IntegrityError("Phase 6 timing is not bound to aware ordered paid intervals")
        models.append({"role": interval["role"], "io_interval_ms": round((end - start).total_seconds() * 1000),
                       "transport_ms": receipt.get("latency_ms"), "outcome": interval["outcome"]})
        intervals.append((start, end))
        adapter_ms += receipt.get("latency_ms") or 0
    for value in [report] + children:
        starts = {e["tool_call_id"]: e for e in value.get("trace", []) if e["event"] == "tool_started"}
        for event in value.get("trace", []):
            if event["event"] == "tool_finished" and event["tool_call_id"] in starts:
                first = starts[event["tool_call_id"]]
                ms = round((datetime.fromisoformat(event["time"]) - datetime.fromisoformat(first["time"])).total_seconds() * 1000)
                tools.append({"run_id": value["run_id"], "tool": event["tool"], "span_ms": ms,
                    "includes_child_model_io": event["tool"].endswith("_child")})
    branches = [b for g in report.get("parallel_groups", []) for b in (g.get("telemetry") or {}).get("branches", [])]
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return {"model_calls": models, "known_model_transport_sum_ms": adapter_ms, "tool_spans": tools,
        "model_dispatch_intervals_union_ms": round(sum((end - start).total_seconds() * 1000 for start, end in merged)),
        "verification_tool_span_sum_ms": sum(t["span_ms"] for t in tools if t["tool"] == "verification"),
        "parallel_queue_ms": {b["domain"]: b.get("queue_ms") for b in branches},
        "read_authorization_split_ms": None, "checkpoint_persistence_split_ms": None,
        "validation_inside_source_tool_split_ms": None,
        "measurement_scope": "transport elapsed excludes receipt validation; tool spans nest reads/auth and Child model I/O; sums are not wall time"}


def validate_timing(row):
    """Check frozen live boundaries without substituting replay elapsed times."""
    keys = ("runtime_wall_ms", "runtime_preparation_ms", "harness_validation_ms", "overall_measured_wall_ms", "wall_clock_ms")
    for key in keys:
        value = row.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise IntegrityError("Phase 6 recorded monotonic timing is not a nonnegative measurement")
    if row["wall_clock_ms"] != row["overall_measured_wall_ms"]:
        raise IntegrityError("Phase 6 overall wall alias differs from measured boundary")
    if not row["run_started"]:
        if any(row.get(key) is not None for key in keys):
            raise IntegrityError("Phase 6 nonstarted run cannot have execution timing")
    elif row["runtime_wall_ms"] is not None:
        if any(row.get(key) is None for key in keys):
            raise IntegrityError("Phase 6 Runtime timing lacks preparation/validation/overall boundaries")
        subtotal = sum(row[key] for key in ("runtime_wall_ms", "runtime_preparation_ms", "harness_validation_ms"))
        if abs(subtotal - row["overall_measured_wall_ms"]) > 2:
            raise IntegrityError("Phase 6 measured timing boundaries exceed overall elapsed time")


def evaluate_pairs(rows):
    pairs = []
    for case_id in CASE_IDS:
        pair = {r["variant"]: r for r in rows if r["case_id"] == case_id}
        baseline, candidate = pair["baseline"], pair["candidate"]
        same_quality = all(r["assessment"]["functional_passed"] for r in (baseline, candidate))
        result = {"case_id": case_id, "baseline_run_id": baseline["run_id"], "candidate_run_id": candidate["run_id"],
            "equal_accepted_quality": same_quality, "baseline_passed": baseline["assessment"]["functional_passed"],
            "candidate_passed": candidate["assessment"]["functional_passed"], "delta_semantics": "candidate_minus_baseline; descriptive only"}
        for key in ("known_tokens", "tokens_accounted", "cumulative_dispatch_tokens_reserved", "root_cumulative_tokens_reserved",
                    "runtime_wall_ms", "runtime_preparation_ms", "harness_validation_ms", "overall_measured_wall_ms", "wall_clock_ms", "parent_wire_bytes"):
            a, b = baseline.get(key), candidate.get(key)
            result[key + "_delta"] = b - a if same_quality and a is not None and b is not None else None
        for key in ("model_dispatch_intervals_union_ms", "known_model_transport_sum_ms", "verification_tool_span_sum_ms"):
            a = (baseline.get("latency") or {}).get(key)
            b = (candidate.get("latency") or {}).get(key)
            result[key + "_delta"] = b - a if same_quality and a is not None and b is not None else None
        pairs.append(result)
    candidates = [r for r in rows if r["variant"] == "candidate"]
    net = [r.get("paid_telemetry_validation", {}).get("net_same_state_wire_bytes_saved")
           if r.get("paid_telemetry_validation") else None for r in candidates]
    saving = sum(net) if len(net) == 2 and all(type(n) is int for n in net) else None
    return {"existing_case_count": 2, "scheduled_run_count": 4, "independent_new_task_count": 0,
        "pairs": pairs, "all_quality_passed": all(p["equal_accepted_quality"] for p in pairs),
        "same_state_net_total_wire_bytes_saved": saving, "primary_lossless_wire_benefit_proven": saving is not None and saving > 0,
        "statistical_superiority": False, "p95_improvement_established": False, "defaults_changed": False}


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("Phase 6 configured endpoint/model changed after freeze")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    dispatch = directory / "dispatch"
    dispatch.mkdir()
    deadline = utcnow() + timedelta(seconds=LIMITS[2])
    model = RecordingModel(config, deadline, dispatch)
    OLD.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha, "deadline": deadline.isoformat(),
        "limits": plan["campaign_limits"], "run_ids": [i["run_id"] for i in plan["items"]], "initial_ledger": model.ledger.snapshot(),
        "independent_new_budget": True, "old_budget_reused": False, "paid_retry": False, "maximum_runs": MAX_RUNS})
    cases, rows = {c["id"]: c for c in plan["cases"]}, []
    for item in plan["items"]:
        run_dir = directory / item["run_id"]
        run_dir.mkdir()
        stopped = model.terminal_unknown or (deadline - utcnow()).total_seconds() <= 0
        OLD.write_new(run_dir / "run-intent.json", {"run_id": item["run_id"], "case_id": item["case_id"],
            "variant": item["variant"], "plan_sha256": expected_sha, "deadline": deadline.isoformat(),
            "paid_retry": False, "external_dispatch_allowed": not stopped, "campaign_decisions_before": model.ledger.snapshot()["decisions"]})
        model.item, model.checkpoints = item, run_dir / "runs"
        started, report, children, paid, timings = time.monotonic(), None, [], None, None
        runtime_started, runtime_finished = None, None
        try:
            if stopped:
                raise ValidationError("Phase 6 campaign unknown outcome or deadline stops remaining runs")
            service, access = sources.context(cases[item["case_id"]])
            runner = runtime(service, CheckpointStore(model.checkpoints), item["variant"], model, inherited_deadline=deadline)
            request = DynamicRequest.from_dict(item["request"])
            runtime_started = time.monotonic()
            try:
                report = runner.run(request, access, run_id=item["run_id"])
            finally:
                runtime_finished = time.monotonic()
            OLD.write_new(run_dir / "report.json", report)
            with (run_dir / "report.md").open("x", encoding="utf-8") as stream:
                stream.write(markdown(report))
            OLD.write_new(run_dir / "trace.json", {"trace": report["trace"], "context_telemetry": report.get("context_telemetry"),
                                                   "parallel_groups": report.get("parallel_groups", [])})
            intents = original.run_intents(model.ledger.snapshot(), item["run_id"])
            assessment = assess(item, report, dispatch, intents)
            safety = original.safety_checks(item, report, sources, assessment)
            children = original.children_from_checkpoints(run_dir, item, report)
            paid = paid_telemetry(item, report, children, dispatch, intents)
            timings = latency(report, children, dispatch, intents)
            assessment["checks"]["paid_telemetry_and_root_usage"] = True
            assessment["functional_passed"] = assessment["functional_passed"] and all(v == "passed" for v in safety.values())
            error_type = None
        except Exception as exc:
            error_type = type(exc).__name__
            OLD.write_new(run_dir / "failure.json", {"error_type": error_type, "paid_retry": False,
                "report_retained": report is not None, "started": not stopped, "ledger": model.ledger.snapshot()})
            assessment = {"functional_passed": False, "checks": {}, "status": report.get("status") if report else None}
            safety = {k: "unknown" for k in SAFETY}
        intents = original.run_intents(model.ledger.snapshot(), item["run_id"])
        root = report.get("root_budget", {}) if report else {}
        measured_finished = time.monotonic()
        overall_ms = round((measured_finished - started) * 1000) if not stopped else None
        row = {"case_id": item["case_id"], "run_id": item["run_id"], "variant": item["variant"], "parent_version": item["parent_version"],
            "report": report, "child_reports": children, "assessment": assessment, "safety_checks": safety,
            "paid_telemetry_validation": paid, "latency": timings, "intents": intents, "error_type": error_type,
            "run_started": not stopped, "wall_clock_ms": overall_ms, "overall_measured_wall_ms": overall_ms,
            "runtime_wall_ms": round((runtime_finished - runtime_started) * 1000) if runtime_finished is not None else None,
            "runtime_preparation_ms": round((runtime_started - started) * 1000) if runtime_started is not None else None,
            "harness_validation_ms": round((measured_finished - runtime_finished) * 1000) if runtime_finished is not None else None,
            "known_tokens": sum(i["total_tokens"] or 0 for i in intents),
            "tokens_accounted": sum(i["total_tokens"] if i["usage_status"] == "known" else i["reservation"] for i in intents),
            "cumulative_dispatch_tokens_reserved": sum(i["reservation"] for i in intents),
            "root_cumulative_tokens_reserved": root.get("tokens_reserved"),
            "parent_wire_bytes": sum(t["total_context_bytes"] for t in report.get("context_telemetry", []) if t["model_dispatched"]) if report else None,
            "independent_new_task_count": 0, "paid_retry": False}
        validate_timing(row)
        OLD.write_new(run_dir / "summary.json", row)
        row["run_file_hashes"] = original.file_hashes(run_dir)
        rows.append(row)
    ledger = model.ledger.snapshot()
    receipt_validation = validate_receipts(dispatch, ledger, plan["items"], directory)
    if history_hashes() != plan["history_hashes"]:
        raise IntegrityError("Phase 6 modified historical frozen evidence")
    dataset = {"schema": "phase6-real-paired-trace/v1", "plan_sha256": expected_sha, "rows": rows,
        "existing_case_count": 2, "independent_new_task_count": 0, "scheduled_run_count": 4,
        "started_run_count": sum(r["run_started"] for r in rows), "maximum_runs": MAX_RUNS,
        "synthetic_rows": 0, "financial_provider_network_calls": 0, "model": config.model}
    OLD.write_new(directory / "trace-dataset.json", dataset)
    summary = {"schema": "phase6-live-summary/v1", "plan_sha256": expected_sha, "ledger": ledger,
        "receipt_validation": receipt_validation, "evaluation": evaluate_pairs(rows),
        "trace_dataset_sha256": OLD.sha(directory / "trace-dataset.json"), "deadline": deadline.isoformat(),
        "remaining_run_slots": MAX_RUNS - sum(r["run_started"] for r in rows),
        "unknown_paid_outcome_stopped_dispatch": model.terminal_unknown,
        "decision": "pending_exact_read_only_replay", "defaults_changed": False, "next_phase_started": False}
    OLD.write_new(directory / "summary.json", summary)
    OLD.write_new(directory / "trace-manifest.json", {"schema": "phase6-trace-manifest/v1", "plan_sha256": expected_sha,
        "trace_dataset_sha256": OLD.sha(directory / "trace-dataset.json"), "summary_sha256": OLD.sha(directory / "summary.json"),
        "files_before_manifest": original.file_hashes(directory)})
    return summary


def replay(expected_sha):
    plan, sources = checked(expected_sha, replay=True)
    directory = OUT / "live"
    before, manifest = original.file_hashes(directory), OLD.read(directory / "trace-manifest.json")
    dataset, summary = OLD.read(directory / "trace-dataset.json"), OLD.read(directory / "summary.json")
    if (manifest["trace_dataset_sha256"] != OLD.sha(directory / "trace-dataset.json")
            or manifest["summary_sha256"] != OLD.sha(directory / "summary.json")
            or manifest["files_before_manifest"] != {k: v for k, v in before.items() if k != "trace-manifest.json"}
            or summary["evaluation"] != evaluate_pairs(dataset["rows"])
            or validate_receipts(directory / "dispatch", summary["ledger"], plan["items"], directory) != summary["receipt_validation"]):
        raise IntegrityError("Phase 6 immutable manifest, paid ledger or evaluation changed")
    rows, identical, retained = {r["run_id"]: r for r in dataset["rows"]}, [], []
    cases = {c["id"]: c for c in plan["cases"]}
    for item in plan["items"]:
        run_dir, row = directory / item["run_id"], rows[item["run_id"]]
        validate_timing(row)
        if original.file_hashes(run_dir) != row["run_file_hashes"]:
            raise IntegrityError("Phase 6 frozen report, source validation or checkpoint changed")
        if row["report"] is None:
            retained.append({"run_id": item["run_id"], "run_started": row["run_started"], "validation_complete": False})
            continue
        service, access = sources.context(cases[item["case_id"]])
        restored = runtime(service, CheckpointStore(run_dir / "runs"), item["variant"], original.NoNetwork()).run(
            DynamicRequest.from_dict(item["request"]), access, resume=item["run_id"])
        if restored != row["report"] or restored != OLD.read(run_dir / "report.json"):
            raise IntegrityError("Phase 6 exact report replay changed")
        identical.append(item["run_id"])
        if row["error_type"] is None:
            assessed = assess(item, restored, directory / "dispatch", row["intents"])
            safety = original.safety_checks(item, restored, sources, assessed)
            children = original.children_from_checkpoints(run_dir, item, restored)
            paid = paid_telemetry(item, restored, children, directory / "dispatch", row["intents"])
            assessed["checks"]["paid_telemetry_and_root_usage"] = True
            assessed["functional_passed"] = assessed["functional_passed"] and all(v == "passed" for v in safety.values())
            if (assessed != row["assessment"] or safety != row["safety_checks"] or children != row["child_reports"]
                    or paid != row["paid_telemetry_validation"] or latency(restored, children, directory / "dispatch", row["intents"]) != row["latency"]):
                raise IntegrityError("Phase 6 oracle/safety/paid/timing replay changed")
        else:
            retained.append({"run_id": item["run_id"], "error_type": row["error_type"], "validation_complete": False})
    if before != original.file_hashes(directory) or history_hashes() != plan["history_hashes"]:
        raise IntegrityError("Phase 6 read-only replay appended checkpoint or changed historical files")
    quality = summary["evaluation"]["all_quality_passed"] and len(identical) == 4 and not retained and summary["ledger"]["unknown_usage_calls"] == 0
    benefit = summary["evaluation"]["primary_lossless_wire_benefit_proven"]
    return {"schema": "phase6-read-only-replay/v1", "plan_sha256": expected_sha,
        "replay_same": len(identical) == sum(r["report"] is not None for r in dataset["rows"]),
        "identical_reports": len(identical), "quality_acceptance_passed": quality, "retained_failures": retained,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "primary_lossless_wire_benefit_proven": benefit,
        "decision": "limited_explicit_lossless_representation_accepted" if quality and benefit
                    else "no_provable_benefit_original_defaults_retained" if quality else "bounded_acceptance_failed_evidence_retained",
        "independent_new_task_count": 0, "defaults_changed": False, "next_phase_started": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", action="store_true")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--diagnosis")
    parser.add_argument("--historical-audit")
    parser.add_argument("--wire-preflight")
    args = parser.parse_args(argv)
    if args.prepare and not (args.diagnosis and args.historical_audit):
        parser.error("prepare requires diagnostic and zero-call historical replay evidence")
    if not args.prepare and not args.plan_sha256:
        parser.error("live/replay requires explicit frozen --plan-sha256")
    try:
        result = prepare(args.diagnosis, args.historical_audit, args.wire_preflight) if args.prepare else live(args.plan_sha256) if args.live else replay(args.plan_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DataError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "failed", "error": "Phase 6 frozen input or execution validation failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
