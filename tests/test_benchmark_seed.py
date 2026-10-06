import json
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext
from stock_research.storage.artifacts import ArtifactStore
from stock_research.temporal import select_records
from helpers import SECURITY, financial_record


class BenchmarkSeedTests(unittest.TestCase):
    def test_frozen_synthetic_pit_cases(self):
        fixture = Path(__file__).resolve().parents[1] / "evaluation" / "pit_seed.json"
        dataset = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertTrue(dataset["synthetic_only"])
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            records = (financial_record(store), financial_record(store, available="2025-04-20T10:00:00",
                       retrieved="2025-04-21T10:00:00", revenue="90"))
            request = DataRequest(SECURITY, Dataset.FINANCIAL_INCOME, date(2024, 12, 31), date(2024, 12, 31))
            access = AccessContext("tenant-a", frozenset(dataset["allowed_sources"]))
            for case in dataset["cases"]:
                with self.subTest(case_id=case["case_id"]):
                    context = QueryContext(access, "synthetic-pit-v1", datetime.fromisoformat(case["as_of_date"]), PITMode(case["mode"]))
                    result = select_records(records, request, context)
                    observed = next((str(m.value) for r in result.records for m in r.metrics if m.name == "revenue"), None)
                    self.assertEqual(observed, case["expected_revenue"])
