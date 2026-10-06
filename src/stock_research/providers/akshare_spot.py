"""Bounded pagination for the original AKShare Eastmoney spot functions.

Replaces only their shared pagination helper inside the isolated worker. URLs,
filters, fields and AKShare's column normalization remain the original inputs.
"""
import json
import math
import time

from ..errors import ProviderSchemaError, TransientProviderError
from ..models import aware, utcnow

URLS = frozenset({'https://82.push2.eastmoney.com/api/qt/clist/get',
                  'https://7.push2.eastmoney.com/api/qt/clist/get'})
FILTERS = frozenset({'m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
                     'm:0 t:80', 'm:1 t:23'})
# Eastmoney adds the related-security fields to f128 responses. The installed
# AKShare 32-column parser expects them even though they are not requested.
AUTOMATIC_FIELDS = frozenset({'f140', 'f141'})


class BoundedSpotPagination:
    def __init__(self, timeout, *, session_factory=None, monotonic=time.monotonic,
                 sleep=time.sleep, clock=utcnow):
        if session_factory is None:
            import requests
            session_factory = requests.Session
        self.deadline = monotonic() + timeout
        self.monotonic, self.sleep, self.session_factory = monotonic, sleep, session_factory
        self.source_response = None
        self.attempt_count = 0
        self.last_http_status = None
        self.clock = clock
        self.called = False

    def __call__(self, url, base_params, timeout=15):
        import pandas as pd
        rows = self.collect(url, base_params)
        frame = pd.DataFrame(rows)
        frame['f3'] = pd.to_numeric(frame['f3'], errors='coerce')
        frame.sort_values(by=['f3'], ascending=False, inplace=True, ignore_index=True)
        frame.reset_index(inplace=True)
        frame['index'] = frame['index'].astype(int) + 1
        return frame

    def collect(self, url, base_params):
        if self.called:
            raise ProviderSchemaError('spot pagination helper cannot be reused for another call')
        self.called = True
        if url not in URLS or base_params.get('fs') not in FILTERS or str(base_params.get('pz')) != '100':
            raise ProviderSchemaError('unsupported original spot pagination contract')
        fields = base_params.get('fields', '').split(',')
        if (not {'f3', 'f12', 'f13'} <= set(fields) or len(fields) != len(set(fields))
                or not 3 <= len(fields) <= 64 or any(not f.startswith('f') or not f[1:].isdigit() for f in fields)):
            raise ProviderSchemaError('invalid original spot field projection')
        params = dict(base_params)
        rows, pages, keys, reported_total, page_capacity, response_fields = [], [], set(), None, None, None
        with self.session_factory() as session:
            for number in range(1, 101):
                if number > 1:
                    if self.monotonic() + 1 >= self.deadline:
                        raise TransientProviderError('spot pagination deadline exceeded')
                    self.sleep(1)
                remaining = self.deadline - self.monotonic()
                if remaining <= 0:
                    raise TransientProviderError('spot pagination deadline exceeded')
                params['pn'] = str(number)
                started = aware(self.clock()).isoformat()
                self.attempt_count += 1
                # Exactly one attempt; neither requests nor this helper retries.
                with session.get(url, params=params, timeout=(min(3, remaining), min(5, remaining)),
                                 allow_redirects=False, stream=True) as response:
                    self.last_http_status = response.status_code
                    if response.status_code != 200:
                        raise TransientProviderError('spot HTTP request rejected')
                    body = bytearray()
                    for chunk in response.iter_content(16384):
                        if self.monotonic() >= self.deadline or len(body) + len(chunk) > 2 * 1024 * 1024:
                            raise TransientProviderError('spot page exceeds deadline or byte bound')
                        body.extend(chunk)
                try:
                    payload = json.loads(body)
                    data = payload['data']
                    total, page_rows = data['total'], data['diff']
                except (KeyError, TypeError, ValueError):
                    raise ProviderSchemaError('spot page data missing') from None
                if (payload.get('rc') != 0 or type(total) is not int or not 1 <= total <= 10000
                        or not isinstance(page_rows, list) or not 1 <= len(page_rows) <= 100):
                    raise ProviderSchemaError('invalid spot total or page size')
                if reported_total is None:
                    reported_total = total
                    page_capacity = len(page_rows)
                    if math.ceil(reported_total / page_capacity) > 100:
                        raise ProviderSchemaError('spot reported pagination exceeds page bound')
                if total != reported_total:
                    raise ProviderSchemaError('spot total changed during capture')
                expected_count = min(page_capacity, reported_total - len(rows))
                if len(page_rows) != expected_count:
                    raise ProviderSchemaError('spot page truncated or repeated')
                projected = []
                for row in page_rows:
                    if not isinstance(row, dict) or not set(fields) <= row.keys():
                        raise ProviderSchemaError('spot requested fields missing')
                    # AKShare assigns normalized columns positionally to the
                    # response object order, which differs from request fields.
                    row = {field: value for field, value in row.items() if field in fields or field in AUTOMATIC_FIELDS}
                    if response_fields is None:
                        response_fields = list(row)
                    if list(row) != response_fields:
                        raise ProviderSchemaError('spot response field order changed')
                    if any(type(value) not in {str, int, float, type(None)} or
                           (type(value) is float and not math.isfinite(value)) for value in row.values()):
                        raise ProviderSchemaError('spot source contains unsupported field value')
                    code, market = row['f12'], row['f13']
                    if (not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit()
                            or type(market) is not int or market not in {0, 1}):
                        raise ProviderSchemaError('spot source identity missing')
                    if (code, market) in keys:
                        raise ProviderSchemaError('duplicate spot source security across pages')
                    keys.add((code, market))
                    projected.append(row)
                pages.append({'page': number, 'reported_total': total, 'row_count': len(projected),
                              'started_at': started, 'finished_at': aware(self.clock()).isoformat(),
                              'rows': projected})
                rows.extend(projected)
                if len(rows) == reported_total:
                    break
            else:
                raise ProviderSchemaError('spot page count exceeds bound')
        self.source_response = {'schema': 'akshare_spot_pages_v1', 'url': url,
            'params': dict(base_params), 'requested_fields': fields, 'reported_total': reported_total,
            'response_fields': response_fields, 'page_capacity': page_capacity,
            'page_count': len(pages), 'attempts': len(pages), 'retries': 0, 'pages': pages,
            'completion_basis': 'stable_total_unique_securities_all_pages'}
        return rows
