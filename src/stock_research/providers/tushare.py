import json
import socket
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from ..errors import (ProviderAuthError, ProviderError, ProviderSchemaError,
                      TransientProviderError, ValidationError)
from ..models import (BASES, DataRecord, DataRequest, Dataset, Metric, aware, digest, utcnow)
from .base import ProviderCapability


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TushareHTTPTransport:
    """One HTTP attempt only. ProviderExecutor owns retries and global rate limits."""
    endpoint = "https://api.tushare.pro"

    def __call__(self, payload: dict, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        request = urllib.request.Request(
            self.endpoint, json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(request, timeout=timeout) as response:
                chunks, size = [], 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TransientProviderError("provider body deadline exceeded")
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ProviderSchemaError("provider response exceeds size limit")
                    chunks.append(chunk)
                return json.loads(b"".join(chunks), parse_float=Decimal)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ProviderAuthError("provider authentication or permission denied") from None
            if exc.code == 429 or 500 <= exc.code < 600:
                retry_after = exc.headers.get("Retry-After", "0")
                try:
                    retry_after = float(retry_after)
                except (TypeError, ValueError):
                    retry_after = 0.0
                raise TransientProviderError("provider temporary HTTP failure", retry_after) from None
            raise ProviderError("provider HTTP request rejected") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            raise TransientProviderError("provider connection failure") from None
        except (ValueError, UnicodeError):
            raise ProviderSchemaError("provider returned invalid JSON") from None


def _date(value):
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ProviderSchemaError("invalid provider date")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise ProviderSchemaError("invalid provider date") from None


def _metric(row, source, target, raw_unit, unit, multiplier=1):
    raw = row[source]
    if raw is None:
        return Metric(target, None, unit, None, raw_unit)
    try:
        value = Decimal(str(raw))
        if not value.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise ProviderSchemaError("non-numeric or non-finite metric") from None
    return Metric(target, value * Decimal(multiplier), unit, str(raw), raw_unit)


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


class TushareProvider:
    capability = ProviderCapability("tushare", "2", frozenset(Dataset), frozenset(BASES.values()))
    DAILY_FIELDS = ("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount")
    INCOME_FIELDS = ("ts_code", "ann_date", "f_ann_date", "end_date", "report_type",
                     "revenue", "total_revenue", "n_income_attr_p")

    def __init__(self, token, artifacts, transport=None, clock=utcnow):
        if not token:
            raise ValidationError("TUSHARE_TOKEN is required")
        self._token = token
        self._artifacts = artifacts
        self._transport = transport or TushareHTTPTransport()
        self._clock = clock

    def fetch(self, request: DataRequest, scope: str, timeout: float):
        daily = request.dataset == Dataset.MARKET_DAILY
        api_name = "daily" if daily else "income"
        fields = self.DAILY_FIELDS if daily else self.INCOME_FIELDS
        params = {"ts_code": request.security.provider_symbol}
        if daily:
            params.update(start_date=request.start.strftime("%Y%m%d"), end_date=request.end.strftime("%Y%m%d"))
        else:
            # income start_date/end_date filter announcement date, NOT report period.
            # Fetch one bounded stock history and filter report periods locally.
            params["report_type"] = "1"
        payload = {"api_name": api_name, "token": self._token, "params": params, "fields": ",".join(fields)}
        started = aware(self._clock())
        response = self._transport(payload, timeout)
        captured = aware(self._clock())
        capture_date = captured.astimezone(timezone(timedelta(hours=8))).date()
        call_id = uuid.uuid4().hex
        if not isinstance(response, dict) or type(response.get("code")) is not int:
            raise ProviderSchemaError("missing response code")
        if response["code"] in {2002, 40203}:
            raise ProviderAuthError("provider authentication or permission denied")
        if response["code"] != 0:
            # Unknown API-level errors are not guessed to be transient; never expose msg/token.
            raise ProviderError("provider rejected API request")
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("fields"), list) or not isinstance(data.get("items"), list):
            raise ProviderSchemaError("invalid tabular response")
        actual_fields, items = data["fields"], data["items"]
        if (any(not isinstance(f, str) for f in actual_fields)
                or len(set(actual_fields)) != len(actual_fields) or not set(fields) <= set(actual_fields)):
            raise ProviderSchemaError("missing or duplicate provider fields")
        if len(items) >= (6000 if daily else 1000):
            raise ProviderSchemaError("possible provider truncation; narrow or paginate explicitly")
        parsed, returned_rows = [], []
        for item in items:
            if not isinstance(item, list) or len(item) != len(actual_fields):
                raise ProviderSchemaError("provider row length mismatch")
            row = dict(zip(actual_fields, item))
            # Project only explicitly requested fields. Untrusted extras/message/headers
            # are never archived, including when outside the selected report window.
            projected = [_json_safe(row[f]) for f in fields]
            if any(type(v) not in {str, int, float, bool, type(None)} for v in projected):
                raise ProviderSchemaError("requested response fields must be scalar")
            if any(isinstance(v, str) and self._token in v for v in projected):
                raise ProviderSchemaError("credential reflected in requested response fields")
            returned_rows.append(projected)
            if row["ts_code"] != request.security.provider_symbol:
                raise ProviderSchemaError("provider returned a different security")
            period = _date(row["trade_date" if daily else "end_date"])
            if period > capture_date:
                raise ProviderSchemaError("provider returned a future observed period")
            if not request.start <= period <= request.end:
                if daily:
                    raise ProviderSchemaError("market row outside request window")
                continue
            if daily:
                metrics = tuple(_metric(row, name, name, "CNY/share", "CNY/share")
                                for name in ("open", "high", "low", "close")) + (
                    _metric(row, "vol", "volume", "lot_100_shares", "share", 100),
                    _metric(row, "amount", "amount", "thousand_CNY", "CNY", 1000))
                values = {m.name: m.value for m in metrics}
                if any(v is not None and v < 0 for v in values.values()):
                    raise ProviderSchemaError("negative market value")
                if all(values[n] is not None for n in ("open", "high", "low", "close")):
                    if not (values["low"] <= min(values["open"], values["close"])
                            <= max(values["open"], values["close"]) <= values["high"]):
                        raise ProviderSchemaError("inconsistent OHLC values")
                announcement, revision_order = None, 0
            else:
                if str(row["report_type"]) != "1":
                    raise ProviderSchemaError("unexpected financial report type")
                announcement = _date(row["ann_date"])
                actual_announcement = _date(row["f_ann_date"]) if row["f_ann_date"] else announcement
                if max(announcement, actual_announcement) > capture_date:
                    raise ProviderSchemaError("provider returned a future disclosure date")
                revision_order = int(max(announcement, actual_announcement).strftime("%Y%m%d"))
                metrics = (_metric(row, "revenue", "revenue", "CNY", "CNY"),
                           _metric(row, "total_revenue", "total_revenue", "CNY", "CNY"),
                           _metric(row, "n_income_attr_p", "net_income_parent", "CNY", "CNY"))
            parsed.append((row, period, metrics, announcement, revision_order))
        # Preserve all returned rows of requested fields before local period filtering.
        sanitized = {"archive_schema": "tushare_requested_response_v2", "api_name": api_name,
                     "params": params, "business_code": 0, "fields": list(fields),
                     "response_fields": [f for f in actual_fields if f in fields],
                     "items": returned_rows, "response_row_count": len(items),
                     "selected_row_count": len(parsed), "started_at": started.isoformat(),
                     "finished_at": captured.isoformat()}
        artifact_id = self._artifacts.put(scope, sanitized)
        records = []
        for row, period, metrics, announcement, revision_order in parsed:
            records.append(DataRecord(
                request.security.security_id, request.security.canonical_symbol, request.dataset,
                period, request.basis, metrics, "tushare", self.capability.version, "https://api.tushare.pro",
                f"{api_name}:{request.security.provider_symbol}:{period.isoformat()}",
                digest({f: _json_safe(row[f]) for f in fields}), captured, captured, captured,
                "observed_at", artifact_id, call_id, announcement_date=announcement,
                revision_order=revision_order, quality_flags=("historical_release_not_verified",)))
        return tuple(records)
