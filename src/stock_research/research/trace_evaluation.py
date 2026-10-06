"""Read-only, deterministic Phase 5 trace descriptions; no routing or tuning.

Rows contain case_id, route (direct/serial/parallel), run_id, sample_kind,
the unmodified Runtime report, and a summary of actually executed validation.
summary.success is bool or None; summary.wall_ms is measured elapsed time;
summary.safety_checks maps named checks to passed/failed/unknown/not_assessable.
Optional child_reports or summary.child_context_telemetry supply actual Child
measurements omitted from the Parent's compact Child result. Missing values stay
unknown. This module neither validates financial ground truth nor reads stores,
contacts models, edits checkpoints, chooses routes, or changes the 12000 cap.
"""
from collections import Counter
from itertools import combinations
from math import ceil, isfinite

from ..errors import ValidationError


SCHEMA = "phase5-trace-evaluation/v1"
CONTEXT_LIMIT_BYTES = 12000
ROUTES = ("direct", "serial", "parallel")
SAFETY_CHECKS = ("point_in_time", "authorization", "immutable_snapshots",
                 "lineage", "numeric_verification")
_KINDS = {"new": "new", "new_validation": "new", "historical": "historical",
          "repair": "repair", "retest": "repair", "synthetic": "synthetic"}
_SAFETY_STATES = ("passed", "failed", "unknown", "not_assessable")
_USAGE_KEYS = ("known_receipt_tokens", "tokens_accounted", "tokens_reserved",
               "tokens_dispatched_reserved", "unknown_usage_calls",
               "unresolved_child_allocations", "model_attempts", "tool_attempts")


def _require(condition, message):
    if not condition:
        raise ValidationError("invalid trace evaluation: " + message)


def _number(value, *, integer=False):
    if value is None:
        return None
    _require(type(value) is int if integer else type(value) in (int, float), "numeric measurement")
    _require(value >= 0 and isfinite(value), "nonnegative finite measurement")
    return value


def _distribution(values):
    """Known subtotal and descriptive nearest-rank quantiles, never imputation."""
    measured = sorted(value for value in values if value is not None)
    missing = len(values) - len(measured)
    return {"sample_count": len(measured), "unknown_count": missing,
            "known_subtotal": sum(measured) if measured else None,
            "total": sum(measured) if measured and not missing else None,
            "minimum": measured[0] if measured else None,
            "maximum": measured[-1] if measured else None,
            "p50": measured[ceil(.50 * len(measured)) - 1] if measured else None,
            "p95": measured[ceil(.95 * len(measured)) - 1] if measured else None,
            "percentile_method": "nearest_rank", "descriptive_only": True,
            "small_sample": len(measured) < 20}


def _checks(report):
    checks = report.get("required_checks")
    if checks is None:
        return {"required": None, "passed": None, "executed": None,
                "completion_rate": None, "fully_decisive_completion_rate": None,
                "execution_required": None, "execution_passed": None,
                "execution_completion_rate": None, "evaluated_completion_rate": None, "statuses": {}}
    _require(type(checks) is list and all(type(check) is dict for check in checks), "required checks")
    identities = [check.get("id") for check in checks]
    _require(all(type(key) is str and key for key in identities)
             and len(set(identities)) == len(identities), "unique required check IDs")
    _require(all(check.get("status", "unknown") in ("passed", "insufficient", "not_completed", "unknown")
                 for check in checks), "required check status")
    statuses = Counter(check.get("status", "unknown") for check in checks)
    passed = statuses.get("passed", 0)
    execution = [check for check in checks if not check["id"].startswith("hypothesis:")]
    execution_passed = sum(check.get("status") == "passed" for check in execution)
    executed = passed + sum(check.get("status") == "insufficient"
                            and check["id"].startswith("hypothesis:") for check in checks)
    return {"required": len(checks), "passed": passed, "executed": executed,
            "completion_rate": passed / len(checks) if checks else None,
            "fully_decisive_completion_rate": passed / len(checks) if checks else None,
            "execution_required": len(execution), "execution_passed": execution_passed,
            "execution_completion_rate": execution_passed / len(execution) if execution else None,
            "evaluated_completion_rate": executed / len(checks) if checks else None,
            "statuses": dict(sorted(statuses.items()))}


