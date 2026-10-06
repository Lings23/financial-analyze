"""Synthetic contract fixtures; these are not provider or financial validation."""
import unittest
import subprocess
from datetime import date, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stock_research.errors import (PermissionDenied, ProviderSchemaError,
                                   TransientProviderError, ValidationError)
from stock_research.models import AccessContext, PITMode
from stock_research.providers.akshare import AkShareCaptureProvider, AkShareSubprocessTransport, SOURCES
from stock_research.storage.artifacts import ArtifactStore
from helpers import ts


CAPTURED = ts("2026-09-28T08:00:00")


def response(endpoint):
    if endpoint == "stock_sse_summary":
        return {"version": "1.18.97", "columns": ["项目", "股票", "主板", "科创板"],
                "rows": [["报告时间", "20260925", "20260925", "20260925"],
                         ["上市股票", 2000, 1500, 500]]}
    if endpoint == "stock_szse_summary":
        return {"version": "1.18.97",
                "columns": ["证券类别", "数量", "成交金额", "总市值", "流通市值"],
                "rows": [["股票", 2000, 123.0, 1000.0, 900.0]]}
    if "spot" in endpoint:
        return {"version": "1.18.97", "columns": ["代码", "名称", "最新价", "成交量", "成交额"],
                "rows": [["600000", "样本", 10.0, 100.0, 1000.0]]}
    metric = "机构参与度" if "jgcyd" in endpoint else "用户关注指数"
    return {"version": "1.18.97", "columns": ["交易日", metric],
            "rows": [["2026-09-25", 20.0]]}


class AkShareTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.artifacts = ArtifactStore(temp.name)
        self.access = AccessContext("tenant-a", frozenset({"akshare"}))
        self.calls = []

        def fake(endpoint, params, timeout):
            self.calls.append((endpoint, params, timeout))
            return response(endpoint)

        self.provider = AkShareCaptureProvider(self.artifacts, fake, lambda: CAPTURED)

    def capture(self, endpoint):
        kwargs = ({"symbol": "600000"} if "comment" in endpoint else
                  {"trade_date": date(2026, 9, 25)} if endpoint == "stock_szse_summary" else {})
        return self.provider.capture(endpoint, self.access, **kwargs)

    def test_all_seven_contracts_and_immutable_snapshots(self):
        for endpoint in SOURCES:
            with self.subTest(endpoint=endpoint):
                capture = self.capture(endpoint)
                self.assertGreater(capture.row_count, 0)
                self.assertEqual(capture.endpoint, endpoint)
                self.assertEqual(capture.captured_at, CAPTURED)
                self.assertEqual(self.provider.read(capture.snapshot_id, self.access,
                                                   CAPTURED, PITMode.PUBLIC).rows, capture.rows)
                self.assertIn("historical_release_not_verified", capture.quality_flags)
                self.assertEqual(self.calls[-1][0], endpoint)
        self.assertEqual(self.calls[1][1], {"date": "20260925"})
        self.assertEqual(self.calls[-1][1], {"symbol": "600000"})

    def test_authorization_and_cutoff_rechecked_on_read(self):
        capture = self.capture("stock_zh_a_spot_em")
        earlier = CAPTURED - timedelta(microseconds=1)
        with self.assertRaises(PermissionDenied):
            self.provider.read(capture.snapshot_id, self.access, earlier)
        with self.assertRaises(PermissionDenied):
            self.provider.read(capture.snapshot_id,
                               AccessContext("tenant-a", frozenset({"tushare"})), CAPTURED)
        with self.assertRaises(FileNotFoundError):
            self.provider.read(capture.snapshot_id,
                               AccessContext("tenant-b", frozenset({"akshare"})), CAPTURED)
        self.assertEqual(self.provider.read(capture.snapshot_id, self.access,
                                            CAPTURED, PITMode.SYSTEM).snapshot_id,
                         capture.snapshot_id)

    def test_bad_parameter_and_schema_fail_before_archiving(self):
        with self.assertRaises(ValidationError):
            self.provider.capture("stock_szse_summary", self.access)
        with self.assertRaises(ValidationError):
            self.provider.capture("stock_comment_detail_scrd_focus_em", self.access,
                                  symbol='600000" or 1=1')
        with self.assertRaises(ValidationError):
            self.provider.capture("stock_zh_a_spot_em", self.access, symbol="600000")
        self.assertFalse(self.calls)
        invalid = response("stock_zh_a_spot_em")
        invalid["columns"].remove("代码")
        invalid["rows"][0].pop(0)
        provider = AkShareCaptureProvider(self.artifacts, lambda *_: invalid,
                                          lambda: CAPTURED)
        with self.assertRaises(ProviderSchemaError):
            provider.capture("stock_zh_a_spot_em", self.access)

    def test_future_dated_source_row_rejected(self):
        invalid = response("stock_comment_detail_scrd_focus_em")
        invalid["rows"][0][0] = "2026-09-29"
        provider = AkShareCaptureProvider(self.artifacts, lambda *_: invalid,
                                          lambda: CAPTURED)
        with self.assertRaises(ProviderSchemaError):
            provider.capture("stock_comment_detail_scrd_focus_em", self.access,
                             symbol="600000")

    def test_unbounded_upstream_call_is_terminated_by_worker_deadline(self):
        with patch("stock_research.providers.akshare.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("akshare", 2)):
            with self.assertRaises(TransientProviderError):
                AkShareSubprocessTransport()("stock_sse_summary", {}, 2)


if __name__ == "__main__":
    unittest.main()
