"""Collect/replay official exchange references for the original frozen SSE rows."""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from exchange_http import get_reference

from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

PLAN = Path('evaluation/p17_20261001_sse_reference_plan.json')
ROOT = Path('.artifacts/p17_20261001/sse_market')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    plan_bytes = PLAN.read_bytes()
    plan = json.loads(plan_bytes)
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    ROOT.mkdir(parents=True, exist_ok=True)
    artifacts = ArtifactStore(ROOT/'artifacts')
    target = ROOT/'collection.json'
    if args.verify_only:
        collection = json.loads(target.read_text(encoding='utf-8'))
        assert collection['plan_sha256'] == plan_sha
    else:
        if target.exists():
            raise ValueError('exchange reference collection already exists')
        assert hashlib.sha256(Path(plan['renderer_path']).read_bytes()).hexdigest() == plan['renderer_sha256']
        aid = artifacts.put_bytes(plan['reference_scope'], plan_bytes)
        collection = {'plan_sha256':plan_sha, 'plan_artifact_id':aid, 'results':[]}
        for item in plan['references']:
            entry = {'code':item['code'], 'url':item['url'], 'started_at':datetime.now(timezone.utc).isoformat()}
            try:
                content = get_reference(item['url'],plan['params'],plan['page_url'])
                entry['http_status'] = 200
                body = json.loads(content, parse_float=Decimal)
                assert body['code'] == item['code']
                entry.update(status='collected', artifact_id=artifacts.put_bytes(
                    plan['reference_scope'], content), row_count=len(body['kline']))
            except Exception as exc:
                entry.update(status='failed', error_type=type(exc).__name__)
            entry['finished_at'] = datetime.now(timezone.utc).isoformat()
            collection['results'].append(entry)
            print(json.dumps(entry), flush=True)
        with target.open('x',encoding='utf-8') as stream:
            json.dump(collection, stream, indent=2)
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    access = AccessContext(plan['original_scope'], frozenset({'tushare'}))
    after = datetime.fromisoformat(plan['original_finished_at'])+timedelta(seconds=1)
    comparisons, failures = [], []
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, db,
                              ArtifactStore('.artifacts/p17_20260930/artifacts'))
        for entry in collection['results']:
            if entry['status'] != 'collected':
                failures.append({'code':entry['code'], 'reason':'reference_fetch_failed'})
                continue
            body = json.loads(artifacts.get(plan['reference_scope'], entry['artifact_id']), parse_float=Decimal)
            assert body['code'] == entry['code']
            rows = body['kline']
            assert len(rows) == entry['row_count'] < 600 and all(len(row)==7 for row in rows)
            indexed = {str(row[0]):row for row in rows}
            assert len(indexed) == len(rows)
            for window in plan['windows']:
                req = DataRequest(Security(entry['code'], 'SSE'), Dataset.MARKET_DAILY,
                                  date.fromisoformat(window['start']), date.fromisoformat(window['end']))
                records = service.query(req, QueryContext(access, plan['original_snapshot'], after, PITMode.SYSTEM)).records
                for record in records:
                    key = record.period.strftime('%Y%m%d')
                    if key not in indexed:
                        failures.append({'code':entry['code'], 'period':key, 'reason':'date_not_in_reference'})
                        continue
                    reference = indexed[key]
                    for metric in record.metrics:
                        rule = plan['fields'][metric.name]
                        expected = Decimal(str(reference[rule['position']]))
                        delta = metric.value-expected
                        comparisons.append({'code':entry['code'], 'date':record.period.isoformat(),
                            'field':metric.name, 'actual':str(metric.value), 'reference':str(expected),
                            'difference':str(delta), 'tolerance':rule['tolerance'],
                            'match':abs(delta)<=Decimal(rule['tolerance']), 'record_id':record.record_id,
                            'reference_artifact_id':entry['artifact_id']})
    expected_cells = len(plan['references'])*plan['original_days_per_stock']*len(plan['fields'])
    matched = sum(c['match'] for c in comparisons)
    mismatches = [c for c in comparisons if not c['match']]
    output = {'checked_at':datetime.now(timezone.utc).isoformat(), 'plan_sha256':plan_sha,
              'original_snapshot':plan['original_snapshot'], 'expected_cells':expected_cells,
              'compared_cells':len(comparisons), 'matched_cells':matched, 'mismatch_count':len(mismatches),
              'missing_count':len(failures), 'failures':failures, 'comparisons':comparisons,
              'all_registered_cells_match':len(comparisons)==expected_cells and matched==expected_cells and not failures,
              'all_markets_verified':False, 'historical_release_verified':False}
    path = ROOT/'comparison.json'
    if args.verify_only:
        prior = json.loads(path.read_text(encoding='utf-8'))
        assert {k:v for k,v in prior.items() if k!='checked_at'} == {k:v for k,v in output.items() if k!='checked_at'}
    else:
        with path.open('x',encoding='utf-8') as stream:
            json.dump(output, stream, indent=2)
    print(json.dumps({k:v for k,v in output.items() if k not in {'comparisons','failures'}}))
    if mismatches:
        print(json.dumps({'mismatch_examples':mismatches[:6]}))
    return 0 if output['all_registered_cells_match'] else 2


if __name__=='__main__':
    raise SystemExit(main())