def _validated_success(row, report, summary, checks):
    observed = summary.get("success")
    _require(observed is None or type(observed) is bool, "validation success")
    expected_status, expected = summary.get("expected_status"), summary.get("expected_required_checks")
    oracle_match = None
    if expected_status is not None or expected is not None:
        _require(expected_status in ("completed", "insufficient") and type(expected) is list, "frozen outcome oracle")
        expected_metrics = _checks({"required_checks": expected})
        _require(expected_metrics["required"] > 0 and expected_metrics["execution_completion_rate"] == 1
                 and expected_metrics["evaluated_completion_rate"] == 1, "complete frozen required check oracle")
        if expected_status == "completed":
            _require(expected_metrics["fully_decisive_completion_rate"] == 1, "completed oracle requires decisive checks")
        actual_checks = report.get("required_checks", [])
        oracle_match = (report.get("status") == expected_status
                        and {check["id"]: check["status"] for check in actual_checks}
                            == {check["id"]: check["status"] for check in expected})
    if observed is not True:
        return observed, oracle_match
    if oracle_match is not None:
        return oracle_match, oracle_match
    if _KINDS[row["sample_kind"]] == "new":
        # New success needs a frozen oracle, including the case's lawful
        # insufficient outcome. A model finish and a bool are not that oracle.
        return None, None
    # Historical scoring belongs to its original frozen acceptance protocol.
    # Preserve that observation, including lawful insufficient outcomes; these
    # runs never enter the new denominator and are not silently rescored here.
    return observed, None


def _usage(report, summary):
    children = report.get("child_results", [])
    root = report.get("root_budget")
    parent = report.get("usage", {})
    _require(type(children) is list and type(parent) is dict
             and (root is None or type(root) is dict), "usage objects")
    # Parent usage is the full root usage when there is no Child; never add it
    # again to a root ledger that already includes settled Child contributions.
    source = root if root is not None else parent if not children else {}
    origin = "root_ledger" if root is not None else "parent_no_child" if not children else "missing_root_with_children"
    direct = root is None and not children
    result = {"origin": origin,
              "known_receipt_tokens": _number(source.get("total_tokens"), integer=True),
              "tokens_accounted": _number(source.get("tokens_accounted"), integer=True),
              "tokens_reserved": _number(source.get("tokens_reserved"), integer=True),
              "tokens_dispatched_reserved": _number(source.get("tokens_dispatched_reserved",
                  parent.get("tokens_reserved") if direct else summary.get("root_tokens_reserved_dispatched")), integer=True),
              "unknown_usage_calls": _number(source.get("unknown_usage_calls"), integer=True),
              "unresolved_child_allocations": _number(source.get("unresolved_child_allocations", 0 if direct else None), integer=True),
              "model_attempts": _number(source.get("model_attempts"), integer=True),
              "tool_attempts": _number(source.get("tool_attempts", parent.get("tool_calls") if direct else None), integer=True)}
    result["complete_receipt_tokens"] = (result["known_receipt_tokens"]
        if result["unknown_usage_calls"] == 0 and result["unresolved_child_allocations"] == 0 else None)
    return result


