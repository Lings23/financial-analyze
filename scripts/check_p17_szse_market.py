"""Official SZSE recent daily reference; older missing dates remain explicit."""
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

PLAN = Path('evaluation/p17_20261001_szse_reference_plan.json')
ROOT = Path('.artifacts/p17_20261001/szse_market')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only',action='store_true')
    args = parser.parse_args()
    raw_plan = PLAN.read_bytes()
    plan = json.loads(raw_plan)
    sha = hashlib.sha256(raw_plan).hexdigest()
    ROOT.mkdir(parents=True,exist_ok=True)
    store = ArtifactStore(ROOT/'artifacts')
    collection_path, comparison_path = ROOT/'collection.json', ROOT/'comparison.json'
    if args.verify_only:
        collection = json.loads(collection_path.read_text(encoding='utf-8'))
        assert sha == collection['plan_sha256']
    else:
        if collection_path.exists():
            raise ValueError('official reference evidence exists')
        for path, expected in plan['source_sha256'].items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
        collection = {'plan_sha256':sha,'plan_artifact_id':store.put_bytes(plan['reference_scope'],raw_plan),'results':[]}
        for code in plan['codes']:
            entry = {'code':code,'started_at':datetime.now(timezone.utc).isoformat()}
            try:
                content = get_reference(plan['url'],dict(plan['params'],code=code),plan['page_url'])
                entry['http_status'] = 200
                body = json.loads(content)
                assert body['code']=='0' and body['data']['code']==code
                entry.update(status='collected',artifact_id=store.put_bytes(
                    plan['reference_scope'],content),row_count=len(body['data']['picupdata']))
            except Exception as exc:
                entry.update(status='failed',error_type=type(exc).__name__)
            entry['finished_at'] = datetime.now(timezone.utc).isoformat()
            collection['results'].append(entry)
            print(json.dumps(entry),flush=True)
        with collection_path.open('x',encoding='utf-8') as stream:
            json.dump(collection,stream,indent=2)
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    access = AccessContext(plan['original_scope'],frozenset({'tushare'}))
    ctx = QueryContext(access,plan['original_snapshot'],datetime.fromisoformat(
        plan['original_finished_at'])+timedelta(seconds=1),PITMode.SYSTEM)
    comparisons, missing = [], []
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(),executor,db,ArtifactStore('.artifacts/p17_20260930/artifacts'))
        for entry in collection['results']:
            indexed = {}
            if entry['status']=='collected':
                body = json.loads(store.get(plan['reference_scope'],entry['artifact_id']),parse_float=Decimal)
                assert body['code']=='0' and body['data']['code']==entry['code']
                upper, lower = body['data']['picupdata'],body['data']['picdowndata']
                assert len(upper)==len(lower)==entry['row_count'] and all(len(row)==9 for row in upper)
                assert all(a[0]==b[0] and a[7]==b[1] for a,b in zip(upper,lower))
                indexed = {row[0]:row for row in upper}
                assert len(indexed)==len(upper)
            for window in plan['windows']:
                req = DataRequest(Security(entry['code'],'SZSE'),Dataset.MARKET_DAILY,
                                  date.fromisoformat(window['start']),date.fromisoformat(window['end']))
                for record in service.query(req,ctx).records:
                    reference = indexed.get(record.period.isoformat())
                    for metric in record.metrics:
                        if reference is None:
                            missing.append({'code':entry['code'],'date':record.period.isoformat(),
                                            'field':metric.name,'reason':'not_in_official_response'})
                            continue
                        rule = plan['fields'][metric.name]
                        expected = Decimal(str(reference[rule['position']]))*Decimal(rule['multiplier'])
                        delta = metric.value-expected
                        comparisons.append({'code':entry['code'],'date':record.period.isoformat(),'field':metric.name,
                            'actual':str(metric.value),'reference':str(expected),'difference':str(delta),
                            'tolerance':rule['tolerance'],'match':abs(delta)<=Decimal(rule['tolerance']),
                            'record_id':record.record_id,'reference_artifact_id':entry['artifact_id']})
    output = {'checked_at':datetime.now(timezone.utc).isoformat(),'plan_sha256':sha,
              'original_snapshot':plan['original_snapshot'],'registered_cells':204,
              'compared_cells':len(comparisons),'matched_cells':sum(c['match'] for c in comparisons),
              'missing_cells':len(missing),'missing':missing,'comparisons':comparisons,
              'all_compared_cells_match':all(c['match'] for c in comparisons),
              'full_registered_coverage_verified':not missing and len(comparisons)==204}
    assert len(comparisons)+len(missing)==204
    if args.verify_only:
        prior = json.loads(comparison_path.read_text(encoding='utf-8'))
        assert {k:v for k,v in prior.items() if k!='checked_at'}=={k:v for k,v in output.items() if k!='checked_at'}
    else:
        with comparison_path.open('x',encoding='utf-8') as stream:
            json.dump(output,stream,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k not in {'comparisons','missing'}}))
    mismatches = [c for c in comparisons if not c['match']]
    if mismatches:
        print(json.dumps({'mismatch_examples':mismatches[:6]}))
    return 0 if output['all_compared_cells_match'] else 2


if __name__=='__main__':
    raise SystemExit(main())
