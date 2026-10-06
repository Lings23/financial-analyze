"""Offline synthetic data demo. It never contacts a financial provider."""
from datetime import date, datetime, timezone
from tempfile import TemporaryDirectory

from .models import AccessContext, DataRequest, Dataset, QueryContext, Security
from .providers.base import ProviderRegistry
from .providers.executor import ExecutionPolicy, ProviderExecutor
from .providers.tushare import TushareProvider
from .service import DataService
from .storage.artifacts import ArtifactStore
from .storage.memory import MemoryRepository


def main():
    captured = datetime(2025, 3, 20, 10, tzinfo=timezone.utc)
    response = {"code": 0, "data": {"fields": list(TushareProvider.INCOME_FIELDS),
                "items": [["600000.SH", "20250320", "20250320", "20241231", "1", 100, 120, 10]]}}
    access = AccessContext("offline-demo", frozenset({"tushare"}))
    request = DataRequest(Security("600000", "SSE"), Dataset.FINANCIAL_INCOME,
                          date(2024, 12, 31), date(2024, 12, 31))
    with TemporaryDirectory() as directory, ProviderExecutor(ExecutionPolicy(min_interval=0)) as executor:
        artifacts = ArtifactStore(directory)
        registry = ProviderRegistry()
        registry.register(TushareProvider("synthetic-token", artifacts, lambda *_: response, lambda: captured))
        service = DataService(registry, executor, MemoryRepository(), artifacts)
        ingestion = service.refresh(request, access)
        before = service.query(request, QueryContext(access, ingestion.snapshot.snapshot_id,
                               datetime(2025, 2, 1, tzinfo=timezone.utc)))
        after = service.query(request, QueryContext(access, ingestion.snapshot.snapshot_id, captured))
        print("SYNTHETIC ONLY - not real financial data")
        print(f"Before disclosure/capture: {before.status}; records={len(before.records)}")
        print(f"At capture: {after.status}; records={len(after.records)}")
        print(f"Provider stats: {executor.stats}")


if __name__ == "__main__":
    main()
