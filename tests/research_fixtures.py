"""Synthetic mechanism fixtures. Never financial ground truth or provider validation."""
from dataclasses import replace
import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from helpers import SECURITY, financial_record, ts
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import AccessContext, DataRecord, Dataset, Metric, PITMode, digest
from stock_research.providers.base import ProviderRegistry
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import Binding, ResearchRequest
from stock_research.research.runtime import ResearchRuntime
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository


class FixtureModel:
    config = SimpleNamespace(model="deepseek-v4-flash-0731")

    def __init__(self, content='{"highlights":["F1"],"assessment":"descriptive_only"}',
                 returned_model="deepseek-v4-flash-0731", finish="stop", crash=None):
        self.content, self.returned_model, self.finish = content, returned_model, finish
        self.crash, self.calls, self.messages = crash, 0, None

    def complete(self, messages, **kwargs):
        self.calls += 1
        self.messages = messages
        if self.crash:
            raise self.crash
        return ChatResult(self.config.model, self.returned_model, self.content, self.finish,
                          "synthetic-model-call", 100, 20, 120, 1)


class BundleFixtureModel(FixtureModel):
    """Synthetic v3 protocol stub, never counted as live model quality."""
    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]['content'])
        self.content = json.dumps(payload['selection_options'][0])
        return super().complete(messages, **kwargs)


def fixture(root, prices=("100", "120", "90"), *, scope="synthetic-phase2", repo=None):
    artifacts = ArtifactStore(root / "artifacts")
    repository = repo or MemoryRepository()
    records = []
    captured = ts("2025-04-15T10:00:00")
    for i, price in enumerate(prices):
        day = date(2025, 4, 1) + timedelta(days=i)
        payload = {"synthetic": True, "day": str(day), "close": price}
        aid = artifacts.put(scope, payload)
        metrics = tuple(Metric(name, None if price is None and name == "close" else
                               Decimal(price or "100") if name in {"open", "high", "low", "close"} else Decimal("1000"),
                               "CNY/share" if name in {"open", "high", "low", "close"} else "share" if name == "volume" else "CNY",
                               price, "synthetic") for name in ("open", "high", "low", "close", "volume", "amount"))
        records.append(DataRecord(SECURITY.security_id, SECURITY.canonical_symbol, Dataset.MARKET_DAILY,
                                  day, "unadjusted_daily", metrics, "fixture", "1", "https://example.invalid/synthetic",
                                  str(day), digest(payload), captured, captured, captured, "observed_at", aid,
                                  "synthetic-market-call", quality_flags=("synthetic_fixture",)))
    current = financial_record(artifacts, scope, revenue="100")
    old = replace(financial_record(artifacts, scope, revenue="80"), period=date(2023, 12, 31))
    snapshot = repository.commit(scope, (*records, current, old))
    request = ResearchRequest(SECURITY, ts("2025-04-16T00:00:00"), PITMode.SYSTEM,
                              (Binding("market_daily", snapshot.snapshot_id, "fixture", date(2025, 4, 1), date(2025, 4, 14)),
                               Binding("financial_income", snapshot.snapshot_id, "fixture", date(2023, 12, 31), date(2024, 12, 31))))
    service = DataService(ProviderRegistry(), None, repository, artifacts)
    store = CheckpointStore(root / "runs")
    return SimpleNamespace(service=service, request=request, access=AccessContext(scope, frozenset({"fixture"})),
                           store=store, records=records, financial=current, repo=repository,
                           runtime=ResearchRuntime(service, store), artifacts=artifacts)
