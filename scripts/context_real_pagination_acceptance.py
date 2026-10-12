"""Bounded real pagination acceptance with durable cross-process accounting.

New task and directories only.  Baseline v5 tests its requested disclosure
closure; explicit candidate v6.2 reads the same frozen complete C objects in pages.
The external model always chooses its own strict action. No source duplication,
response substitution, old paid retries or budget/deadline reset is permitted.
"""
import argparse
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import time
import uuid
from unittest.mock import patch

import context_window_acceptance as prior
import context_window_optimized_acceptance as optimized
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.context_window import rebuild_selection, restore_object_atoms
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, FinancialRequest, MarketRequest, ParallelParentSpec
from stock_research.research.dynamic_protocol import dynamic_messages, observe_tool
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result

OLD = prior.OLD
OUT = OLD.ROOT / ".artifacts/context-real-pagination/first-real-20261008"
VERSIONS = {"baseline": "dynamic-parent-parallel-v5", "candidate": "dynamic-parent-parallel-v6.2"}
LIMITS = (64, 384000, 1800)
INITIAL_RUNS, MAX_RUNS, PAUSE_EXIT = 2, 4, 86
CHILD_SPECS = prior.CHILD_SPECS
ACCEPTANCE = {"scope": "one new explicit four-dataset task; complete frozen C objects and input refs, not whole O/E disclosure",
    "version_scope": "all new real page/overlimit evidence belongs to explicit v6.2; prior v6.1 unverified paging verdict unchanged",
    "baseline": "current real v5 requested disclosure closure exceeds 12000; that attempted wire is never dispatched",
    "candidate": "actual model discovery if needed, target refs then current paid continuation cursor; ordered atoms reconstruct exact originals",
    "quality": "all four declared datasets and complete original oracle, every business check, actual verification and finish",
    "recovery": "actual child process exit after committed first context_read tool_finished; fresh process resumes same run and deadline",
    "completed_replay": "identical report; zero new model/provider/checkpoint appends",
    "comparison": "baseline is incomplete, so Token/latency are descriptive unequal-outcome costs, not efficiency gains"}


def sources():
    import context_real_pagination_sources
    return context_real_pagination_sources


def spec_for(variant):
    if variant not in VERSIONS:
        raise IntegrityError("Real pagination variant is outside freeze")
    return ParallelParentSpec(version=VERSIONS[variant])


def runtime(service, checkpoints, variant, model=None, **kwargs):
    return DynamicRuntime(service, checkpoints, model, spec_for(variant), domain_child_specs=CHILD_SPECS, **kwargs)


def code_files():
    files = {**optimized.code_files(), "scripts/context_real_pagination_acceptance.py": OLD.sha(Path(__file__))}
    path = OLD.ROOT / "scripts/context_real_pagination_sources.py"
    if path.is_file():
        files[path.relative_to(OLD.ROOT).as_posix()] = OLD.sha(path)
    return files


def history_hashes():
    return {**optimized.history_hashes(), "context-window-v6.1": prior.original.file_hashes(optimized.OUT)}


