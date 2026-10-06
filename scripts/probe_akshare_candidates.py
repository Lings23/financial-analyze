"""Bounded, metadata-only live probes for shortlisted AKShare interfaces.

This is a diagnostic script, not a production provider or a PIT release verifier.
It never emits financial cell values or upstream exception text.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path


PROBES = {
    "stock_zh_a_hist": dict(symbol="600000", period="daily", start_date="20240901",
                            end_date="20240930", adjust="", timeout=10),
    "tool_trade_date_hist_sina": {},
    "stock_dividend_cninfo": dict(symbol="600000"),
    "stock_share_change_cninfo": dict(symbol="600000", start_date="20230101", end_date="20241231"),
    "stock_allotment_cninfo": dict(symbol="600000", start_date="20230101", end_date="20241231"),
    "stock_profit_sheet_by_report_em": dict(symbol="SH600000"),
    "stock_balance_sheet_by_report_em": dict(symbol="SH600000"),
    "stock_cash_flow_sheet_by_report_em": dict(symbol="SH600000"),
    "stock_zh_a_disclosure_report_cninfo": dict(symbol="600000", market="沪深京",
                                                  category="", start_date="20240901", end_date="20240930"),
    "index_zh_a_hist": dict(symbol="000001", period="daily", start_date="20240901",
                            end_date="20240930"),
    "index_detail_hist_cni": dict(symbol="399005"),
    "index_detail_hist_adjust_cni": dict(symbol="399005"),
    "stock_info_a_code_name": {},
    "stock_industry_change_cninfo": dict(symbol="600000", start_date="20230101",
                                           end_date="20241231"),
    "stock_news_em": dict(symbol="600000"),
}


def child(name):
    try:
        import akshare as ak
        import pandas as pd

        frame = getattr(ak, name)(**PROBES[name])
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("AKShare did not return a DataFrame")
        columns = [str(column) for column in frame.columns]
        if len(frame) > 20000 or len(columns) > 400 or len(set(columns)) != len(columns):
            raise ValueError("result exceeds diagnostic bounds")
        serialized = frame.to_json(orient="split", force_ascii=False, date_format="iso")
        if len(serialized.encode("utf-8")) > 20 * 1024 * 1024:
            raise ValueError("result exceeds diagnostic size")
        temporal = [column for column in columns if any(term in column.lower() for term in
                    ("日期", "时间", "披露", "发布", "更新", "修订", "date", "time", "publish", "update"))]
        release = [column for column in columns if any(term in column.lower() for term in
                   ("公告", "披露", "发布", "更新", "修订", "publish", "announce", "update", "version"))]
        temporal_ranges = {}
        for column in temporal[:20]:
            values = [str(value) for value in frame[column].dropna().head(20000)
                      if re.match(r"^[12]\d{3}[-/]?\d{2}[-/]?\d{2}", str(value))]
            if values:
                temporal_ranges[column] = {"first": min(values), "last": max(values),
                                           "sample": values[0]}
        pit_checks = {}
        if {"REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE"} <= set(columns):
            report = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
            notice = pd.to_datetime(frame["NOTICE_DATE"], errors="coerce")
            update = pd.to_datetime(frame["UPDATE_DATE"], errors="coerce")
            pit_checks = {
                "report_dates_present": int(report.notna().sum()),
                "notice_dates_present": int(notice.notna().sum()),
                "update_dates_present": int(update.notna().sum()),
                "notice_after_report": int((notice > report).sum()),
                "update_after_notice": int((update > notice).sum()),
                "report_by_2024_09_30_updated_later": int(((report <= pd.Timestamp("2024-09-30"))
                                                            & (update > pd.Timestamp("2024-09-30"))).sum()),
                "noticed_by_2024_09_30_updated_later": int(((notice <= pd.Timestamp("2024-09-30"))
                                                             & (update > pd.Timestamp("2024-09-30"))).sum()),
            }
        print(json.dumps({"name": name, "status": "returned", "rows": len(frame),
                          "columns": columns[:40], "column_count": len(columns),
                          "temporal_columns": temporal[:20], "release_columns": release[:20],
                          "temporal_ranges": temporal_ranges, "pit_checks": pit_checks,
                          "parsed_table_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                          "captured_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"name": name, "status": "failed", "error_type": type(exc).__name__}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", choices=["all", *PROBES], default="all")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--output", default=".runtime/akshare-candidate-probe.json")
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        child(args.name)
        return 0
    if not 0 < args.timeout <= 120:
        parser.error("timeout must be in (0, 120] seconds")
    names = list(PROBES) if args.name == "all" else [args.name]
    results = []
    for name in names:
        try:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                  "--child", "--name", name],
                                 capture_output=True, timeout=args.timeout, check=False)
            if run.returncode != 0:
                result = {"name": name, "status": "worker_failed"}
            else:
                result = json.loads(run.stdout)
        except subprocess.TimeoutExpired:
            result = {"name": name, "status": "timeout"}
        except (ValueError, OSError):
            result = {"name": name, "status": "worker_failed"}
        results.append(result)
        sys.stdout.write(json.dumps({k: result.get(k) for k in
                                    ("name", "status", "rows", "column_count", "error_type") if k in result}) + "\n")
        sys.stdout.flush()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"akshare_version": version("akshare"), "probes": results},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
