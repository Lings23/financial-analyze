"""Bounded real-source P1.7 pilot. Never emits or archives provider credentials."""

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from stock_research.__main__ import _project_tushare_token
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare import TushareHTTPTransport, TushareProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


PLAN_SHA256 = "8adbc927102e6e82a5ef9c5736b92bc3757504475d3a1d5ff110f33daa268636"


def json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    pending.replace(path)


class AuditedTransport:
    """Archive only the response table and request metadata, never token or msg."""

    def __init__(self, artifacts, scope):
        self.inner = TushareHTTPTransport()
        self.artifacts = artifacts
        self.scope = scope
        self.calls = []

    def __call__(self, payload, timeout):
        started = datetime.now(timezone.utc)
        response = self.inner(payload, timeout)
        finished = datetime.now(timezone.utc)
        data = response.get("data") if isinstance(response, dict) else None
        sanitized = {
            "api_name": payload["api_name"],
            "params": payload["params"],
            "requested_fields": payload["fields"].split(","),
            "business_code": response.get("code") if isinstance(response, dict) else None,
            "response_fields": data.get("fields") if isinstance(data, dict) else None,
            "response_items": json_safe(data.get("items")) if isinstance(data, dict) else None,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        }
        artifact_id = self.artifacts.put(self.scope, sanitized)
        self.calls.append({
            "api_name": payload["api_name"],
            "params": payload["params"],
            "business_code": sanitized["business_code"],
            "raw_response_artifact_id": artifact_id,
            "response_row_count": len(data.get("items", [])) if isinstance(data, dict) and isinstance(data.get("items"), list) else None,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        })
        return response