def historical_replay():
    before = history_hashes()
    previous = optimized.historical_replay()
    latest = optimized.readonly_replay(OLD.sha(optimized.OUT / "plan.json"))
    if (previous.get("status") != "passed" or previous.get("unique_historical_reports_replayed") != 35
            or latest.get("identical_reports") != 4 or not latest.get("replay_same")
            or any(result.get(key) != 0 for result in (previous, latest)
                for key in ("model_calls", "provider_calls", "checkpoint_appends"))
            or history_hashes() != before):
        raise IntegrityError("All 39 historical completed reports must replay identically with zero appended work")
    return {"schema": "real-pagination-historical-readonly-replay/v1", "status": "passed",
        "completed_reports_replayed": 39, "all_identical": True, "historical_hashes": before,
        "historical_files_unchanged": True, "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}


def evidence_ref(path):
    return prior.evidence_ref(path)


def projection(item, state, *, diagnostic=False):
    return sources().projection(item, state, item["variant"], diagnostic=diagnostic)


def live_history(directory, scope, run):
    """Ordinary read-only connection: the live database may still be appended."""
    uri = (Path(directory) / "checkpoints.sqlite3").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        rows = connection.execute("SELECT seq,previous,hash,payload FROM checkpoints WHERE scope=? AND run=? ORDER BY seq", (scope, run)).fetchall()
    previous, result = "", []
    for expected, (seq, parent, checksum, payload) in enumerate(rows):
        state = json.loads(payload)
        if seq != expected or parent != previous or digest({"previous": parent, "state": state}) != checksum:
            raise IntegrityError("Live paid checkpoint chain changed")
        previous = checksum
        result.append(state)
    if not result:
        raise IntegrityError("Live paid checkpoint is missing")
    return result


def validate_paid_state(item, state):
    if any(observation != item["catalog_observations"].get("O:" + tool)
           for tool, observation in state["observations"].items()):
        raise IntegrityError("Current paid facts/evidence differ from the complete authorized source oracle")


def role_spec(item, role):
    if role == item["parent_version"]:
        return spec_for(item["variant"])
    matches = [spec for spec in CHILD_SPECS.values() if spec.version == role]
    if len(matches) != 1:
        raise IntegrityError("Paid role differs from frozen parent/child versions")
    return matches[0]


def validate_outbound(messages, item, kwargs, checkpoints):
    payload = json.loads(messages[1]["content"])
    role, turn = payload["protocol_version"], payload["control"]["decision"]
    spec = role_spec(item, role)
    if role == item["parent_version"]:
        pending = [state for state in live_history(checkpoints, item["scope"], item["run_id"])
            if state["phase"] == "model_pending" and state.get("decisions")
            and state["decisions"][-1]["turn"] == turn and state["decisions"][-1]["message_sha256"] == digest(messages)]
        if not pending:
            raise IntegrityError("Real page outbound lacks exact durable paid state")
        state = pending[0]
        if state["request"] != item["request"] or state["spec_version"] != item["parent_version"]:
            raise IntegrityError("Real page paid request or version changed")
        rebuilt, metadata = projection(item, state)
        if rebuilt != messages or state["context"] != {"status": "prepared", **metadata}:
            raise IntegrityError("Real page paid wire differs from full authorized state")
        validate_paid_state(item, state)
    else:
        # The existing independently validated Child v3 messages are rebuilt
        # from the durable Child state, not from candidate projection contents.
        domain = next(domain for domain, child in CHILD_SPECS.items() if child.version == role)
        request = (FinancialRequest if domain == "financial" else MarketRequest).from_parent(
            DynamicRequest.from_dict(item["request"]))
        if payload["available_tools"] != [domain] or any(observation != item["authorization_envelope"]["source_observations"][domain]
                for observation in payload["observations"]):
            raise IntegrityError("Unchanged Child exceeds original delegated authorized sources")
        rebuilt, _ = dynamic_messages(request, [domain], payload["observations"], payload["required_checks"],
            payload["control"]["plan"], 12000, decision=turn, version=role,
            protocol_error=payload["control"].get("previous_action_error"),
            finish_rejection=payload["control"].get("finish_rejection"))
        if rebuilt != messages:
            raise IntegrityError("Child outbound differs from its unchanged v3 authority")
    if kwargs.get("max_tokens") != spec.output_tokens or sum(len(message["content"].encode("utf-8")) for message in messages) > 12000:
        raise IntegrityError("Real pagination output or actual wire cap changed")
    return role, spec, turn


_loader = importlib.util.spec_from_file_location("_real_pagination_recorder_helpers", prior.__file__)
_helpers = importlib.util.module_from_spec(_loader)
_loader.loader.exec_module(_helpers)
_helpers.VERSIONS, _helpers.LIMITS = VERSIONS, LIMITS
_helpers.validate_outbound, _helpers.role_spec = validate_outbound, role_spec


def restored_ledger(directory, items):
    """Reconcile durable snapshots and every original intent/receipt, never retry."""
    directory = Path(directory)
    snapshots = sorted(directory.glob("ledger-*.json"))
    ledger = OLD.RootLedger(LIMITS[0], LIMITS[1])
    if not snapshots:
        if any(directory.glob("*.json")):
            raise IntegrityError("Unbound durable paid intent blocks recovery")
        return ledger, {}, 0, False
    revisions = [int(path.name.split("-")[1]) for path in snapshots]
    if revisions != list(range(1, max(revisions) + 1)):
        raise IntegrityError("Campaign snapshot history was deleted or reordered")
    saved = OLD.read(snapshots[-1])
    if (saved["max_decisions"] != LIMITS[0] or saved["max_tokens_accounted"] != LIMITS[1]
            or saved["decisions"] != len(saved["intents"])):
        raise IntegrityError("Recovered campaign limits or denominator changed")
    ledger.intents = deepcopy(saved["intents"])
    ledger.accounted = saved["tokens_accounted"]
    ledger.cumulative_reserved = saved["cumulative_tokens_reserved"]
    counts, known, accounted, reserved = {}, 0, 0, 0
    by_run = {item["run_id"]: item for item in items}
    for number, intent in enumerate(ledger.intents, 1):
        run, role = intent["task_id"].split("/")
        if run not in by_run or intent["number"] != number:
            raise IntegrityError("Recovered paid identity is outside campaign")
        spec = role_spec(by_run[run], role)
        prefix = f"{number:03d}"
        messages = OLD.read(directory / (prefix + "-messages.json"))
        raw = OLD.read(directory / (prefix + "-intent.json"))
        initial = {key: value for key, value in intent.items() if key not in {"prompt_tokens", "completion_tokens"}}
        initial.update(usage_status="unknown", total_tokens=None)
        amount = sum(len(message["content"].encode("utf-8")) for message in messages) + 256 + spec.output_tokens
        if raw != initial or amount != intent["reservation"] or digest(messages) != intent["messages_sha256"]:
            raise IntegrityError("Recovered original reservation or wire changed")
        counts[(run, role)] = counts.get((run, role), 0) + 1
        if counts[(run, role)] > spec.max_decisions:
            raise IntegrityError("Recovered paid role exceeds unchanged local limit")
        receipt_path = directory / (prefix + "-receipt.json")
        if intent["usage_status"] == "known":
            result = ChatResult(**OLD.read(receipt_path))
            validate_model_result(result, spec, amount)
            if any(getattr(result, key) != intent[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("Recovered receipt differs from charged known usage")
            known += result.total_tokens
            accounted += result.total_tokens
        elif intent["usage_status"] == "unknown":
            accounted += amount
        else:
            raise IntegrityError("Recovered unknown reservation was released")
        reserved += amount
    # A crash during reservation/settlement can leave newer intent files. It is
    # not safe to infer their outcome or send another request under new counters.
    if len(list(directory.glob("*-intent.json"))) != len(ledger.intents):
        raise IntegrityError("Orphan paid intent blocks all external recovery")
    if (known != saved["known_tokens"] or accounted != ledger.accounted or reserved != ledger.cumulative_reserved
            or accounted > LIMITS[1] or len(ledger.intents) > LIMITS[0]):
        raise IntegrityError("Recovered campaign accounting differs from immutable receipts")
    unknown = saved["unknown_usage_calls"] != 0 or any("terminal-unknown" in path.name for path in snapshots)
    return ledger, counts, max(revisions), unknown


class RecordingModel(_helpers.RecordingModel):
    def __init__(self, config, deadline, directory, items):
        _helpers.ChatModelAdapter = ChatModelAdapter
        super().__init__(config, deadline, directory)
        self.ledger, self.role_calls, self.revision, self.terminal_unknown = restored_ledger(directory, items)


class PauseAfterCommittedRead(CheckpointStore):
    def __init__(self, directory, item, run_directory):
        super().__init__(directory)
        self.item, self.run_directory = item, Path(run_directory)

    def append(self, scope, run, state):
        result = super().append(scope, run, state)
        last = state["trace"][-1] if state.get("trace") else {}
        marker = self.run_directory / "committed-page-process-exit.json"
        if (run == self.item["run_id"] and last.get("event") == "tool_finished"
                and last.get("tool") == "context_read" and len(state["window_store"]["receipts"]) == 1
                and not marker.exists()):
            OLD.write_new(marker, {"schema": "real-page-committed-process-exit/v1", "run_id": run,
                "deadline": state["deadline"], "turn": state["model_attempts"], "tool_call_id": last["tool_call_id"],
                "trace_seq": last["seq"], "pending_action": state["pending_action"], "pending_tool": state["pending_tool"],
                "page_receipt": state["window_store"]["receipts"][0], "pid": os.getpid(), "expected_exit": PAUSE_EXIT})
            os._exit(PAUSE_EXIT)
        return result


def atom_coverage(item, report, checkpoint_directory):
    """Two actual model choices plus exact complete ordered target object atoms."""
    history = prior.readonly_history(checkpoint_directory, item["scope"], item["run_id"])
    final = history[-1]
    exact_receipts = _helpers.page_audit(item, report, checkpoint_directory)
    receipts = final["window_store"]["receipts"]
    if len(receipts) not in {2, 3}:
        raise IntegrityError("Real continuation requires two or three actual committed page reads")
    atoms, slices, previous_end, object_pages, discovery_pages = [], [], 0, 0, 0
    hypothesis_ends = [event["seq"] for event in report["trace"]
        if event["event"] == "tool_finished" and event["tool"] == "hypotheses"]
    verification_starts = [event["seq"] for event in report["trace"]
        if event["event"] == "tool_started" and event["tool"] == "verification"]
    if len(hypothesis_ends) != 1 or len(verification_starts) != 1:
        raise IntegrityError("Frozen object-read goal lacks actual hypotheses/verification ordering")
    for index, receipt in enumerate(receipts):
        committed = next((state for state in history if receipt in state.get("window_store", {}).get("receipts", [])), None)
        if committed is None:
            raise IntegrityError("Actual page has no durable original receipt state")
        observations, _ = sources().exact_goal_collection(item, committed)
        action = final["decisions"][receipt["turn"] - 1]["action"]
        if action["action"] != "context_read":
            raise IntegrityError("Committed read was not an actual model context_read action")
        read_ends = [event for event in report["trace"] if event["event"] == "tool_finished"
            and event["tool"] == "context_read" and event["tool_call_id"] == receipt["tool_call_id"]]
        if len(read_ends) != 1 or not hypothesis_ends[0] < read_ends[0]["seq"] < verification_starts[0]:
            raise IntegrityError("Actual object reads did not occur after hypotheses and before verification")
        window = next(window for window in final["window_store"]["windows"] if window["turn"] == receipt["turn"])
        page = rebuild_selection(observations, receipt["selection_after"], scope=item["scope"], run_id=item["run_id"])
        selection = page["selection"]
        if selection["kind"] != "objects":
            if index != 0 or discovery_pages or selection["kind"] not in {"directory", "facts"}:
                raise IntegrityError("Only one actual discovery page before the frozen target objects is allowed")
            discovery_pages += 1
            if receipt["content_hash"] != page["content_hash"]:
                raise IntegrityError("Actual discovery page content differs from its original catalog")
            slices.append({"kind": selection["kind"], "turn": receipt["turn"], "start": page["start"],
                "end": page["end"], "total": page["total"], "has_more": page["has_more"],
                "window_ref": window["window_ref"], "content_hash": page["content_hash"]})
            continue
        if (selection["kind"] != "objects" or selection["refs"] != item["goal_refs"]
                or selection["start"] != previous_end or receipt["content_hash"] != page["content_hash"]):
            raise IntegrityError("Real page slice is not contiguous exact frozen target collection")
        if object_pages:
            cursor = action.get("cursor")
            if cursor not in window["cursors"]:
                raise IntegrityError("Real continuation token was not registered in its actual current paid window")
            issued = window["cursors"][cursor]
            if any(issued[key] != selection[key] for key in issued if key != "end"):
                raise IntegrityError("Real model cursor moved to another object or interval")
        else:
            if sorted(action.get("refs", [])) != item["goal_refs"] or not page["has_more"]:
                raise IntegrityError("First real object read must select the frozen targets and require continuation")
            if any(ref not in window["allowed_refs"] for ref in action["refs"]):
                raise IntegrityError("Object target was not issued in its current actual paid window")
        if index < len(receipts) - 1 and not page["has_more"]:
            raise IntegrityError("Extra read followed an already complete target collection")
        atoms.extend(page["atoms"])
        object_pages += 1
        previous_end = page["end"]
        slices.append({"kind": "objects", "turn": receipt["turn"], "start": page["start"], "end": page["end"],
            "total": page["total"], "has_more": page["has_more"], "window_ref": window["window_ref"],
            "content_hash": page["content_hash"], "actual_model_action": action["action"]})
    if object_pages not in {2, 3} or receipts[-1]["selection_after"]["end"] != slices[-1]["total"] or restore_object_atoms(atoms) != item["goal_objects"]:
        raise IntegrityError("Real target objects were not completely reconstructed without loss")
    return {"passed": True, "actual_context_read_count": len(receipts),
        "actual_continuation_cursor_count": sum("cursor" in final["decisions"][receipt["turn"] - 1]["action"] for receipt in receipts),
        "actual_object_page_count": object_pages, "actual_discovery_page_count": discovery_pages,
        "complete_original_target_c_objects": True, "complete_claim_count": len(item["goal_refs"]),
        "full_evidence_objects_read": False, "slices": slices,
        "exact_boundaries_and_paid_windows": exact_receipts["exact_page_receipts"]}


def frozen_item(task, variant, run_id):
    item = deepcopy(task)
    messages = sources().preview(task, variant, run_id)
    item.update(case_id=task["case"]["id"], variant=variant, run_id=run_id,
        parent_version=VERSIONS[variant], request=task["request_by_variant"][variant], messages=messages,
        available_tools=json.loads(messages[1]["content"])["available_tools"],
        parent_spec_identity=spec_for(variant).identity, input_sha256=task["source_payload_sha256"])
    return item


def validate_gate(offline_path, preflight_path, *, check_current=True):
    offline, probe = OLD.read(offline_path), OLD.read(preflight_path)
    if (offline.get("schema") != "real-pagination-offline-gate/v1" or offline.get("status") != "passed"
            or offline.get("command") != "PYTHONPATH=src python -m unittest discover -s tests -v"
            or offline.get("failures") != 0 or offline.get("errors") != 0
            or type(offline.get("tests_run")) is not int or offline["tests_run"] <= 0
            or type(offline.get("skipped")) is not int or not 0 <= offline["skipped"] < offline["tests_run"]
            or not offline.get("code_files") or not offline.get("test_files")
            or evidence_ref(OLD.ROOT / offline["log"]["path"]) != offline["log"]
            or check_current and (offline["code_files"] != code_files() or offline["test_files"] != prior.test_files())):
        raise IntegrityError("Real pagination requires a full current code/test/log-bound offline gate")
    if (probe.get("schema") != "real-pagination-readonly-preflight/v1" or probe.get("status") != "passed"
            or probe.get("task_sha256") != digest(sources().build_task())
            or type(probe.get("baseline_requested_closure_bytes")) is not int or probe["baseline_requested_closure_bytes"] <= 12000
            or not probe.get("baseline_typed_budget_rejected")
            or probe.get("candidate_object_page_count") not in {2, 3}
            or probe.get("candidate_total_context_reads") not in {2, 3}
            or probe["candidate_object_page_count"] > probe["candidate_total_context_reads"]
            or type(probe.get("candidate_max_wire_bytes")) is not int or not 0 < probe["candidate_max_wire_bytes"] <= 12000
            or not all(probe.get(key) is True for key in ("candidate_complete_target_atoms", "target_refs_hidden_in_question",
                "original_sources_grants_pit_oracle_revalidated", "historical_files_unchanged"))
            or probe.get("historical_hashes") != history_hashes()
            or any(probe.get(key) != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))):
        raise IntegrityError("Real pagination preflight lacks a genuine current overlimit closure and bounded exact page path")
    previous = probe.get("historical_completed_zero_append_replay", {})
    if (previous.get("status") != "passed" or previous.get("completed_reports_replayed") != 39
            or previous.get("all_identical") is not True or previous.get("historical_hashes") != history_hashes()
            or any(previous.get(key) != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))):
        raise IntegrityError("Real pagination freeze requires all 39 historical reports with zero appended work")
    return offline, probe


def prepare(offline_path, preflight_path):
    if OUT.exists():
        raise IntegrityError("New pagination campaign already exists; original freeze cannot be overwritten")
    validate_gate(offline_path, preflight_path)
    task = sources().build_task()
    ids = [uuid.uuid4().hex for _ in range(MAX_RUNS)]
    items = [frozen_item(task, variant, ids[index]) for index, variant in enumerate(VERSIONS)]
    config = load_model_config()
    plan = {"schema": "real-pagination-frozen-plan/v1", "task": task, "task_sha256": digest(task), "items": items,
        "reserved_repair_run_ids": ids[INITIAL_RUNS:], "scheduled_run_count": INITIAL_RUNS,
        "maximum_campaign_runs": MAX_RUNS, "independent_new_task_count": 1, "nonblind_reused_source_task": True,
        "campaign_limits": {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]},
        "specs": {variant: {"version": spec_for(variant).version, "identity": spec_for(variant).identity,
            "limits": prior.original.local_limits(spec_for(variant))} for variant in VERSIONS},
        "child_specs": {domain: {"version": spec.version, "identity": spec.identity,
            "limits": prior.original.local_limits(spec)} for domain, spec in CHILD_SPECS.items()},
        "model": config.model, "endpoint_sha256": digest(config.endpoint), "context_limit_bytes": 12000,
        "offline_gate": evidence_ref(offline_path), "readonly_preflight": evidence_ref(preflight_path),
        "code_files": code_files(), "test_files": prior.test_files(), "history_hashes": history_hashes(),
        "acceptance": ACCEPTANCE, "old_budget_reused": False, "defaults_changed": False,
        "unknown_outcomes_stop": True, "automatic_repair": False, "next_phase_started": False,
        "repair_policy": "two reserved same-task slots require separately frozen evidence; never automatic retries",
        "source_network_calls": 0, "child_protocol_opt_in": "v3"}
    OLD.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": OLD.sha(OUT / "plan.json"), "scheduled_run_count": 2,
        "reserved_repair_run_slots": 2, "independent_new_task_count": 1, "model_calls": 0, "provider_calls": 0}


