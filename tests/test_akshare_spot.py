"""Synthetic paginated HTTP fixtures; no provider or financial ground truth."""
import copy
import json
import importlib.util
import unittest
from datetime import timedelta
from tempfile import TemporaryDirectory

from stock_research.errors import IntegrityError, PermissionDenied, ProviderSchemaError, TransientProviderError
from stock_research.models import AccessContext
from stock_research.providers.akshare import AkShareCaptureProvider
from stock_research.providers.akshare_spot import BoundedSpotPagination
from stock_research.storage.artifacts import ArtifactStore
from test_akshare import CAPTURED

URL = 'https://82.push2.eastmoney.com/api/qt/clist/get'
PARAMS = {'pn': '1', 'pz': '100', 'fs': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
          'fields': 'f12,f13,f14,f2,f3,f5,f6'}


def raw(code):
    # Response order deliberately differs from request order.
    return {'f2': 10, 'f3': 1, 'f5': 100, 'f6': 1000, 'f12': code, 'f13': 1, 'f14': 'synthetic'}


def page(rows, total=3):
    return {'rc': 0, 'data': {'total': total, 'diff': rows}}


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = iter(pages), []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def get(self, url, **kwargs):
        self.calls.append((url, copy.deepcopy(kwargs)))
        payload = next(self.pages)
        if isinstance(payload, Exception): raise payload
        return FakeResponse(payload)


class FakeResponse:
    status_code = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def iter_content(self, _): yield json.dumps(self.payload).encode()