def _context(row, report, summary):
    sources = [report.get("context_telemetry", [])]
    child_reports = row.get("child_reports", [])
    _require(type(child_reports) is list and all(type(child) is dict for child in child_reports), "Child reports")
    sources.extend(child.get("context_telemetry", []) for child in child_reports)
    sources.append(summary.get("child_context_telemetry", []))
    expected_runs = {row["run_id"]: report.get("usage", {}).get("model_attempts")}
    for child in report.get("child_results", []):
        _require(type(child) is dict and type(child.get("child_run_id")) is str, "Child result identity")
        expected_runs[child["child_run_id"]] = child.get("usage", {}).get("model_attempts")
    for group in report.get("parallel_groups", []):
        for branch in (group.get("telemetry") or {}).get("branches", []):
            if type(branch.get("child_run_id")) is str:
                expected_runs.setdefault(branch["child_run_id"], None)
    for child in child_reports:
        _require(child.get("run_id") in expected_runs and child.get("run_id") != row["run_id"], "bound Child report")
        _require(child.get("parent_run_id", row["run_id"]) == row["run_id"], "Child parent binding")
        attempts = child.get("usage", {}).get("model_attempts")
        if attempts is not None:
            previous = expected_runs[child["run_id"]]
            _require(previous is None or previous == attempts, "Child attempt count differs")
            expected_runs[child["run_id"]] = attempts
    records = {}
    for source in sources:
        _require(type(source) is list, "context telemetry list")
        for record in source:
            _require(type(record) is dict and type(record.get("run_id")) is str
                     and record.get("run_id") in expected_runs
                     and type(record.get("turn_id")) is int and record["turn_id"] > 0, "context telemetry identity")
            key = (record["run_id"], record["turn_id"])
            _require(key not in records or records[key] == record, "conflicting repeated context measurement")
            records[key] = record
    measured, overflows, dispatched_over, cap_mismatches = [], 0, 0, 0
    unknown = 0
    for record in records.values():
        size = _number(record.get("total_context_bytes"), integer=True)
        limit = _number(record.get("context_limit_bytes"), integer=True)
        flag, dispatched = record.get("context_budget_exceeded"), record.get("model_dispatched")
        _require(flag is None or type(flag) is bool, "context overflow flag")
        _require(dispatched is None or type(dispatched) is bool, "context dispatch flag")
        if size is None or flag is None or limit is None or dispatched is None:
            unknown += 1
        if size is not None:
            measured.append(size)
        overflows += flag is True or (size is not None and size > CONTEXT_LIMIT_BYTES)
        dispatched_over += dispatched is True and size is not None and size > CONTEXT_LIMIT_BYTES
        cap_mismatches += limit is not None and limit != CONTEXT_LIMIT_BYTES
    recorded_runs = {key[0] for key in records}
    missing_runs = sorted(set(expected_runs) - recorded_runs)
    missing_turn_counts, unknown_counts, dispatch_inconsistencies = {}, [], 0
    for run_id, attempts in sorted(expected_runs.items()):
        attempts = _number(attempts, integer=True)
        if attempts is None:
            unknown_counts.append(run_id)
        else:
            present = sum(identity == run_id and turn <= attempts for identity, turn in records)
            missing_turn_counts[run_id] = attempts - present
            dispatch_inconsistencies += sum(identity == run_id and turn > attempts
                and record.get("model_dispatched") is True
                for (identity, turn), record in records.items())
    return {"fixed_limit_bytes": CONTEXT_LIMIT_BYTES, "measured_turns": len(records),
            "maximum_bytes": max(measured) if measured else None,
            "overflow_turns": overflows if records else None,
            "dispatched_over_limit_turns": dispatched_over if records else None,
            "cap_mismatch_turns": cap_mismatches if records else None,
            "unknown_measurements": unknown, "missing_run_ids": missing_runs,
            "dispatch_attempt_inconsistencies": dispatch_inconsistencies,
            "missing_attempt_turn_counts": missing_turn_counts, "unknown_run_attempt_counts": unknown_counts,
            "measurement_complete": bool(records) and not unknown and not missing_runs
                and not unknown_counts and not any(missing_turn_counts.values()) and not dispatch_inconsistencies}


def _latency(row, report, summary):
    groups = report.get("parallel_groups", [])
    _require(type(groups) is list, "parallel groups")
    sections, branches = [], []
    for group in groups:
        _require(type(group) is dict, "parallel group")
        telemetry = group.get("telemetry")
        if telemetry is None:
            sections.append(None)
            continue
        _require(type(telemetry) is dict and type(telemetry.get("branches", [])) is list, "parallel telemetry")
        sections.append(_number(telemetry.get("wall_clock_ms")))
        for branch in telemetry.get("branches", []):
            _require(type(branch) is dict, "branch latency")
            branches.append({"domain": branch.get("domain"), "child_run_id": branch.get("child_run_id"),
                             "execution_ms": _number(branch.get("execution_ms")), "origin": "parallel_telemetry"})
    if not groups:
        children = report.get("child_results", [])
        child_wall = summary.get("child_wall_ms", {})
        _require(type(child_wall) is dict, "Child wall measurements")
        for child in children:
            domain = child.get("domain", "financial")
            branches.append({"domain": domain, "child_run_id": child.get("child_run_id"),
                             "execution_ms": _number(child_wall.get(domain)), "origin": "measured_child_wall"})
    return {"wall_ms": _number(summary.get("wall_ms")),
            "parallel_section_ms": sum(sections) if sections and all(v is not None for v in sections) else None,
            "parallel_section_status": "measured" if sections and all(v is not None for v in sections)
                else "unknown" if row["route"] == "parallel" else "not_assessable",
            "children": branches}


