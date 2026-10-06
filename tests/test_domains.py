"""Synthetic fixtures verify P1.8 contracts/security; never financial ground truth."""
import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_research.domains import DomainDataset as D, DomainRecord, DomainRequest, Subject
from stock_research.errors import IntegrityError, PermissionDenied, ProviderSchemaError, ValidationError
from stock_research.models import AccessContext, DataRecord, PITMode, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.documents import AkShareNewsProvider, CNInfoAnnouncementProvider, document_url
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare_domains import SPECS, TushareDomainProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository


CAPTURED = datetime(2026, 9, 30, 2, tzinfo=timezone.utc)
EQUITY = Subject("equity", "600000", "SSE")
INDEX = Subject("index", "000300.SH")


def request(domain, selector=""):
    subject = Subject("exchange", "SSE") if domain == D.CALENDAR else INDEX if domain in {
        D.INDEX_DAILY, D.INDEX_WEIGHT} else EQUITY
    period = date(2024, 12, 31) if domain in {D.BALANCE, D.CASHFLOW} else date(2026, 9, 29)
    return DomainRequest(subject, domain, period, period, selector)


def synthetic_row(domain):
    row = {f: "1" for f in SPECS[domain][1]}
    row.update(ts_code="600000.SH", exchange="SSE", index_code="000300.SH", con_code="000001.SZ",
               trade_date="20260929", cal_date="20260929", pretrade_date="20260928", end_date="20241231",
               ann_date="20250331", f_ann_date="20250401", report_type="1", comp_type="2", end_type="4",
               update_flag="1", adj_factor="2.5", weight="5.2", open="10", high="12", low="8", close="11",
               vol="4", amount="50", total_assets="100", total_liab="70",
               total_hldr_eqy_inc_min_int="30", total_hldr_eqy_exc_min_int="25")
    if domain == D.INDEX_DAILY:
        row["ts_code"] = "000300.SH"
    return {f: row[f] for f in SPECS[domain][1]}