def checked(expected_sha, *, replay=False):
    if not isinstance(expected_sha, str) or OLD.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("Explicit real-pagination frozen plan hash differs")
    plan = OLD.read(OUT / "plan.json")
    task = sources().build_task()
    if (plan.get("schema") != "real-pagination-frozen-plan/v1" or plan["task"] != task or plan["task_sha256"] != digest(task)
            or plan["history_hashes"] != history_hashes() or plan["acceptance"] != ACCEPTANCE
            or plan["context_limit_bytes"] != 12000 or plan["maximum_campaign_runs"] != MAX_RUNS
            or plan["campaign_limits"] != {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]}
            or plan["scheduled_run_count"] != 2 or plan["independent_new_task_count"] != 1
            or plan["child_protocol_opt_in"] != "v3" or plan["old_budget_reused"] is not False
            or plan["automatic_repair"] is not False or plan["defaults_changed"] is not False
            or plan["specs"] != {variant: {"version": spec_for(variant).version, "identity": spec_for(variant).identity,
                "limits": prior.original.local_limits(spec_for(variant))} for variant in VERSIONS}
            or plan["child_specs"] != {domain: {"version": spec.version, "identity": spec.identity,
                "limits": prior.original.local_limits(spec)} for domain, spec in CHILD_SPECS.items()}
            or not replay and (plan["code_files"] != code_files() or plan["test_files"] != prior.test_files())):
        raise IntegrityError("Real pagination task, original sources, budgets or frozen implementation changed")
    if len(plan["items"]) != 2 or [item["variant"] for item in plan["items"]] != list(VERSIONS):
        raise IntegrityError("Real pagination initial denominator/order changed")
    ids = [item["run_id"] for item in plan["items"]] + plan["reserved_repair_run_ids"]
    if len(ids) != 4 or len(set(ids)) != 4:
        raise IntegrityError("Real pagination needs four distinct new bounded run identities")
    for item in plan["items"]:
        if item != frozen_item(task, item["variant"], item["run_id"]):
            raise IntegrityError("Real pagination frozen request/preview/oracle changed")
    for key in ("offline_gate", "readonly_preflight"):
        if evidence_ref(OLD.ROOT / plan[key]["path"]) != plan[key]:
            raise IntegrityError("Real pagination gate evidence changed")
    validate_gate(OLD.ROOT / plan["offline_gate"]["path"], OLD.ROOT / plan["readonly_preflight"]["path"], check_current=not replay)
    return plan


