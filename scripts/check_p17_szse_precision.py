"""Explicit post-capture precision correction; preserve the stricter failed run."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    root = Path('.artifacts/p17_20261001/szse_market')
    rule_path = Path('evaluation/p17_20261001_szse_precision_rule.json')
    rule_bytes = rule_path.read_bytes()
    rule = json.loads(rule_bytes)
    prior = json.loads((root/'comparison.json').read_text(encoding='utf-8'))
    source_plan = json.loads(Path('evaluation/p17_20261001_szse_reference_plan.json').read_text(encoding='utf-8'))
    assert prior['plan_sha256'] == rule['original_plan_sha256']
    assert hashlib.sha256((root/'comparison.json').read_bytes()).hexdigest() == rule['original_comparison_sha256']
    for path, sha in source_plan['source_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha
    source_store = ArtifactStore(root/'artifacts')
    rule_aid = source_store.put_bytes(source_plan['reference_scope'],rule_bytes)
    collection = json.loads((root/'collection.json').read_text(encoding='utf-8'))
    references = {entry['code']:json.loads(source_store.get(source_plan['reference_scope'],
                   entry['artifact_id']),parse_float=Decimal)['data'] for entry in collection['results']}
    indices = {code:{row[0]:row for row in data['picupdata']} for code,data in references.items()}
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    access = AccessContext(source_plan['original_scope'],frozenset({'tushare'}))
    ctx = QueryContext(access,source_plan['original_snapshot'],datetime.fromisoformat(
        source_plan['original_finished_at'])+timedelta(seconds=1),PITMode.SYSTEM)
    compared, cache = [], {}
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(),executor,db,ArtifactStore('.artifacts/p17_20260930/artifacts'))
        for item in prior['comparisons']:
            key = item['code'],item['date']
            if key not in cache:
                period = date.fromisoformat(item['date'])
                req = DataRequest(Security(item['code'],'SZSE'),Dataset.MARKET_DAILY,period,period)
                records = service.query(req,ctx).records
                assert len(records)==1 and records[0].record_id==item['record_id']
                cache[key] = {m.name:m.value for m in records[0].metrics}
            actual = cache[key][item['field']]
            assert actual == Decimal(item['actual'])
            source = indices[item['code']][item['date']]
            field_rule = source_plan['fields'][item['field']]
            raw = source[field_rule['position']]
            expected = Decimal(str(raw))*Decimal(field_rule['multiplier'])
            assert expected == Decimal(item['reference'])
            tolerance = Decimal(field_rule['tolerance'])
            if item['field']=='volume':
                assert type(raw) is int  # Source is printed to zero decimal 100-share lots.
                tolerance = Decimal(rule['reference_share_quantum'])/2
                assert tolerance == Decimal(rule['volume_tolerance_shares'])
            difference = actual-expected
            compared.append({**item,'difference':str(difference),'tolerance':str(tolerance),
                             'match':abs(difference)<=tolerance,'exact_match':difference==0})
    report = {'checked_at':datetime.now(timezone.utc).isoformat(),'rule_artifact_id':rule_aid,
              'original_snapshot':prior['original_snapshot'],'registered_cells':prior['registered_cells'],
              'compared_cells':len(compared),'matched_cells':sum(c['match'] for c in compared),
              'exact_match_cells':sum(c['exact_match'] for c in compared),'missing_cells':prior['missing_cells'],
              'comparisons':compared,'missing':prior['missing'],
              'precision_rule_corrected_after_capture':True,'full_registered_coverage_verified':False,
              'all_compared_cells_match':all(c['match'] for c in compared)}
    path = root/'comparison-precision.json'
    if path.exists():
        frozen = json.loads(path.read_text(encoding='utf-8'))
        assert {k:v for k,v in frozen.items() if k!='checked_at'} == {k:v for k,v in report.items() if k!='checked_at'}
    else:
        with path.open('x',encoding='utf-8') as stream:
            json.dump(report,stream,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k not in {'comparisons','missing'}}))
    return 0 if report['all_compared_cells_match'] else 2


if __name__=='__main__':
    raise SystemExit(main())
