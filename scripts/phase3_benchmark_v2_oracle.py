"""Independent, read-only Source/Fraction oracle for the frozen v2 benchmark.

No production module, Agent evaluator, previous verdict, model, or network call
supplies an answer. Full immutable snapshots select the authorized PIT inputs;
raw content-addressed artifacts validate their fields. Official PDF accuracy is
reported separately from the transformation checks. Outputs are exclusive writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction as F
import hashlib
import itertools
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CN = timezone(timedelta(hours=8))
VERSION = "independent-source-fraction-v2/1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
SECRET_NAMES = {"test_api.txt", "tushare.txt", ".env", "p17-dsn.txt"}
BASES = {"market_daily": "unadjusted_daily", "financial_income": "consolidated_cumulative_cny",
         "adjustment_factor": "raw_adjustment_factor", "index_daily": "price_index_daily",
         "financial_balance": "consolidated_balance_cny",
         "financial_cashflow": "consolidated_cumulative_cashflow_cny",
         "trade_calendar": "exchange_schedule", "announcement": "official_pdf_observed",
         "news_recent": "recent_news_observed"}
RAW_FIELDS = {"net_income_parent": "n_income_attr_p", "factor": "adj_factor",
    "operating_cashflow": "n_cashflow_act", "investing_cashflow": "n_cashflow_inv_act",
    "financing_cashflow": "n_cash_flows_fnc_act", "cash_begin": "c_cash_equ_beg_period",
    "cash_end": "c_cash_equ_end_period", "cash_net_change": "n_incr_cash_cash_equ",
    "total_equity": "total_hldr_eqy_inc_min_int", "equity_parent": "total_hldr_eqy_exc_min_int",
    "monetary_funds": "money_cap", "total_liabilities": "total_liab"}
APIS = {"market_daily": "daily", "financial_income": "income", "adjustment_factor": "adj_factor",
        "index_daily": "index_daily", "financial_balance": "balancesheet",
        "financial_cashflow": "cashflow"}
FORMULAS = {
    "observed_price_change": "last_close / first_close - 1; unadjusted",
    "observed_max_drawdown": "max(1 - close / running_max(close)); observed unadjusted closes",
    "factor_adjusted_price_change": "(last_close * last_factor) / (first_close * first_factor) - 1; not total return",
    "benchmark_price_change": "last_index_close / first_index_close - 1; price index",
    "price_change_difference": "stock_unadjusted_price_change - benchmark_price_change; not alpha",
    "event_observed_price_change": "last_post_anchor_close / last_pre_anchor_close - 1; unadjusted; not causal impact",
    "identity": "identity; latest visible report period; preserve source basis",
    "yoy": "current_same_period / prior_year_same_period - 1; positive base required",
    "absolute_profit_change": "current_same_period - prior_year_same_period; signed CNY amount; no positive-base condition"}
CATALOGUE = {
    "mechanical_adjustment": ("价格变化中存在复权因子变化", ["market_daily", "adjustment_factor"],
                             "对齐因子调整与未复权变化不等；不声称已排除全部公司行动"),
    "market_direction": ("股票与基准在同一观察区间同向变化", ["market_daily", "index_daily"],
                         "日期完全对齐且非零变化同号；不证明市场导致个股变化"),
    "financial_deterioration": ("同报告期收入与归母净利润同比均下降", ["financial_income"],
                                "两项正基数同比均小于零；方向冲突单列"),
    "cashflow_divergence": ("同报告期正利润伴随负经营现金流", ["financial_income", "financial_cashflow"],
                           "累计合并口径、同报告期，归母净利润为正且经营现金流为负；不判断舞弊或偿债能力"),
    "event_chronology": ("合格披露时间锚点前后均有观察收盘价", ["market_daily", "explicit_event_record"],
                         "使用合格公开时间或日期精度保守边界；采集时间与网页标称时间不足以建立事件顺序"),
    "absolute_profit_change": ("同报告期归母净利润金额增加", ["financial_income"],
                              "本期累计合并归母净利润减上年同报告期金额大于零；允许非正基数；不是百分比同比或因果解释")}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf8")).hexdigest()


def aware(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return result


def rid(record):
    payload = dict(record)
    payload.pop("ingested_at")
    return digest(payload)


def identity(record):
    if "security_id" in record:
        return record["security_id"]
    subject = record["subject"]
    code = subject["exchange"] + ":" + subject["code"] if subject["kind"] == "equity" else subject["code"]
    return "CN:" + subject["kind"] + ":" + code


def artifacts(record):
    ids = {record["artifact_id"], *record.get("supporting_artifact_ids", [])}
    if record.get("release_evidence_artifact_id"):
        ids.add(record["release_evidence_artifact_id"])
    attrs = dict(record.get("attributes", []))
    ids.update(attrs[k] for k in ("pdf_artifact_id", "body_artifact_id") if k in attrs)
    return sorted(ids)


def metric(record, name):
    matches = [m for m in record.get("metrics", []) if m["name"] == name]
    return matches[0] if len(matches) == 1 else None


def number(value):
    return None if value is None else F(str(value))


def equivalent(a, b):
    return a is None and b is None or a is not None and b is not None and number(a) == number(b)


def iso8(value):
    value = str(value)
    return value[:4] + "-" + value[4:6] + "-" + value[6:8]


def fraction_json(value):
    return None if value is None else [value.numerator, value.denominator]


def unique_object(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


class Reader:
    def __init__(self, repository_root=ROOT):
        self.root = Path(repository_root).resolve()
        self.reads = {}

    def path(self, name, base=None):
        target = Path(name)
        if not target.is_absolute():
            target = (Path(base) if base is not None else self.root) / target
        target = target.resolve()
        if not target.is_relative_to(self.root) or target.name.lower() in SECRET_NAMES:
            raise ValueError("read is outside the authorized source workspace")
        return target

    def bytes(self, name, expected=None, base=None):
        path = self.path(name, base)
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if expected is not None and sha != expected:
            raise ValueError("frozen source SHA256 mismatch: " + path.relative_to(self.root).as_posix())
        self.reads[path.relative_to(self.root).as_posix()] = sha
        return raw

    def json(self, name, expected=None, base=None):
        return json.loads(self.bytes(name, expected, base), object_pairs_hook=unique_object)


def select_inputs(case, frozen):
    """Select from full members, never from report Evidence or prior selections."""
    request = case["request"]
    cutoff = aware(request["as_of"])
    if request["mode"] not in {"public", "system"}:
        raise ValueError("unknown PIT mode")
    snapshots = frozen.get("snapshots", frozen.get("full_snapshots", []))
    if isinstance(snapshots, dict):
        snapshots = list(snapshots.values())
    lookup = {}
    checks = {"request_matches_frozen_inputs": frozen.get("request", request) == request,
              "recipient_scope_matches": frozen.get("scope", case["scope"]) == case["scope"],
              "source_scopes_match": frozen.get("source_scopes", case["source_scopes"]) == case["source_scopes"]}
    for index, snapshot in enumerate(snapshots):
        owner = snapshot.get("owner_scope", snapshot.get("scope"))
        sid = snapshot.get("snapshot", snapshot.get("snapshot_id"))
        rows = snapshot.get("records", [])
        ids = sorted(rid(row) for row in rows)
        valid = (ids == sorted(set(ids)) and snapshot.get("record_ids", ids) == ids
                 and digest({"scope": owner, "record_ids": ids}) == sid)
        checks["full_snapshot_membership_hash_" + str(index)] = valid
        if (owner, sid) in lookup:
            checks["full_snapshot_unique_" + str(index)] = lookup[(owner, sid)] == rows
        lookup[(owner, sid)] = rows
    selected, bindings = {}, {}
    for binding in request["bindings"]:
        dataset = binding["dataset"]
        bindings[dataset] = binding
        owner = case["source_scopes"][dataset]
        metadata = frozen.get("binding_metadata", {}).get(dataset)
        if metadata is not None:
            checks["trusted_source_owner_" + dataset] = metadata.get("owner_scope") == owner
            checks["trusted_authorized_read_" + dataset] = (metadata.get("trusted") is True and metadata.get("authorized") is True
                and metadata.get("scope") == case["scope"] and metadata.get("snapshot") == binding["snapshot"]
                and metadata.get("provider") == binding["provider"] and metadata.get("artifacts_verified") is True)
        key = owner, binding["snapshot"]
        checks["bound_snapshot_available_" + dataset] = key in lookup
        rows = lookup.get(key, [])
        if metadata is not None:
            checks["trusted_full_members_equal_snapshot_" + dataset] = metadata.get("snapshot_record_ids") == sorted(rid(row) for row in rows)
        subject = ("CN:index:" + request["benchmark"] if dataset == "index_daily" else
                   "CN:exchange:" + request["exchange"] if dataset == "trade_calendar" else
                   "CN:equity:" + request["exchange"] + ":" + request["symbol"])
        eligible = []
        for row in rows:
            if (row["dataset"] == dataset and row["provider"] == binding["provider"]
                    and identity(row) == subject and binding["start"] <= row["period"] <= binding["end"]
                    and row.get("basis", BASES[dataset]) == BASES[dataset]
                    and aware(row["available_at"]) <= cutoff
                    and (request["mode"] != "system" or aware(row["ingested_at"]) <= cutoff)):
                eligible.append(row)
        groups = {}
        for row in eligible:
            family = row["period"], row.get("basis", BASES[dataset]), row.get("fact_id")
            groups.setdefault(family, []).append(row)
        chosen = []
        for family, versions in groups.items():
            rank = max((aware(row["available_at"]), row.get("revision_order", 0)) for row in versions)
            best = [row for row in versions if (aware(row["available_at"]), row.get("revision_order", 0)) == rank]
            signatures = []
            for row in best:
                attrs = dict(row.get("attributes", []))
                if dataset in {"financial_balance", "financial_cashflow"}:
                    attrs.pop("update_flag", None)
                signatures.append(digest({"metrics": row.get("metrics", []), "attributes": attrs}))
            checks["unambiguous_visible_" + dataset + "_" + family[0]] = len(set(signatures)) == 1
            chosen.append(min(best, key=rid))
        selected[dataset] = sorted(chosen, key=lambda row: (row["period"], rid(row)))
        checks["series_unique_periods_" + dataset] = dataset in {"announcement", "news_recent"} or len({r["period"] for r in chosen}) == len(chosen)
        checks["all_read_rows_temporal_" + dataset] = all(
            aware(row["ingested_at"]) >= aware(row["retrieved_at"])
            and (row["availability_basis"] != "observed_at" or aware(row["available_at"]) >= aware(row["retrieved_at"]))
            and (dataset not in {"market_daily", "index_daily"} or
                 datetime.combine(date.fromisoformat(row["period"]), time(15), CN) <= cutoff)
            for row in chosen)
        captured = frozen.get("datasets", {}).get(dataset)
        if captured is not None:
            captured = captured.get("records", []) if isinstance(captured, dict) else captured
            checks["frozen_query_equals_independent_selection_" + dataset] = captured == selected[dataset]
    return selected, bindings, checks


def source_evidence(record, metric_name, binding):
    value = metric(record, metric_name)
    if value is None:
        raise ValueError("missing explicit metric schema")
    eid = digest({"record": rid(record), "metric": metric_name})
    return {"id": eid, "kind": "source", "record_id": rid(record), "metric": metric_name,
        "value": value["value"], "unit": value["unit"], "raw_value": value["raw_value"],
        "raw_unit": value["raw_unit"], "period": record["period"],
        "basis": record.get("basis", BASES[record["dataset"]]), "provider": record["provider"],
        "provider_version": record["provider_version"], "source_url": record["source_url"],
        "revision_id": record["revision_id"], "artifact_ids": artifacts(record),
        "provider_call_id": record["provider_call_id"], "available_at": record["available_at"],
        "published_at": record.get("published_at"), "retrieved_at": record["retrieved_at"],
        "ingested_at": record["ingested_at"], "availability_basis": record["availability_basis"],
        "snapshot": binding["snapshot"]}


def expected_anchor(selected, bindings, request):
    if not request.get("event_record_id"):
        return {"status": "insufficient", "reason": "event_anchor_not_requested"}, None
    for dataset, rows in selected.items():
        for row in rows:
            if rid(row) != request["event_record_id"]:
                continue
            if dataset not in {"financial_income", "announcement", "news_recent"}:
                return {"status": "insufficient", "reason": "event_anchor_dataset_not_supported"}, row
            anchor = {"record_id": rid(row), "dataset": dataset, "snapshot": bindings[dataset]["snapshot"],
                "provider": row["provider"], "provider_call_id": row["provider_call_id"],
                "source_url": row["source_url"], "artifact_ids": artifacts(row),
                "revision_id": row["revision_id"], "available_at": row["available_at"],
                "ingested_at": row["ingested_at"], "retrieved_at": row["retrieved_at"],
                "availability_basis": row["availability_basis"], "source_period": row["period"], "causal_claim": False}
            if row["availability_basis"] == "verified_release":
                release = aware(row["published_at"])
                anchor.update(status="verified", precision="timestamp", disclosed_at=row["published_at"],
                              boundary_date=release.astimezone(CN).date().isoformat())
            elif row["availability_basis"] == "verified_release_date":
                release = date.fromisoformat(row["release_date"])
                anchor.update(status="verified", precision="date_conservative_next_day",
                    release_date=release.isoformat(), boundary_date=(release + timedelta(days=1)).isoformat(),
                    release_evidence_artifact_id=row["release_evidence_artifact_id"])
            else:
                anchor.update(status="insufficient", reason="capture_is_not_event_release_time")
            return anchor, row
    return {"status": "insufficient", "reason": "event_anchor_not_visible"}, None


def expected_facts(selected, bindings, request):
    """Complete expected Claim set using only source strings and Fraction arithmetic."""
    facts, evidence = {}, {}

    def source(row, name):
        ev = source_evidence(row, name, bindings[row["dataset"]])
        evidence[ev["id"]] = ev
        return number(ev["value"]), ev["id"]

    def add(name, value, unit, inputs, formula, window, extra_available=()):
        inputs = list(dict.fromkeys(inputs))
        available = max([aware(evidence[e]["available_at"]) for e in inputs]
                        + [aware(t) for t in extra_available])
        facts[name] = {"name": name, "fraction": fraction_json(value), "unit": unit,
            "inputs": inputs, "formula": formula, "window": window, "available_at": available.isoformat()}

    def prices(dataset):
        values = []
        for row in selected.get(dataset, []):
            value, eid = source(row, "close")
            if value is None or value <= 0:
                return []
            values.append((row["period"], value, eid))
        return values if len(values) >= 2 else []

    stock = prices("market_daily")
    if stock:
        window = [stock[0][0], stock[-1][0]]
        change = stock[-1][1] / stock[0][1] - 1
        add("observed_price_change", change, "ratio", [stock[0][2], stock[-1][2]], FORMULAS["observed_price_change"], window)
        peak, drawdown = stock[0][1], F(0)
        for _, value, _ in stock:
            peak = max(peak, value)
            drawdown = max(drawdown, 1 - value / peak)
        add("observed_max_drawdown", drawdown, "ratio", [v[2] for v in stock], FORMULAS["observed_max_drawdown"], window)
        if "adjustment_factor" in selected:
            factors = {row["period"]: source(row, "factor") for row in selected["adjustment_factor"]}
            if all(day in factors and factors[day][0] is not None and factors[day][0] > 0 for day, _, _ in stock):
                first, last = stock[0], stock[-1]
                adjusted = last[1] * factors[last[0]][0] / (first[1] * factors[first[0]][0]) - 1
                add("factor_adjusted_price_change", adjusted, "ratio", [first[2], last[2], factors[first[0]][1], factors[last[0]][1]], FORMULAS["factor_adjusted_price_change"], window)
        if "index_daily" in selected:
            index = prices("index_daily")
            if index and [v[0] for v in index] == [v[0] for v in stock]:
                change_index = index[-1][1] / index[0][1] - 1
                add("benchmark_price_change", change_index, "ratio", [index[0][2], index[-1][2]], FORMULAS["benchmark_price_change"], window)
                add("price_change_difference", change - change_index, "ratio", [stock[0][2], stock[-1][2], index[0][2], index[-1][2]], FORMULAS["price_change_difference"], window)
    for dataset in ("financial_income", "financial_balance", "financial_cashflow"):
        rows = selected.get(dataset, [])
        if not rows:
            continue
        latest = rows[-1]
        for value in latest["metrics"]:
            amount, eid = source(latest, value["name"])
            if amount is not None:
                add(dataset + "." + value["name"], amount, value["unit"], [eid], FORMULAS["identity"], [latest["period"]] * 2)
        if dataset == "financial_income":
            prior = next((row for row in rows if row["period"] == str(int(latest["period"][:4]) - 1) + latest["period"][4:]), None)
            for name in ("revenue", "net_income_parent"):
                current, ceid = source(latest, name)
                if prior:
                    previous, peid = source(prior, name)
                    if current is not None and previous is not None and previous > 0:
                        add(name + "_yoy", current / previous - 1, "ratio", [peid, ceid], FORMULAS["yoy"], [prior["period"], latest["period"]])
            if "absolute_profit_change" in request["hypotheses"] and prior:
                current, ceid = source(latest, "net_income_parent")
                previous, peid = source(prior, "net_income_parent")
                if (current is not None and previous is not None
                        and metric(prior, "net_income_parent")["unit"] == metric(latest, "net_income_parent")["unit"] == "CNY"
                        and prior.get("basis", BASES[dataset]) == latest.get("basis", BASES[dataset])):
                    add("financial_income.absolute_profit_change", current - previous, "CNY", [peid, ceid], FORMULAS["absolute_profit_change"], [prior["period"], latest["period"]])
    anchor, event_row = expected_anchor(selected, bindings, request)
    pair = None
    if stock and anchor["status"] == "verified":
        if anchor["precision"] == "timestamp":
            release = aware(anchor["disclosed_at"])
            before = [row for row in selected["market_daily"] if datetime.combine(date.fromisoformat(row["period"]), time(15), CN) < release]
            after = [row for row in selected["market_daily"] if datetime.combine(date.fromisoformat(row["period"]), time(15), CN) >= release]
        else:
            before = [row for row in selected["market_daily"] if row["period"] < anchor["release_date"]]
            after = [row for row in selected["market_daily"] if row["period"] >= anchor["boundary_date"]]
        if before and after:
            pair = before[-1], after[-1]
            first, aeid = source(pair[0], "close")
            last, beid = source(pair[1], "close")
            if first is not None and last is not None and first > 0 and last > 0:
                add("event_observed_price_change", last / first - 1, "ratio", [aeid, beid], FORMULAS["event_observed_price_change"], [row["period"] for row in pair], [anchor["available_at"]])
    return facts, evidence, anchor, event_row, pair


def expected_hypotheses(facts, evidence, selected, request, anchor):
    """Reported status support differs from accepting a hypothesis or task success."""
    expected = {}
    for hid in request["hypotheses"]:
        if hid not in CATALOGUE:
            raise ValueError("unknown preregistered hypothesis")
        title, required, rule = CATALOGUE[hid]
        status, reason, names, counter = "insufficient", "required_evidence_missing", [], []
        if hid == "mechanical_adjustment":
            required_names = ["observed_price_change", "factor_adjusted_price_change"]
            if all(name in facts for name in required_names):
                names = required_names
                fids = facts[required_names[1]]["inputs"][2:]
                differs = number(evidence[fids[0]]["value"]) != number(evidence[fids[-1]]["value"])
                status, reason = ("supported", "factor_changes_endpoint_result") if differs else ("unsupported", "no_endpoint_adjustment_difference_observed")
                if not differs:
                    counter = names[:]
        elif hid == "market_direction":
            required_names = ["observed_price_change", "benchmark_price_change"]
            if all(name in facts for name in required_names):
                names = required_names
                a, b = (F(*facts[name]["fraction"]) for name in names)
                if a == 0 or b == 0:
                    reason = "zero_change_has_no_direction"
                elif a * b > 0:
                    status, reason = "supported", "same_direction_observed"
                else:
                    status, reason, counter = "unsupported", "opposite_direction_observed", names[:]
        elif hid == "financial_deterioration":
            required_names = ["revenue_yoy", "net_income_parent_yoy"]
            if all(name in facts for name in required_names):
                names = required_names
                declining = [F(*facts[name]["fraction"]) < 0 for name in names]
                counter = [name for name, declines in zip(names, declining) if not declines]
                status, reason = (("supported", "both_same_period_yoy_decline") if all(declining) else
                                  ("conflicted", "mixed_financial_directions") if any(declining) else
                                  ("unsupported", "neither_metric_declines"))
        elif hid == "cashflow_divergence":
            required_names = ["financial_income.net_income_parent", "financial_cashflow.operating_cashflow"]
            if all(name in facts for name in required_names):
                names = required_names
                if facts[names[0]]["window"] != facts[names[1]]["window"]:
                    reason = "financial_period_mismatch"
                else:
                    a, b = (F(*facts[name]["fraction"]) for name in names)
                    status, reason = (("supported", "positive_profit_negative_operating_cashflow") if a > 0 and b < 0 else
                                      ("unsupported", "divergence_condition_not_observed"))
                    if status == "unsupported":
                        counter = names[:]
        elif hid == "event_chronology":
            if "event_observed_price_change" in facts:
                status, reason, names = "supported", "verified_anchor_and_observed_pre_post_closes", ["event_observed_price_change"]
            else:
                reason = anchor.get("reason", "event_pre_post_closes_missing")
        elif hid == "absolute_profit_change":
            name = "financial_income.absolute_profit_change"
            if name in facts:
                names = [name]
                amount = F(*facts[name]["fraction"])
                if amount > 0:
                    status, reason = "supported", "same_period_profit_amount_increased"
                else:
                    status, reason, counter = "unsupported", ("same_period_profit_amount_decreased" if amount < 0 else "same_period_profit_amount_unchanged"), names[:]
            else:
                rows = selected.get("financial_income", [])
                if not rows:
                    reason = "no_visible_financial_period"
                else:
                    current = rows[-1]
                    prior = next((r for r in rows if r["period"] == str(int(current["period"][:4]) - 1) + current["period"][4:]), None)
                    if prior is None:
                        reason = "prior_year_same_period_not_visible"
                    elif any(metric(r, "net_income_parent")["value"] is None for r in (prior, current)):
                        reason = "net_income_parent_missing"
                    else:
                        reason = "financial_unit_or_basis_mismatch"
        expected[hid] = {"id": hid, "title": title, "status": status, "reason": reason,
            "required_evidence": required, "test_rule": rule, "claim_names": names,
            "counterevidence_claim_names": counter, "anchor_record_id": anchor.get("record_id") if hid == "event_chronology" else None,
            "conclusion_strength": "descriptive_test_only", "causal_claim": False, "coverage": "not_verified"}
    return expected


NUMBER = re.compile(r"(?<![\w.])\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|(?<![\w.])\(?-?\d+\.\d+\)?")


def compact(value):
    return re.sub(r"\s+", "", value)


def money(line):
    line = re.sub(r"(?<=\d)\s+(?=,)", "", line)
    line = re.sub(r"(?<!\d)(-?\d)\s+(\d{2},)", r"\1\2", line)
    return [F(token.replace(",", "").replace("(", "-").replace(")", "")) for token in NUMBER.findall(line)]


class OfficialPDF:
    """Locators locate printed cells; no locator numeric value/verdict is used."""
    def __init__(self, reader):
        self.reader = reader
        self.readers, self.pages, self.locators, self.results = {}, {}, {}, {}
        for rel in (".artifacts/p17_20261001/formal/financial_values/manual/candidates.json",
                    ".artifacts/p17_20261001/formal/financial_values/bse-qualified-reviewed/candidates.json"):
            if (reader.root / rel).is_file():
                for period in reader.json(rel)["periods"]:
                    for field, ref in period["values"].items():
                        self.locators[(period["code"], period["exchange"], period["period"], field)] = {
                            key: ref[key] for key in ("source", "pdf_page", "header_page")}
        rel = ".artifacts/phase3/fullscope-20261003/cashflow-reference/review.json"
        if (reader.root / rel).is_file():
            for ref in reader.json(rel)["references"]:
                self.locators[(ref["code"], ref["exchange"], ref["period"], ref["field"])] = {
                    key: ref[key] for key in ("source", "pdf_page", "header_page")}

    def text(self, path, page, expected=None):
        import pdfplumber
        target = self.reader.path(path)
        self.reader.bytes(target, expected)
        key = target.as_posix(), page
        if key not in self.pages:
            if target not in self.readers:
                self.readers[target] = pdfplumber.open(target)
            self.pages[key] = self.readers[target].pages[page - 1].extract_text(x_tolerance=3) or ""
        return self.pages[key]

    def close(self):
        for document in self.readers.values():
            document.close()

    def qualified_cell(self, envelope, ev, raw, paths):
        version = envelope["version"]
        ref = version["field_evidence"].get(ev["metric"])
        if ref is None:
            return {"qualified_missing_is_explicit_null": ev["raw_value"] is None and ev["value"] is None}, None
        path = paths[envelope["pdf_sha256"]]
        page = self.text(path, ref["pdf_page"], envelope["pdf_sha256"])
        lines = page.splitlines()
        if version["label"] == "original":
            label = {"revenue": "营业收入", "net_income_parent": "归属于上市公司股东的净利润"}[ev["metric"]]
            annual = page.split("近三年主要会计数据和财务指标", 1)[-1].split("分季度主要会计数据", 1)[0]
            matched = [line for line in annual.splitlines() if compact(line).startswith(label)]
            if len(matched) != 1:
                raise ValueError("qualified original printed field not unique")
            row = matched[0]
            values = money(row)
            context = {"official_period": "2024年" in compact(page), "official_unit_yuan": "元" in page,
                "official_company": "重庆智飞生物制品股份有限公司" in compact(page),
                "official_current_column": len(values) >= 3 and all(year in compact(annual) for year in ("2024年", "2023年", "2022年"))}
            amount = values[0]
        else:
            table_header = self.text(path, 8, envelope["pdf_sha256"])
            if ev["metric"] == "revenue":
                body = page.split("对合并利润表的影响", 1)[1]
                matched = [line for line in body.splitlines() if compact(line).startswith("营业收入")]
                if len(matched) != 1:
                    raise ValueError("qualified correction revenue row not unique")
                row = matched[0]
            else:
                bodylines = page.split("对母公司利润表的影响", 1)[0].splitlines()
                matches = [pos for pos, line in enumerate(bodylines) if compact(line).startswith("归属于母公司所有者的净")]
                if len(matches) != 1:
                    raise ValueError("qualified correction parent-profit row not unique")
                pos = matches[0]
                row = bodylines[pos]
                if len(money(row)) < 3:
                    row += " | " + bodylines[pos + 1]
            values = money(row)
            amount = values[2]
            context = {"official_period": "2024年年度财务报表" in compact(table_header),
                "official_consolidated_section": "对合并利润表的影响" in compact(table_header),
                "official_adjusted_column": "调整后金额" in compact(table_header) and len(values) >= 3,
                "official_adjustment_arithmetic": values[0] + values[1] == values[2]}
            qualification = raw.get(envelope["qualification_sha256"], {})
            original = next((v for v in qualification.get("versions", []) if v["label"] == "original"), None)
            if original is None or original["pdf"]["sha256"] not in paths:
                raise ValueError("correction CNY unit requires original disclosed-column bridge")
            original_page = self.text(paths[original["pdf"]["sha256"]], original["field_evidence"][ev["metric"]]["pdf_page"], original["pdf"]["sha256"])
            annual = original_page.split("近三年主要会计数据和财务指标", 1)[-1].split("分季度主要会计数据", 1)[0]
            label = "营业收入" if ev["metric"] == "revenue" else "归属于上市公司股东的净利润"
            originals = [line for line in annual.splitlines() if compact(line).startswith(label)]
            context["correction_unit_inherited_from_original_cny"] = "元" in original_page and len(originals) == 1
            context["correction_disclosed_column_matches_original"] = len(originals) == 1 and money(originals[0])[0] == values[0]
        cover = self.text(path, 1, envelope["pdf_sha256"])
        context["official_company_security_identity"] = "重庆智飞生物制品股份有限公司" in compact(cover) and "300122" in compact(cover)
        context["official_printed_value_matches"] = ev["raw_value"] is not None and number(ev["raw_value"]) == amount
        return context, {"path": path, "sha256": envelope["pdf_sha256"], "pdf_page": ref["pdf_page"],
            "column": "first current-year" if version["label"] == "original" else "third adjusted",
            "row_excerpt": row, "fraction": fraction_json(amount)}

    def bridge(self, key, ref):
        """Four source-revision cells with printed before/after restatement bridge.

        An adjusted later comparative column alone cannot certify old source values.
        These particular prior-period before columns are independently cross-checked
        against their adjustment table, period, unit and arithmetic context.
        """
        symbol, exchange, period, field = key
        if period != "2024-06-30" or field not in {"revenue", "net_income_parent"} or symbol not in {"688184", "920489"}:
            return None
        source = ref["source"]
        path, sha = source["path"], source["sha256"]
        if symbol == "688184":
            summary = self.text(path, 8, sha)
            explanation = self.text(path, 177, sha)
            reporting_interval = self.text(path, 5, sha)
            header = self.text(path, 178, sha)
            checks = {"bridge_report_current_and_prior_period": "2025" in compact(summary) and "2024" in compact(summary),
                "bridge_current_reporting_interval": "2025年1月1日至2025年6月30日" in compact(reporting_interval),
                "bridge_prior_half_year_explicit": "2024年半年度财务报表" in compact(explanation),
                "bridge_restatement_explicit": "追溯重述法" in compact(explanation),
                "bridge_consolidated": "对合并利润表的影响" in compact(header),
                "bridge_before_delta_after_header": all(label in compact(header) for label in ("调整前金额", "调整金额", "调整后金额"))}
            label = "营业收入" if field == "revenue" else "归属于上市公司股东的净利润"
            summaries = [line for line in summary.splitlines() if compact(line).startswith(label)]
            if len(summaries) != 1 or len(money(summaries[0])) < 3:
                raise ValueError("printed summary restatement columns not unique")
            summary_values = money(summaries[0])
            page = 178 if field == "revenue" else 179
            text = self.text(path, page, sha)
            body = text.split("对合并利润表的影响", 1)[-1].split("对母公司利润表的影响", 1)[0]
            label = "营业收入" if field == "revenue" else "归属于母公司所有者的净利润"
            lines = body.splitlines()
            matches = [pos for pos, line in enumerate(lines) if compact(line).startswith(label)]
            if len(matches) != 1:
                raise ValueError("printed consolidated restatement row not unique")
            pos, row = matches[0], lines[matches[0]]
            if len(money(row)) < 3 and pos + 1 < len(lines):
                row += " | " + lines[pos + 1]
            values = money(row)
            checks["bridge_before_delta_equals_after"] = len(values) == 3 and values[0] + values[1] == values[2]
            checks["bridge_summary_matches_both_ends"] = len(values) == 3 and summary_values[2] == values[0] and summary_values[1] == values[2]
            return values[0], F(1, 200), checks, {"pdf_page": page, "header_page": 178, "summary_page": 8,
                "column": "before adjustment", "row_excerpt": row, "summary_row_excerpt": summaries[0], "bridge_values": [fraction_json(v) for v in values]}
        header = self.text(path, 9, sha)
        table = self.text(path, 10, sha)
        explanation = self.text(path, 11, sha)
        summary = self.text(path, 8, sha)
        cover = self.text(path, 1, sha)
        reporting_interval = self.text(path, 5, sha)
        checks = {"bridge_current_report_2025_h1": "2025" in compact(cover) and "半年度" in compact(cover),
            "bridge_current_reporting_interval": "2025年1月1日至2025年6月30日" in compact(reporting_interval),
            "bridge_prior_period_header": "上年期末（上年同期）" in compact(header),
            "bridge_before_after_header": "调整重述前" in compact(header) and "调整重述后" in compact(header),
            "bridge_unit_yuan": "单位：元" in compact(header),
            "bridge_same_control_restatement": "同一控制" in compact(explanation) and "重述" in compact(explanation)}
        lines = table.splitlines()
        label = "营业收入" if field == "revenue" else "归属于母公司所有"
        matches = [pos for pos, line in enumerate(lines) if compact(line).startswith(label)]
        if len(matches) != 1:
            raise ValueError("printed prior-period before/after row not unique")
        pos, row = matches[0], lines[matches[0]]
        if len(money(row)) < 2:
            row += " | " + lines[pos + 1]
        values = money(row)
        summary_label = "营业收入" if field == "revenue" else "归属于上市公司股东的净利润"
        summaries = [line for line in summary.splitlines() if compact(line).startswith(summary_label)]
        if not summaries and field == "net_income_parent":
            summaries = [line for line in summary.splitlines() if "归属于" in compact(line) and "净利润" in compact(line)]
        summary_values = money(summaries[0]) if len(summaries) == 1 else []
        checks["bridge_physical_two_columns"] = len(values) == 2
        checks["bridge_adjusted_equals_summary_prior"] = len(summary_values) >= 2 and summary_values[1] == values[1]
        return values[0], F(1, 200), checks, {"pdf_page": 10, "header_page": 9, "summary_page": 8,
            "explanation_page": 11, "column": "before restatement", "row_excerpt": row,
            "summary_row_excerpt": summaries[0] if summaries else None, "bridge_values": [fraction_json(v) for v in values]}

    def check(self, ev, request):
        key = request["symbol"], request["exchange"], ev["period"], ev["metric"]
        cache_key = key + (ev["revision_id"], str(ev["value"]))
        if cache_key in self.results:
            return self.results[cache_key]
        result = {"security": key[0], "exchange": key[1], "period": key[2], "metric": key[3],
            "source_revision": ev["revision_id"], "assessable": False, "supported": None,
            "reason": "no_independent_official_security_period_field_locator"}
        lookup, column = key, 0
        if lookup not in self.locators and key[2] == "2024-06-30":
            lookup, column = (key[0], key[1], "2025-06-30", key[3]), 1
        ref = self.locators.get(lookup)
        if ref is not None and ev["value"] is not None:
            source = ref["source"]
            result["source_ref"] = {k: source[k] for k in ("path", "sha256", "source_url")}
            result["source_ref"].update(pdf_page=ref["pdf_page"], header_page=ref["header_page"])
            try:
                bridge = self.bridge(key, ref) if column == 1 else None
                if bridge is not None:
                    value, tolerance, checks, detail = bridge
                    if not all(checks.values()):
                        raise ValueError("printed source-version bridge context incomplete: " + ",".join(k for k, v in checks.items() if not v))
                    result.update(detail, source_version_basis="printed_before_restatement_column_and_independent_adjustment_context", checks=checks)
                else:
                    header = self.text(source["path"], ref["header_page"], source["sha256"])
                    page = self.text(source["path"], ref["pdf_page"], source["sha256"])
                    h = compact(header)
                    if lookup[2][:4] not in h or column == 1 and key[2][:4] not in h:
                        raise ValueError("official period columns not independently identified")
                    if "合并" not in h and "本集团" not in h:
                        raise ValueError("official consolidated/group context not identified")
                    scale = F(1000000) if "百万元" in h else F(1000) if "千元" in h else F(1) if "元" in h else None
                    if scale is None:
                        raise ValueError("official unit not identified")
                    lines, candidates = page.splitlines(), []
                    for pos, line in enumerate(lines):
                        label = compact(line)
                        joined = label + compact("".join(lines[pos + 1:pos + 4]))
                        if ev["metric"] == "revenue":
                            match = "营业收入" in label and "营业总收入" not in label
                        elif ev["metric"] == "total_revenue":
                            match = "营业总收入" in label
                        elif ev["metric"] == "net_income_parent":
                            match = "归属于" in label and any(k in label for k in ("母公司", "上市公司", "本行股东")) and ("净利" in joined or "净亏" in joined)
                        elif ev["metric"] == "operating_cashflow":
                            if "经营活动" in label and "现金流" in label and "净额" not in joined and pos >= len(lines) - 3:
                                joined += compact("".join(self.text(source["path"], ref["pdf_page"] + 1, source["sha256"]).splitlines()[:8]))
                            match = "经营活动" in label and ("产生" in label or "使用" in label) and "净额" in joined
                        else:
                            match = False
                        if match:
                            if len(money(line)) < 2 and pos + 1 < len(lines) and len(money(lines[pos + 1])) >= 2:
                                line += " | " + lines[pos + 1]
                            if len(money(line)) >= 2:
                                candidates.append((line, money(line)))
                    if not candidates and ev["metric"] == "operating_cashflow" and ref["pdf_page"] > ref["header_page"]:
                        prior = self.text(source["path"], ref["pdf_page"] - 1, source["sha256"]).splitlines()
                        labels = [line for line in prior if "经营活动" in compact(line) and ("产生" in compact(line) or "使用" in compact(line))]
                        rows = [(line, money(line)) for line in lines if len(money(line)) >= 2]
                        if labels and rows and "净额" in compact(rows[0][0]):
                            candidates = [(labels[-1] + " | " + rows[0][0], rows[0][1])]
                    if len(candidates) != 1:
                        raise ValueError("official label row not unique/complete")
                    row, values = candidates[0]
                    value = values[column] * scale
                    tokens = NUMBER.findall(row)
                    decimals = len(tokens[column].replace(",", "").strip("()").split(".")[1]) if "." in tokens[column] else 0
                    tolerance = scale * F(1, 2 * 10 ** decimals)
                    result.update(row_excerpt=row, column_index=column, unit_multiplier=str(scale))
                supported = abs(number(ev["value"]) - value) <= tolerance
                result.update(assessable=True, supported=supported,
                    reason="official_printed_consolidated_column_independently_reextracted",
                    official_fraction=fraction_json(value), tolerance_fraction=fraction_json(tolerance), provider_value=ev["value"])
                if column == 1 and bridge is None:
                    # Exact numeric agreement does not establish original source revision.
                    result.update(assessable=False, supported=None,
                        observed_numeric_agreement=supported,
                        reason="original_prior_period_source_revision_not_independently_bridged_to_later_comparative_column")
            except (ValueError, IndexError, KeyError, AssertionError, ImportError) as exc:
                result.update(assessable=False, supported=None, reason="not_assessable: " + str(exc))
        self.results[cache_key] = result
        return result


def qualification_checks(record, raw, paths, pdf):
    checks, refs = {}, []
    envelope = raw.get(record["artifact_id"], {})
    checks["qualified_source_envelope"] = envelope.get("schema") == "qualified_cninfo_income_v1"
    if not checks["qualified_source_envelope"]:
        return checks, refs
    version = envelope["version"]
    qualification = raw.get(envelope["qualification_sha256"], {})
    index = raw.get(envelope["index_sha256"], {})
    rows = [row for row in index.get("rows", []) if row.get("announcementId") == version["announcement_id"]]
    checks["qualified_exact_index_identity"] = len(rows) == 1
    checks["qualified_manifest_version_present"] = version in qualification.get("versions", [])
    checks["qualified_security_period"] = (version["symbol"] in identity(record)
        and version["exchange"] in identity(record) and version["period"] == record["period"])
    checks["qualified_source_url"] = version["pdf"]["url"] == record["source_url"]
    checks["qualified_source_revision"] = digest({"qualification": envelope["qualification_sha256"], "version": version}) == record["revision_id"]
    checks["qualified_artifact_closure"] = {envelope["qualification_sha256"], envelope["index_sha256"], envelope["pdf_sha256"]} <= set(artifacts(record))
    names = sorted(v["label"] for v in qualification.get("versions", []))
    allowed = [list(group) for size in range(1, len(names) + 1) for group in itertools.combinations(names, size) if version["label"] in group]
    checks["qualified_provider_version"] = record["provider_version"] in {"qualified-date-1:" + digest({"manifest": envelope["qualification_sha256"], "labels": labels}) for labels in allowed}
    checks["qualified_capture_binding"] = envelope["provider_call_id"] == record["provider_call_id"] and aware(envelope["retrieved_at"]) == aware(record["retrieved_at"])
    if rows:
        row = rows[0]
        release = datetime.fromtimestamp(row["announcementTime"] / 1000, CN).date()
        checks["qualified_official_index_code"] = row["secCode"] == version["symbol"]
        checks["qualified_official_index_url"] = row["adjunctUrl"] == version["pdf"]["url"].removeprefix("https://static.cninfo.com.cn/")
        checks["qualified_date_not_intraday_timestamp"] = record.get("published_at") is None and release.isoformat() == record.get("release_date") == version["release_date"]
        boundary = datetime.combine(release + timedelta(days=1), time(), CN)
        checks["qualified_next_day_availability"] = aware(record["available_at"]) == boundary and record["availability_basis"] == "verified_release_date"
        checks["qualified_exchange_index"] = index.get("form", {}).get("column") == {"SZSE": "szse", "SSE": "sse", "BSE": "bse"}[version["exchange"]]
        refs.append({"path": paths[envelope["index_sha256"]], "sha256": envelope["index_sha256"],
            "announcement_id": row["announcementId"], "security": row["secCode"], "adjunct_url": row["adjunctUrl"],
            "raw_announcement_time": row["announcementTime"], "release_date_only": release.isoformat(),
            "precision": "date_conservative_next_day"})
    cover = pdf.text(paths[envelope["pdf_sha256"]], 1, envelope["pdf_sha256"])
    checks["qualified_pdf_company_code"] = "重庆智飞生物制品股份有限公司" in compact(cover) and version["symbol"] in compact(cover)
    checks["qualified_pdf_declared_document_type"] = ("2024年年度报告摘要" in compact(cover) if version["label"] == "original" else "关于前期会计差错涉及追溯调整与年度报告更正的公告" in compact(cover))
    refs.append({"path": paths[envelope["pdf_sha256"]], "sha256": envelope["pdf_sha256"], "pdf_page": 1,
        "identity_excerpt": "company/security/document identity on first official PDF page; meeting date is not disclosure time"})
    return checks, refs


def raw_source_checks(ev, record, request, raw, paths, pdf):
    """Validate original provider fields/version, with official accuracy separate."""
    checks, refs = {}, [{"artifact_id": aid, "path": paths.get(aid), "sha256": aid} for aid in ev["artifact_ids"]]
    checks["content_addressed_attachments_available"] = all(aid in paths for aid in ev["artifact_ids"])
    if record["provider"] == "tushare":
        archive = raw.get(record["artifact_id"], {})
        checks["original_response_api"] = archive.get("api_name") == APIS.get(record["dataset"])
        checks["original_response_business_success"] = archive.get("business_code", 0) == 0
        rows = [row if isinstance(row, dict) else dict(zip(archive.get("fields", []), row)) for row in archive.get("items", [])]
        matches = [(index, row) for index, row in enumerate(rows) if digest(row) == ev["revision_id"]]
        checks["exact_original_source_revision"] = len(matches) == 1
        if matches:
            index, row = matches[0]
            code = request["benchmark"] if record["dataset"] == "index_daily" else request["symbol"] + "." + {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[request["exchange"]]
            field = RAW_FIELDS.get(ev["metric"], ev["metric"])
            checks["original_security"] = row.get("ts_code") == code
            checks["original_trade_or_report_period"] = iso8(row.get("trade_date", row.get("end_date", ""))) == ev["period"]
            checks["original_field_present"] = field in row
            checks["original_field_value"] = field in row and equivalent(row[field], ev["raw_value"])
            checks["source_normalization"] = equivalent(ev["raw_value"], ev["value"])
            expected_unit = "point" if record["dataset"] == "index_daily" else "CNY/share" if ev["metric"] == "close" else "ratio" if ev["metric"] == "factor" else "CNY"
            checks["original_and_normalized_unit"] = ev["raw_unit"] == ev["unit"] == expected_unit
            checks["consolidated_cumulative_report"] = record["dataset"] not in {"financial_income", "financial_balance", "financial_cashflow"} or str(row.get("report_type")) == "1"
            checks["source_basis"] = ev["basis"] == BASES[record["dataset"]]
            checks["provider_endpoint"] = ev["source_url"] == "https://api.tushare.pro"
            versions = {"1", "2", "2-archive-projection-1"} if record["dataset"] in {"market_daily", "financial_income"} else {"p18-1"}
            checks["provider_version_contract"] = ev["provider_version"] in versions
            checks["capture_not_historical_release"] = ev["availability_basis"] == "observed_at" and aware(ev["available_at"]) == aware(ev["retrieved_at"])
            if archive.get("finished_at"):
                checks["original_archive_capture_time"] = aware(archive["finished_at"]) == aware(ev["retrieved_at"])
            refs[0].update(raw_field=field, row_index=index, security=code, period=ev["period"])
    elif record["provider"] == "cninfo":
        qc, qr = qualification_checks(record, raw, paths, pdf)
        checks.update(qc)
        refs.extend(qr)
        envelope = raw.get(record["artifact_id"], {})
        if checks.get("qualified_source_envelope"):
            value = envelope["version"]["values_cny"][ev["metric"]]
            checks["qualified_envelope_raw_value"] = equivalent(value, ev["raw_value"])
            checks["qualified_normalization"] = equivalent(ev["raw_value"], ev["value"])
            checks["qualified_cny_unit"] = ev["raw_unit"] == ev["unit"] == "CNY"
            try:
                pc, pr = pdf.qualified_cell(envelope, ev, raw, paths)
                checks.update(pc)
                if pr:
                    refs.append(pr)
            except (ValueError, IndexError, KeyError, AssertionError) as exc:
                checks["qualified_printed_cell_assessable"] = False
                refs.append({"not_assessable": str(exc)})
    else:
        checks["known_original_field_contract"] = False
    return checks, refs


def empty_dataset_checks(case, frozen, binding, reader):
    """A successful exact-request raw empty response, not absence of members."""
    dataset = binding["dataset"]
    proof = frozen.get("binding_metadata", {}).get(dataset, {}).get("empty_dataset_capture")
    checks = {"original_empty_response_proof_present_" + dataset: isinstance(proof, dict)}
    if not isinstance(proof, dict):
        return checks
    owner = case["source_scopes"][dataset]
    subject = "CN:equity:" + case["request"]["exchange"] + ":" + case["request"]["symbol"]
    expected_identity = {"security_id": subject, "dataset": dataset, "start": binding["start"],
                         "end": binding["end"], "basis": BASES[dataset]}
    checks["exact_empty_authorized_scope_snapshot_" + dataset] = (proof.get("kind") == "tushare_requested_response_v2_empty/v1"
        and proof.get("source_authorized") is True and proof.get("source_scope") == owner
        and proof.get("bound_snapshot") == binding["snapshot"] and proof.get("request_identity") == expected_identity)
    aid = proof.get("archive_artifact_id")
    locators = [path for path, sha in case["source_hashes"].items() if sha == aid]
    checks["empty_response_original_hash_locator_" + dataset] = isinstance(aid, str) and HEX.fullmatch(aid) is not None and bool(locators)
    if not locators:
        return checks
    archive = reader.json(locators[0], aid)
    checks["empty_response_proof_equals_original_bytes_" + dataset] = proof.get("archive") == archive
    checks["empty_response_exact_api_schema_" + dataset] = (binding["provider"] == "tushare"
        and archive.get("archive_schema") == "tushare_requested_response_v2"
        and archive.get("api_name") == APIS.get(dataset))
    checks["empty_response_success_not_failure_" + dataset] = type(archive.get("business_code")) is int and archive["business_code"] == 0
    checks["empty_response_zero_original_rows_" + dataset] = (archive.get("items") == []
        and type(archive.get("response_row_count")) is int and archive["response_row_count"] == 0
        and type(archive.get("selected_row_count")) is int and archive["selected_row_count"] == 0)
    code = case["request"]["symbol"] + "." + {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[case["request"]["exchange"]]
    checks["empty_response_exact_security_window_" + dataset] = archive.get("params") == {
        "ts_code": code, "start_date": binding["start"].replace("-", ""), "end_date": binding["end"].replace("-", "")}
    checks["empty_response_field_schema_" + dataset] = (archive.get("fields") == archive.get("response_fields")
        and {"ts_code", "trade_date", "close"} <= set(archive.get("fields", [])))
    try:
        checks["empty_response_capture_before_cutoff_" + dataset] = (aware(archive["started_at"]) <= aware(archive["finished_at"])
            <= aware(case["request"]["as_of"]))
    except (ValueError, TypeError, KeyError):
        checks["empty_response_capture_before_cutoff_" + dataset] = False
    return checks


def unit(unit_id, unit_type, checks, *, assessable=True, hallucination=False, **kwargs):
    failures = [name for name, valid in checks.items() if not valid]
    return {"unit_id": unit_id, "unit_type": unit_type, "assessable": assessable,
        "supported": not failures if assessable else None,
        "hallucination": hallucination if failures and assessable else False if assessable else None,
        "checks": checks, "failure_category": failures,
        "reasoning_summary": "Independent frozen-source checks agree." if not failures else ", ".join(failures), **kwargs}


def review_case(case, frozen, report, reader, pdf, agent):
    selected, bindings, input_checks = select_inputs(case, frozen)
    expected, evidence, anchor, event_record, pair = expected_facts(selected, bindings, case["request"])
    expected_h = expected_hypotheses(expected, evidence, selected, case["request"], anchor)
    paths = frozen.get("artifact_paths", {})
    raw = {}
    for aid, path in paths.items():
        payload = reader.bytes(path, aid)
        if not payload.startswith(b"%PDF"):
            try:
                raw[aid] = json.loads(payload, object_pairs_hook=unique_object)
            except (UnicodeDecodeError, ValueError):
                pass
    for binding in case["request"]["bindings"]:
        owner = case["source_scopes"][binding["dataset"]]
        snapshot = next((item for item in frozen["snapshots"] if item["owner_scope"] == owner and item["snapshot"] == binding["snapshot"]), None)
        if snapshot is not None and not any(row["dataset"] == binding["dataset"] and row["provider"] == binding["provider"] for row in snapshot["records"]):
            input_checks.update(empty_dataset_checks(case, frozen, binding, reader))
    records = {rid(row): row for rows in selected.values() for row in rows}
    reported_ev = report.get("evidence", {})
    ev_units = []
    for eid in sorted(set(evidence) | set(reported_ev)):
        ev, actual = evidence.get(eid), reported_ev.get(eid)
        checks, refs = {}, []
        if ev is None:
            checks["evidence_belongs_to_complete_expected_inputs"] = False
        else:
            checks["expected_evidence_present"] = actual is not None
            if actual is not None:
                checks["exact_source_evidence_fields"] = {k: v for k, v in actual.items() if k != "tool_call_id"} == ev
            source_checks, refs = raw_source_checks(ev, records[ev["record_id"]], case["request"], raw, paths, pdf)
            checks.update(source_checks)
        ev_units.append(unit("evidence/" + eid, "source_evidence", checks, evidence_id=eid,
                             source_refs=refs, expected_evidence=ev, reported_evidence=actual))
    ev_support = {u["evidence_id"]: u["supported"] is True for u in ev_units}
    all_input_checks = all(input_checks.values())
    facts = report.get("facts", [])
    by_name = {}
    for fact in facts:
        by_name.setdefault(fact.get("name"), []).append(fact)
    units = []
    for name in sorted(set(expected) | set(by_name)):
        oracle = expected.get(name)
        actuals = by_name.get(name, [])
        if not actuals:
            # Absence is a completion defect, not an emitted claim occurrence.
            continue
        for fact in actuals:
            checks = {"authorized_full_snapshot_checks": all_input_checks,
                      "claim_in_complete_independent_expected_set": oracle is not None,
                      "claim_name_unique": len(actuals) == 1,
                      "claim_content_addressed_id": fact.get("id") == digest({k: v for k, v in fact.items() if k != "id"})}
            error, tolerance = None, None
            if oracle:
                exact = F(*oracle["fraction"])
                tolerance = F(0) if name == "financial_income.absolute_profit_change" or oracle["formula"] == FORMULAS["identity"] else max(F(1, 10 ** 28), abs(exact) * F(1, 10 ** 28))
                try:
                    error = abs(number(fact["value"]) - exact)
                    checks["fraction_numeric_value"] = error <= tolerance
                except (ValueError, TypeError, ZeroDivisionError):
                    checks["fraction_numeric_value"] = False
                for key in ("unit", "inputs", "formula", "window"):
                    checks["exact_" + key] = fact.get(key) == oracle[key]
                try:
                    checks["exact_derived_available_at"] = aware(fact["available_at"]) == aware(oracle["available_at"]) <= aware(case["request"]["as_of"])
                except (ValueError, KeyError, TypeError):
                    checks["exact_derived_available_at"] = False
                checks["all_original_source_inputs_supported"] = all(ev_support.get(eid, False) for eid in oracle["inputs"])
            refs = [ref for eid in fact.get("inputs", []) for evu in ev_units if evu["evidence_id"] == eid for ref in evu["source_refs"]]
            units.append(unit("fact/" + str(fact.get("id")), "numeric_claim", checks,
                hallucination=oracle is None or any(checks.get(k) is False for k in ("fraction_numeric_value", "exact_unit", "exact_formula", "exact_window", "exact_inputs")),
                claim_id=fact.get("id"), name=name, evidence_refs=fact.get("inputs", []), source_refs=refs,
                oracle=oracle, absolute_error_fraction=fraction_json(error), tolerance_fraction=fraction_json(tolerance)))
    fact_support = {u["name"]: u["supported"] is True for u in units}
    fact_ids = {name: rows[0]["id"] for name, rows in by_name.items() if len(rows) == 1}
    hs = {h.get("id"): h for h in report.get("hypotheses", [])}
    for hid in sorted(set(expected_h) | set(hs)):
        oracle, actual = expected_h.get(hid), hs.get(hid)
        checks = {"requested_hypothesis_present": oracle is not None and actual is not None,
                  "hypothesis_unique": sum(h.get("id") == hid for h in report.get("hypotheses", [])) == 1,
                  "authorized_full_snapshot_checks": all_input_checks}
        if oracle is not None and actual is not None:
            for key in ("title", "status", "reason", "required_evidence", "test_rule", "anchor_record_id", "conclusion_strength", "causal_claim", "coverage"):
                checks["exact_" + key] = actual.get(key) == oracle[key]
            checks["complete_claim_references"] = actual.get("claim_ids") == [fact_ids.get(name) for name in oracle["claim_names"]]
            checks["complete_counterevidence_references"] = actual.get("counterevidence_claim_ids") == [fact_ids.get(name) for name in oracle["counterevidence_claim_names"]]
            checks["all_claims_independently_supported"] = all(fact_support.get(name, False) for name in oracle["claim_names"])
            declaration = case["expected_behavior"]["hypotheses"][hid]
            checks["preregistered_permitted_status"] = oracle["status"] in declaration.get("permitted_statuses", [declaration.get("status")])
        refs = sorted({aid for rows in selected.values() for row in rows for aid in artifacts(row)})
        units.append(unit("hypothesis/" + hid, "hypothesis_state", checks,
            hallucination=actual is not None and (oracle is None or actual.get("causal_claim") is True or checks.get("exact_status") is False or checks.get("exact_reason") is False),
            hypothesis_id=hid, expected_hypothesis=oracle, reported_hypothesis=actual,
            evidence_refs=[] if actual is None else actual.get("claim_ids", []), source_refs=[{"path": paths[aid], "sha256": aid} for aid in refs if aid in paths]))
    if "event_chronology" in case["request"]["hypotheses"]:
        declared = case["event"]
        checks = {"authorized_full_snapshot_checks": all_input_checks,
            "exact_anchor_fields": report.get("event_anchor") == anchor,
            "qualified_anchor_visible": anchor["status"] == "verified",
            "explicit_event_identity": event_record is not None and rid(event_record) == declared["record_id"] == case["request"]["event_record_id"],
            "explicit_event_source": event_record is not None and declared["source"] == {k: event_record.get(k) for k in ("provider", "source_url", "source_key")},
            "explicit_event_version": event_record is not None and declared["version"] == {k: event_record.get(k) for k in ("provider_version", "revision_id")},
            "explicit_event_precision": declared["release_precision"] == anchor.get("precision"),
            "actual_pre_post_closes": pair is not None,
            "event_numeric_claim_supported": fact_support.get("event_observed_price_change", False)}
        refs = []
        if event_record is not None:
            qc, refs = qualification_checks(event_record, raw, paths, pdf)
            checks.update(qc)
        if pair is not None:
            checks["endpoints_inside_declared_before_after_windows"] = all(start <= row["period"] <= end for row, (start, end) in zip(pair, (declared["before_window"], declared["after_window"])))
            if anchor.get("precision") == "timestamp":
                moment = aware(anchor["disclosed_at"])
                checks["strict_before_event_after"] = datetime.combine(date.fromisoformat(pair[0]["period"]), time(15), CN) < moment < datetime.combine(date.fromisoformat(pair[1]["period"]), time(15), CN)
            else:
                checks["strict_before_event_after"] = pair[0]["period"] < anchor["release_date"] < pair[1]["period"]
        units.append(unit("critical_anchor/required", "required_event_anchor", checks, hallucination=checks["exact_anchor_fields"] is False,
            anchor_valid=all(checks.values()), source_refs=refs, expected_anchor=anchor,
            expected_price_endpoints=[] if pair is None else [row["period"] for row in pair]))
    for eid, ev in evidence.items():
        if ev["provider"] == "tushare" and ev["metric"] in {"revenue", "total_revenue", "net_income_parent", "operating_cashflow"}:
            pdf.check(ev, case["request"])
        elif ev["provider"] == "cninfo" and ev["value"] is not None:
            envelope = raw.get(records[ev["record_id"]]["artifact_id"], {})
            try:
                checks, ref = pdf.qualified_cell(envelope, ev, raw, paths)
                key = case["request"]["symbol"], case["request"]["exchange"], ev["period"], ev["metric"], ev["revision_id"], str(ev["value"])
                pdf.results[key] = {"security": key[0], "exchange": key[1], "period": key[2], "metric": key[3],
                    "source_revision": key[4], "assessable": True, "supported": all(checks.values()),
                    "reason": "qualified_exact_official_version_cell_reextracted", "checks": checks, "source_ref": ref}
            except (ValueError, KeyError, IndexError) as exc:
                pass  # source check above preserves this as a failure; no guessed official cell.
    hyp_units = [u for u in units if u["unit_type"] == "hypothesis_state"]
    expected_missing = sorted(set(expected) - set(by_name))
    decisive = sum(h["status"] != "insufficient" for h in expected_h.values())
    justified_insufficient = any(h["status"] == "insufficient" for h in expected_h.values())
    diagnostics = report.get("insufficiency_diagnostics", [])
    codes = {reason["code"] for diagnostic in diagnostics for reason in diagnostic.get("insufficiency_reasons", [])}
    completion = {"complete_independent_fact_set": not expected_missing and set(by_name) == set(expected) and all(fact_support.values()),
        "complete_independent_evidence_set": set(reported_ev) == set(evidence) and all(ev_support.values()),
        "all_required_hypotheses_correct": len(hyp_units) == len(expected_h) and all(u["supported"] is True for u in hyp_units),
        "mandatory_fact_names_present_and_supported": all(fact_support.get(name, False) for name in case["expected_behavior"]["mandatory_fact_names"]),
        "preregistered_diagnostic_codes_present": set(case["expected_behavior"]["diagnostic_codes"]) <= codes,
        "insufficient_permitted_by_preregistration": not justified_insufficient or case["expected_behavior"].get("allow_source_proven_insufficiency") is True,
        "required_event_anchor_correct": all(u["supported"] is True for u in units if u["unit_type"] == "required_event_anchor"),
        "request_matches_manifest": report.get("request") == case["request"],
        "fixed_model_verified_once": (report.get("model", {}).get("status") == "verified" and agent.get("dispatch_count") == 1
            and report["model"].get("requested_model") == report["model"].get("returned_model") == "deepseek-v4-flash-0731"
            and agent.get("model") == report["model"]),
        "model_selections_reference_known_facts_and_requested_tests": (bool(report.get("model", {}).get("highlights"))
            and set(report["model"]["highlights"]) <= {f["id"] for f in facts}
            and bool(report["model"].get("hypotheses")) and set(report["model"]["hypotheses"]) <= set(expected_h)),
        "original_input_checks": all_input_checks}
    return {"case_id": case["id"], "task_id": case["id"], "level": case["level"], "split": case["split"],
        "input_checks": input_checks, "units": units, "evidence_checks": ev_units,
        "expected_facts": expected, "expected_hypotheses": expected_h,
        "required_completion": {"checks": completion, "completed": all(completion.values()),
            "required_checks": len(expected_h), "correct_required_checks": sum(u["supported"] is True for u in hyp_units),
            "decisive_required_checks": decisive, "decisive_correct_checks": sum(u["supported"] is True and u["expected_hypothesis"]["status"] != "insufficient" for u in hyp_units if u["expected_hypothesis"]),
            "missing_computable_fact_names": expected_missing,
            "source_proven_insufficient": justified_insufficient, "markdown_semantic_review_required": True},
        "deterministic_success_candidate": all(completion.values()),
        "markdown_semantic_assessable": None, "markdown_review_not_inherited_from_JSON": True}


def write_new(path, value):
    with Path(path).open("x", encoding="utf8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def run(manifest_path, outdir, *, repository_root=ROOT):
    """Audit completed Agent outputs against frozen independent source inputs.

    Writes deterministic-review.json and official-coverage.json only. Markdown
    semantic truth is delegated to a distinct independent reviewer and never
    automatically inherited from correct structured claims.
    """
    reader = Reader(repository_root)
    manifest_path = reader.path(manifest_path)
    campaign = manifest_path.parent
    outdir = reader.path(outdir)
    outputs = [outdir / name for name in ("deterministic-review.json", "official-coverage.json")]
    if any(path.exists() for path in outputs):
        raise FileExistsError("refusing to overwrite an independent frozen review")
    manifest = reader.json(manifest_path)
    if (manifest.get("schema") != "phase3-contract-gated-benchmark-v2"
            or digest(manifest["cases"]) != manifest["candidate_sha256"]
            or digest(manifest["contract_validation"]) != manifest["contract_validation_sha256"]
            or manifest["contract_validation"].get("all_cases_contract_valid") is not True):
        raise ValueError("formal whole-batch contract freeze is required")
    results = reader.json(campaign / "agent-results.json")
    entries = results.get("cases", results.get("results", []))
    lookup = {entry["case_id"]: entry for entry in entries}
    if len(lookup) != len(entries) or set(lookup) != {case["id"] for case in manifest["cases"]}:
        raise ValueError("all frozen cases need exactly one immutable Agent result")
    pdf = OfficialPDF(reader)
    tasks = []
    try:
        for case in manifest["cases"]:
            entry = lookup[case["id"]]
            frozen = reader.json(case.get("input_path", campaign / "inputs" / (case["id"] + ".json")), case.get("input_sha256"))
            report_path = entry.get("report_path", campaign / "live" / (case["id"] + ".json"))
            report = reader.json(report_path, entry.get("report_sha256"))
            if "output" in entry and report != entry["output"]:
                raise ValueError("Agent result receipt differs from raw report")
            for path, expected in case["source_hashes"].items():
                reader.bytes(path, expected)
            task = review_case(case, frozen, report, reader, pdf, entry)
            task["raw_report_sha256"] = reader.reads[reader.path(report_path).relative_to(reader.root).as_posix()]
            tasks.append(task)
    finally:
        pdf.close()
    units = [unit for task in tasks for unit in task["units"]]
    official = list(pdf.results.values())
    review = {"schema": VERSION, "manifest_sha256": reader.reads[manifest_path.relative_to(reader.root).as_posix()],
        "oracle_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "production_imports": 0, "generation_model_calls": 0, "provider_network_calls": 0,
        "previous_scores_used_as_ground_truth": False, "tasks": tasks, "source_hashes": reader.reads,
        "summary": {"tasks": len(tasks), "units": len(units), "source_assessable_units": sum(u["assessable"] is True for u in units),
            "supported_units": sum(u["supported"] is True for u in units), "hallucinated_units": sum(u["hallucination"] is True for u in units),
            "deterministic_success_candidates": sum(task["deterministic_success_candidate"] for task in tasks),
            "required_checks": sum(task["required_completion"]["required_checks"] for task in tasks),
            "correct_required_checks": sum(task["required_completion"]["correct_required_checks"] for task in tasks),
            "decisive_required_checks": sum(task["required_completion"]["decisive_required_checks"] for task in tasks),
            "decisive_correct_checks": sum(task["required_completion"]["decisive_correct_checks"] for task in tasks),
            "failures": dict(Counter(k for u in units for k in u["failure_category"]))},
        "limits": ["Source-qualified transformation agreement does not certify every provider's financial accuracy.",
            "Official prior-period comparisons require an independently printed source-version bridge.",
            "Markdown semantic truth and final task success require a distinct independent review.",
            "Frozen current validation corpus is reused material, not a blind generalization certificate."]}
    coverage = {"schema": "independent-official-coverage-v2/1", "manifest_sha256": review["manifest_sha256"],
        "previous_verdicts_used": False, "generation_model_calls": 0, "provider_network_calls": 0,
        "checks": official, "summary": {"distinct_source_revision_cells": len(official),
            "assessable": sum(row["assessable"] is True for row in official),
            "supported": sum(row["supported"] is True for row in official),
            "contradicted": sum(row["supported"] is False for row in official),
            "not_assessable": sum(row["assessable"] is False for row in official)},
        "pdf_page_extractions": [{"path": str(Path(path).relative_to(reader.root)), "page": page, "text": text} for (path, page), text in sorted(pdf.pages.items())]}
    outdir.mkdir(parents=True, exist_ok=True)
    write_new(outputs[0], review)
    write_new(outputs[1], coverage)
    return review, coverage


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("outdir")
    args = parser.parse_args()
    review, coverage = run(args.manifest, args.outdir)
    print(json.dumps({"deterministic": review["summary"], "official": coverage["summary"]}, ensure_ascii=False))
