import json
import unittest
from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory

from stock_research.errors import ProviderAuthError, ProviderError, ProviderSchemaError
from stock_research.models import DataRequest, Dataset
from stock_research.providers.tushare import TushareProvider
from stock_research.storage.artifacts import ArtifactStore
from helpers import SECURITY, ts


class TushareTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = ArtifactStore(self.temp.name)
        self.capture = ts("2025-05-01T10:00:00")
        self.daily = DataRequest(SECURITY, Dataset.MARKET_DAILY, date(2025, 3, 20), date(2025, 3, 20))
        self.income = DataRequest(SECURITY, Dataset.FINANCIAL_INCOME, date(2024, 12, 31), date(2024, 12, 31))
        self.response = {"code": 0, "data": {"fields": list(TushareProvider.DAILY_FIELDS),
                         "items": [["600000.SH", "20250320", "10.01", "11", "9", "10.02", "12.5", "23.4"]]}}
        self.seen_payloads = []

    def fetch(self, request=None):
        def transport(payload, timeout):
            self.seen_payloads.append(payload)
            self.assertGreater(timeout, 0)
            return self.response
        provider = TushareProvider("SECRET-DO-NOT-STORE", self.artifacts, transport, lambda: self.capture)
        return provider.fetch(request or self.daily, "tenant-a", 1)

    def test_decimal_and_unit_normalization(self):
        record = self.fetch()[0]
        metrics = {m.name: m for m in record.metrics}
        self.assertEqual(metrics["close"].value, Decimal("10.02"))
        self.assertEqual(metrics["volume"].value, Decimal("1250"))
        self.assertEqual(metrics["amount"].value, Decimal("23400"))
        self.assertEqual(metrics["volume"].raw_unit, "lot_100_shares")
        self.assertEqual(record.available_at, self.capture)
        self.assertEqual(record.availability_basis, "observed_at")

    def test_income_does_not_filter_by_report_period_as_announcement(self):
        self.response = {"code": 0, "data": {"fields": list(TushareProvider.INCOME_FIELDS),
                         "items": [["600000.SH", "20250320", "20250420", "20241231", "1", 100, 120, None],
                                   ["600000.SH", "20240420", None, "20231231", "1", 90, 110, 8]]}}
        records = self.fetch(self.income)
        self.assertEqual(len(records), 1)
        self.assertNotIn("start_date", self.seen_payloads[0]["params"])
        self.assertEqual(records[0].available_at, self.capture)
        self.assertEqual(records[0].revision_order, 20250420)
        self.assertIsNone(next(m.value for m in records[0].metrics if m.name == "net_income_parent"))

    def test_archive_never_contains_request_token_or_unknown_response_fields(self):
        self.response["msg"] = "SECRET-DO-NOT-STORE"
        self.response["data"]["fields"].append("untrusted_extra")
        self.response["data"]["items"][0].append("SECRET-DO-NOT-STORE")
        record = self.fetch()[0]
        artifact = self.artifacts.get("tenant-a", record.artifact_id).decode()
        self.assertNotIn("SECRET-DO-NOT-STORE", artifact)
        self.assertNotIn("untrusted_extra", artifact)
        self.assertEqual(json.loads(artifact)["api_name"], "daily")

    def test_empty_is_valid_but_not_invented_data(self):
        self.response["data"]["items"] = []
        self.assertEqual(self.fetch(), ())

    def test_requested_response_archives_out_of_window_rows_and_capture_metadata(self):
        self.response = {"code": 0, "data": {"fields": list(TushareProvider.INCOME_FIELDS),
                         "items": [["600000.SH", "20250320", None, "20241231", "1", 100, 120, 10],
                                   ["600000.SH", "20240420", None, "20231231", "1", 90, 110, 8]]}}
        record = self.fetch(self.income)[0]
        archive = json.loads(self.artifacts.get("tenant-a", record.artifact_id))
        self.assertEqual(archive["response_row_count"], 2)
        self.assertEqual(archive["selected_row_count"], 1)
        self.assertEqual(len(archive["items"]), 2)
        self.assertEqual(archive["items"][1][3], "20231231")
        self.assertEqual(archive["archive_schema"], "tushare_requested_response_v2")
        self.assertEqual(archive["finished_at"], self.capture.isoformat())
        self.assertEqual(record.provider_version, "2")

    def test_out_of_window_requested_field_cannot_archive_reflected_credential(self):
        self.response = {"code": 0, "data": {"fields": list(TushareProvider.INCOME_FIELDS),
                         "items": [["600000.SH", "20240420", None, "20231231", "1", "SECRET-DO-NOT-STORE", 110, 8]]}}
        with self.assertRaises(ProviderSchemaError):
            self.fetch(self.income)
        self.assertFalse(any(p.is_file() for p in self.artifacts.root.rglob('*')))

    def test_missing_field_is_schema_failure(self):
        self.response["data"]["fields"].pop()
        self.response["data"]["items"][0].pop()
        with self.assertRaises(ProviderSchemaError):
            self.fetch()

    def test_duplicate_field_is_schema_failure(self):
        self.response["data"]["fields"][0] = "trade_date"
        with self.assertRaises(ProviderSchemaError):
            self.fetch()

    def test_bad_row_length_is_schema_failure(self):
        self.response["data"]["items"][0].pop()
        with self.assertRaises(ProviderSchemaError):
            self.fetch()

    def test_non_finite_and_non_numeric_rejected(self):
        for invalid in ("NaN", "Infinity", "oops", True):
            with self.subTest(value=invalid):
                self.response["data"]["items"][0][2] = invalid
                with self.assertRaises(ProviderSchemaError):
                    self.fetch()

    def test_wrong_security_or_outside_date_rejected(self):
        self.response["data"]["items"][0][0] = "000001.SZ"
        with self.assertRaises(ProviderSchemaError):
            self.fetch()
        self.response["data"]["items"][0][0] = "600000.SH"
        self.response["data"]["items"][0][1] = "20250321"
        with self.assertRaises(ProviderSchemaError):
            self.fetch()

    def test_invalid_ohlc_rejected(self):
        self.response["data"]["items"][0][3] = "8"
        with self.assertRaises(ProviderSchemaError):
            self.fetch()

    def test_auth_and_unknown_errors_do_not_leak_messages(self):
        for code, error in ((2002, ProviderAuthError), (40203, ProviderAuthError), (5000, ProviderError)):
            self.response = {"code": code, "msg": "SECRET-DO-NOT-STORE"}
            with self.assertRaises(error) as caught:
                self.fetch()
            self.assertNotIn("SECRET", str(caught.exception))

    def test_possible_truncation_rejected(self):
        self.response["data"]["items"] *= 6000
        with self.assertRaises(ProviderSchemaError):
            self.fetch()
