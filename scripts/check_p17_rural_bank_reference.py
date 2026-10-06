"""Supplement independently frozen filing fields; retain all 225 sample cells."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess

from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

ROOT = Path('.artifacts/p17_20261001/formal')
SUB = ROOT / 'rural_bank_reference'
PLAN = Path('evaluation/p17_20261001_rural_bank_reference_plan.json')
RULE = Path('evaluation/p17_20261001_rural_bank_reference_values.json')


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def compact(text): return ''.join(text.split())


def main():
    global SUB, PLAN, RULE
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--case', choices=('rural-bank', 'konka'), default='rural-bank')
    args = parser.parse_args()
    if args.case == 'konka':
        SUB = ROOT / 'konka_reference'
        PLAN = Path('evaluation/p17_20261001_konka_reference_plan.json')
        RULE = Path('evaluation/p17_20261001_konka_reference_values.json')
    plan, rule = json.loads(PLAN.read_bytes()), json.loads(RULE.read_bytes())
    collection = json.loads((SUB / 'collection.json').read_bytes())
    assert collection['plan_sha256'] == sha(PLAN) == rule['plan_sha256']
    assert sha(SUB / 'collection.json') == rule['collection_sha256']
    assert plan['original_plan_sha256'] == sha(Path('evaluation/p17_20261001_formal_financial_reference_plan.json'))
    discovery = ROOT / ('bse_identity_discovery/run.json' if args.case == 'konka' else 'reference_gap_discovery/run.json')
    assert plan['discovery_run_sha256'] == sha(discovery)
    assert collection['scope'] == plan['scope'] and len(collection['requests']) == len(plan['requests']) == 1
    entry, item = collection['requests'][0], plan['requests'][0]
    expected_files = 2 if args.case == 'konka' else 1
    assert entry['request'] == item and entry['status'] == 'collected' and len(entry['files']) == expected_files
    source = next(f for f in entry['files'] if f['record_id'] == rule['source_record_id'])
    assert source['sha256'] == rule['source_pdf_sha256'] and source['record_id'] == rule['source_record_id']
    pdf = Path(source['path']).resolve()
    assert pdf.is_relative_to(SUB.resolve()) and sha(pdf) == source['sha256']
    after = datetime.fromisoformat(collection['finished_at']) + timedelta(seconds=1)
    req = DomainRequest(Subject('equity', item['code'], item['exchange']), DomainDataset.ANNOUNCEMENT,
                        date.fromisoformat(item['start_date']), date.fromisoformat(item['end_date']), item['selector'])
    access = AccessContext(plan['scope'], frozenset({'cninfo'}))
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    checks = []
    with ProviderExecutor() as executor:
        cn = DataService(ProviderRegistry(), executor, db, ArtifactStore(SUB / 'artifacts'))
        assert cn.artifacts.get(access.scope, collection['plan_artifact']) == PLAN.read_bytes()
        ctx = QueryContext(access, entry['snapshot_id'], after, PITMode.SYSTEM)
        docs = cn.query(req, ctx).records
        assert len(docs) == expected_files
        assert {d.record_id for d in docs} == {f['record_id'] for f in entry['files']}
        doc = next(d for d in docs if d.record_id == source['record_id'])
        assert doc.source_url == source['source_url'] and dict(doc.attributes)['title'] == source['title']
        assert cn.evidence(req, ctx, doc.record_id, source['sha256']) == pdf.read_bytes()
        for f in entry['files']:
            exported = Path(f['path']).resolve()
            assert exported.is_relative_to(SUB.resolve())
            content = cn.evidence(req, ctx, f['record_id'], f['sha256'])
            assert content == exported.read_bytes() and hashlib.sha256(content).hexdigest() == f['sha256']
        index = json.loads(cn.evidence(req, ctx, doc.record_id, source['source_index_artifact']))
        assert index['total'] == expected_files and len(index['rows']) == expected_files
        assert all(r['secCode'] == item['code'] for r in index['rows'])
        assert not cn.query(req, QueryContext(access, entry['snapshot_id'], doc.available_at-timedelta(microseconds=1))).records
        denied = QueryContext(AccessContext(access.scope, frozenset({'tushare'})), entry['snapshot_id'], after)
        assert not cn.query(req, denied).records
        for bad in (denied, QueryContext(AccessContext(access.scope+'-other', access.allowed_providers), entry['snapshot_id'], after)):
            try: cn.evidence(req, bad, doc.record_id, source['sha256'])
            except PermissionDenied: pass
            else: raise AssertionError('unauthorized PDF read accepted')
        pages = {}
        for page, anchors in rule['page_anchors'].items():
            text = subprocess.run(['pdftotext','-enc','UTF-8','-layout','-f',page,'-l',page,str(pdf),'-'],
                                  capture_output=True, check=True, timeout=20).stdout.decode('utf8')
            pages[int(page)] = compact(text)
            assert all(compact(anchor) in pages[int(page)] for anchor in anchors)
        run = json.loads((ROOT/'run.json').read_bytes())
        ts = DataService(ProviderRegistry(), executor, db, ArtifactStore(ROOT/'artifacts'))
        period = date.fromisoformat(item['period'])
        tsreq = DataRequest(Security(item['code'], item['exchange']), Dataset.FINANCIAL_INCOME, period, period)
        tsctx = QueryContext(AccessContext(run['scope'], frozenset({'tushare'})), item['original_snapshot'], after)
        records = ts.query(tsreq, tsctx).records
        assert len(records) == 1 and records[0].record_id == item['original_record_id']
        ts.evidence(tsreq, tsctx, records[0].record_id)
        actual = {m.name:m.value for m in records[0].metrics}
        fields = set(item['fields']) if args.case == 'konka' else {'revenue', 'net_income_parent'}
        assert set(rule['values']) == fields
        for field, value in rule['values'].items():
            assert compact(value['row_excerpt']) in pages[value['pdf_page']]
            printed_columns = re.findall(r'[-－]?\d{1,3}(?:,\d{3})+(?:\.\d+)?', value['row_excerpt'])
            assert printed_columns[rule.get('column_index', 0)] == value['printed']
            expected = Decimal(value['printed'].replace(',', '')) * Decimal(rule['multiplier'])
            assert actual[field] is not None
            delta = actual[field] - expected
            checks.append({'code':item['code'],'exchange':item['exchange'],'period':item['period'],'field':field,
                           'actual':str(actual[field]),'reference':str(expected),'difference':str(delta),
                           'tolerance_cny':rule['tolerance_cny'],'match':abs(delta)<=Decimal(rule['tolerance_cny']),
                           'record_id':records[0].record_id,'source_pdf_sha256':source['sha256'],
                           'source_url':source['source_url'],'pdf_page':value['pdf_page'],'header_page':rule.get('header_page',3)})
    previous_path = ROOT/'rural_bank_reference/comparison.json' if args.case == 'konka' else ROOT/'financial_values/manual/comparison.json'
    assert sha(previous_path) == rule['previous_comparison_sha256']
    previous = json.loads(previous_path.read_bytes())
    previous_count = 182 if args.case == 'konka' else 180
    assert previous['registered_cells'] == 225 and previous['independent_compared'] == previous_count
    key = lambda e: (e['code'],e['period'],e['field'])
    new_keys = {key(e) for e in checks}
    added_count = 3 if args.case == 'konka' else 2
    assert len(new_keys) == added_count and not new_keys.intersection(key(e) for e in previous['comparisons'])
    assert new_keys <= {key(e) for e in previous['missing']}
    compared = previous['comparisons'] + checks
    missing = [e for e in previous['missing'] if key(e) not in new_keys]
    for e in missing:
        if e['code'] == item['code'] and e['period'] == item['period']:
            assert e['field'] == 'total_revenue'
            e['reason'] = 'no_independent_printed_total_revenue_in_annual_summary'
    assert len(compared) == previous_count+added_count and len(compared)+len(missing) == 225
    output = {'checked_at':utcnow().isoformat(),'qualification_sha256':sha(RULE),'registered_cells':225,
              'independent_compared':len(compared),'matched':sum(e['match'] for e in compared),
              'mismatched':sum(not e['match'] for e in compared),'unverified':len(missing),
              'counts_by_exchange':dict(Counter(e['exchange'] for e in compared)),
              'counts_by_field':dict(Counter(e['field'] for e in compared)),
              'snapshot_pdf_scope_source_pit_authorization_passed':True,
              'historical_publication_not_upgraded':True,'phase1_complete':False,
              'comparisons':compared,'missing':missing}
    target = SUB/'comparison.json'
    if args.verify_only:
        prior = json.loads(target.read_bytes())
        assert {k:v for k,v in prior.items() if k!='checked_at'} == {k:v for k,v in output.items() if k!='checked_at'}
    else:
        with target.open('x', encoding='utf8') as stream: json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k not in {'comparisons','missing'}}))
    if any(not e['match'] for e in checks): raise AssertionError('independent financial comparison differs')


if __name__ == '__main__': main()