def _normalize(row):
    _require(type(row) is dict, "row object")
    for name in ("case_id", "run_id"):
        _require(type(row.get(name)) is str and row[name], "row identity")
    _require(row.get("route") in ROUTES and row.get("sample_kind") in _KINDS, "route or sample kind")
    report, summary = row.get("report") or {}, row.get("summary") or {}
    _require(type(report) is dict and type(summary) is dict, "report and summary")
    _require(report.get("run_id", row["run_id"]) == row["run_id"], "report run binding")
    checks = _checks(report)
    observed_success = summary.get("success")
    success, oracle_match = _validated_success(row, report, summary, checks)
    # Missing executed validation remains unknown, even if the model finished.
    success_inconsistent = observed_success is True and success is False
    safety = summary.get("safety_checks", {})
    _require(type(safety) is dict, "executed safety checks")
    safety = {name: safety.get(name, "unknown") for name in sorted(set(SAFETY_CHECKS) | set(safety))}
    _require(all(type(name) is str and state in _SAFETY_STATES for name, state in safety.items()), "safety state")
    return {"case_id": row["case_id"], "route": row["route"], "run_id": row["run_id"],
            "sample_kind": _KINDS[row["sample_kind"]], "report_status": report.get("status"),
            "stop_reason": report.get("stop_reason"), "success": success,
            "observed_validation_success": observed_success, "frozen_outcome_oracle_match": oracle_match,
            "assessment_scope": "new_frozen_validation" if _KINDS[row["sample_kind"]] == "new"
                else "historical_or_mechanism_observation_only",
            "success_inconsistent": success_inconsistent, "required_checks": checks,
            "root_usage": _usage(report, summary), "latency": _latency(row, report, summary),
            "context": _context(row, report, summary), "safety_checks": safety}


def _route_summary(runs):
    success_count = sum(run["success"] is True for run in runs)
    unknown_success = sum(run["success"] is None for run in runs)
    required = [run["required_checks"]["required"] for run in runs]
    passed = [run["required_checks"]["passed"] for run in runs]
    executed = [run["required_checks"]["executed"] for run in runs]
    execution_required = [run["required_checks"]["execution_required"] for run in runs]
    execution_passed = [run["required_checks"]["execution_passed"] for run in runs]
    complete_checks = all(value is not None for value in required + passed)
    safety = {}
    for name in sorted(set(SAFETY_CHECKS) | {key for run in runs for key in run["safety_checks"]}):
        counts = Counter(run["safety_checks"].get(name, "unknown") for run in runs)
        safety[name] = {state: counts.get(state, 0) for state in _SAFETY_STATES}
    return {"independent_task_count": len({run["case_id"] for run in runs}), "run_count": len(runs),
            "success": {"passed": success_count, "failed": sum(run["success"] is False for run in runs),
                        "unknown": unknown_success, "denominator": len(runs),
                        "rate": success_count / len(runs) if runs and not unknown_success else None,
                        "observed_lower_bound_rate": success_count / len(runs) if runs else None},
            "required_checks": {"required": sum(required) if complete_checks else None,
                                "passed": sum(passed) if complete_checks else None,
                                "executed": sum(executed) if complete_checks else None,
                                "completion_rate": sum(passed) / sum(required)
                                    if complete_checks and sum(required) else None,
                                "fully_decisive_completion_rate": sum(passed) / sum(required)
                                    if complete_checks and sum(required) else None,
                                "evaluated_completion_rate": sum(executed) / sum(required)
                                    if complete_checks and sum(required) else None,
                                "execution_required": sum(execution_required) if complete_checks else None,
                                "execution_passed": sum(execution_passed) if complete_checks else None,
                                "execution_completion_rate": sum(execution_passed) / sum(execution_required)
                                    if complete_checks and sum(execution_required) else None,
                                "unknown_runs": sum(value is None for value in required)},
            "root_usage": {name: _distribution([run["root_usage"][name] for run in runs]) for name in _USAGE_KEYS},
            "wall_ms": _distribution([run["latency"]["wall_ms"] for run in runs]),
            "parallel_section_ms": _distribution([run["latency"]["parallel_section_ms"] for run in runs]),
            "child_execution_ms": _distribution([child["execution_ms"] for run in runs for child in run["latency"]["children"]]),
            "context": {"fixed_limit_bytes": CONTEXT_LIMIT_BYTES,
                        "maximum_bytes": max((run["context"]["maximum_bytes"] for run in runs
                                              if run["context"]["maximum_bytes"] is not None), default=None),
                        "overflow_turns": _distribution([run["context"]["overflow_turns"] for run in runs]),
                        "dispatched_over_limit_turns": _distribution([run["context"]["dispatched_over_limit_turns"] for run in runs]),
                        "cap_mismatch_turns": _distribution([run["context"]["cap_mismatch_turns"] for run in runs]),
                        "incomplete_measurement_runs": sum(not run["context"]["measurement_complete"] for run in runs)},
            "safety": {"checks": safety,
                       "observed_validation_failures": sum(value["failed"] for value in safety.values()),
                       "unknown_checks": sum(value["unknown"] for value in safety.values()),
                       "not_assessable_checks": sum(value["not_assessable"] for value in safety.values())}}


