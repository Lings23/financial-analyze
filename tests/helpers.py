from datetime import date, datetime, timezone
from decimal import Decimal

from stock_research.models import DataRecord, Dataset, Metric, Security, digest

SECURITY = Security("600000", "SSE")


def ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def financial_record(artifacts, scope="tenant-a", available="2025-03-20T10:00:00",
                     retrieved="2025-04-01T10:00:00", revenue="100", provider="fixture"):
    payload = {"synthetic": True, "revenue": revenue, "available": available}
    artifact_id = artifacts.put(scope, payload)
    release, capture = ts(available), ts(retrieved)
    return DataRecord(
        SECURITY.security_id, SECURITY.canonical_symbol, Dataset.FINANCIAL_INCOME,
        date(2024, 12, 31), "consolidated_cumulative_cny",
        (Metric("revenue", Decimal(revenue), "CNY", revenue, "CNY"),
         Metric("total_revenue", Decimal(revenue), "CNY", revenue, "CNY"),
         Metric("net_income_parent", Decimal("10"), "CNY", "10", "CNY")),
        provider, "1", "https://example.invalid/synthetic", "synthetic:20241231",
        digest(payload), release, capture, capture, "verified_release", artifact_id,
        "synthetic-call", published_at=release, announcement_date=release.date(),
        quality_flags=("synthetic_fixture",))
