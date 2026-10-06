"""Observed AKShare captures; deliberately separate from historical DataRecord facts."""
import json
import math
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType

from ..errors import PermissionDenied, ProviderError, ProviderSchemaError, TransientProviderError, ValidationError
from ..models import AccessContext, PITMode, aware, utcnow


PROVIDER = "akshare"
SOURCES = {
    "stock_sse_summary": "https://www.sse.com.cn/market/stockdata/statistic/",
    "stock_szse_summary": "https://www.szse.cn/market/overview/index.html",
    "stock_zh_a_spot_em": "https://quote.eastmoney.com/center/gridlist.html#hs_a_board",
    "stock_cy_a_spot_em": "https://quote.eastmoney.com/center/gridlist.html#gem_board",
    "stock_kc_a_spot_em": "https://quote.eastmoney.com/center/gridlist.html#kcb_board",
    "stock_comment_detail_zlkp_jgcyd_em": "https://data.eastmoney.com/stockcomment/stock/",
    "stock_comment_detail_scrd_focus_em": "https://data.eastmoney.com/stockcomment/stock/",
}
REQUIRED_COLUMNS = {
    "stock_sse_summary": {"项目", "股票", "主板", "科创板"},
    "stock_szse_summary": {"证券类别", "数量", "成交金额", "总市值", "流通市值"},
    "stock_zh_a_spot_em": {"代码", "名称", "最新价", "成交量", "成交额"},
    "stock_cy_a_spot_em": {"代码", "名称", "最新价", "成交量", "成交额"},
    "stock_kc_a_spot_em": {"代码", "名称", "最新价", "成交量", "成交额"},
    "stock_comment_detail_zlkp_jgcyd_em": {"交易日", "机构参与度"},
    "stock_comment_detail_scrd_focus_em": {"交易日", "用户关注指数"},
}
SPOT = frozenset({"stock_zh_a_spot_em", "stock_cy_a_spot_em", "stock_kc_a_spot_em"})
COMMENT = frozenset({"stock_comment_detail_zlkp_jgcyd_em", "stock_comment_detail_scrd_focus_em"})
SHANGHAI = timezone(timedelta(hours=8))


def _params(endpoint: str, symbol: str | None, trade_date: date | None) -> dict:
    if endpoint not in SOURCES:
        raise ValidationError("unsupported AKShare endpoint")
    if endpoint in COMMENT:
        if symbol is None or not re.fullmatch(r"\d{6}", symbol):
            raise ValidationError("six-digit symbol required for AKShare comment endpoint")
        if trade_date is not None:
            raise ValidationError("trade_date is not supported by comment endpoint")
        return {"symbol": symbol}
    if endpoint == "stock_szse_summary":
        if symbol is not None or type(trade_date) is not date:
            raise ValidationError("trade_date required for SZSE summary")
        if trade_date > utcnow().astimezone(SHANGHAI).date():
            raise ValidationError("future trade_date is invalid")
        return {"date": trade_date.strftime("%Y%m%d")}
    if symbol is not None or trade_date is not None:
        raise ValidationError("this AKShare endpoint takes no parameters")
    return {}


class AkShareSubprocessTransport:
    """Single attempt. Process termination bounds AKShare calls lacking HTTP timeouts."""

    def __call__(self, endpoint: str, params: dict, timeout: float) -> dict:
        if timeout <= 0 or timeout > 120:
            raise ValidationError("AKShare timeout must be in (0, 120] seconds")
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "stock_research.providers.akshare_worker",
                 endpoint, json.dumps(params, separators=(",", ":")), str(timeout)],
                capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise TransientProviderError("AKShare call exceeded deadline") from None
        except OSError:
            raise ProviderError("AKShare worker could not start") from None
        diagnostic = None
        if completed.returncode and len(completed.stdout) < 4096:
            try:
                value = json.loads(completed.stdout).get('worker_failure')
                if (isinstance(value, dict) and set(value) == {'error_type', 'attempts', 'last_http_status', 'retries'}
                        and isinstance(value['error_type'], str) and re.fullmatch(r'[A-Za-z_]{1,80}', value['error_type'])
                        and type(value['attempts']) is int and 0 <= value['attempts'] <= 100
                        and value['retries'] == 0 and (value['last_http_status'] is None
                            or type(value['last_http_status']) is int and 100 <= value['last_http_status'] <= 599)):
                    diagnostic = value
            except (ValueError, TypeError, AttributeError):
                pass
        if completed.returncode == 5:
            error = TransientProviderError("AKShare network connection failure")
            error.diagnostic = diagnostic
            raise error
        if completed.returncode == 6:
            error = ProviderSchemaError("AKShare upstream parser or source schema failed")
            error.diagnostic = diagnostic
            raise error
        if completed.returncode != 0:
            raise ProviderError("AKShare call failed")
        if len(completed.stdout) > 16 * 1024 * 1024:
            raise ProviderSchemaError("AKShare response exceeds size limit")
        try:
            return json.loads(completed.stdout)
        except (ValueError, UnicodeError):
            raise ProviderSchemaError("AKShare worker returned invalid JSON") from None


