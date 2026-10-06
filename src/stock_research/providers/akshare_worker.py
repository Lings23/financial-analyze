"""Bounded subprocess entry point for the seven approved AKShare functions."""
import json
import math
import sys
from datetime import date, datetime
from decimal import Decimal

import requests


ENDPOINTS = frozenset({
    "stock_sse_summary", "stock_szse_summary", "stock_zh_a_spot_em",
    "stock_cy_a_spot_em", "stock_kc_a_spot_em",
    "stock_comment_detail_zlkp_jgcyd_em",
    "stock_comment_detail_scrd_focus_em",
    "stock_news_em",
    "stock_info_a_code_name",
})


def _scalar(value):
    if value is None:
        return None
    if str(value) in {"NaT", "<NA>", "nan"}:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if hasattr(value, "item"):
        return _scalar(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    raise ValueError("unsupported provider scalar")


def main():
    if len(sys.argv) not in {3, 4} or sys.argv[1] not in ENDPOINTS:
        return 2
    endpoint = sys.argv[1]
    pagination = None
    try:
        params = json.loads(sys.argv[2])
        if not isinstance(params, dict):
            return 2
        import akshare as ak
        import pandas as pd

        function = getattr(ak, endpoint)
        pagination = None
        if endpoint in {'stock_zh_a_spot_em', 'stock_cy_a_spot_em', 'stock_kc_a_spot_em'}:
            from .akshare_spot import BoundedSpotPagination
            from ..errors import ProviderSchemaError, TransientProviderError
            timeout = float(sys.argv[3]) if len(sys.argv) == 4 else 45
            if not 0 < timeout <= 120:
                return 2
            if 'fetch_paginated_data' not in function.__globals__:
                return 6
            pagination = BoundedSpotPagination(timeout)
            function.__globals__['fetch_paginated_data'] = pagination
        frame = function(**params)
        if not isinstance(frame, pd.DataFrame) or len(frame) > 10000 or len(frame.columns) > 64:
            return 3
        columns = [str(c) for c in frame.columns]
        if len(set(columns)) != len(columns):
            return 3
        rows = [[_scalar(value) for value in row] for row in frame.itertuples(index=False, name=None)]
        result = {"version": ak.__version__, "columns": columns, "rows": rows}
        if pagination is not None:
            result['source_response'] = pagination.source_response
        payload = json.dumps(result,
                             ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 16 * 1024 * 1024:
            return 3
        sys.stdout.buffer.write(payload.encode("utf-8"))
        return 0
    except Exception as exc:
        from ..errors import ProviderSchemaError, TransientProviderError
        if pagination is not None:
            sys.stdout.buffer.write(json.dumps({'worker_failure': {'error_type': type(exc).__name__,
                'attempts': pagination.attempt_count, 'last_http_status': pagination.last_http_status,
                'retries': 0}}).encode('utf8'))
        if isinstance(exc, (TransientProviderError, requests.exceptions.RequestException)):
            return 5
        if isinstance(exc, (ProviderSchemaError, AttributeError, KeyError, IndexError, ValueError, TypeError)):
            return 6
        # Upstream exception text can include URLs, response bodies or credentials.
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
