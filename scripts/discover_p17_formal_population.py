"""Bounded metadata discovery for formal strata; never financial ground truth."""
import hashlib
import argparse
import json
from pathlib import Path
import time
from datetime import date
from decimal import Decimal
import re

from stock_research.__main__ import _project_tushare_token
from stock_research.models import utcnow
from stock_research.providers.tushare import TushareHTTPTransport, _json_safe
from stock_research.providers.documents import DocumentHTTPTransport
from stock_research.storage.artifacts import ArtifactStore

ROOT = Path('.artifacts/p17_20261001/formal_discovery')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--liquidity-only', action='store_true')
    parser.add_argument('--liquidity-date', type=date.fromisoformat)
    parser.add_argument('--label')
    args = parser.parse_args()
    global ROOT
    if args.liquidity_only: ROOT = ROOT / ('liquidity_' + args.liquidity_date.isoformat() if args.liquidity_date else 'liquidity')
    if args.label:
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,40}', args.label): raise ValueError('invalid evidence label')
        ROOT = ROOT / args.label
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / 'run.json'
    if target.exists(): raise ValueError('discovery exists; refusing overwrite')
    scope = 'p17-formal-discovery-20261001'
    artifacts = ArtifactStore(ROOT / 'artifacts')
    plan = {'scope': scope, 'purpose': 'current metadata for pre-registration, not historical universe or value validation',
        'max_attempts': 1, 'timeout_seconds': 12, 'min_interval_seconds': 2.5,
        'requests': [
            {'api': 'stock_basic', 'params': {'exchange': '', 'list_status': 'L'},
             'fields': ['ts_code', 'symbol', 'name', 'exchange', 'market', 'industry', 'list_date']},
            {'api': 'suspend_d', 'params': {'start_date': '20260915', 'end_date': '20260925', 'suspend_type': 'S'},
             'fields': ['ts_code', 'trade_date', 'suspend_timing', 'suspend_type']}],
        'cninfo_discovery': {'searchkey': '停牌', 'date_window': '2026-09-10~2026-09-25', 'max_pages': 1, 'page_size': 30}}
    if args.liquidity_only:
        plan['requests'] = [{'api': 'daily', 'params': {'trade_date': args.liquidity_date.strftime('%Y%m%d') if args.liquidity_date else '20260925'},
                             'fields': ['ts_code', 'trade_date', 'vol', 'amount']}]
        plan['cninfo_discovery'] = None
    run = {'scope': scope, 'plan_artifact_id': artifacts.put(scope, plan), 'started_at': utcnow().isoformat(), 'results': []}
    token = _project_tushare_token()
    transport = TushareHTTPTransport()
    for spec in plan['requests']:
        entry = {'request': spec, 'started_at': utcnow().isoformat()}
        try:
            response = transport({'api_name': spec['api'], 'token': token, 'params': spec['params'],
                                  'fields': ','.join(spec['fields'])}, 12)
            code = response.get('code')
            entry['business_code'] = code
            if code != 0: raise ValueError('provider business request rejected')
            data = response['data']
            fields, rows = data['fields'], data['items']
            assert isinstance(fields, list) and set(spec['fields']) <= set(fields) and len(fields) == len(set(fields))
            assert isinstance(rows, list) and len(rows) < 10000
            projected = []
            for row in rows:
                assert isinstance(row, list) and len(row) == len(fields)
                selected = [row[fields.index(f)] for f in spec['fields']]
                for cell in selected:
                    assert cell is None or type(cell) in {str, int, float, Decimal}
                    assert not isinstance(cell, Decimal) or cell.is_finite()
                    assert not isinstance(cell, str) or token not in cell
                projected.append(selected)
            payload = {'api': spec['api'], 'params': spec['params'], 'fields': spec['fields'], 'items': projected,
                       'started_at': entry['started_at'], 'finished_at': utcnow().isoformat()}
            entry.update(status='collected', row_count=len(rows), artifact_id=artifacts.put(scope, _json_safe(payload)))
        except Exception as exc:
            entry.update(status='failed', error_type=type(exc).__name__)
        entry['finished_at'] = utcnow().isoformat()
        run['results'].append(entry)
        print(json.dumps({k: v for k, v in entry.items() if k != 'request'}), flush=True)
        time.sleep(2.5)
    if args.liquidity_only:
        run['finished_at'] = utcnow().isoformat()
        with target.open('x', encoding='utf8') as stream: json.dump(run, stream, indent=2)
        return
    entry = {'api': 'cninfo_halt_title_discovery', 'started_at': utcnow().isoformat()}
    form = {'pageNum': '1', 'pageSize': '30', 'column': 'szse', 'tabName': 'fulltext', 'plate': '', 'stock': '',
            'searchkey': '停牌', 'secid': '', 'category': '', 'trade': '', 'seDate': '2026-09-10~2026-09-25',
            'sortName': '', 'sortType': '', 'isHLtitle': 'false'}
    try:
        endpoint = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
        body = DocumentHTTPTransport()(endpoint, 12, form=form)
        rows = body.get('announcements') or []
        assert isinstance(rows, list) and len(rows) <= 30
        projected = [{k: row[k] for k in ('secCode', 'announcementId', 'announcementTitle', 'announcementTime', 'adjunctUrl')} for row in rows]
        payload = {'endpoint': endpoint, 'form': form, 'total': body['totalAnnouncement'], 'rows': projected}
        entry.update(status='collected', row_count=len(rows), reported_total=body['totalAnnouncement'],
                     artifact_id=artifacts.put(scope, payload), full_index_coverage_claimed=False)
    except Exception as exc:
        entry.update(status='failed', error_type=type(exc).__name__)
    entry['finished_at'] = utcnow().isoformat()
    run['results'].append(entry)
    run['finished_at'] = utcnow().isoformat()
    with target.open('x', encoding='utf8') as stream: json.dump(run, stream, indent=2)
    print(json.dumps(entry))


if __name__ == '__main__': main()
