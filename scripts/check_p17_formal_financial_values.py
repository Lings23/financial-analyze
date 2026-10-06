"""Compare reviewed independent original-table values with fixed source records."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

ROOT = Path('.artifacts/p17_20261001/formal')
REVIEW = Path('evaluation/p17_20261001_formal_financial_values_review.json')


def compact(text): return ''.join(text.split()).replace('－','-').replace('—','-').replace('–','-')


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');parser.add_argument('--review',type=Path,default=REVIEW);args=parser.parse_args()
    rule = json.loads(args.review.read_bytes()); candidate_path = Path(rule.get('candidates_path',str(ROOT/'financial_values/candidates.json')))
    assert candidate_path.resolve().is_relative_to((ROOT/'financial_values').resolve())
    assert hashlib.sha256(candidate_path.read_bytes()).hexdigest() == rule['candidates_sha256']
    refs = json.loads(candidate_path.read_bytes())
    finplan_path = Path(rule.get('reference_plan_path','evaluation/p17_20261001_formal_financial_reference_plan.json'))
    finplan = json.loads(finplan_path.read_bytes())
    collection_path = Path(rule.get('collection_path',str(ROOT/'financial_references/collection.json')))
    assert collection_path.resolve().is_relative_to(ROOT.resolve())
    collection = json.loads(collection_path.read_text(encoding='utf8'))
    assert collection['plan_sha256'] == hashlib.sha256(finplan_path.read_bytes()).hexdigest()
    assert hashlib.sha256(collection_path.read_bytes()).hexdigest() == refs['collection_sha256']
    run = json.loads((ROOT/'run.json').read_text(encoding='utf8'))
    requests = {(e['code'],e['period']):e for e in finplan['requests']}
    source_entries = {(e['request']['code'],e['request']['period']):e for e in collection['requests']}
    selected = {(e['code'],e['period'],e['field']) for e in rule['reviewed']}; assert len(selected) == len(rule['reviewed']) == rule.get('expected_count',142)
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    ts_access = AccessContext(run['scope'],frozenset({'tushare'}));cn_access = AccessContext(collection['scope'],frozenset({'cninfo'}))
    after = datetime.fromisoformat(collection['finished_at'])+timedelta(seconds=1)
    page_cache,source_cache={},{}; compared,missing=[],[]
    with ProviderExecutor() as executor:
        ts = DataService(ProviderRegistry(),executor,db,ArtifactStore(ROOT/'artifacts'))
        cn = DataService(ProviderRegistry(),executor,db,ArtifactStore(collection_path.parent/'artifacts'))
        for ref in refs['periods']:
            registered = requests[(ref['code'],ref['period'])];period = date.fromisoformat(ref['period'])
            req = DataRequest(Security(ref['code'],ref['exchange']),Dataset.FINANCIAL_INCOME,period,period)
            ctx = QueryContext(ts_access,registered['original_snapshot'],after,PITMode.SYSTEM)
            records = ts.query(req,ctx).records;assert len(records)==1 and records[0].record_id==registered['original_record_id']
            record = records[0];ts.evidence(req,ctx,record.record_id);actual={m.name:m.value for m in record.metrics}
            for field in finplan['requests'][0]['fields']:
                key=ref['code'],ref['period'],field
                if key not in selected:
                    missing.append({'code':ref['code'],'exchange':ref['exchange'],'period':ref['period'],'field':field,
                                    'reason':ref['missing'].get(field,{}).get('reason','not_reviewed')});continue
                value=ref['values'][field];source=value['source'];pdf=Path(source['path'])
                cachekey=(ref['code'],ref['period'],source['record_id'])
                if cachekey not in source_cache:
                    entry=source_entries[(ref['code'],ref['period'])]
                    cnreq=DomainRequest(Subject('equity',ref['code'],ref['exchange']),DomainDataset.ANNOUNCEMENT,
                        date.fromisoformat(registered['start_date']),date.fromisoformat(registered['end_date']),registered['selector'])
                    cnctx=QueryContext(cn_access,entry['snapshot_id'],after,PITMode.SYSTEM)
                    doc=next(r for r in cn.query(cnreq,cnctx).records if r.record_id==source['record_id'])
                    data=cn.evidence(cnreq,cnctx,doc.record_id,source['sha256'])
                    assert data==pdf.read_bytes() and hashlib.sha256(data).hexdigest()==source['sha256']
                    assert doc.source_url==source['source_url'] and dict(doc.attributes)['title']==source['title']
                    if 'identity_manifest_sha256' in finplan:
                        index=json.loads(cn.evidence(cnreq,cnctx,doc.record_id))
                        proof=index['identity_qualification']
                        assert hashlib.sha256(proof['reviewed_manifest_utf8'].encode('utf8')).hexdigest()==proof['sha256']==finplan['identity_manifest_sha256']
                        assert proof['availability_not_upgraded'] is True
                    source_cache[cachekey]=True
                for page in {value['pdf_page'],value['header_page']}:
                    pk=(str(pdf),page)
                    if pk not in page_cache:
                        page_cache[pk]=subprocess.run(['pdftotext','-enc','UTF-8','-layout','-f',str(page),'-l',str(page),str(pdf),'-'],
                            capture_output=True,check=True,timeout=20).stdout.decode('utf8')
                body=compact(page_cache[(str(pdf),value['pdf_page'])])
                assert compact(value['row_excerpt']) in body and compact(value['printed']) in body
                # A cross-page heading is checked on its own page and the captured
                # period/unit header is retained; number occurrence alone cannot qualify.
                heading=value.get('table_heading','合并利润表')
                assert heading in {'合并利润表','合并及银行利润表'}
                header_text=compact(page_cache[(str(pdf),value['header_page'])])
                assert heading in header_text
                assert all(compact(a) in header_text for a in value.get('extra_header_anchors',[]))
                if rule.get('verify_source_columns'):
                    from prepare_p17_formal_financial_values import NUM
                    assert compact(value['header_excerpt']) in header_text
                    assert NUM.findall(value['row_excerpt'])[value.get('column_index',0)] == value['printed']
                expected=Decimal(value['decimal'])*Decimal(value['multiplier']);assert str(expected)==value['value_cny']
                if actual[field] is None:
                    missing.append({'code':ref['code'],'exchange':ref['exchange'],'period':ref['period'],'field':field,'reason':'provider_null'});continue
                delta=actual[field]-expected; tolerance=Decimal(value['tolerance_cny'])
                compared.append({'code':ref['code'],'exchange':ref['exchange'],'period':ref['period'],'field':field,
                    'actual':str(actual[field]),'reference':str(expected),'difference':str(delta),'tolerance_cny':str(tolerance),
                    'match':abs(delta)<=tolerance,'record_id':record.record_id,'source_pdf_sha256':source['sha256'],
                    'source_url':source['source_url'],'pdf_page':value['pdf_page'],'header_page':value['header_page']})
    assert len(compared)+len(missing)==len(refs['periods'])*3 and len(compared)==len(selected)
    if 'previous_comparison_path' in rule:
        previous_path=Path(rule['previous_comparison_path'])
        assert previous_path.resolve().is_relative_to(ROOT.resolve())
        assert hashlib.sha256(previous_path.read_bytes()).hexdigest()==rule['previous_comparison_sha256']
        prior=json.loads(previous_path.read_bytes());assert prior['registered_cells']==225
        key=lambda e:(e['code'],e['period'],e['field'])
        added={key(e) for e in compared}
        assert len(added)==len(compared) and not added.intersection(key(e) for e in prior['comparisons'])
        assert added <= {key(e) for e in prior['missing']}
        compared=prior['comparisons']+compared
        missing=[e for e in prior['missing'] if key(e) not in added]
    assert len(compared)+len(missing)==225
    output={'checked_at':utcnow().isoformat(),'review_sha256':hashlib.sha256(args.review.read_bytes()).hexdigest(),
            'registered_cells':225,'independent_compared':len(compared),'matched':sum(e['match'] for e in compared),
            'mismatched':sum(not e['match'] for e in compared),'unverified':len(missing),
            'counts_by_exchange':dict(Counter(e['exchange'] for e in compared)),
            'counts_by_field':dict(Counter(e['field'] for e in compared)),
            'all_registered_cells_verified':not missing and all(e['match'] for e in compared),
            'historical_publication_not_upgraded':True,'phase1_complete':False,'comparisons':compared,'missing':missing}
    label=rule.get('comparison_label')
    if label:
        import re
        assert re.fullmatch(r'[a-z][a-z0-9_-]{0,30}',label)
    target=ROOT/'financial_values'/label/'comparison.json' if label else ROOT/'financial_values/comparison.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    if args.verify_only:
        prior=json.loads(target.read_text(encoding='utf8'));assert {k:v for k,v in prior.items() if k!='checked_at'}=={k:v for k,v in output.items() if k!='checked_at'}
    else:
        if target.exists():raise ValueError('financial comparison exists; refusing overwrite')
        with target.open('x',encoding='utf8') as stream:json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k not in {'comparisons','missing'}}))
    if any(not e['match'] for e in compared):print(json.dumps({'mismatches':[e for e in compared if not e['match']]}))


if __name__=='__main__':main()
