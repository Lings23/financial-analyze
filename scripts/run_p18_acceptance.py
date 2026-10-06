"""Pre-registered real P1.8 collection and permission/PIT/persistence replay."""
import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from stock_research.__main__ import _project_tushare_token
from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, PITMode, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.documents import AkShareNewsProvider, CNInfoAnnouncementProvider
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare_domains import TushareDomainProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

PLAN = Path("evaluation/p18_20261001_sample_plan.json")
ROOT = Path(".artifacts/p18_20261001")


def request(item):
    return DomainRequest(Subject(item["kind"], item["code"], item.get("exchange", "")),
                         DomainDataset(item["dataset"]), date.fromisoformat(item["start"]),
                         date.fromisoformat(item["end"]), item.get("selector", ""))


def replay(run, db, artifacts):
    reports = []
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, db, artifacts)
        for item in run["results"]:
            if item["status"] != "ingested":
                continue
            req = request(item["request"])
            rows = db.read(run["scope"], item["snapshot_id"])
            matched = [r for r in rows if r.security_id == req.subject.security_id and r.dataset == req.dataset
                       and req.start <= r.period <= req.end and req.matches(r)]
            if not matched:
                raise AssertionError("mandatory domain snapshot is empty")
            before = min(r.available_at for r in matched)-timedelta(microseconds=1)
            after = max(r.ingested_at for r in matched)+timedelta(microseconds=1)
            access = AccessContext(run["scope"], frozenset({item["request"]["provider"]}))
            ctx = QueryContext(access, item["snapshot_id"], after, PITMode.SYSTEM)
            visible = service.query(req, ctx)
            pre = service.query(req, QueryContext(access, item["snapshot_id"], before))
            forbidden = AccessContext(run["scope"], frozenset({"tushare", "cninfo", "akshare"}-{item["request"]["provider"]}))
            denied = service.query(req, QueryContext(forbidden, item["snapshot_id"], after))
            scope_denied = False
            try:
                service.query(req, QueryContext(AccessContext("wrong-p18-scope", access.allowed_providers),
                                               item["snapshot_id"], after))
            except PermissionDenied:
                scope_denied = True
            hashes = sorted(r.record_id for r in rows)
            if (pre.records or denied.records or not scope_denied
                    or sorted(item["snapshot_record_ids"]) != hashes):
                raise AssertionError("P1.8 PIT, authorization or frozen snapshot failed")
            owners = {aid: r for r in visible.records for aid in r.artifact_ids}
            evidence_checks = len(owners)
            for aid, r in owners.items():
                content = service.evidence(req, ctx, r.record_id, aid)
                if hashlib.sha256(content).hexdigest() != aid:
                    raise AssertionError("source bytes changed")
            reports.append({"dataset": req.dataset.value, "subject": req.subject.security_id,
                            "visible_count": len(visible.records), "before_capture_count": len(pre.records),
                            "unauthorized_count": len(denied.records), "wrong_scope_denied": scope_denied,
                            "snapshot_unchanged": True, "evidence_checks": evidence_checks})
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "plan_sha256": run["plan_sha256"],
            "run_label": run["label"], "all_requests_ingested": all(r["status"] == "ingested" for r in run["results"]),
            "domains": reports}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="attempt1")
    parser.add_argument("--replay-only", action="store_true")
    args = parser.parse_args()
    if not args.label.isalnum():
        raise ValueError("alphanumeric evidence label required")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    ROOT.mkdir(parents=True, exist_ok=True)
    run_path = ROOT / f"{args.label}.json"
    db = PostgresRepository(Path(".runtime/p17-dsn.txt").read_text(encoding="utf-8").strip())
    artifacts = ArtifactStore(ROOT / "artifacts")
    if args.replay_only:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if run["plan_sha256"] != plan_sha:
            raise AssertionError("pre-registered plan changed")
        report = replay(run, db, artifacts)
        check_path = ROOT / f"{args.label}-replay.json"
        if check_path.exists():
            prior = json.loads(check_path.read_text(encoding="utf-8"))
            if {k: v for k, v in prior.items() if k != "checked_at"} != {k: v for k, v in report.items() if k != "checked_at"}:
                raise AssertionError("replay differs from frozen evidence")
        else:
            with check_path.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["all_requests_ingested"] else 2
    if run_path.exists():
        raise ValueError("run evidence exists; use another label or replay-only")
    # Archive plan before the first source request.
    plan_artifact = artifacts.put(plan["scope"], plan)
    db.migrate()
    previous = json.loads(Path(".artifacts/p17_20260930/run.json").read_text(encoding="utf-8"))
    legacy_ids = [previous["results"][i]["snapshot_id"] for i in (0, -1)]
    legacy_counts = [len(db.read(previous["scope"], sid)) for sid in legacy_ids]
    if legacy_counts != [9, 120]:
        raise AssertionError("legacy persistent snapshots changed")
    run = {"label": args.label, "scope": plan["scope"], "plan_sha256": plan_sha,
           "plan_artifact_id": plan_artifact, "legacy_snapshot_counts_after_v2_migration": legacy_counts,
           "started_at": datetime.now(timezone.utc).isoformat(), "results": []}
    registry = ProviderRegistry()
    registry.register(TushareDomainProvider(_project_tushare_token(), artifacts))
    registry.register(CNInfoAnnouncementProvider(artifacts))
    registry.register(AkShareNewsProvider(artifacts))
    policy = ExecutionPolicy(total_timeout=90, attempt_timeout=90, min_interval=1.5, max_attempts=1)
    parent = None
    with ProviderExecutor(policy) as executor:
        service = DataService(registry, executor, db, artifacts)
        for item in plan["requests"]:
            try:
                result = service.refresh(request(item), AccessContext(plan["scope"], frozenset({item["provider"]})),
                                         (item["provider"],), parent, use_cache=False)
                if result.record_count == 0:
                    raise AssertionError("mandatory request returned no records")
                parent = result.snapshot.snapshot_id
                rows = db.read(plan["scope"], parent)
                entry = {"request": item, "status": "ingested", "record_count": result.record_count,
                         "snapshot_id": parent, "snapshot_record_ids": [r.record_id for r in rows],
                         "warnings": result.warnings}
            except Exception as exc:
                # Safe category only; never emit DSN, token or upstream exception text.
                entry = {"request": item, "status": "failed", "error_type": type(exc).__name__}
            run["results"].append(entry)
            print(json.dumps({k: entry[k] for k in ("status", "record_count", "error_type") if k in entry}
                             | {"dataset": item["dataset"], "code": item["code"]}), flush=True)
        run["provider_stats"] = executor.stats
    run["finished_at"] = datetime.now(timezone.utc).isoformat()
    run["last_snapshot_id"] = parent
    with run_path.open("x", encoding="utf-8") as stream:
        json.dump(run, stream, ensure_ascii=False, indent=2)
    report = replay(run, db, artifacts)
    with (ROOT / f"{args.label}-replay.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"run_path": str(run_path), "all_requests_ingested": report["all_requests_ingested"],
                      "verified_requests": len(report["domains"]), "stats": run["provider_stats"]}))
    return 0 if report["all_requests_ingested"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
