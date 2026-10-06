"""P1.8 Tushare contracts. All returned versions are current observations."""
import uuid
from datetime import timezone, timedelta
from decimal import Decimal

from ..domains import DomainDataset as D, DomainRecord, BASES
from ..errors import ProviderAuthError, ProviderError, ProviderSchemaError, ValidationError
from ..models import aware, digest, utcnow
from .base import ProviderCapability
from .tushare import TushareHTTPTransport, _date, _metric, _json_safe


MAPS = {
    D.ADJUSTMENT: (("adj_factor", "factor", "ratio", "ratio", 1),),
    D.INDEX_DAILY: tuple((f, f, "point", "point", 1) for f in ("open", "high", "low", "close")) + (
        ("vol", "volume", "lot_100_shares", "share", 100), ("amount", "amount", "thousand_CNY", "CNY", 1000)),
    D.INDEX_WEIGHT: (("weight", "weight", "percent", "ratio", Decimal("0.01")),),
    D.BALANCE: tuple((raw, name, "CNY", "CNY", 1) for raw, name in (
        ("total_assets", "total_assets"), ("total_liab", "total_liabilities"),
        ("total_hldr_eqy_inc_min_int", "total_equity"), ("total_hldr_eqy_exc_min_int", "equity_parent"),
        ("money_cap", "monetary_funds"))),
    D.CASHFLOW: tuple((raw, name, "CNY", "CNY", 1) for raw, name in (
        ("n_cashflow_act", "operating_cashflow"), ("n_cashflow_inv_act", "investing_cashflow"),
        ("n_cash_flows_fnc_act", "financing_cashflow"), ("n_incr_cash_cash_equ", "cash_net_change"),
        ("c_cash_equ_beg_period", "cash_begin"), ("c_cash_equ_end_period", "cash_end"))),
}
FINANCIAL_META = ("ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", "end_type", "update_flag")
SPECS = {
    D.CALENDAR: ("trade_cal", ("exchange", "cal_date", "is_open", "pretrade_date"), 1000),
    D.ADJUSTMENT: ("adj_factor", ("ts_code", "trade_date", "adj_factor"), 6000),
    D.INDEX_DAILY: ("index_daily", ("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"), 6000),
    D.INDEX_WEIGHT: ("index_weight", ("index_code", "con_code", "trade_date", "weight"), 5000),
    D.BALANCE: ("balancesheet", FINANCIAL_META + tuple(m[0] for m in MAPS[D.BALANCE]), 1000),
    D.CASHFLOW: ("cashflow", FINANCIAL_META + tuple(m[0] for m in MAPS[D.CASHFLOW]), 1000),
}


