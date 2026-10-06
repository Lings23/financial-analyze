"""Pre-freeze input validation, separate from the legacy Research Runtime.

This module never refreshes data, selects an event, changes a request, or scores
an Agent response. ``validate_contract`` accepts only already-authorized source
rows and explicit trusted application metadata. Missing metadata is unknown,
never a pass. A checkable failed financial/market precondition remains a valid
input with a separate intrinsic/data limitation, preserving its denominator.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from ..errors import PermissionDenied, ValidationError
from ..domains import BASES as DOMAIN_BASES, DomainDataset
from ..models import AccessContext, QueryContext
from .study_contracts import StudyRequest


VERSION = "benchmark-contract/v1"
ISSUE_CATEGORIES = (
    "research_agent_implementation_defect",
    "benchmark_or_request_contract_defect",
    "data_or_evidence_insufficiency",
    "intrinsic_precondition_or_temporal_impossibility",
)
REQUIRED_DATASETS = {
    "mechanical_adjustment": ("market_daily", "adjustment_factor"),
    "market_direction": ("market_daily", "index_daily"),
    "financial_deterioration": ("financial_income",),
    "absolute_profit_change": ("financial_income",),
    "cashflow_divergence": ("financial_income", "financial_cashflow"),
    "event_chronology": ("market_daily",),
}
CN = timezone(timedelta(hours=8))
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _row_dict(row):
    return row.to_dict() if hasattr(row, "to_dict") else dict(row)


def _record_id(row):
    payload = dict(row)
    payload.pop("ingested_at", None)
    payload.pop("record_id", None)
    return _hash(payload)


def _moment(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timezone-aware source timestamp required")
    return value


def _number(row, name):
    values = [m.get("value") for m in row.get("metrics", []) if m.get("name") == name]
    if len(values) != 1 or values[0] is None:
        return None
    try:
        result = Decimal(str(values[0]))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def _closes(rows):
    return sorted((r for r in rows if (_number(r, "close") is not None
                                      and _number(r, "close") > 0)), key=lambda r: r["period"])


def _verified_empty_capture(proof, request, binding, owner_scope):
    """Verify an authorized original empty response without inventing rows."""
    if not isinstance(proof, dict):
        return False
    api_names = {"market_daily": "daily", "index_daily": "index_daily", "adjustment_factor": "adj_factor"}
    api_name = api_names.get(binding.dataset)
    try:
        archive = proof["archive"]
        if (api_name is None or binding.provider != "tushare"
                or proof.get("kind") != "tushare_requested_response_v2_empty/v1"
                or proof.get("source_authorized") is not True or proof.get("source_scope") != owner_scope
                or proof.get("bound_snapshot") != binding.snapshot
                or proof.get("request_identity") != request.data_request(binding).identity()
                or _hash(archive) != proof.get("archive_artifact_id")):
            return False
        required_fields = {"ts_code", "trade_date", "adj_factor" if binding.dataset == "adjustment_factor" else "close"}
        if (archive.get("archive_schema") != "tushare_requested_response_v2"
                or archive.get("api_name") != api_name or type(archive.get("business_code")) is not int
                or archive["business_code"] != 0 or archive.get("items") != []
                or type(archive.get("response_row_count")) is not int or archive["response_row_count"] != 0
                or type(archive.get("selected_row_count")) is not int or archive["selected_row_count"] != 0
                or not required_fields <= set(archive.get("response_fields", []))):
            return False
        params = archive["params"]
        subject = request.data_request(binding).security
        if (params.get("ts_code") != subject.provider_symbol
                or params.get("start_date") != binding.start.strftime("%Y%m%d")
                or params.get("end_date") != binding.end.strftime("%Y%m%d")):
            return False
        started, captured = _moment(archive["started_at"]), _moment(archive["finished_at"])
        return started <= captured <= request.as_of
    except (KeyError, TypeError, ValueError):
        return False


def validate_contract(request, scope, datasets, binding_metadata):
    """Audit a frozen request against independently supplied source inputs.

    ``datasets`` maps Dataset names to source-row lists or ``{"records": [...]}``.
    Rows must already be selected under the request's PIT/window/version rules.
    Each metadata entry must contain ``trusted=True``, ``authorized=True``,
    ``artifacts_verified=True``, recipient ``scope``, ``snapshot``, ``provider``,
    ``provider_datasets``, ``snapshot_datasets``, and complete
    ``snapshot_record_ids``. ``owner_scope`` defaults to recipient ``scope``;
    an explicit owner permits an application-authorized ScopedReadService grant.
    Snapshot identity and membership are independently rehashed here.

    For an actually empty compatible Tushare daily/index/factor query, optional
    ``empty_dataset_capture`` carries a verified original requested-response-v2
    archive, its immutable hash, exact request identity, authorized owner scope
    and bound snapshot. Its captured response must be successful, exactly empty,
    match security/window, and be visible at cutoff. This proves data absence,
    not Dataset/provider incompatibility; it never adds rows or permits a
    different provider. The application must authorize and verify the original
    archive before providing this descriptor.

    Trust/authorization flags are a trusted application boundary, not fields to
    accept from an Agent, CLI request JSON, or the report being evaluated.
    """
    payload = request.to_dict() if isinstance(request, StudyRequest) else request
    raw_datasets = {k: [_row_dict(r) for r in (v.get("records", []) if isinstance(v, dict) else v)]
                    for k, v in datasets.items()}
    result = {
        "schema": VERSION, "scope": scope,
        "input_sha256": _hash({"request": payload, "scope": scope,
                               "datasets": raw_datasets, "binding_metadata": binding_metadata}),
        "valid": None, "status": "not_assessable", "issues": [],
        "dataset_compatibility": {}, "event_completeness": {"required": False},
        "temporal_feasibility": {"required": False}, "hypothesis_preconditions": {},
    }
    invalid, unknown = False, False

    def issue(code, detail, *, category=ISSUE_CATEGORIES[1], dataset=None,
              hypothesis=None, blocks=False, unassessable=False):
        nonlocal invalid, unknown
        item = {"category": category, "code": code, "detail": detail,
                "dataset": dataset, "hypothesis": hypothesis,
                "blocks_freeze": blocks or unassessable}
        if item not in result["issues"]:
            result["issues"].append(item)
        invalid = invalid or blocks
        unknown = unknown or unassessable

    def finish():
        result["valid"] = False if invalid else (None if unknown else True)
        result["status"] = ("benchmark_contract_invalid" if invalid else
                            "not_assessable" if unknown else "benchmark_contract_valid")
        counts = Counter(i["category"] for i in result["issues"])
        result["problem_class_counts"] = {key: counts[key] for key in ISSUE_CATEGORIES}
        return result

    try:
        request = request if isinstance(request, StudyRequest) else StudyRequest.from_dict(payload)
    except (ValidationError, TypeError, ValueError):
        issue("invalid_request_schema", "StudyRequest schema or aware cutoff is invalid", blocks=True)
        return finish()
    if not isinstance(scope, str) or not scope.strip():
        issue("invalid_scope", "Trusted application scope is missing", blocks=True)
    bindings = {b.dataset: b for b in request.bindings}
    cutoff = request.as_of
    selected = {}

    for name, binding in bindings.items():
        check = {"provider": binding.provider, "snapshot": binding.snapshot,
                 "compatible": None, "visible_record_count": 0}
        result["dataset_compatibility"][name] = check
        meta = binding_metadata.get(name)
        if not isinstance(meta, dict) or meta.get("trusted") is not True:
            issue("trusted_binding_metadata_missing", "Independent trusted metadata is required",
                  dataset=name, unassessable=True)
            continue
        if meta.get("authorized") is not True:
            issue("source_not_authorized", "Current source read authorization is absent",
                  dataset=name, blocks=True)
            continue
        if (meta.get("scope") != scope or meta.get("snapshot") != binding.snapshot
                or meta.get("provider") != binding.provider):
            issue("binding_identity_mismatch", "Scope/snapshot/provider differs from trusted binding",
                  dataset=name, blocks=True)
            check["compatible"] = False
            continue
        required_metadata = {"provider_datasets", "snapshot_datasets", "snapshot_record_ids"}
        if not required_metadata <= meta.keys() or meta.get("artifacts_verified") is not True:
            issue("trusted_source_metadata_incomplete", "Capabilities, full membership and artifact verification required",
                  dataset=name, unassessable=True)
            continue
        ids = meta["snapshot_record_ids"]
        if (not isinstance(ids, (list, tuple))
                or any(not isinstance(r, str) or not _HEX.fullmatch(r) for r in ids)
                or len(ids) != len(set(ids))):
            issue("snapshot_membership_invalid", "Snapshot record IDs must be complete unique immutable hashes",
                  dataset=name, blocks=True)
            check["compatible"] = False
            continue
        sid = _hash({"scope": meta.get("owner_scope", scope), "record_ids": sorted(ids)})
        if sid != binding.snapshot:
            issue("snapshot_hash_mismatch", "Snapshot identity does not match scope and complete member IDs",
                  dataset=name, blocks=True)
            check["compatible"] = False
            continue
        provider_compatible = name in meta["provider_datasets"]
        snapshot_contains_dataset = name in meta["snapshot_datasets"]
        empty_proof = meta.get("empty_dataset_capture")
        empty_capture_verified = (provider_compatible and not snapshot_contains_dataset
                                  and _verified_empty_capture(empty_proof, request, binding, meta.get("owner_scope", scope)))
        check.update(provider_compatible=provider_compatible,
                     snapshot_contains_dataset=snapshot_contains_dataset,
                     empty_capture_verified=empty_capture_verified)
        if not provider_compatible or (not snapshot_contains_dataset and not empty_capture_verified):
            issue("market_source_incompatible" if name == "market_daily" else "dataset_source_incompatible",
                  "Required Dataset is outside provider capability or absent from snapshot without independently verified empty-query provenance",
                  dataset=name, blocks=True)
            if empty_proof is not None and not snapshot_contains_dataset and not empty_capture_verified:
                issue("empty_capture_provenance_invalid", "Empty-query evidence fails exact request, hash, authorization or capture-time checks",
                      dataset=name, blocks=True)
            check["compatible"] = False
            continue
        check["compatible"] = True
        rows = raw_datasets.get(name, [])
        if empty_capture_verified and rows:
            issue("empty_capture_provenance_invalid", "Verified empty Dataset contradicts supplied visible source rows",
                  dataset=name, blocks=True)
            continue
        accepted, keys = [], set()
        expected_id = request.data_request(binding).security.security_id
        for row in rows:
            try:
                rid = _record_id(row)
                subject = row.get("subject")
                row_security = row.get("security_id")
                if subject:
                    symbol = (f"{subject['exchange']}:{subject['code']}" if subject["kind"] == "equity"
                              else subject["code"])
                    row_security = f"CN:{subject['kind']}:{symbol}"
                period = date.fromisoformat(row["period"])
                available, ingested = _moment(row["available_at"]), _moment(row["ingested_at"])
                retrieved = _moment(row["retrieved_at"])
                expected_basis = request.data_request(binding).basis
                row_basis = row.get("basis")
                if row.get("record_kind") == "domain_v2":
                    row_basis = DOMAIN_BASES[DomainDataset(name)]
                key = (period, row_basis, row.get("fact_id", ""))
                if (rid not in ids or (row.get("record_id") is not None and row["record_id"] != rid)
                        or row.get("dataset") != name or row.get("provider") != binding.provider
                        or row_security != expected_id or row_basis != expected_basis
                        or not binding.start <= period <= binding.end):
                    raise ValueError("source identity/window/membership mismatch")
                if available > cutoff or (request.mode.value == "system" and ingested > cutoff):
                    raise ValueError("selected source is not PIT-visible")
                if not all(row.get(k) for k in ("provider_version", "revision_id", "source_url", "source_key",
                                                "provider_call_id", "artifact_id")):
                    raise ValueError("source version/lineage is missing")
                if not _HEX.fullmatch(row["artifact_id"]) or ingested < retrieved:
                    raise ValueError("invalid source artifact or ingestion chronology")
                availability_basis = row.get("availability_basis")
                if availability_basis == "observed_at":
                    if available < retrieved:
                        raise ValueError("observed source visibility was backdated")
                elif availability_basis == "verified_release":
                    published = _moment(row["published_at"])
                    if published > retrieved or available < published:
                        raise ValueError("verified source publication chronology is inconsistent")
                elif availability_basis == "verified_release_date":
                    release_date = date.fromisoformat(row["release_date"])
                    if (row.get("published_at") is not None
                            or not _HEX.fullmatch(row.get("release_evidence_artifact_id", ""))
                            or available < datetime.combine(release_date + timedelta(days=1), time(), CN)
                            or release_date > retrieved.astimezone(CN).date()):
                        raise ValueError("date-only source publication is unqualified or backdated")
                else:
                    raise ValueError("source availability precision is unknown")
                if key in keys:
                    raise ValueError("multiple selected source versions for one fact")
                keys.add(key)
                if name in {"market_daily", "index_daily"} and datetime.combine(period, time(15), CN) > cutoff:
                    raise ValueError("daily close is after cutoff")
                accepted.append(row)
            except (KeyError, TypeError, ValueError):
                issue("source_selection_contract_mismatch", "Selected source violates identity, window, membership, version or PIT",
                      dataset=name, blocks=True)
        selected[name] = sorted(accepted, key=lambda r: r["period"])
        check["visible_record_count"] = len(accepted)
        if not accepted:
            issue("missing_dataset", "Legal compatible snapshot has no matching PIT-visible source rows",
                  dataset=name, category=ISSUE_CATEGORIES[2])

    for hid in request.hypotheses:
        need = REQUIRED_DATASETS[hid]
        missing = [name for name in need if name not in bindings]
        pre = {"required_datasets": list(need), "checkable": None, "condition": "not_assessable"}
        result["hypothesis_preconditions"][hid] = pre
        for name in missing:
            issue("required_dataset_not_bound", "Required hypothesis Dataset has no input binding",
                  dataset=name, hypothesis=hid, blocks=True)
        if missing:
            pre.update(checkable=False, condition="contract_invalid")
            continue
        if hid in {"market_direction", "mechanical_adjustment"}:
            other_name = "index_daily" if hid == "market_direction" else "adjustment_factor"
            market_window, other_window = bindings["market_daily"], bindings[other_name]
            if max(market_window.start, other_window.start) > min(market_window.end, other_window.end):
                pre.update(checkable=False, condition="contract_invalid")
                issue("required_windows_disjoint", "Required stock and comparison/factor binding windows have no common date",
                      hypothesis=hid, blocks=True)
                continue
        if any(name not in selected for name in need):
            continue
        if any(not selected[name] for name in need):
            pre.update(checkable=False, condition="evidence_missing")
            continue
        pre["checkable"] = True
        pre["condition"] = "checkable"
        if hid in {"financial_deterioration", "absolute_profit_change"}:
            income = selected["financial_income"]
            latest = income[-1]
            prior_period = str(int(latest["period"][:4]) - 1) + latest["period"][4:]
            prior = next((r for r in income if r["period"] == prior_period), None)
            pre["report_period"] = latest["period"]
            pre["required_prior_period"] = prior_period
            if prior is None:
                income_binding = bindings["financial_income"]
                if not income_binding.start.isoformat() <= prior_period <= income_binding.end.isoformat():
                    pre.update(checkable=False, condition="contract_invalid")
                    issue("required_report_period_outside_window", "Requested financial window excludes the required same-period prior-year base",
                          dataset="financial_income", hypothesis=hid, blocks=True)
                else:
                    pre.update(checkable=False, condition="evidence_missing")
                    issue("missing_report_period", "Visible latest financial period has no visible same-period prior-year base",
                          dataset="financial_income", hypothesis=hid, category=ISSUE_CATEGORIES[2])
            else:
                for metric in (("net_income_parent",) if hid == "absolute_profit_change" else ("revenue", "net_income_parent")):
                    a, b = _number(latest, metric), _number(prior, metric)
                    if a is None or b is None:
                        pre.update(checkable=False, condition="evidence_missing")
                        issue("missing_metric", f"Same-period {metric} input is missing",
                              dataset="financial_income", hypothesis=hid, category=ISSUE_CATEGORIES[2])
                    elif b <= 0 and hid == "financial_deterioration":
                        pre["condition"] = "positive_base_precondition_failed"
                        issue("positive_base_precondition_failed", f"Visible same-period {metric} base is nonpositive; original rule cannot compute this YoY",
                              dataset="financial_income", hypothesis=hid, category=ISSUE_CATEGORIES[3])
        elif hid == "cashflow_divergence":
            a, b = selected["financial_income"][-1], selected["financial_cashflow"][-1]
            if a["period"] != b["period"]:
                pre.update(checkable=False, condition="evidence_missing")
                issue("missing_report_period", "Latest visible income and cashflow periods differ",
                      hypothesis=hid, category=ISSUE_CATEGORIES[2])
            elif _number(a, "net_income_parent") is None or _number(b, "operating_cashflow") is None:
                pre.update(checkable=False, condition="evidence_missing")
                issue("missing_metric", "Same-period profit/cashflow input is missing", hypothesis=hid,
                      category=ISSUE_CATEGORIES[2])
        elif hid in {"market_direction", "mechanical_adjustment"}:
            invalid_close_datasets = [name for name in ("market_daily", "index_daily" if hid == "market_direction" else "market_daily")
                                      if any(_number(r, "close") is None or _number(r, "close") <= 0 for r in selected[name])]
            if invalid_close_datasets:
                pre.update(checkable=False, condition="evidence_missing")
                for name in sorted(set(invalid_close_datasets)):
                    issue("missing_metric", "Original full-series rule cannot ignore missing/nonpositive closing prices",
                          dataset=name, hypothesis=hid, category=ISSUE_CATEGORIES[2])
                continue
            prices = _closes(selected["market_daily"])
            if len(prices) < 2:
                pre.update(checkable=False, condition="evidence_missing")
                issue("no_valid_market_window", "Fewer than two visible positive closing prices",
                      dataset="market_daily", hypothesis=hid, category=ISSUE_CATEGORIES[2])
            elif hid == "market_direction":
                benchmark = _closes(selected["index_daily"])
                if len(benchmark) < 2:
                    pre.update(checkable=False, condition="evidence_missing")
                    issue("no_valid_market_window", "Fewer than two visible positive index closing prices",
                          dataset="index_daily", hypothesis=hid, category=ISSUE_CATEGORIES[2])
                elif [r["period"] for r in prices] != [r["period"] for r in benchmark]:
                    pre["condition"] = "exact_date_alignment_failed"
                    issue("exact_date_alignment_failed", "Visible stock and index trading dates do not align under the original exact-date rule",
                          hypothesis=hid, category=ISSUE_CATEGORIES[3])
            else:
                factors = {r["period"]: _number(r, "factor") for r in selected["adjustment_factor"]}
                if any(factors.get(r["period"]) is None or factors[r["period"]] <= 0 for r in prices):
                    pre.update(checkable=False, condition="evidence_missing")
                    issue("missing_metric", "Positive adjustment factors are absent on observed price dates",
                          dataset="adjustment_factor", hypothesis=hid, category=ISSUE_CATEGORIES[2])

    if "event_chronology" in request.hypotheses:
        event_check = result["event_completeness"]
        event_check.update(required=True, record_id=request.event_record_id, valid=False)
        temporal = result["temporal_feasibility"]
        temporal.update(required=True, possible_under_request=None, observed_before=[], observed_after=[])
        if request.event_record_id is None:
            issue("missing_event", "event_chronology requires a specific target-security event_record_id",
                  hypothesis="event_chronology", blocks=True)
        else:
            events = [(name, r) for name, rows in selected.items() for r in rows
                      if _record_id(r) == request.event_record_id]
            if len(events) != 1:
                issue("event_binding_not_assessable" if unknown else "invalid_event_binding",
                      "Requested event cannot be uniquely verified in authorized bound sources" if unknown else
                      "Requested event is absent, superseded or not uniquely visible in authorized bound sources",
                      hypothesis="event_chronology", blocks=not unknown, unassessable=unknown)
            else:
                name, row = events[0]
                basis = row.get("availability_basis")
                try:
                    if name not in {"financial_income", "announcement", "news_recent"}:
                        raise ValueError()
                    if basis == "verified_release_date":
                        release = date.fromisoformat(row["release_date"])
                        if not _HEX.fullmatch(row.get("release_evidence_artifact_id", "")) or row.get("published_at") is not None:
                            raise ValueError()
                        boundary = datetime.combine(release + timedelta(days=1), time(), CN)
                        if _moment(row["available_at"]) < boundary:
                            raise ValueError()
                        before_last, after_first = release - timedelta(days=1), release + timedelta(days=1)
                        event_check.update(precision="date_conservative_next_day", release_date=release.isoformat())
                        before_rule = lambda r: date.fromisoformat(r["period"]) < release
                        after_rule = lambda r: date.fromisoformat(r["period"]) >= after_first
                    elif basis == "verified_release":
                        moment = _moment(row["published_at"])
                        if _moment(row["available_at"]) < moment:
                            raise ValueError()
                        day = moment.astimezone(CN).date()
                        close = datetime.combine(day, time(15), CN)
                        before_last = day if close < moment else day - timedelta(days=1)
                        after_first = day if close >= moment else day + timedelta(days=1)
                        event_check.update(precision="timestamp", disclosed_at=moment.isoformat())
                        before_rule = lambda r: datetime.combine(date.fromisoformat(r["period"]), time(15), CN) < moment
                        after_rule = lambda r: datetime.combine(date.fromisoformat(r["period"]), time(15), CN) >= moment
                    else:
                        raise ValueError()
                    event_check.update(valid=True, dataset=name, revision_id=row["revision_id"],
                                       provider_version=row["provider_version"], available_at=row["available_at"])
                    market_binding = bindings.get("market_daily")
                    first_after = max(market_binding.start, after_first)
                    possible = (market_binding.start <= min(market_binding.end, before_last)
                                and first_after <= market_binding.end
                                and datetime.combine(first_after, time(15), CN) <= cutoff)
                    temporal.update(possible_under_request=possible,
                                    earliest_allowed_after_close=datetime.combine(first_after, time(15), CN).isoformat())
                    if not possible:
                        issue("temporal_condition_impossible", "Original window/cutoff cannot contain both legal pre-event and post-event closes",
                              hypothesis="event_chronology", category=ISSUE_CATEGORIES[3], blocks=True)
                    prices = _closes(selected.get("market_daily", []))
                    before, after = [r for r in prices if before_rule(r)], [r for r in prices if after_rule(r)]
                    temporal.update(observed_before=[r["period"] for r in before],
                                    observed_after=[r["period"] for r in after])
                    if possible and (not before or not after):
                        issue("no_valid_market_window", "Compatible authorized inputs contain no positive visible closes on both legal event sides",
                              dataset="market_daily", hypothesis="event_chronology", category=ISSUE_CATEGORIES[2])
                    result["hypothesis_preconditions"]["event_chronology"].update(
                        checkable=bool(before and after), condition="checkable" if before and after else "evidence_missing")
                except (KeyError, TypeError, ValueError):
                    issue("invalid_event_binding", "Event release/version/time precision lacks a qualified source anchor",
                          hypothesis="event_chronology", blocks=True)
    return finish()


def validate_service_contract(request, access, service, metadata_reader):
    """Read each binding through its normal authorized service, then audit it.

    ``metadata_reader(request, binding, access)`` is supplied by the trusted
    application and resolves current source grants, immutable snapshot members,
    provider capability and archived source verification. It is mandatory for
    composed readers, and must never trust request/Agent-provided metadata.
    Authorization exceptions propagate; there is no unauthorized fallback.
    """
    request = request if isinstance(request, StudyRequest) else StudyRequest.from_dict(request)
    datasets, metadata = {}, {}
    for binding in request.bindings:
        if binding.provider not in access.allowed_providers:
            raise PermissionDenied("benchmark binding provider is not authorized")
        narrowed = AccessContext(access.scope, frozenset({binding.provider}))
        context = QueryContext(narrowed, binding.snapshot, request.as_of, request.mode)
        result = service.query(request.data_request(binding), context)
        if result.snapshot_id != binding.snapshot or result.as_of_date != context.as_of_date:
            raise ValidationError("benchmark query returned a different snapshot or cutoff")
        datasets[binding.dataset] = [r.to_dict() for r in result.records]
        metadata[binding.dataset] = metadata_reader(request, binding, narrowed)
    return validate_contract(request, access.scope, datasets, metadata)


def require_freezable(validations):
    """Fail closed before a new capability benchmark is frozen.

    Callers may persist the independent precheck report before this assertion.
    It does not write files and cannot silently remove an invalid/unknown case.
    Correct data-insufficient or intrinsic-precondition diagnostics attached to
    an otherwise valid request do not remove that case from capability metrics.
    """
    validations = tuple(validations)
    if not validations or any(v.get("schema") != VERSION or v.get("valid") is not True for v in validations):
        raise ValidationError("benchmark freeze blocked: every case requires a known valid input contract")
    return validations