def children(run_directory, item, report):
    return [prior.readonly_history(Path(run_directory) / "runs", item["scope"], child["child_run_id"])[-1]["report"]
        for child in report.get("child_results", [])]


def paid_usage(item, report, child_reports, directory, intents):
    reports = {item["parent_version"]: report,
        **{CHILD_SPECS[child.get("domain", "financial")].version: child for child in child_reports}}
    bound = set()
    for intent in intents:
        messages = OLD.read(Path(directory) / f"{intent['number']:03d}-messages.json")
        payload = json.loads(messages[1]["content"])
        role, turn = payload["protocol_version"], payload["control"]["decision"]
        telemetry = reports[role]["context_telemetry"][turn - 1]
        amount = sum(len(message["content"].encode("utf-8")) for message in messages)
        if ((role, turn) in bound or telemetry["message_sha256"] != digest(messages)
                or telemetry["total_context_bytes"] != amount or amount > 12000
                or telemetry["context_budget_exceeded"] or not telemetry["model_dispatched"]):
            raise IntegrityError("Actual paid telemetry differs from its exact bounded wire")
        if intent["usage_status"] == "known" and any(telemetry[left] != intent[right] for left, right in
                (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens"))):
            raise IntegrityError("Actual Parent/Child tokens differ from physical paid receipts")
        bound.add((role, turn))
    dispatched = {(role, index + 1) for role, value in reports.items()
        for index, telemetry in enumerate(value["context_telemetry"]) if telemetry["model_dispatched"]}
    root = report["root_budget"]
    known = sum(intent["total_tokens"] or 0 for intent in intents)
    if (bound != dispatched or root["model_attempts"] != len(intents) or root["total_tokens"] != known
            or root["tokens_accounted"] != sum(intent["total_tokens"] if intent["usage_status"] == "known" else intent["reservation"] for intent in intents)
            or root["unknown_usage_calls"] != sum(intent["usage_status"] != "known" for intent in intents)
            or root["tokens_dispatched_reserved"] != sum(intent["reservation"] for intent in intents)):
        raise IntegrityError("Actual root accounting differs from all Parent/Child dispatch receipts")
    return {"exact_paid_turns": len(bound), "root_usage_same": True, "context_limit_bytes": 12000}


def baseline_overflow(item, report, run_directory):
    history = prior.readonly_history(Path(run_directory) / "runs", item["scope"], item["run_id"])
    final = history[-1]
    over = [entry for entry in report.get("context_telemetry", []) if entry.get("context_budget_exceeded")]
    disclosures = final["context_store"]["disclosures"]
    if (report["status"] != "partial" or report.get("stop_reason") != "dynamic_context_budget_exceeded"
            or len(over) != 1 or over[0]["model_dispatched"] or over[0]["total_context_bytes"] <= 12000
            or not disclosures or sorted(disclosures[-1]["refs"]) != item["goal_refs"]):
        raise IntegrityError("Baseline did not genuinely reject the requested complete closure before dispatch")
    action = final["decisions"][disclosures[-1]["turn"] - 1]["action"]
    if action["action"] != "disclose" or sorted(action["refs"]) != item["goal_refs"]:
        raise IntegrityError("Baseline closure was not selected by the actual configured model")
    wire, _ = sources().baseline_disclosure(item, final, decision=final.get("model_attempts", len(final["decisions"])) + 1)
    amount = sum(len(message["content"].encode("utf-8")) for message in wire)
    if amount != over[0]["total_context_bytes"] or amount <= 12000:
        raise IntegrityError("Baseline overflow telemetry differs from the complete actual next-turn closure")
    return {"passed": True, "actual_model_disclose": True, "requested_closure_bytes": amount,
        "typed_stop_reason": report["stop_reason"], "oversized_attempt_not_dispatched": True,
        "default_mandatory_stage_overflow_claim": False, "disclosure_granularity_differs": True}


def recovery_boundary(item, run_directory, *, completed=False):
    directory = Path(run_directory)
    marker = OLD.read(directory / "committed-page-process-exit.json")
    history = prior.readonly_history(directory / "runs", item["scope"], item["run_id"])
    candidates = [state for state in history if state.get("trace") and state["trace"][-1]["seq"] == marker["trace_seq"]]
    if not candidates:
        raise IntegrityError("Process interruption lacks a committed checkpoint boundary")
    state = candidates[0]
    if (state["trace"][-1]["event"] != "tool_finished" or state["trace"][-1].get("tool") != "context_read"
            or state["pending_action"] is not None or state["pending_tool"] is not None
            or len(state["window_store"]["receipts"]) != 1 or marker["page_receipt"] != state["window_store"]["receipts"][0]
            or state["deadline"] != marker["deadline"] or state["run_id"] != item["run_id"]
            or state["model_attempts"] != marker["turn"] or state["phase"] == "model_pending"
            or marker["pending_action"] is not None or marker["pending_tool"] is not None):
        raise IntegrityError("Real page process exit was not after the safely committed tool_finished boundary")
    if completed and (history[-1]["deadline"] != marker["deadline"] or history[-1]["run_id"] != item["run_id"]
            or history[-1]["model_attempts"] <= marker["turn"]):
        raise IntegrityError("Resumption reset the original local deadline, run identity or decisions")
    return {"passed": True, "run_id": item["run_id"], "deadline": marker["deadline"], "turn_at_exit": marker["turn"],
        "first_committed_read_before_next_paid": True, "old_paid_retried": False, "budget_reset": False}


def process_recovery_proof(item, run_directory):
    directory = Path(run_directory)
    marker, initial, resumed, intent = [OLD.read(directory / name) for name in (
        "committed-page-process-exit.json", "initial-process-result.json", "resumed-process-intent.json", "resume-intent.json")]
    if (initial["exit_code"] != PAUSE_EXIT or marker["pid"] != initial["pid"] or resumed["pid"] == initial["pid"]
            or resumed["resume"] is not True or resumed["run_id"] != item["run_id"]
            or intent["first_pid"] != initial["pid"] or intent["exit_code"] != PAUSE_EXIT
            or intent["same_run_id"] is not True or intent["paid_retry"] is not False
            or intent["ledger_before"]["unknown_usage_calls"] != 0):
        raise IntegrityError("Committed-page recovery lacks a real original process exit and separate resumed process")
    return {"first_pid": initial["pid"], "resumed_pid": resumed["pid"], "first_exit_code": PAUSE_EXIT,
        "same_run_id": True, "actual_cross_process": True, "unknown_paid_calls_at_resume": 0}


def assess_run(item, report, run_directory):
    if (observe_tool("hypotheses", report) != item["catalog_observations"]["O:hypotheses"]
            or len(report.get("parallel_groups", [])) != 1
            or {child["domain"] for child in report.get("child_results", [])} != {"financial", "market"}):
        raise IntegrityError("Actual complete four-dataset source/hypotheses or frozen parallel route differs")
    if item["variant"] == "baseline":
        return {"acceptance_passed": True, "business_quality_passed": False,
            "baseline_overflow": baseline_overflow(item, report, run_directory), "unequal_outcome_efficiency_claim": False}
    quality = sources().assess_complete(item, report)
    if not quality["functional_passed"]:
        raise IntegrityError("Candidate failed the complete original business oracle and actual final verification")
    final = prior.readonly_history(Path(run_directory) / "runs", item["scope"], item["run_id"])[-1]
    if not runtime(None, None, "candidate")._verification_execution_matches(final):
        raise IntegrityError("Candidate lacks the original authoritative actual verification execution")
    return {"acceptance_passed": True, "business_quality_passed": True, "quality": quality,
        "page_audit": atom_coverage(item, report, Path(run_directory) / "runs"),
        "committed_page_recovery": recovery_boundary(item, run_directory, completed=True),
        "actual_cross_process": process_recovery_proof(item, run_directory)}


def worker(expected_sha, variant, *, resume=False):
    plan = checked(expected_sha)
    item = next(item for item in plan["items"] if item["variant"] == variant)
    directory, dispatch = OUT / "live" / item["run_id"], OUT / "live" / "dispatch"
    campaign = OLD.read(OUT / "live" / "campaign-intent.json")
    deadline = datetime.fromisoformat(campaign["deadline"])
    created = datetime.fromisoformat(campaign["created_at"])
    run_intent = OLD.read(directory / "run-intent.json")
    if (created.tzinfo is None or deadline != created + timedelta(seconds=LIMITS[2])
            or run_intent["deadline"] != campaign["deadline"] or run_intent["plan_sha256"] != expected_sha
            or run_intent["run_id"] != item["run_id"]):
        raise IntegrityError("Original campaign absolute deadline or frozen current task changed")
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("Configured model/endpoint changed after freeze")
    model = RecordingModel(config, deadline, dispatch, plan["items"])
    if model.terminal_unknown or deadline <= utcnow():
        raise IntegrityError("Unknown paid outcome or original campaign deadline prevents new dispatch")
    model.item, model.checkpoints = item, directory / "runs"
    if resume:
        recovery_boundary(item, directory)
    store = CheckpointStore(model.checkpoints) if resume or variant == "baseline" else PauseAfterCommittedRead(model.checkpoints, item, directory)
    service, access = sources().context(plan["task"])
    started, report = time.monotonic(), None
    try:
        report = runtime(service, store, variant, model, inherited_deadline=deadline).run(
            DynamicRequest.from_dict(item["request"]), access,
            **({"resume": item["run_id"]} if resume else {"run_id": item["run_id"]}))
        OLD.write_new(directory / "report.json", report)
        assessment = assess_run(item, report, directory)
        error = None
    except Exception as exc:
        error = type(exc).__name__
        OLD.write_new(directory / "failure.json", {"error_type": error, "report_retained": report is not None,
            "paid_retry": False, "ledger": model.ledger.snapshot()})
        assessment = {"acceptance_passed": False, "business_quality_passed": False}
    intents = [intent for intent in model.ledger.intents if intent["task_id"].split("/")[0] == item["run_id"]]
    child_reports = children(directory, item, report) if report else []
    usage = paid_usage(item, report, child_reports, dispatch, intents) if report else None
    row = {"run_id": item["run_id"], "case_id": item["case_id"], "variant": variant, "parent_version": item["parent_version"],
        "report": report, "child_reports": child_reports, "paid_usage": usage,
        "assessment": assessment, "error_type": error, "intents": intents,
        "token_usage": prior.token_usage(intents, item["parent_version"]), "worker_pid": os.getpid(),
        "worker_runtime_ms": round((time.monotonic() - started) * 1000), "resume": resume,
        "original_campaign_deadline": campaign["deadline"], "new_task_count": 1, "paid_retry": False}
    OLD.write_new(directory / "summary.json", row)
    return row


def launch_worker(expected_sha, item, *, resume=False):
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--variant", item["variant"], "--plan-sha256", expected_sha]
    if resume:
        command.append("--resume")
    directory = OUT / "live" / item["run_id"]
    log = directory / ("resumed-process.log" if resume else "initial-process.log")
    with log.open("xb") as stream:
        process = subprocess.Popen(command, cwd=Path.cwd(), stdout=stream, stderr=stream,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        OLD.write_new(directory / ("resumed-process-intent.json" if resume else "initial-process-intent.json"),
            {"pid": process.pid, "resume": resume, "run_id": item["run_id"], "plan_sha256": expected_sha, "started_at": utcnow().isoformat()})
        code = process.wait()
    OLD.write_new(directory / ("resumed-process-result.json" if resume else "initial-process-result.json"),
        {"pid": process.pid, "exit_code": code, "resume": resume, "finished_at": utcnow().isoformat()})
    return process.pid, code


def live(expected_sha):
    plan = checked(expected_sha)
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    dispatch = directory / "dispatch"
    dispatch.mkdir()
    created = utcnow()
    deadline = created + timedelta(seconds=LIMITS[2])
    OLD.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha, "deadline": deadline.isoformat(),
        "created_at": created.isoformat(),
        "limits": plan["campaign_limits"], "initial_ledger": OLD.RootLedger(LIMITS[0], LIMITS[1]).snapshot(),
        "run_ids": [item["run_id"] for item in plan["items"]], "independent_new_budget": True, "paid_retry": False})
    rows = []
    for item in plan["items"]:
        run_directory = directory / item["run_id"]
        run_directory.mkdir()
        ledger, _, _, unknown = restored_ledger(dispatch, plan["items"])
        if unknown or deadline <= utcnow():
            OLD.write_new(run_directory / "not-started.json", {"reason": "unknown_outcome_or_deadline", "paid_retry": False})
            continue
        OLD.write_new(run_directory / "run-intent.json", {"run_id": item["run_id"], "variant": item["variant"],
            "deadline": deadline.isoformat(), "plan_sha256": expected_sha, "decisions_before": len(ledger.intents), "paid_retry": False})
        pid, code = launch_worker(expected_sha, item)
        if code == PAUSE_EXIT:
            if item["variant"] != "candidate":
                raise IntegrityError("Unexpected process interruption outside candidate page boundary")
            boundary = recovery_boundary(item, run_directory)
            ledger, _, revision, unknown = restored_ledger(dispatch, plan["items"])
            if unknown:
                raise IntegrityError("Unknown paid outcome blocks page recovery")
            OLD.write_new(run_directory / "resume-intent.json", {"first_pid": pid, "exit_code": code,
                "boundary": boundary, "original_campaign_deadline": deadline.isoformat(), "ledger_revision": revision,
                "ledger_before": ledger.snapshot(), "same_run_id": True, "paid_retry": False})
            next_pid, next_code = launch_worker(expected_sha, item, resume=True)
            if next_pid == pid or next_code == PAUSE_EXIT:
                raise IntegrityError("Recovery did not use a new process for the same original run")
        summary_path = run_directory / "summary.json"
        if summary_path.exists():
            row = OLD.read(summary_path)
            row["run_file_hashes"] = prior.original.file_hashes(run_directory)
            rows.append(row)
        else:
            rows.append({"run_id": item["run_id"], "variant": item["variant"], "report": None,
                "assessment": {"acceptance_passed": False}, "error_type": "WorkerProcessStopped", "paid_retry": False})
    ledger, _, _, unknown = restored_ledger(dispatch, plan["items"])
    receipts = _helpers.validate_receipts(dispatch, ledger.snapshot(), plan["items"], directory)
    result = {"schema": "real-pagination-live-summary/v1", "plan_sha256": expected_sha, "rows": rows,
        "ledger": ledger.snapshot(), "receipt_validation": receipts, "deadline": deadline.isoformat(),
        "accepted": len(rows) == 2 and all(row["assessment"]["acceptance_passed"] for row in rows) and not unknown,
        "remaining_same_task_repair_slots": 2, "independent_new_task_count": 1,
        "unknown_outcomes_stop": unknown, "paid_retry": False, "efficiency_improvement_claim": False,
        "model_calls": len(ledger.intents), "financial_provider_network_calls": 0, "defaults_changed": False}
    OLD.write_new(directory / "summary.json", result)
    OLD.write_new(directory / "trace-manifest.json", {"schema": "real-pagination-trace-manifest/v1", "plan_sha256": expected_sha,
        "files_before_manifest": prior.original.file_hashes(directory)})
    if plan["history_hashes"] != history_hashes():
        raise IntegrityError("Real pagination changed immutable historical artifacts")
    return result


def replay(expected_sha):
    plan = checked(expected_sha, replay=True)
    directory = OUT / "live"
    before = prior.original.file_hashes(directory)
    manifest, summary = OLD.read(directory / "trace-manifest.json"), OLD.read(directory / "summary.json")
    if manifest["files_before_manifest"] != {key: value for key, value in before.items() if key != "trace-manifest.json"}:
        raise IntegrityError("Live manifest differs from original immutable files")
    ledger, _, _, unknown = restored_ledger(directory / "dispatch", plan["items"])
    if ledger.snapshot() != summary["ledger"] or _helpers.validate_receipts(directory / "dispatch", ledger.snapshot(), plan["items"], directory) != summary["receipt_validation"]:
        raise IntegrityError("Read-only receipt ledger differs from original live evidence")
    identical, retained = [], []
    by_run = {row["run_id"]: row for row in summary["rows"]}
    with patch.object(CheckpointStore, "append", side_effect=AssertionError("read-only replay cannot append")), \
            patch.object(prior.original.NoNetwork, "complete", side_effect=AssertionError("read-only replay cannot dispatch")):
        for item in plan["items"]:
            row = by_run.get(item["run_id"])
            if row is None or row.get("report") is None:
                retained.append(item["run_id"])
                continue
            run_directory = directory / item["run_id"]
            service, access = sources().context(plan["task"])
            restored = runtime(service, CheckpointStore(run_directory / "runs"), item["variant"], prior.original.NoNetwork()).run(
                DynamicRequest.from_dict(item["request"]), access, resume=item["run_id"])
            if restored != row["report"] or restored != OLD.read(run_directory / "report.json"):
                raise IntegrityError("Completed recovery changed the full original report")
            if row["assessment"]["acceptance_passed"] and assess_run(item, restored, run_directory) != row["assessment"]:
                raise IntegrityError("Completed replay changed overlimit/quality/full object coverage evidence")
            if (row["token_usage"] != prior.token_usage(row["intents"], item["parent_version"])
                    or row["paid_usage"] != paid_usage(item, restored, row["child_reports"], directory / "dispatch", row["intents"])):
                raise IntegrityError("Completed replay changed actual root/Parent/Child Token evidence")
            identical.append(item["run_id"])
    if before != prior.original.file_hashes(directory) or plan["history_hashes"] != history_hashes():
        raise IntegrityError("Read-only completed replay appended or changed original artifacts")
    return {"schema": "real-pagination-readonly-replay/v1", "status": "passed" if summary["accepted"] and len(identical) == 2 and not retained else "failures_retained",
        "plan_sha256": expected_sha, "identical_reports": len(identical), "retained_failures": retained,
        "real_pagination_overlimit_recovery_accepted": summary["accepted"] and len(identical) == 2 and not unknown,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0, "live_files_unchanged": True,
        "efficiency_improvement_claim": False, "full_evidence_objects_read": False}


def audit(expected_sha):
    result = replay(expected_sha)
    plan = checked(expected_sha, replay=True)
    directory = OUT / "live"
    summary, matched, chains = OLD.read(directory / "summary.json"), [], []
    by_run = {row["run_id"]: row for row in summary["rows"]}
    for item in plan["items"]:
        row = by_run.get(item["run_id"])
        if not row or row.get("report") is None:
            continue
        checkpoint_directory = directory / item["run_id"] / "runs"
        histories = {item["parent_version"]: prior.readonly_history(checkpoint_directory, item["scope"], item["run_id"])}
        for child in row["child_reports"]:
            role = CHILD_SPECS[child.get("domain", "financial")].version
            histories[role] = prior.readonly_history(checkpoint_directory, item["scope"], child["run_id"])
            if histories[role][-1]["report"] != child:
                raise IntegrityError("Child full report differs from its own original paid state")
        chains.append({"run_id": item["run_id"], "run_count": len(histories), "checkpoint_rows": sum(map(len, histories.values()))})
        for intent in row["intents"]:
            prefix = f"{intent['number']:03d}"
            messages = OLD.read(directory / "dispatch" / (prefix + "-messages.json"))
            payload = json.loads(messages[1]["content"])
            role, turn = payload["protocol_version"], payload["control"]["decision"]
            pending = [state for state in histories[role] if state["phase"] == "model_pending" and state.get("decisions")
                and state["decisions"][-1]["turn"] == turn and state["decisions"][-1]["message_sha256"] == digest(messages)]
            if len(pending) < 1 or pending[0]["decisions"][-1]["token_reservation"] != intent["reservation"]:
                raise IntegrityError("Actual model action lacks an exact own-run durable predispatch reservation")
            matched.append({"intent": intent["number"], "role": role, "turn": turn, "exact_paid_state": True})
    return {"schema": "real-pagination-readonly-actual-audit/v1", "status": result["status"], "replay": result,
        "chains": chains, "matched_paid_states": matched, "live_files_unchanged": True,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "live", "worker", "replay", "audit", "historical-replay"):
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--offline-evidence", type=Path)
    parser.add_argument("--preflight-evidence", type=Path)
    parser.add_argument("--variant", choices=tuple(VERSIONS))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.historical_replay:
            result = historical_replay()
        elif args.prepare:
            if not args.offline_evidence or not args.preflight_evidence:
                parser.error("prepare requires full offline and read-only preflight evidence")
            result = prepare(args.offline_evidence, args.preflight_evidence)
        elif args.worker:
            if not args.variant or not args.plan_sha256:
                parser.error("worker requires frozen plan SHA and variant")
            row = worker(args.plan_sha256, args.variant, resume=args.resume)
            result = {"status": "passed" if row["assessment"]["acceptance_passed"] else "failure_retained", "run_id": row["run_id"]}
        else:
            if not args.plan_sha256:
                parser.error("this mode requires the explicit frozen plan SHA")
            result = live(args.plan_sha256) if args.live else audit(args.plan_sha256) if args.audit else replay(args.plan_sha256)
        if args.output:
            OLD.write_new(args.output, result)
        print(canonical_json(result if not args.live else {"accepted": result["accepted"], "plan_sha256": args.plan_sha256,
            "known_tokens": result["ledger"]["known_tokens"], "unknown_calls": result["ledger"]["unknown_usage_calls"]}))
        return 0
    except Exception as exc:
        print(canonical_json({"status": "failed", "error_type": type(exc).__name__, "paid_retry": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