def response(domain, rows):
    fields = list(SPECS[domain][1])
    return {"code": 0, "data": {"fields": fields, "items": [[r[f] for f in fields] for r in rows]}}


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = ArtifactStore(self.temp.name)
        self.scope = "synthetic-domain-test"

    def fetch(self, domain, rows=None, req=None):
        payload = response(domain, rows if rows is not None else [synthetic_row(domain)])
        provider = TushareDomainProvider("SYNTHETIC-DO-NOT-ARCHIVE", self.artifacts,
                                         lambda *_: payload, lambda: CAPTURED)
        return provider.fetch(req or request(domain), self.scope, 5)

    def test_six_tushare_domain_contracts_roundtrip_without_token(self):
        for domain in SPECS:
            with self.subTest(domain=domain):
                record = self.fetch(domain)[0]
                self.assertEqual(DataRecord.from_dict(json.loads(json.dumps(record.to_dict()))), record)
                self.assertNotIn(b"SYNTHETIC-DO-NOT-ARCHIVE", self.artifacts.get(self.scope, record.artifact_id))

    def test_units_are_normalized_and_raw_values_preserved(self):
        values = {m.name: m for m in self.fetch(D.INDEX_DAILY)[0].metrics}
        self.assertEqual(str(values["volume"].value), "400")
        self.assertEqual(values["volume"].raw_value, "4")
        self.assertEqual(str(values["amount"].value), "50000")
        self.assertEqual(str(self.fetch(D.INDEX_WEIGHT)[0].metrics[0].value), "0.052")

    def test_financial_period_not_sent_as_announcement_window(self):
        seen = []
        def transport(payload, timeout):
            seen.append(payload["params"])
            return response(D.CASHFLOW, [synthetic_row(D.CASHFLOW)])
        provider = TushareDomainProvider("synthetic", self.artifacts, transport, lambda: CAPTURED)
        provider.fetch(request(D.CASHFLOW), self.scope, 5)
        self.assertEqual(seen, [{"ts_code": "600000.SH", "report_type": "1", "period": "20241231"}])

    def test_report_type_and_revision_are_preserved(self):
        record = self.fetch(D.BALANCE)[0]
        self.assertEqual(dict(record.attributes)["comp_type"], "2")
        self.assertEqual(record.revision_order, 20250401)
        row = synthetic_row(D.BALANCE)
        row["report_type"] = "6"
        with self.assertRaises(ProviderSchemaError):
            self.fetch(D.BALANCE, [row])

    def test_update_flag_only_duplicates_are_value_equivalent_but_values_cannot_conflict(self):
        row = synthetic_row(D.CASHFLOW)
        records = self.fetch(D.CASHFLOW, [row, {**row, "update_flag": "0"}])
        repo = MemoryRepository()
        snap = repo.commit(self.scope, records)
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, repo, self.artifacts)
            ctx = QueryContext(AccessContext(self.scope, frozenset({"tushare"})), snap.snapshot_id, CAPTURED)
            self.assertEqual(len(service.query(request(D.CASHFLOW), ctx).records), 1)
            changed = replace(records[0], metrics=tuple(replace(m, value=m.value+1)
                              if m.name == "operating_cashflow" else m for m in records[0].metrics))
            conflict = repo.commit(self.scope, (changed,), snap.snapshot_id)
            with self.assertRaises(IntegrityError):
                service.query(request(D.CASHFLOW), replace(ctx, snapshot_id=conflict.snapshot_id))

    def test_financial_missing_is_null_and_negative_cashflow_is_valid(self):
        row = synthetic_row(D.CASHFLOW)
        row.update(n_cashflow_inv_act="-50", n_cashflow_act=None)
        record = self.fetch(D.CASHFLOW, [row])[0]
        metrics = {m.name: m.value for m in record.metrics}
        self.assertIsNone(metrics["operating_cashflow"])
        self.assertEqual(str(metrics["investing_cashflow"]), "-50")

    def test_calendar_future_schedule_is_known_only_after_capture(self):
        row = synthetic_row(D.CALENDAR)
        row.update(cal_date="20261001", pretrade_date="20260930", is_open="0")
        req = DomainRequest(Subject("exchange", "SSE"), D.CALENDAR, date(2026, 10, 1), date(2026, 10, 1))
        record = self.fetch(D.CALENDAR, [row], req)[0]
        repo = MemoryRepository()
        snapshot = repo.commit(self.scope, (record,))
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, repo, self.artifacts)
            context = QueryContext(AccessContext(self.scope, frozenset({"tushare"})), snapshot.snapshot_id, CAPTURED)
            self.assertEqual(service.query(req, context).records, (record,))
            self.assertFalse(service.query(req, replace(context, as_of_date=CAPTURED-timedelta(microseconds=1))).records)

    def test_wrong_subject_outside_window_and_invalid_factor_fail(self):
        for key, value in (("ts_code", "000001.SZ"), ("trade_date", "20260928"), ("adj_factor", "0"),
                           ("adj_factor", "NaN"), ("adj_factor", None)):
            row = synthetic_row(D.ADJUSTMENT)
            row[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ProviderSchemaError):
                self.fetch(D.ADJUSTMENT, [row])

    def test_subject_kind_prevents_equity_index_collision_and_naive_cutoff(self):
        with self.assertRaises(ValidationError):
            DomainRequest(EQUITY, D.CALENDAR, date(2026, 9, 29), date(2026, 9, 29))
        self.assertNotEqual(INDEX.security_id, Subject("equity", "000300", "SSE").security_id)
        with self.assertRaises(ValidationError):
            QueryContext(AccessContext(self.scope, frozenset({"tushare"})), "snapshot", datetime(2026, 9, 30))

    def test_non_calendar_future_and_observation_backdate_rejected(self):
        record = self.fetch(D.ADJUSTMENT)[0]
        with self.assertRaises(ValidationError):
            replace(record, period=date(2026, 10, 1))
        with self.assertRaises(ValidationError):
            replace(record, available_at=CAPTURED-timedelta(days=1))
        with self.assertRaises(ValidationError):
            replace(record, availability_basis="verified_release")

    def test_constituents_have_distinct_grain_and_frozen_revision(self):
        first = synthetic_row(D.INDEX_WEIGHT)
        second = {**first, "con_code": "600000.SH"}
        rows = self.fetch(D.INDEX_WEIGHT, [first, second])
        repo = MemoryRepository()
        old = repo.commit(self.scope, rows)
        revised = replace(rows[0], retrieved_at=CAPTURED+timedelta(hours=1),
                          available_at=CAPTURED+timedelta(hours=1), ingested_at=CAPTURED+timedelta(hours=1))
        new = repo.commit(self.scope, (revised,), old.snapshot_id)
        self.assertEqual(len(repo.read(self.scope, old.snapshot_id)), 2)
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, repo, self.artifacts)
            ctx = QueryContext(AccessContext(self.scope, frozenset({"tushare"})), new.snapshot_id, CAPTURED)
            result = service.query(request(D.INDEX_WEIGHT), ctx)
            self.assertEqual(len(result.records), 2)
            self.assertNotIn(revised, result.records)

    def test_provider_row_limit_rejects_possible_truncation(self):
        row = synthetic_row(D.BALANCE)
        with self.assertRaises(ProviderSchemaError):
            self.fetch(D.BALANCE, [row] * 1000)

    def test_domain_cache_respects_scope_and_permissions(self):
        provider = TushareDomainProvider("synthetic", self.artifacts,
            lambda *_: response(D.ADJUSTMENT, [synthetic_row(D.ADJUSTMENT)]), lambda: CAPTURED)
        with ProviderExecutor(ExecutionPolicy(min_interval=0)) as executor:
            executor.fetch(provider, request(D.ADJUSTMENT), AccessContext("one", frozenset({"tushare"})))
            executor.fetch(provider, request(D.ADJUSTMENT), AccessContext("two", frozenset({"tushare"})))
            self.assertEqual(executor.stats["attempts"], 2)
            with self.assertRaises(PermissionDenied):
                executor.fetch(provider, request(D.ADJUSTMENT), AccessContext("one", frozenset({"akshare"})))


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = ArtifactStore(self.temp.name)
        self.scope = "synthetic-document-test"
        self.row = {"secCode": "600000", "announcementId": "12345", "announcementTitle": "合成年报摘要",
                    "announcementTime": int(datetime(2026, 9, 29, tzinfo=timezone(timedelta(hours=8))).timestamp()*1000),
                    "adjunctUrl": "finalpage/2026-09-29/12345.PDF"}

    def fake(self, url, timeout, form=None, kind="json"):
        if url.endswith("szse_stock.json"):
            return {"stockList": [{"code": "600000", "orgId": "synthetic-org"}]}
        if kind == "pdf":
            return b"%PDF-1.4 synthetic fixture, not an official report"
        return {"totalAnnouncement": 1, "announcements": [self.row]}

    def record(self):
        return CNInfoAnnouncementProvider(self.artifacts, self.fake, lambda: CAPTURED).fetch(
            request(D.ANNOUNCEMENT, "年报摘要"), self.scope, 5)[0]

    def test_pdf_original_bytes_and_metadata_hash_are_archived(self):
        record = self.record()
        aid = dict(record.attributes)["pdf_artifact_id"]
        self.assertEqual(aid, dict(record.attributes)["document_sha256"])
        self.assertTrue(self.artifacts.get(self.scope, aid).startswith(b"%PDF"))
        self.assertEqual(DataRecord.from_dict(json.loads(json.dumps(record.to_dict()))), record)

    def test_document_evidence_read_checks_cutoff_source_scope_and_record_link(self):
        record = replace(self.record(), ingested_at=CAPTURED+timedelta(minutes=1))
        repo = MemoryRepository()
        snap = repo.commit(self.scope, (record,))
        req = request(D.ANNOUNCEMENT, "年报摘要")
        access = AccessContext(self.scope, frozenset({"cninfo"}))
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, repo, self.artifacts)
            ctx = QueryContext(access, snap.snapshot_id, CAPTURED)
            self.assertTrue(service.evidence(req, ctx, record.record_id, record.artifact_ids[1]).startswith(b"%PDF"))
            for bad in (replace(ctx, as_of_date=CAPTURED-timedelta(microseconds=1)),
                        replace(ctx, mode=PITMode.SYSTEM),
                        replace(ctx, access=AccessContext(self.scope, frozenset({"tushare"}))),
                        replace(ctx, access=AccessContext("wrong", frozenset({"cninfo"})))):
                with self.assertRaises(PermissionDenied):
                    service.evidence(req, bad, record.record_id)
            with self.assertRaises(PermissionDenied):
                service.evidence(req, ctx, record.record_id, "f"*64)

    def test_missing_or_tampered_attachment_invalidates_visible_result(self):
        record = self.record()
        repo = MemoryRepository()
        snap = repo.commit(self.scope, (record,))
        self.artifacts._path(self.scope, record.artifact_ids[1]).write_bytes(b"tampered synthetic PDF")
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, repo, self.artifacts)
            with self.assertRaises(IntegrityError):
                service.query(request(D.ANNOUNCEMENT), QueryContext(
                    AccessContext(self.scope, frozenset({"cninfo"})), snap.snapshot_id, CAPTURED))

    def test_pdf_url_cannot_escape_origin_or_downgrade_or_redirect(self):
        for url in ("http://static.cninfo.com.cn/finalpage/2026-09-29/12345.PDF",
                    "https://evil.example/finalpage/2026-09-29/12345.PDF",
                    "https://static.cninfo.com.cn@evil.example/finalpage/2026-09-29/12345.PDF",
                    "https://static.cninfo.com.cn/finalpage/2026-09-29/12345.PDF?target=evil"):
            with self.assertRaises(ProviderSchemaError):
                document_url(url, "pdf")

    def test_index_wrong_security_date_title_or_invalid_pdf_fails(self):
        base = dict(self.row)
        for key, value in (("secCode", "000001"), ("announcementTitle", "不同标题"),
                           ("announcementTime", 1), ("adjunctUrl", "../evil.PDF")):
            self.row = {**base, key: value}
            with self.subTest(key=key), self.assertRaises(ProviderSchemaError):
                self.record()
        self.row = base
        def bad_pdf(url, timeout, form=None, kind="json"):
            return b"not a PDF" if kind == "pdf" else self.fake(url, timeout, form, kind)
        with self.assertRaises(ProviderSchemaError):
            CNInfoAnnouncementProvider(self.artifacts, bad_pdf, lambda: CAPTURED).fetch(
                request(D.ANNOUNCEMENT), self.scope, 5)

    def test_pagination_bound_and_partial_index_fail_closed(self):
        for total in (301, 2):
            def invalid(url, timeout, form=None, kind="json"):
                result = self.fake(url, timeout, form, kind)
                if form:
                    result = {"totalAnnouncement": total, "announcements": [self.row]}
                return result
            with self.assertRaises(ProviderSchemaError):
                CNInfoAnnouncementProvider(self.artifacts, invalid, lambda: CAPTURED).fetch(
                    request(D.ANNOUNCEMENT), self.scope, 5)

    def news(self, timestamp="2026-09-29 10:30:00", content=None):
        table = {"version": "synthetic", "columns": ["关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"],
                 "rows": [["600000", "合成新闻", "合成摘要", timestamp, "合成来源",
                           "http://finance.eastmoney.com/a/2026092912345.html"]]}
        def transport(endpoint, *_):
            return {"columns": ["code", "name"], "rows": [["600000", "合成公司"]]} if endpoint == "stock_info_a_code_name" else table
        return AkShareNewsProvider(self.artifacts, transport,
            lambda *_args, **_kwargs: content or '<html><title>合成新闻</title><div id="ContentBody">合成公司测试新闻正文</div></html>'.encode(), lambda: CAPTURED).fetch(
                request(D.NEWS), self.scope, 5)

    def test_recent_news_archives_source_html_and_preserves_snippet_semantics(self):
        record = self.news()[0]
        self.assertEqual(dict(record.attributes)["body_kind"], "original_html")
        self.assertEqual(record.available_at, CAPTURED)
        self.assertTrue(self.artifacts.get(self.scope, record.artifact_ids[1]).startswith(b"<html>"))
        self.assertIn("recent_list_coverage_not_verified", record.quality_flags)

    def test_recent_news_does_not_claim_historical_window_coverage(self):
        self.assertEqual(self.news("2024-09-29 10:30:00"), ())

    def test_numeric_keyword_and_sidebar_mention_do_not_establish_company_association(self):
        page = '<html><title>合成新闻</title><div id="ContentBody">其他公司回购600000股</div><div>合成公司股票行情</div></html>'.encode()
        self.assertEqual(self.news(content=page), ())

    def test_qualified_news_code_requires_the_requested_exchange(self):
        for suffix, count in (("SH", 1), ("SZ", 0), ("BJ", 0)):
            page = f'<html><title>合成新闻</title><div id="ContentBody">证券600000.{suffix}的测试正文</div></html>'.encode()
            with self.subTest(suffix=suffix):
                self.assertEqual(len(self.news(content=page)), count)

    def test_challenge_html_and_wrong_article_title_fail_closed(self):
        for page in ('<html><title>验证页面</title><div id="ContentBody">合成公司</div></html>',
                     '<html><title>合成新闻</title><div>没有可识别文章正文</div></html>'):
            with self.assertRaises(ProviderSchemaError):
                self.news(content=page.encode())

    def test_same_document_time_with_conflicting_content_is_ambiguous(self):
        record = self.record()
        different = replace(record, attributes=tuple((k, "different synthetic title" if k == "title" else v)
                                                     for k, v in record.attributes))
        repo = MemoryRepository()
        snap = repo.commit(self.scope, (record, different))
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, repo, self.artifacts)
            with self.assertRaises(IntegrityError):
                service.query(request(D.ANNOUNCEMENT), QueryContext(
                    AccessContext(self.scope, frozenset({"cninfo"})), snap.snapshot_id, CAPTURED))


if __name__ == "__main__":
    unittest.main()
