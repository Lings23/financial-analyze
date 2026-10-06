"""Compare independent official filing transcriptions to the original frozen pilot."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only',action='store_true')
    args = parser.parse_args()
    root = Path('.artifacts/p17_20261001')
    original_root = Path('.artifacts/p17_20260930')
    run = json.loads((original_root/'run.json').read_text(encoding='utf-8'))
    plan = json.loads(Path('evaluation/p17_20261001_reference_plan.json').read_text(encoding='utf-8'))
    ref_path = Path('evaluation/p17_20261001_reference_values.json')
    refs = json.loads(ref_path.read_text(encoding='utf-8'))
    prior_quality = json.loads((original_root/'comparison.json').read_text(encoding='utf-8'))
    snapshot = run['results'][-1]['snapshot_id']
    assert snapshot==plan['original_snapshot']
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    access = AccessContext(run['scope'],frozenset({'tushare'}))
    comparisons, missing = [], []
    candidates = {(e['code'],e['period']):e for e in plan['requests']}
    page_cache = {}
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(),executor,db,ArtifactStore(original_root/'artifacts'))
        for ref in refs['financial']:
            registered = candidates[(ref['code'],ref['period'])]
            req = DataRequest(Security(ref['code'],registered['exchange']),Dataset.FINANCIAL_INCOME,
                              date.fromisoformat(ref['period']),date.fromisoformat(ref['period']))
            query = service.query(req,QueryContext(access,snapshot,
                       datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1),PITMode.SYSTEM))
            assert len(query.records)==1
            record = query.records[0]
            assert record.record_id==registered['original_record_id']
            values = {m.name:m.value for m in record.metrics}
            source = ref['source']
            pdf = Path(source['path'])
            assert hashlib.sha256(pdf.read_bytes()).hexdigest()==source['sha256']
            for field,item in ref['values'].items():
                key = (str(pdf),item['pdf_page'])
                if key not in page_cache:
                    page = subprocess.run(['pdftotext','-enc','UTF-8','-layout','-f',str(item['pdf_page']),
                                           '-l',str(item['pdf_page']),str(pdf),'-'],
                                           check=True,capture_output=True,timeout=15).stdout.decode('utf-8')
                    page_cache[key] = page
                text = page_cache[key].replace(',','').replace(' ','')
                assert item['printed'] in text, 'locked transcription absent from its original PDF page'
                expected = Decimal(item['printed'])*Decimal(item['multiplier'])
                difference = values[field]-expected
                comparisons.append({'dataset':'financial_income','code':ref['code'],
                    'exchange':registered['exchange'],'period':ref['period'],'field':field,
                    'actual':str(values[field]),'reference':str(expected),'difference':str(difference),
                    'tolerance':item['tolerance_cny'],'match':abs(difference)<=Decimal(item['tolerance_cny']),
                    'record_id':record.record_id,'source_url':source['source_url'],
                    'pdf_sha256':source['sha256'],'pdf_page':item['pdf_page'],
                    'official_index_date':source['source_date'],'tushare_ann_date':registered['announcement_date']})
            for item in ref['uncomparable_fields']:
                missing.append({'code':ref['code'],'period':ref['period'],**item})
    assert len(comparisons)+len(missing)==len(candidates)*3==54
    market = [c for c in prior_quality['comparisons'] if c['dataset']=='market_daily']
    assert len(market)==27 and all(c['match'] for c in market)
    total_cells = prior_quality['metric_cells']
    output = {'checked_at':datetime.now(timezone.utc).isoformat(),'snapshot_id':snapshot,
              'reference_values_sha256':hashlib.sha256(ref_path.read_bytes()).hexdigest(),
              'registered_financial_cells':54,'independent_financial_compared':len(comparisons),
              'independent_financial_matched':sum(c['match'] for c in comparisons),
              'uncomparable_financial_cells':len(missing),
              'financial_comparisons':comparisons,'financial_missing':missing,
              'financial_comparison_counts_by_exchange':dict(Counter(c['exchange'] for c in comparisons)),
              'financial_comparison_counts_by_field':dict(Counter(c['field'] for c in comparisons)),
              'previous_independent_market_compared':len(market),'original_metric_cells':total_cells,
              'combined_independent_compared':len(market)+len(comparisons),
              'combined_independent_matched':sum(c['match'] for c in market+comparisons),
              'remaining_uncompared_cells':total_cells-len(market)-len(comparisons),
              'all_compared_values_match':all(c['match'] for c in comparisons),
              'market_wide_accuracy_verified':False,'historical_release_verified':False}
    path = root/'reference-comparison.json'
    if args.verify_only:
        prior = json.loads(path.read_text(encoding='utf-8'))
        assert {k:v for k,v in prior.items() if k!='checked_at'}=={k:v for k,v in output.items() if k!='checked_at'}
    else:
        with path.open('x',encoding='utf-8') as stream: json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k not in {'financial_comparisons','financial_missing'}},ensure_ascii=False))
    return 0 if output['all_compared_values_match'] else 2


if __name__=='__main__': raise SystemExit(main())