def _paired(runs):
    by_case = {}
    for run in runs:
        by_case.setdefault(run["case_id"], {})[run["route"]] = run
    result = []
    for case_id, routes in sorted(by_case.items()):
        for left_route, right_route in combinations(ROUTES, 2):
            left, right = routes.get(left_route), routes.get(right_route)
            if left is None or right is None:
                continue
            pair = {"case_id": case_id, "left_route": left_route, "right_route": right_route,
                    "left_run_id": left["run_id"], "right_run_id": right["run_id"],
                    "left_success": left["success"], "right_success": right["success"],
                    "both_successful": left["success"] is True and right["success"] is True,
                    "delta_semantics": "right_minus_left; descriptive; failures retained"}
            values = {"wall_ms": (left["latency"]["wall_ms"], right["latency"]["wall_ms"]),
                      "success": (int(left["success"]) if left["success"] is not None else None,
                                  int(right["success"]) if right["success"] is not None else None),
                      "required_check_completion": (left["required_checks"]["completion_rate"], right["required_checks"]["completion_rate"]),
                      "execution_completion": (left["required_checks"]["execution_completion_rate"], right["required_checks"]["execution_completion_rate"]),
                      "evaluated_completion": (left["required_checks"]["evaluated_completion_rate"], right["required_checks"]["evaluated_completion_rate"])}
            values.update({name: (left["root_usage"][name], right["root_usage"][name])
                           for name in ("complete_receipt_tokens", "tokens_accounted", "tokens_reserved", "tokens_dispatched_reserved")})
            pair["deltas"] = {name: b - a if a is not None and b is not None else None for name, (a, b) in values.items()}
            result.append(pair)
    return result


def evaluate_traces(rows):
    """Describe actual new validation runs; preserve excluded historical outcomes.

    Replayed identical run IDs are deduplicated. Conflicting copies are rejected.
    A second new run of the same case/route must be marked repair/retest so it
    cannot replace a failure or enlarge the independent task denominator.
    """
    _require(type(rows) in (list, tuple), "rows sequence")
    unique, original, duplicates = {}, {}, 0
    for row in rows:
        run = _normalize(row)
        identity = run["run_id"]
        if identity in unique:
            _require(original[identity] == row, "conflicting duplicate run")
            duplicates += 1
        else:
            unique[identity], original[identity] = run, row
    runs = sorted(unique.values(), key=lambda run: (run["case_id"], ROUTES.index(run["route"]), run["run_id"]))
    new = [run for run in runs if run["sample_kind"] == "new"]
    keys = [(run["case_id"], run["route"]) for run in new]
    _require(len(keys) == len(set(keys)), "new same-case route rerun must be marked repair/retest")
    excluded = [run for run in runs if run["sample_kind"] != "new"]
    return {"schema": SCHEMA,
            "denominators": {"independent_new_task_count": len({run["case_id"] for run in new}),
                             "new_run_count": len(new), "all_unique_run_count": len(runs),
                             "duplicate_rows_ignored": duplicates,
                             "excluded_run_counts": {kind: sum(run["sample_kind"] == kind for run in excluded)
                                                     for kind in ("historical", "repair", "synthetic")}},
            "routes": {route: _route_summary([run for run in new if run["route"] == route]) for route in ROUTES},
            "runs": new, "excluded_runs": excluded, "paired_cases": _paired(new),
            "assessment_limits": {"task_success": "bounded functional completion against executed validation",
                                  "financial_ground_truth": "not_assessed",
                                  "composite_quality_score": "not_defined",
                                  "statistical_route_superiority": "not_established",
                                  "threshold_tuning": "not_performed",
                                  "context_limit_bytes": CONTEXT_LIMIT_BYTES}}