def requests_from_plan(plan):
    for security_row in plan["securities"]:
        security = Security(security_row["symbol"], security_row["exchange"])
        for window in plan["daily_windows"]:
            yield DataRequest(security, Dataset.MARKET_DAILY,
                              date.fromisoformat(window["start"]), date.fromisoformat(window["end"]))
        periods = [date.fromisoformat(x) for x in plan["financial_periods"]]
        yield DataRequest(security, Dataset.FINANCIAL_INCOME, min(periods), max(periods))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=Path("evaluation/p17_20260930_sample_plan.json"))
    parser.add_argument("--dsn-file", type=Path, default=Path(".runtime/p17-dsn.txt"))
    parser.add_argument("--root", type=Path, default=Path(".artifacts/p17_20260930"))
    parser.add_argument("--replay-only", action="store_true")
    args = parser.parse_args()

    plan_bytes = args.plan.read_bytes()
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    if plan_sha != PLAN_SHA256:
        raise ValueError("pre-registered P1.7 sample plan hash changed")
    plan = json.loads(plan_bytes)
    scope = plan["scope"]
    artifacts = ArtifactStore(args.root / "artifacts")
    dsn = args.dsn_file.read_text(encoding="utf-8").strip()
    repository = PostgresRepository(dsn)
    repository.migrate()
    access = AccessContext(scope, frozenset({"tushare"}))
    registry = ProviderRegistry()
    output_path = args.root / "run.json"

    if args.replay_only:
        run = json.loads(output_path.read_text(encoding="utf-8"))
        first = next((entry for entry in run["results"] if entry["status"] == "ingested" and entry["record_count"]), None)
        last = next((entry for entry in reversed(run["results"]) if entry["status"] == "ingested" and entry["record_count"]), None)
        if first is None or last is None:
            raise ValueError("no nonempty real snapshot for replay")
        first_records = repository.read(scope, first["snapshot_id"])
        last_records = repository.read(scope, last["snapshot_id"])
        if tuple(r.record_id for r in first_records) != tuple(first["snapshot_record_ids"]):
            raise AssertionError("frozen first snapshot changed")
        if tuple(r.record_id for r in last_records) != tuple(last["snapshot_record_ids"]):
            raise AssertionError("last snapshot changed")
        first_request = DataRequest(Security(first["symbol"], first["exchange"]),
                                    Dataset(first["dataset"]), date.fromisoformat(first["start"]),
                                    date.fromisoformat(first["end"]))
        # Service.query verifies Artifact integrity in addition to repository hashes.
        with ProviderExecutor(ExecutionPolicy(max_attempts=1)) as executor:
            service = DataService(registry, executor, repository, artifacts)
            relevant = [r for r in first_records if r.security_id == first_request.security.security_id
                        and r.dataset == first_request.dataset and first_request.start <= r.period <= first_request.end]
            earliest = min(r.available_at for r in relevant)
            latest_ingested = max(r.ingested_at for r in relevant)
            before = service.query(first_request, QueryContext(access, first["snapshot_id"],
                                                               earliest - timedelta(microseconds=1), PITMode.PUBLIC))
            after = service.query(first_request, QueryContext(access, first["snapshot_id"],
                                                              latest_ingested + timedelta(microseconds=1), PITMode.SYSTEM))
            denied = service.query(first_request, QueryContext(
                AccessContext(scope, frozenset({"akshare"})), first["snapshot_id"],
                latest_ingested + timedelta(microseconds=1), PITMode.SYSTEM))
            try:
                repository.read(scope + "-other", first["snapshot_id"])
                wrong_scope_denied = False
            except PermissionDenied:
                wrong_scope_denied = True
        replay = {
            "replayed_at": datetime.now(timezone.utc).isoformat(),
            "first_snapshot_id": first["snapshot_id"],
            "last_snapshot_id": last["snapshot_id"],
            "first_snapshot_record_count": len(first_records),
            "last_snapshot_record_count": len(last_records),
            "before_capture_visible_count": len(before.records),
            "after_ingestion_visible_count": len(after.records),
            "unauthorized_provider_visible_count": len(denied.records),
            "wrong_scope_denied": wrong_scope_denied,
            "all_observed_at": all(r.availability_basis == "observed_at" for r in last_records),
            "frozen_snapshot_hashes_match": True,
        }
        write_json(args.root / "replay.json", replay)
        print(json.dumps(replay, ensure_ascii=False))
        return 0 if (not before.records and after.records and not denied.records
                     and wrong_scope_denied and replay["all_observed_at"]) else 2

    if output_path.exists():
        raise ValueError("run evidence already exists; refusing to overwrite a real collection")
    token = _project_tushare_token()
    if not token:
        raise ValueError("project Tushare token is missing")
    transport = AuditedTransport(artifacts, scope)
    registry.register(TushareProvider(token, artifacts, transport=transport))
    run = {"plan_sha256": plan_sha, "scope": scope,
           "started_at": datetime.now(timezone.utc).isoformat(), "results": []}
    policy = ExecutionPolicy(total_timeout=45, attempt_timeout=15, max_attempts=2,
                             min_interval=1.5, provider_concurrency=1, cache_ttl=0)
    with ProviderExecutor(policy) as executor:
        service = DataService(registry, executor, repository, artifacts)
        parent = None
        for request in requests_from_plan(plan):
            entry = {"symbol": request.security.symbol, "exchange": request.security.exchange,
                     "dataset": request.dataset.value, "start": request.start.isoformat(),
                     "end": request.end.isoformat(), "audit_call_start_index": len(transport.calls)}
            try:
                result = service.refresh(request, access, parent_snapshot_id=parent, use_cache=False)
                parent = result.snapshot.snapshot_id
                records = repository.read(scope, parent)
                entry.update(status="ingested", snapshot_id=parent, record_count=result.record_count,
                             snapshot_record_ids=[r.record_id for r in records],
                             warnings=result.warnings)
            except Exception as exc:
                entry.update(status="failed", error_type=type(exc).__name__)
            entry["audit_call_end_index"] = len(transport.calls)
            run["results"].append(entry)
            run["calls"] = transport.calls
            run["provider_stats"] = executor.stats
            write_json(output_path, run)
    run["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output_path, run)
    counts = {"requests": len(run["results"]),
              "ingested": sum(x["status"] == "ingested" for x in run["results"]),
              "failed": sum(x["status"] == "failed" for x in run["results"]),
              "records_in_last_snapshot": len(repository.read(scope, parent)) if parent else 0,
              "provider_stats": run["provider_stats"]}
    print(json.dumps(counts, ensure_ascii=False))
    return 0 if not counts["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
