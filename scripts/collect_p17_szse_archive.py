"""Frozen SZSE official archive references, separate from runtime providers."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode

from discover_p17_szse_history import validate
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

PLAN = Path('evaluation/p17_20261001_szse_archive_plan.json')
ROOT = Path('.artifacts/p17_20261001/szse_archive')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def prepare():
    formal_path = Path('evaluation/p17_20261001_formal_plan.json')
    formal = json.loads(formal_path.read_bytes())
    old_path = Path('evaluation/p17_20261001_szse_reference_plan.json')
    old = json.loads(old_path.read_bytes())
    discovery = Path('.artifacts/p17_20261001/szse_history_discovery')
    metadata_path = discovery / 'archive-metadata.json'
    metadata = next(t for t in json.loads(metadata_path.read_bytes()) if t['metadata']['tabkey'] == 'tab1')['metadata']
    assert metadata['catalogid'] == '1815_stock'
    assert metadata['cols']['cjgs'] == '成交量<br>(万股)' and metadata['cols']['cjje'] == '成交金额<br>(万元)'
    assert {c['name'] for c in metadata['conditions']} >= {'txtDMorJC', 'txtBeginDate', 'TABKEY'}
    groups = [dict(label='formal', original_scope=formal['scope'],
                   snapshot_id=json.loads(Path('.artifacts/p17_20261001/formal/run.json').read_bytes())['results'][-1]['snapshot_id'],
                   run_path='.artifacts/p17_20261001/formal/run.json', original_artifacts='.artifacts/p17_20261001/formal/artifacts',
                   codes=[s['symbol'] for s in formal['securities'] if s['exchange'] == 'SZSE'],
                   dates=formal['daily_windows'][0]['dates'], window=formal['daily_windows'][0]),
              dict(label='original', original_scope=old['original_scope'], snapshot_id=old['original_snapshot'],
                   finished_at=old['original_finished_at'], original_artifacts='.artifacts/p17_20260930/artifacts',
                   codes=old['codes'], dates=formal['daily_windows'][0]['dates'], window=old['windows'][0])]
    assert len(groups[0]['codes']) == 8 and len(groups[1]['codes']) == 2 and len(groups[0]['dates']) == 9
    groups[0]['finished_at'] = json.loads(Path(groups[0]['run_path']).read_bytes())['finished_at']
    sources = [formal_path, old_path, metadata_path, discovery/'page.html', discovery/'archive-page.html',
               discovery/'res-min-assets-script0.js', discovery/'archive-probe.json', Path(__file__)]
    rules = {
        'open': {'source_field': 'ks', 'multiplier': '1', 'tolerance': '0.005'},
        'close': {'source_field': 'ss', 'multiplier': '1', 'tolerance': '0.005'},
        'high': {'source_field': 'zg', 'multiplier': '1', 'tolerance': '0.005'},
        'low': {'source_field': 'zd', 'multiplier': '1', 'tolerance': '0.005'},
        'volume': {'source_field': 'cjgs', 'multiplier': '10000', 'tolerance': '50'},
        'amount': {'source_field': 'cjje', 'multiplier': '10000', 'tolerance': '50'},
    }
    plan = {'scope': 'p17-szse-archive-reference-20261001', 'created_at': datetime.now(timezone.utc).isoformat(),
            'url': 'https://www.szse.cn/api/report/ShowReport/data',
            'page_url': 'https://www.szse.cn/market/trend/archive/index.html',
            'params': {'SHOWTYPE': 'JSON', 'CATALOGID': '1815_stock', 'TABKEY': 'tab1', 'PAGENO': '1'},
            'groups': groups, 'rules': rules, 'min_interval_seconds': 2.5,
            'logical_requests': 90, 'registered_cells': 540, 'overall_deadline_seconds': 420,
            'source_sha256': {str(path): digest(path) for path in sources},
            'rule_basis': 'Official archive table prints prices to 0.01 CNY, volume to 0.01 ten-thousand shares and amount to 0.01 ten-thousand CNY; half-print-step tolerance fixed before provider-value comparison. Footer covers all trading methods.',
            'probe_seen_before_freeze': '002363/2024-09-18 official row only; not a blind statistical certification',
            'phase1_complete': False}
    write(PLAN, plan)
    print(json.dumps({'plan_sha256': digest(PLAN), 'logical_requests': 90, 'registered_cells': 540}))


def collect(plan, store):
    for path, expected in plan['source_sha256'].items():
        assert digest(path) == expected
    result = {'plan_sha256': digest(PLAN), 'plan_artifact_id': store.put_bytes(plan['scope'], PLAN.read_bytes()),
              'started_at': datetime.now(timezone.utc).isoformat(), 'results': [], 'retries': 0, 'cache_hits': 0}
    started, last_start = time.monotonic(), None
    for group in plan['groups']:
        for code in group['codes']:
            for day in group['dates']:
                entry = {'group': group['label'], 'code': code, 'date': day, 'attempts': 0, 'retries': 0}
                if time.monotonic() - started > plan['overall_deadline_seconds']:
                    entry.update(status='not_attempted', reason='overall_deadline')
                else:
                    if last_start is not None:
                        time.sleep(max(0, plan['min_interval_seconds']-(time.monotonic()-last_start)))
                    params = dict(plan['params'], txtDMorJC=code, txtBeginDate=day)
                    url = plan['url'] + '?' + urlencode(params)
                    validate(url)
                    entry.update(url=url, attempts=1, started_at=datetime.now(timezone.utc).isoformat())
                    last_start = time.monotonic()
                    try:
                        run = subprocess.run([sys.executable, str(Path(__file__).with_name('discover_p17_szse_history.py').resolve()),
                                              '--child', url], capture_output=True, timeout=16, check=False)
                        if run.returncode:
                            entry.update(status='failed', worker_exit=run.returncode)
                        else:
                            assert len(run.stdout) <= 3*1024*1024
                            entry['artifact_id'] = store.put_bytes(plan['scope'], run.stdout)
                            body = json.loads(run.stdout)
                            tab = next(t for t in body if t['metadata']['tabkey'] == 'tab1')
                            rows = tab['data']; metadata = tab['metadata']
                            assert tab['error'] is None and metadata['catalogid'] == '1815_stock'
                            assert metadata['pageno'] == metadata['pagecount'] == metadata['recordcount'] == len(rows) == 1
                            assert rows[0]['zqdm'] == code and rows[0]['jyrq'] == day
                            entry.update(status='collected', http_status=200, row_count=1)
                    except Exception as exc:
                        entry.update(status='failed', error_type=type(exc).__name__)
                    entry['finished_at'] = datetime.now(timezone.utc).isoformat()
                result['results'].append(entry)
                if len(result['results']) % 10 == 0 or entry['status'] != 'collected':
                    print(json.dumps({'completed': len(result['results']), 'status_counts': dict(Counter(e['status'] for e in result['results']))}), flush=True)
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    result['http_attempts'] = sum(e['attempts'] for e in result['results'])
    assert len(result['results']) == plan['logical_requests']
    write(ROOT/'collection.json', result)
    return result


def compare(plan, collected, store):
    assert collected['plan_sha256'] == digest(PLAN)
    assert store.get(plan['scope'], collected['plan_artifact_id']) == PLAN.read_bytes()
    refs = {}
    for entry in collected['results']:
        key = entry['group'], entry['code'], entry['date']
        assert key not in refs
        refs[key] = None
        if entry['status'] == 'collected':
            body = json.loads(store.get(plan['scope'], entry['artifact_id']))
            tab = next(t for t in body if t['metadata']['tabkey'] == 'tab1')
            m = tab['metadata']; rows = tab['data']
            assert tab['error'] is None and m['catalogid'] == '1815_stock'
            assert m['recordcount'] == m['pagecount'] == m['pageno'] == len(rows) == 1
            assert rows[0]['zqdm'] == entry['code'] and rows[0]['jyrq'] == entry['date']
            assert m['cols']['cjgs'] == '成交量<br>(万股)' and m['cols']['cjje'] == '成交金额<br>(万元)'
            for rule in plan['rules'].values():
                number = Decimal(rows[0][rule['source_field']].replace(',', ''))
                assert number.is_finite() and number.as_tuple().exponent == -2
            refs[key] = rows[0], entry['artifact_id']
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    cells = []
    for group in plan['groups']:
        access = AccessContext(group['original_scope'], frozenset({'tushare'}))
        after = datetime.fromisoformat(group['finished_at']) + timedelta(seconds=1)
        ctx = QueryContext(access, group['snapshot_id'], after, PITMode.SYSTEM)
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, db, ArtifactStore(group['original_artifacts']))
            for code in group['codes']:
                req = DataRequest(Security(code, 'SZSE'), Dataset.MARKET_DAILY,
                                  date.fromisoformat(group['window']['start']), date.fromisoformat(group['window']['end']))
                records = {r.period.isoformat(): r for r in service.query(req, ctx).records}
                for record in records.values():
                    for aid in record.artifact_ids:
                        service.evidence(req, ctx, record.record_id, aid)
                for day in group['dates']:
                    record = records.get(day)
                    reference = refs[group['label'], code, day]
                    metrics = {m.name: m.value for m in record.metrics} if record else {}
                    for name, rule in plan['rules'].items():
                        cell = {'group': group['label'], 'code': code, 'date': day, 'field': name,
                                'record_id': record.record_id if record else None}
                        if record is None:
                            cell['status'] = 'missing_provider'
                        elif metrics.get(name) is None:
                            cell['status'] = 'provider_null'
                        elif reference is None:
                            cell['status'] = 'missing_reference'
                        else:
                            row, aid = reference
                            expected = Decimal(row[rule['source_field']].replace(',', '')) * Decimal(rule['multiplier'])
                            delta = metrics[name] - expected
                            cell.update(reference_artifact_id=aid, actual=str(metrics[name]), reference=str(expected),
                                        difference=str(delta), tolerance=rule['tolerance'], exact=delta == 0,
                                        status='match' if abs(delta) <= Decimal(rule['tolerance']) else 'mismatch')
                        cells.append(cell)
    assert len(cells) == plan['registered_cells']
    assert len({(c['group'], c['code'], c['date'], c['field']) for c in cells}) == len(cells)
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'plan_sha256': digest(PLAN),
            'registered_cells': len(cells), 'status_counts': dict(Counter(c['status'] for c in cells)),
            'groups': {g['label']: dict(Counter(c['status'] for c in cells if c['group'] == g['label'])) for g in plan['groups']},
            'exact_matches': sum(c.get('exact', False) for c in cells), 'cells': cells,
            'historical_publication_not_upgraded': True, 'whole_market_statistical_certification': False, 'phase1_complete': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare(); return 0
    plan = json.loads(PLAN.read_bytes()); ROOT.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(ROOT/'artifacts')
    if args.collect:
        if (ROOT/'collection.json').exists():
            raise ValueError('collection exists; cannot overwrite frozen evidence')
        collected = collect(plan, store)
        print(json.dumps({'registered_requests': 90, 'http_attempts': collected['http_attempts'],
                          'status_counts': dict(Counter(e['status'] for e in collected['results']))})); return 0
    result = compare(plan, json.loads((ROOT/'collection.json').read_bytes()), store)
    path = ROOT/'comparison.json'
    if args.verify_only:
        prior = json.loads(path.read_bytes())
        assert {k:v for k,v in prior.items() if k != 'checked_at'} == {k:v for k,v in result.items() if k != 'checked_at'}
    else:
        write(path, result)
    print(json.dumps({k:v for k,v in result.items() if k != 'cells'}))
    return 2 if result['status_counts'].get('mismatch', 0) else 0


if __name__ == '__main__':
    raise SystemExit(main())