class SpotPaginationTests(unittest.TestCase):
    def paginator(self, pages, **kwargs):
        session = FakeSession(pages)
        helper = BoundedSpotPagination(30, session_factory=lambda: session, sleep=lambda _: None,
                                       clock=lambda: CAPTURED, **kwargs)
        return helper, session

    def test_all_pages_exact_count_unique_keys_and_response_order(self):
        helper, session = self.paginator([page([raw('600000'), raw('600001')]), page([raw('600002')])])
        rows = helper.collect(URL, PARAMS)
        self.assertEqual(len(rows), 3)
        self.assertEqual(list(rows[0]), list(raw('600000')))
        proof = helper.source_response
        self.assertEqual(proof['response_fields'], list(raw('600000')))
        self.assertEqual(proof['requested_fields'], PARAMS['fields'].split(','))
        self.assertEqual(proof['page_capacity'], 2)
        self.assertEqual(proof['attempts'], 2)
        self.assertEqual(proof['retries'], 0)
        self.assertEqual([args['params']['pn'] for _, args in session.calls], ['1', '2'])
        self.assertTrue(all(not args['allow_redirects'] for _, args in session.calls))

    def test_repeat_page_truncation_total_drift_and_empty_rejected(self):
        invalid = [page([raw('600000')]), page([raw('600002')], total=4),
                   page([raw('600000'), raw('600001')]), page([], total=3)]
        for last in invalid:
            helper, session = self.paginator([page([raw('600000'), raw('600001')]), last])
            with self.subTest(last=last), self.assertRaises(ProviderSchemaError):
                helper.collect(URL, PARAMS)
            self.assertIsNone(helper.source_response)
            self.assertEqual(len(session.calls), 2)

    def test_failed_http_not_retried_and_no_partial_success(self):
        helper, session = self.paginator([ConnectionError('synthetic network failure')])
        with self.assertRaises(ConnectionError): helper.collect(URL, PARAMS)
        self.assertEqual(len(session.calls), 1)
        self.assertIsNone(helper.source_response)

    def test_deadline_and_page_bound_stop_before_next_request(self):
        ticks = iter([0, 1, 2, 29.5])
        helper, session = self.paginator([page([raw('600000'), raw('600001')])], monotonic=lambda: next(ticks))
        with self.assertRaises(TransientProviderError): helper.collect(URL, PARAMS)
        self.assertEqual(len(session.calls), 1)
        helper, session = self.paginator([page([raw('600000')], total=1000)])
        with self.assertRaises(ProviderSchemaError): helper.collect(URL, PARAMS)
        self.assertEqual(len(session.calls), 1)

    def test_source_archive_pit_scope_and_hash_checks(self):
        helper, _ = self.paginator([page([raw('600000'), raw('600001')]), page([raw('600002')])])
        raw_rows = helper.collect(URL, PARAMS)
        response = {'version': 'synthetic', 'columns': ['代码', '名称', '最新价', '成交量', '成交额'],
                    'rows': [[r['f12'], r['f14'], r['f2'], r['f5'], r['f6']] for r in raw_rows],
                    'source_response': helper.source_response}
        with TemporaryDirectory() as root:
            artifacts = ArtifactStore(root)
            provider = AkShareCaptureProvider(artifacts, lambda *_: response, lambda: CAPTURED)
            access = AccessContext('synthetic', frozenset({'akshare'}))
            capture = provider.capture('stock_zh_a_spot_em', access)
            self.assertEqual(capture.completion_basis, 'stable_total_unique_securities_all_pages')
            self.assertEqual(len(capture.source_artifact_ids), 1)
            self.assertNotIn('source_response_not_archived', capture.quality_flags)
            self.assertEqual(json.loads(provider.source_evidence(capture.snapshot_id, access, CAPTURED)[0]), helper.source_response)
            orphaned = json.loads(artifacts.get(access.scope, capture.snapshot_id))
            orphaned.pop('source_artifact_ids')
            orphaned_id = artifacts.put(access.scope, orphaned)
            with self.assertRaises(ProviderSchemaError): provider.read(orphaned_id, access, CAPTURED)
            with self.assertRaises(PermissionDenied):
                provider.source_evidence(capture.snapshot_id, access, CAPTURED - timedelta(microseconds=1))
            with self.assertRaises(PermissionDenied):
                provider.source_evidence(capture.snapshot_id, AccessContext('synthetic', frozenset({'tushare'})), CAPTURED)
            with self.assertRaises(FileNotFoundError):
                provider.source_evidence(capture.snapshot_id, AccessContext('other', frozenset({'akshare'})), CAPTURED)
            aid = capture.source_artifact_ids[0]
            artifacts._path('synthetic', aid).write_bytes(b'synthetic corruption')
            with self.assertRaises(IntegrityError): provider.read(capture.snapshot_id, access, CAPTURED)

    def test_normalization_wrong_board_duplicate_and_substituted_host_rejected(self):
        helper, _ = self.paginator([page([raw('600000')], total=1)])
        helper.collect(URL, PARAMS)
        columns = ['代码', '名称', '最新价', '成交量', '成交额']
        rows = [['600000', 'synthetic', 10, 100, 1000]]
        for change in ('host', 'count', 'value', 'duplicate', 'board'):
            proof, test_rows = copy.deepcopy(helper.source_response), copy.deepcopy(rows)
            endpoint = 'stock_zh_a_spot_em'
            if change == 'host': proof['url'] = URL.replace('82.', '7.')
            elif change == 'count': proof['reported_total'] = 2
            elif change == 'value': test_rows[0][2] = 99
            elif change == 'duplicate':
                proof['pages'].append(copy.deepcopy(proof['pages'][0]))
                proof['page_count'] = proof['attempts'] = 2
            else:
                endpoint = 'stock_cy_a_spot_em'
                proof['url'] = URL.replace('82.', '7.')
                proof['params']['fs'] = 'm:0 t:80'
            with self.subTest(change=change), self.assertRaises(ProviderSchemaError):
                AkShareCaptureProvider._validate_spot_source(endpoint, columns, test_rows, proof)

    @unittest.skipUnless(importlib.util.find_spec('akshare'), 'optional AKShare SDK not installed')
    def test_installed_sdk_all_23_column_mappings_with_synthetic_source(self):
        import akshare as ak
        expected = {'最新价': 2, '涨跌幅': 3, '涨跌额': 4, '成交量': 5, '成交额': 6, '振幅': 7,
            '最高': 15, '最低': 16, '今开': 17, '昨收': 18, '量比': 10, '换手率': 8,
            '市盈率-动态': 9, '市净率': 23, '总市值': 20, '流通市值': 21, '涨速': 22,
            '5分钟涨跌': 11, '60日涨跌幅': 24, '年初至今涨跌幅': 25, '序号': 1}
        numbers = [*(n for n in range(1, 26) if n != 19), 62, 115, 128, 136, 140, 141, 152]
        for name, code, market in [('stock_zh_a_spot_em', '600000', 1),
                ('stock_cy_a_spot_em', '300750', 0), ('stock_kc_a_spot_em', '688590', 1)]:
            source = {f'f{n}': n for n in numbers}
            source.update(f12=code, f13=market, f14='synthetic')
            helper, _ = self.paginator([page([source], total=1)])
            function = getattr(ak, name)
            old = function.__globals__['fetch_paginated_data']
            try:
                function.__globals__['fetch_paginated_data'] = helper
                frame = function()
            finally:
                function.__globals__['fetch_paginated_data'] = old
            with self.subTest(endpoint=name):
                self.assertEqual(len(frame.columns), 23)
                self.assertEqual(frame.iloc[0]['代码'], code)
                self.assertEqual(frame.iloc[0]['名称'], 'synthetic')
                for column, value in expected.items(): self.assertEqual(frame.iloc[0][column], value)
                AkShareCaptureProvider._validate_spot_source(name, list(frame.columns),
                    frame.values.tolist(), helper.source_response, CAPTURED)

    def test_page_chronology_and_failure_diagnostics_are_bounded_and_safe(self):
        import subprocess
        from unittest.mock import patch
        from stock_research.providers.akshare import AkShareSubprocessTransport
        helper, _ = self.paginator([page([raw('600000')], total=1)])
        helper.collect(URL, PARAMS)
        proof = helper.source_response
        proof['pages'][0]['finished_at'] = (CAPTURED + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ProviderSchemaError):
            AkShareCaptureProvider._validate_spot_source('stock_zh_a_spot_em',
                ['代码', '名称', '最新价', '成交量', '成交额'], [['600000', 'synthetic', 10, 100, 1000]], proof, CAPTURED)
        diagnostic = {'error_type': 'ProxyError', 'attempts': 1, 'last_http_status': None, 'retries': 0}
        for invalid in (False, True):
            value = dict(diagnostic)
            if invalid: value['error_type'] = 'synthetic-secret@proxy'
            completed = subprocess.CompletedProcess([], 5, json.dumps({'worker_failure': value}).encode(), b'')
            with patch('stock_research.providers.akshare.subprocess.run', return_value=completed):
                with self.assertRaises(TransientProviderError) as caught:
                    AkShareSubprocessTransport()('stock_zh_a_spot_em', {}, 2)
            self.assertEqual(caught.exception.diagnostic, None if invalid else diagnostic)
            self.assertNotIn('synthetic-secret', str(caught.exception))
