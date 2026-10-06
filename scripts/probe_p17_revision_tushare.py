"""Exploratory current Tushare value for a documented 2024 restatement."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from run_p17_pilot import AuditedTransport
from stock_research.__main__ import _project_tushare_token
from stock_research.models import AccessContext, DataRequest, Dataset, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare import TushareProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    root = Path(".artifacts/p17_20260930/revision")
    output = root / "tushare_probe.json"
    if output.exists():
        raise ValueError("revision probe already exists; refusing overwrite")
    scope = "p17-revision-exploratory-20260930"
    artifacts = ArtifactStore(root / "artifacts")
    transport = AuditedTransport(artifacts, scope)
    provider = TushareProvider(_project_tushare_token(), artifacts, transport=transport)
    registry = ProviderRegistry()
    registry.register(provider)
    repo = PostgresRepository(Path(".runtime/p17-dsn.txt").read_text(encoding="utf-8").strip())
    request = DataRequest(Security("300122", "SZSE"), Dataset.FINANCIAL_INCOME,
                          date(2024, 12, 31), date(2024, 12, 31))
    access = AccessContext(scope, frozenset({"tushare"}))
    with ProviderExecutor(ExecutionPolicy(total_timeout=35, attempt_timeout=15,
                                           max_attempts=2, min_interval=1.5)) as executor:
        result = DataService(registry, executor, repo, artifacts).refresh(request, access,
                                                                           use_cache=False)
    records = repo.read(scope, result.snapshot.snapshot_id)
    evidence = {"captured_run_at": datetime.now(timezone.utc).isoformat(),
                "scope": scope, "snapshot_id": result.snapshot.snapshot_id,
                "raw_call": transport.calls[0], "record_count": len(records),
                "records": [{"period": r.period.isoformat(),
                             "announcement_date": r.announcement_date.isoformat() if r.announcement_date else None,
                             "available_at": r.available_at.isoformat(),
                             "availability_basis": r.availability_basis,
                             "record_id": r.record_id,
                             "metrics": {m.name: str(m.value) if m.value is not None else None
                                         for m in r.metrics}} for r in records]}
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"record_count": len(records), "records": evidence["records"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