class TushareDomainProvider:
    capability = ProviderCapability("tushare", "p18-1", frozenset(SPECS),
                                    frozenset(BASES[d] for d in SPECS))

    def __init__(self, token, artifacts, transport=None, clock=utcnow):
        if not token:
            raise ValidationError("TUSHARE_TOKEN is required")
        self._token, self.artifacts = token, artifacts
        self.transport, self.clock = transport or TushareHTTPTransport(), clock

    def fetch(self, request, scope, timeout):
        if request.dataset not in SPECS:
            raise ValidationError("unsupported Tushare domain")
        domain = request.dataset
        api, fields, row_limit = SPECS[domain]
        financial = domain in {D.BALANCE, D.CASHFLOW}
        if domain == D.CALENDAR:
            params = {"exchange": request.subject.code}
        elif domain == D.INDEX_WEIGHT:
            params = {"index_code": request.subject.provider_symbol}
        else:
            params = {"ts_code": request.subject.provider_symbol}
        if financial:
            params["report_type"] = "1"
            if request.start == request.end:
                params["period"] = request.start.strftime("%Y%m%d")
        else:
            params.update(start_date=request.start.strftime("%Y%m%d"), end_date=request.end.strftime("%Y%m%d"))
        response = self.transport({"api_name": api, "token": self._token, "params": params,
                                   "fields": ",".join(fields)}, timeout)
        captured = aware(self.clock())
        today = captured.astimezone(timezone(timedelta(hours=8))).date()
        if not isinstance(response, dict) or type(response.get("code")) is not int:
            raise ProviderSchemaError("invalid Tushare response envelope")
        if response["code"] in {2002, 40203}:
            raise ProviderAuthError("Tushare domain permission denied")
        if response["code"] != 0:
            raise ProviderError("Tushare domain request rejected")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ProviderSchemaError("invalid Tushare table")
        actual, items = data.get("fields"), data.get("items")
        if (not isinstance(actual, list) or any(not isinstance(f, str) for f in actual)
                or len(actual) != len(set(actual)) or not set(fields) <= set(actual)
                or not isinstance(items, list) or len(items) >= row_limit):
            raise ProviderSchemaError("missing fields or possible truncation; split request")
        rows = []
        for item in items:
            if not isinstance(item, list) or len(item) != len(actual):
                raise ProviderSchemaError("Tushare row length mismatch")
            rows.append({key: dict(zip(actual, item))[key] for key in fields})
        parsed = []
        for row in rows:
            key = "exchange" if domain == D.CALENDAR else ("index_code" if domain == D.INDEX_WEIGHT else "ts_code")
            if row[key] != request.subject.provider_symbol:
                raise ProviderSchemaError("Tushare returned different subject")
            period = _date(row["cal_date" if domain == D.CALENDAR else "end_date" if financial else "trade_date"])
            if domain != D.CALENDAR and period > today:
                raise ProviderSchemaError("future non-schedule period")
            if not request.start <= period <= request.end:
                if financial:
                    continue
                raise ProviderSchemaError("Tushare row outside domain window")
            attrs, revision = {}, 0
            fact_id = period.isoformat()
            if domain == D.CALENDAR:
                if str(row["is_open"]) not in {"0", "1"}:
                    raise ProviderSchemaError("invalid calendar open flag")
                prev = _date(row["pretrade_date"]) if row["pretrade_date"] else None
                if prev and prev >= period:
                    raise ProviderSchemaError("invalid previous trading day")
                attrs = {"is_open": str(row["is_open"]), "pretrade_date": prev.isoformat() if prev else None}
            if financial:
                ann = _date(row["ann_date"])
                f_ann = _date(row["f_ann_date"]) if row["f_ann_date"] else ann
                if str(row["report_type"]) != "1" or max(ann, f_ann) > today:
                    raise ProviderSchemaError("unexpected report type or future disclosure")
                if str(row["comp_type"]) not in {"1", "2", "3", "4", "7"}:
                    raise ProviderSchemaError("unknown company report type")
                attrs = {k: str(row[k]) if row[k] is not None else None for k in FINANCIAL_META[1:] if k != "end_date"}
                revision = int(max(ann, f_ann).strftime("%Y%m%d"))
            if domain == D.INDEX_WEIGHT:
                # Constituents are a separate grain; never collapse all rows of one index/day.
                from ..domains import Subject
                code = row["con_code"]
                if not isinstance(code, str) or len(code) != 9 or code[-2:] not in {"SH", "SZ", "BJ"}:
                    raise ProviderSchemaError("invalid constituent code")
                Subject("equity", code[:6], {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[code[-2:]])
                attrs, fact_id = {"constituent_code": code}, code
            metrics = tuple(_metric(row, *mapping) for mapping in MAPS.get(domain, ()))
            values = {m.name: m.value for m in metrics}
            if domain == D.ADJUSTMENT and (values["factor"] is None or values["factor"] <= 0):
                raise ProviderSchemaError("invalid adjustment factor")
            if domain == D.INDEX_WEIGHT and (values["weight"] is None or not 0 <= values["weight"] <= 1):
                raise ProviderSchemaError("invalid normalized weight")
            if domain == D.INDEX_DAILY:
                if any(v is not None and v < 0 for v in values.values()):
                    raise ProviderSchemaError("negative index metric")
                if all(values[k] is not None for k in ("open", "high", "low", "close")):
                    if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
                        raise ProviderSchemaError("inconsistent index OHLC")
            parsed.append((row, period, fact_id, metrics, attrs, revision))
        artifact = self.artifacts.put(scope, {"api_name": api, "params": params, "code": 0,
                                              "fields": list(fields), "items": _json_safe(rows)})
        call = uuid.uuid4().hex
        flags = ("historical_release_not_verified",)
        if domain == D.INDEX_WEIGHT:
            flags += ("monthly_weight_not_daily_membership",)
        return tuple(DomainRecord(request.subject, domain, period, fact, metrics, tuple(attrs.items()),
                                  "tushare", self.capability.version, "https://api.tushare.pro", f"{api}:{fact}",
                                  digest(_json_safe(row)), captured, captured, captured, artifact, call, revision,
                                  quality_flags=flags)
                     for row, period, fact, metrics, attrs, revision in parsed)
