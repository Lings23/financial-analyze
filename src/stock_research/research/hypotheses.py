"""Predeclared evidence tests; support is descriptive and never establishes causation."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from ..models import DataRecord, digest
from .profit_change import PROFIT_CATALOGUE, profit_change_hypothesis, profit_change_diagnostics


CATALOGUE = {
    "absolute_profit_change": PROFIT_CATALOGUE,
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
}


def event_anchor(datasets, request):
    if not request.event_record_id:
        return {"status": "insufficient", "reason": "event_anchor_not_requested"}
    for dataset, result in datasets.items():
        for row in result["records"]:
            record = DataRecord.from_dict(row)
            if record.record_id != request.event_record_id:
                continue
            if dataset not in {"financial_income", "announcement", "news_recent"}:
                return {"status": "insufficient", "reason": "event_anchor_dataset_not_supported"}
            anchor = {"record_id": record.record_id, "dataset": dataset,
                      "snapshot": result["snapshot"], "provider": record.provider,
                      "provider_call_id": record.provider_call_id, "source_url": record.source_url,
                      "artifact_ids": list(record.artifact_ids), "revision_id": record.revision_id,
                      "available_at": record.available_at.isoformat(),
                      "ingested_at": record.ingested_at.isoformat(),
                      "retrieved_at": record.retrieved_at.isoformat(),
                      "availability_basis": record.availability_basis,
                      "source_period": record.period.isoformat(), "causal_claim": False}
            if record.availability_basis == "verified_release":
                moment = record.published_at
                anchor.update(status="verified", precision="timestamp", disclosed_at=moment.isoformat(),
                              boundary_date=moment.astimezone(timezone(timedelta(hours=8))).date().isoformat())
            elif record.availability_basis == "verified_release_date":
                boundary = record.release_date + timedelta(days=1)
                anchor.update(status="verified", precision="date_conservative_next_day",
                              release_date=record.release_date.isoformat(), boundary_date=boundary.isoformat(),
                              release_evidence_artifact_id=record.release_evidence_artifact_id)
            else:
                anchor.update(status="insufficient", reason="capture_is_not_event_release_time")
            return anchor
    return {"status": "insufficient", "reason": "event_anchor_not_visible"}


def event_prices(datasets, anchor):
    if anchor["status"] != "verified":
        return None
    boundary = anchor["boundary_date"]
    prices = sorted(datasets.get("market_daily", {}).get("records", []), key=lambda r: r["period"])
    if anchor["precision"] == "timestamp":
        moment = datetime.fromisoformat(anchor["disclosed_at"])
        def close_at(row):
            return datetime.combine(datetime.fromisoformat(row["period"]).date(), time(15),
                                    timezone(timedelta(hours=8)))
        before = [r for r in prices if close_at(r) < moment]
        after = [r for r in prices if close_at(r) >= moment]
    else:
        before = [r for r in prices if r["period"] < boundary]
        after = [r for r in prices if r["period"] >= boundary]
    if not before or not after:
        return None
    # Date-only disclosures exclude the ambiguous release day from the pre-event endpoint.
    if anchor["precision"] == "date_conservative_next_day":
        before = [r for r in before if r["period"] < anchor["release_date"]]
        if not before:
            return None
    pair = (before[-1], after[-1])
    for r in pair:
        value = next(m["value"] for m in r["metrics"] if m["name"] == "close")
        if value is None or Decimal(value) <= 0:
            return None
    return pair


def test_hypotheses(computed, datasets, request):
    facts = {f["name"]: f for f in computed["facts"]}
    anchor = computed["event_anchor"]
    results = []
    for hid in request.hypotheses:
        if hid == "absolute_profit_change":
            results.append(profit_change_hypothesis(computed, datasets, request))
            continue
        title, required, rule = CATALOGUE[hid]
        status, reason, references, counter = "insufficient", "required_evidence_missing", [], []
        if hid == "mechanical_adjustment":
            names = ("observed_price_change", "factor_adjusted_price_change")
            if all(n in facts for n in names):
                references = [facts[n]["id"] for n in names]
                # Compare precise source factors; rounding of two Decimal ratios must
                # not create or hide a mechanical factor change.
                factor_inputs = facts[names[1]]["inputs"][2:]
                differs = (Decimal(computed["evidence"][factor_inputs[0]]["value"]) !=
                           Decimal(computed["evidence"][factor_inputs[-1]]["value"]))
                status, reason = ("supported", "factor_changes_endpoint_result") if differs else (
                    "unsupported", "no_endpoint_adjustment_difference_observed")
                if not differs:
                    counter = references[:]
        elif hid == "market_direction":
            names = ("observed_price_change", "benchmark_price_change")
            if all(n in facts for n in names):
                references = [facts[n]["id"] for n in names]
                a, b = (Decimal(facts[n]["value"]) for n in names)
                if a == 0 or b == 0:
                    reason = "zero_change_has_no_direction"
                elif a * b > 0:
                    status, reason = "supported", "same_direction_observed"
                else:
                    status, reason, counter = "unsupported", "opposite_direction_observed", references[:]
        elif hid == "financial_deterioration":
            names = ("revenue_yoy", "net_income_parent_yoy")
            if all(n in facts for n in names):
                references = [facts[n]["id"] for n in names]
                declines = [Decimal(facts[n]["value"]) < 0 for n in names]
                counter = [facts[n]["id"] for n, declining in zip(names, declines) if not declining]
                status, reason = ("supported", "both_same_period_yoy_decline") if all(declines) else (
                    ("conflicted", "mixed_financial_directions") if any(declines) else (
                        "unsupported", "neither_metric_declines"))
        elif hid == "cashflow_divergence":
            names = ("financial_income.net_income_parent", "financial_cashflow.operating_cashflow")
            if all(n in facts for n in names):
                references = [facts[n]["id"] for n in names]
                if facts[names[0]]["window"] != facts[names[1]]["window"]:
                    reason = "financial_period_mismatch"
                else:
                    a, b = (Decimal(facts[n]["value"]) for n in names)
                    status, reason = ("supported", "positive_profit_negative_operating_cashflow") if a > 0 and b < 0 else (
                        "unsupported", "divergence_condition_not_observed")
                    if status == "unsupported":
                        counter = references[:]
        elif hid == "event_chronology":
            if "event_observed_price_change" in facts:
                references = [facts["event_observed_price_change"]["id"]]
                status, reason = "supported", "verified_anchor_and_observed_pre_post_closes"
            else:
                reason = anchor.get("reason", "event_pre_post_closes_missing")
        results.append({"id": hid, "title": title, "status": status, "reason": reason,
                        "required_evidence": required, "test_rule": rule, "claim_ids": references,
                        "counterevidence_claim_ids": counter,
                        "anchor_record_id": anchor.get("record_id") if hid == "event_chronology" else None,
                        "conclusion_strength": "descriptive_test_only", "causal_claim": False,
                        "coverage": "not_verified"})
    return results


def diagnose_insufficiency(computed, datasets, request):
    """Explain existing insufficient tests using only their already loaded inputs.

    This is a separately versioned report annotation, not a change to the catalogue,
    formulas, hypothesis status or legacy checkpoint payload. Empty query results do
    not establish provider/snapshot incompatibility. No source or snapshot is read
    here, and rows outside the request/PIT boundary cannot supply financial values.
    """
    contract = "benchmark_or_request_contract_defect"
    data = "data_or_evidence_insufficiency"
    intrinsic = "intrinsic_precondition_or_temporal_impossibility"
    bindings = {b.dataset: b for b in request.bindings}
    facts = {f["name"]: f for f in computed.get("facts", [])}
    evidence = computed.get("evidence", {})
    zone = timezone(timedelta(hours=8))

    def records(name):
        binding = bindings.get(name)
        result = datasets.get(name)
        if (binding is None or result is None or result.get("snapshot") != binding.snapshot
                or result.get("provider") != binding.provider):
            return []
        expected_security = request.data_request(binding).security.security_id
        allowed = []
        for row in result.get("records", []):
            record = DataRecord.from_dict(row)
            if (record.dataset.value == name and record.provider == binding.provider
                    and record.security_id == expected_security
                    and binding.start <= record.period <= binding.end
                    and record.available_at <= request.as_of
                    and (request.mode.value != "system" or record.ingested_at <= request.as_of)):
                allowed.append(record)
        return sorted(allowed, key=lambda record: record.period)

    def metric(record, name):
        return next((m.value for m in record.metrics if m.name == name), None)

    def valid_prices(rr):
        return len(rr) >= 2 and all(metric(r, "close") is not None
                                    and metric(r, "close") > 0 for r in rr)

    results = []
    for hypothesis in computed.get("hypotheses", []):
        if hypothesis["status"] != "insufficient":
            continue
        hid = hypothesis["id"]
        if hid == "absolute_profit_change":
            results.extend(profit_change_diagnostics(computed, datasets, request))
            continue
        reasons = []

        def add(code, category, detail, names=(), rr=(), field=None):
            record_refs = sorted({r.record_id for r in rr})
            item = {"code": code, "failure_category": category, "datasets": list(names),
                    "record_refs": record_refs,
                    "evidence_refs": sorted(key for key, source in evidence.items()
                                            if source.get("record_id") in record_refs
                                            and (field is None or source.get("metric") == field)),
                    "detail": detail}
            if field is not None:
                item["metric"] = field
            if item not in reasons:
                reasons.append(item)

        required = [name for name in CATALOGUE[hid][1] if name != "explicit_event_record"]
        for name in required:
            if name not in bindings:
                add("missing_dataset", contract, "研究请求未绑定检验必需的数据集。", (name,))
            elif name not in datasets or not datasets[name].get("records"):
                add("missing_dataset", data, "已加载的授权可见结果中没有该数据集的记录；不能据此判断 Provider 能力。", (name,))
            elif len(records(name)) != len(datasets[name]["records"]):
                # The verifier will reject these rows; annotations never make them usable.
                add("market_source_incompatible" if name == "market_daily" else "invalid_dataset_binding",
                    contract, "已加载结果与请求的数据集、来源、快照、证券、窗口或 PIT 绑定不一致。", (name,))

        prices = records("market_daily")
        if "market_daily" in required and prices and not valid_prices(prices):
            add("no_valid_market_window", data, "可见行情少于两条或收盘价缺失、非正，不能形成有效价格比较。",
                ("market_daily",), prices, "close")

        if hid == "mechanical_adjustment" and valid_prices(prices):
            factors = records("adjustment_factor")
            by_date = {r.period: r for r in factors}
            if factors and any(p.period not in by_date for p in prices):
                add("exact_date_alignment_failed", intrinsic,
                    "实际可见行情日期未全部具有同日复权因子；原规则不允许插值或缩窗口。",
                    ("market_daily", "adjustment_factor"), factors)
            invalid = [r for r in factors if r.period in {p.period for p in prices}
                       and (metric(r, "factor") is None or metric(r, "factor") <= 0)]
            if invalid:
                add("missing_metric", data, "同日复权因子字段缺失或非正，不能计算因子调整变化。",
                    ("adjustment_factor",), invalid, "factor")

        elif hid == "market_direction":
            index = records("index_daily")
            if index and not valid_prices(index):
                add("no_valid_market_window", data, "可见基准少于两条或收盘值缺失、非正，不能形成有效比较。",
                    ("index_daily",), index, "close")
            if valid_prices(prices) and valid_prices(index):
                if [r.period for r in prices] != [r.period for r in index]:
                    add("exact_date_alignment_failed", intrinsic,
                        "股票与基准的全部实际观察日期不完全相同；原规则不允许插值或缩窗口。",
                        ("market_daily", "index_daily"), [*prices, *index])
                elif hypothesis.get("reason") == "zero_change_has_no_direction":
                    add("zero_change_has_no_direction", intrinsic,
                        "已计算变化中至少一侧为零，原同向规则没有可判定方向。",
                        ("market_daily", "index_daily"), [*prices, *index])

        elif hid == "financial_deterioration":
            income = records("financial_income")
            if income:
                current = income[-1]
                prior_period = str(current.period.year - 1) + current.period.isoformat()[4:]
                prior = next((r for r in income if r.period.isoformat() == prior_period), None)
                if prior is None:
                    add("missing_report_period", data,
                        "最新可见报告期没有上年同报告期的可见基数；未将缺失当零。",
                        ("financial_income",), (current,))
                for name in ("revenue", "net_income_parent"):
                    if name + "_yoy" in facts:
                        continue
                    missing = [r for r in (current, prior) if r is not None and metric(r, name) is None]
                    if missing:
                        add("missing_metric", data, "同比所需字段显式缺失；未将缺失当零。",
                            ("financial_income",), missing, name)
                    if prior is not None and metric(prior, name) is not None and metric(prior, name) <= 0:
                        add("positive_base_precondition_failed", intrinsic,
                            "上年同报告期字段已经可见但基数非正，不满足原正基数同比规则。",
                            ("financial_income",), (prior,), name)

        elif hid == "cashflow_divergence":
            income, cashflow = records("financial_income"), records("financial_cashflow")
            if income and cashflow:
                if income[-1].period != cashflow[-1].period:
                    add("missing_report_period", data,
                        "最新可见利润与经营现金流报告期不相同，缺少原检验要求的同报告期输入。",
                        ("financial_income", "financial_cashflow"), (income[-1], cashflow[-1]))
                for name, rr, field in (("financial_income", income, "net_income_parent"),
                                        ("financial_cashflow", cashflow, "operating_cashflow")):
                    if metric(rr[-1], field) is None:
                        add("missing_metric", data, "检验必需字段显式缺失；未将缺失当零。",
                            (name,), (rr[-1],), field)

        elif hid == "event_chronology":
            anchor = computed.get("event_anchor", {})
            if not request.event_record_id:
                add("missing_event", contract, "请求要求事件时序检验，但未指定明确的 event_record_id。")
            else:
                candidate = next((DataRecord.from_dict(row) for result in datasets.values()
                                  for row in result.get("records", [])
                                  if DataRecord.from_dict(row).record_id == request.event_record_id), None)
                if candidate is None:
                    add("missing_event", data,
                        "指定事件没有出现在已经授权且可见的结果中；无法仅据空结果判断缺失、版本或时间原因。")
                elif candidate.record_id not in {r.record_id for name in datasets for r in records(name)} or (
                        candidate.security_id != request.security.security_id
                        or candidate.dataset.value not in {"financial_income", "announcement", "news_recent"}):
                    add("invalid_event_binding", contract,
                        "指定事件与目标证券、支持的事件类型、来源绑定或 PIT 可见条件不一致。")
                elif anchor.get("status") != "verified":
                    add("invalid_event_binding", contract,
                        "指定事件没有合格披露时间或日期资格；采集时刻不能代替事件公开时间。", rr=(candidate,))
                else:
                    binding = bindings.get("market_daily")
                    impossible = False
                    if binding is not None:
                        if anchor["precision"] == "timestamp":
                            moment = datetime.fromisoformat(anchor["disclosed_at"]).astimezone(zone)
                            first_close = datetime.combine(binding.start, time(15), zone)
                            impossible = first_close >= moment
                            after_day = max(binding.start, moment.date())
                            after_close = datetime.combine(after_day, time(15), zone)
                            if after_close < moment:
                                after_close += timedelta(days=1)
                        else:
                            release_day = datetime.fromisoformat(anchor["release_date"]).date()
                            boundary_day = datetime.fromisoformat(anchor["boundary_date"]).date()
                            impossible = binding.start >= release_day
                            after_close = datetime.combine(max(binding.start, boundary_day), time(15), zone)
                        impossible = (impossible or after_close.date() > binding.end
                                      or after_close > request.as_of)
                    if impossible:
                        add("temporal_condition_impossible", intrinsic,
                            "原行情窗口或 cutoff 无法同时容纳合法事前及事后 15:00 收盘；未使用未来行情。",
                            ("market_daily",), (candidate,))
                    elif prices:
                        add("no_valid_market_window", data,
                            "原时间条件可能容纳前后收盘，但可见结果没有原检验所需的有效前后行情。",
                            ("market_daily",), prices, "close")

        if not reasons:
            add("diagnostic_not_assessable", "not_assessable",
                "已保留原 insufficient 状态；现有已加载输入不足以确定更具体的原因。")
        results.append({"hypothesis_id": hid, "status": "insufficient", "insufficiency_reasons": reasons})
    return results