@dataclass(frozen=True)
class AkShareCapture:
    snapshot_id: str
    endpoint: str
    params: dict
    source_url: str
    provider_version: str
    captured_at: datetime
    ingested_at: datetime
    call_id: str
    columns: tuple[str, ...]
    rows: tuple[tuple, ...]
    quality_flags: tuple[str, ...]
    source_artifact_ids: tuple[str, ...] = ()
    completion_basis: str = "not_verified"

    @property
    def row_count(self):
        return len(self.rows)


class AkShareCaptureProvider:
    """Scope-isolated immutable raw snapshot store, with PIT checked on every read."""

    def __init__(self, artifacts, transport=None, clock=utcnow):
        self.artifacts = artifacts
        self.transport = transport or AkShareSubprocessTransport()
        self.clock = clock

    @staticmethod
    def _authorize(access: AccessContext):
        if not isinstance(access, AccessContext) or PROVIDER not in access.allowed_providers:
            raise PermissionDenied("provider not authorized")

    def capture(self, endpoint: str, access: AccessContext, *, symbol=None,
                trade_date=None, timeout=45.0) -> AkShareCapture:
        self._authorize(access)
        params = _params(endpoint, symbol, trade_date)
        if timeout <= 0 or timeout > 120:
            raise ValidationError("AKShare timeout must be in (0, 120] seconds")
        response = self.transport(endpoint, params, timeout)
        captured = aware(self.clock())
        columns, rows = self._validate(endpoint, params, response, captured)
        source = response.get('source_response')
        source_ids = ()
        if source is not None:
            self._validate_spot_source(endpoint, columns, rows, source, captured)
            source_ids = (self.artifacts.put(access.scope, source),)
        ingested = aware(self.clock())
        if ingested < captured:
            raise ProviderSchemaError("capture clock moved backwards")
        payload = {"provider": PROVIDER, "provider_version": response["version"],
                   "endpoint": endpoint, "params": params, "source_url": SOURCES[endpoint],
                   "captured_at": captured.isoformat(), "ingested_at": ingested.isoformat(),
                   "call_id": uuid.uuid4().hex, "availability_basis": "observed_at",
                   "columns": columns, "rows": rows,
                   "quality_flags": ["historical_release_not_verified", "coverage_not_verified",
                                     "source_response_not_archived"] + (
                       ["upstream_transport_unverified"] if endpoint in {
                           "stock_sse_summary", "stock_szse_summary"} else [])}
        if source_ids:
            payload['source_artifact_ids'] = source_ids
            payload['completion_basis'] = source['completion_basis']
            payload['quality_flags'].remove('source_response_not_archived')
            payload['quality_flags'].append('pagination_complete_at_capture')
        snapshot_id = self.artifacts.put(access.scope, payload)
        return self._decode(snapshot_id, payload)

    def read(self, snapshot_id: str, access: AccessContext, cutoff: datetime,
             mode: PITMode = PITMode.PUBLIC) -> AkShareCapture:
        self._authorize(access)
        cutoff = aware(cutoff)
        if not isinstance(mode, PITMode):
            raise ValidationError("PIT mode required")
        try:
            payload = json.loads(self.artifacts.get(access.scope, snapshot_id))
            capture = self._decode(snapshot_id, payload)
        except (ValueError, KeyError, TypeError):
            raise ProviderSchemaError("invalid AKShare snapshot") from None
        if capture.captured_at > cutoff or (mode == PITMode.SYSTEM and capture.ingested_at > cutoff):
            raise PermissionDenied("snapshot is not visible at cutoff")
        for aid in capture.source_artifact_ids:
            source = json.loads(self.artifacts.get(access.scope, aid))
            self._validate_spot_source(capture.endpoint, capture.columns, capture.rows, source, capture.captured_at)
        return capture

    def source_evidence(self, snapshot_id, access, cutoff, mode=PITMode.PUBLIC):
        capture = self.read(snapshot_id, access, cutoff, mode)
        return tuple(self.artifacts.get(access.scope, aid) for aid in capture.source_artifact_ids)

    @staticmethod
    def _validate_spot_source(endpoint, columns, rows, source, captured=None):
        from .akshare_spot import AUTOMATIC_FIELDS, URLS
        expected_filter = {'stock_zh_a_spot_em': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
                           'stock_cy_a_spot_em': 'm:0 t:80', 'stock_kc_a_spot_em': 'm:1 t:23'}
        if (endpoint not in SPOT or not isinstance(source, dict)
                or source.get('schema') != 'akshare_spot_pages_v1' or source.get('url') not in URLS
                or source.get('completion_basis') != 'stable_total_unique_securities_all_pages'
                or not isinstance(source.get('params'), dict)
                or source.get('params', {}).get('fs') != expected_filter[endpoint]
                or source.get('retries') != 0):
            raise ProviderSchemaError('invalid original spot source lineage')
        expected_url = 'https://' + ('82' if endpoint == 'stock_zh_a_spot_em' else '7') + '.push2.eastmoney.com/api/qt/clist/get'
        if source['url'] != expected_url:
            raise ProviderSchemaError('spot source substituted its original host')
        total, capacity, pages = source.get('reported_total'), source.get('page_capacity'), source.get('pages')
        fields = source.get('requested_fields')
        order = source.get('response_fields')
        if (type(total) is not int or total != len(rows) or not 1 <= total <= 10000
                or type(capacity) is not int or not 1 <= capacity <= 100
                or not isinstance(pages, list) or not 1 <= len(pages) <= 100
                or source.get('page_count') != len(pages) or source.get('attempts') != len(pages)
                or not isinstance(fields, list) or not isinstance(order, list)
                or any(not isinstance(field, str) for field in fields + order)
                or len(set(fields)) != len(fields) or len(set(order)) != len(order)
                or not {'f2', 'f5', 'f6', 'f12', 'f13', 'f14'} <= set(fields)
                or not set(fields) <= set(order) <= set(fields) | AUTOMATIC_FIELDS
                or source['params'].get('fields') != ','.join(fields)):
            raise ProviderSchemaError('spot pagination coverage metadata invalid')
        if len(pages) != math.ceil(total / capacity):
            raise ProviderSchemaError('spot page count differs from total and capacity')
        raw, previous_end = {}, None
        for number, page in enumerate(pages, 1):
            try:
                started = aware(datetime.fromisoformat(page['started_at']))
                finished = aware(datetime.fromisoformat(page['finished_at']))
            except (ValueError, TypeError, KeyError, ValidationError):
                raise ProviderSchemaError('spot page timestamps require timezone-aware provenance') from None
            if started > finished or previous_end is not None and started < previous_end or captured is not None and finished > captured:
                raise ProviderSchemaError('spot page chronology violates capture time')
            previous_end = finished
            count = min(capacity, total - len(raw))
            items = page.get('rows')
            if (page.get('page') != number or page.get('reported_total') != total
                    or not isinstance(items, list) or len(items) != count or page.get('row_count') != count):
                raise ProviderSchemaError('spot pagination omitted or repeated page')
            for item in items:
                if (not isinstance(item, dict) or set(item) != set(order)
                        or not isinstance(item.get('f12'), str) or not re.fullmatch(r'\d{6}', item['f12'])
                        or type(item.get('f13')) is not int or item['f13'] not in {0, 1}
                        or any(type(value) not in {str, int, float, type(None)}
                               or (type(value) is float and not math.isfinite(value)) for value in item.values())
                        or item.get('f12') in raw):
                    raise ProviderSchemaError('spot raw row duplicated or changed fields')
                raw[item.get('f12')] = item
        if len(raw) != total:
            raise ProviderSchemaError('spot source does not cover reported total')
        positions = {column: columns.index(column) for column in ('代码', '名称', '最新价', '成交量', '成交额')}
        normalized_codes = [row[positions['代码']] for row in rows]
        if len(set(normalized_codes)) != len(rows) or set(normalized_codes) != set(raw):
            raise ProviderSchemaError('spot normalized security set differs from source')
        for row in rows:
            code = row[positions['代码']]
            if ((endpoint == 'stock_cy_a_spot_em' and not code.startswith('30'))
                    or (endpoint == 'stock_kc_a_spot_em' and not code.startswith('68'))
                    or endpoint == 'stock_cy_a_spot_em' and raw[code]['f13'] != 0
                    or endpoint == 'stock_kc_a_spot_em' and raw[code]['f13'] != 1):
                raise ProviderSchemaError('spot security outside requested board')
            for column, field in {'名称': 'f14', '最新价': 'f2', '成交量': 'f5', '成交额': 'f6'}.items():
                value = raw[code].get(field)
                if column != '名称':
                    if value in {None, '-'}:
                        value = None
                    else:
                        try:
                            value = float(value)
                        except (ValueError, TypeError):
                            raise ProviderSchemaError('invalid source spot numeric field') from None
                if row[positions[column]] != value:
                    raise ProviderSchemaError('spot normalized field differs from source')

    @staticmethod
    def _validate(endpoint, params, response, captured):
        if not isinstance(response, dict) or not isinstance(response.get("version"), str):
            raise ProviderSchemaError("missing AKShare version")
        columns, rows = response.get("columns"), response.get("rows")
        if (not isinstance(columns, list) or any(not isinstance(c, str) for c in columns)
                or len(columns) != len(set(columns)) or not REQUIRED_COLUMNS[endpoint] <= set(columns)
                or not isinstance(rows, list) or len(rows) > 10000):
            raise ProviderSchemaError("AKShare column or row schema changed")
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ProviderSchemaError("AKShare row schema changed")
            if any(type(value) not in {str, int, float, bool, type(None)}
                   or (type(value) is float and not math.isfinite(value)) for value in row):
                raise ProviderSchemaError("AKShare returned unsupported cell value")
        index = {name: columns.index(name) for name in REQUIRED_COLUMNS[endpoint]}
        today = captured.astimezone(SHANGHAI).date()
        if endpoint == "stock_sse_summary" and rows:
            report = [r for r in rows if r[index["项目"]] == "报告时间"]
            if len(report) != 1:
                raise ProviderSchemaError("SSE report date missing or ambiguous")
            try:
                value = str(report[0][index["股票"]])
                published_date = datetime.strptime(value, "%Y%m%d").date()
            except (TypeError, ValueError):
                raise ProviderSchemaError("invalid SSE report date") from None
            if published_date > today:
                raise ProviderSchemaError("future SSE report date")
        if endpoint == "stock_szse_summary" and date.fromisoformat(
                f"{params['date'][:4]}-{params['date'][4:6]}-{params['date'][6:]}") > today:
            raise ProviderSchemaError("future SZSE requested date")
        if endpoint in COMMENT:
            for row in rows:
                try:
                    trading_day = date.fromisoformat(str(row[index["交易日"]]))
                except ValueError:
                    raise ProviderSchemaError("invalid comment trading date") from None
                if trading_day > today:
                    raise ProviderSchemaError("future comment trading date")
        if endpoint in SPOT:
            for row in rows:
                if not re.fullmatch(r"\d{6}", str(row[index["代码"]])):
                    raise ProviderSchemaError("invalid spot security code")
        return columns, rows

    @staticmethod
    def _decode(snapshot_id, payload):
        if payload.get("provider") != PROVIDER or payload.get("endpoint") not in SOURCES \
                or payload.get("availability_basis") != "observed_at":
            raise ProviderSchemaError("invalid AKShare snapshot identity")
        captured = aware(datetime.fromisoformat(payload["captured_at"]))
        ingested = aware(datetime.fromisoformat(payload["ingested_at"]))
        if ingested < captured:
            raise ProviderSchemaError("invalid AKShare ingestion time")
        columns, rows = AkShareCaptureProvider._validate(payload["endpoint"], payload["params"],
            {"version": payload["provider_version"], "columns": payload["columns"],
             "rows": payload["rows"]}, captured)
        source_ids = payload.get('source_artifact_ids', ())
        completion = payload.get('completion_basis', 'not_verified')
        if (not isinstance(source_ids, (list, tuple)) or len(source_ids) > 1
                or any(not isinstance(aid, str) or not re.fullmatch(r'[0-9a-f]{64}', aid) for aid in source_ids)
                or completion not in {'not_verified', 'stable_total_unique_securities_all_pages'}
                or bool(source_ids) != (completion == 'stable_total_unique_securities_all_pages')):
            raise ProviderSchemaError('spot completion requires its archived source evidence')
        return AkShareCapture(snapshot_id, payload["endpoint"], MappingProxyType(dict(payload["params"])),
                              payload["source_url"], payload["provider_version"], captured,
                              ingested, payload["call_id"], tuple(columns),
                              tuple(tuple(row) for row in rows), tuple(payload["quality_flags"]),
                              tuple(source_ids), completion)
