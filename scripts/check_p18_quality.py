"""Recompute P1.8 real evidence checks; never infer market-wide accuracy."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from run_p18_acceptance import ROOT, request
from stock_research.models import AccessContext, PITMode, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.documents import article_text
from stock_research.providers.executor import ProviderExecutor
from stock_research.providers.tushare_domains import MAPS
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

REFERENCES = Path('evaluation/p18_20261001_reference_values.json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='attempt2')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if not args.label.isalnum():
        raise ValueError('alphanumeric evidence label required')
    run = json.loads((ROOT / (args.label + '.json')).read_text(encoding='utf-8'))
    refs = json.loads(REFERENCES.read_text(encoding='utf-8'))
    manifest = {r['label']: r for r in json.loads(Path(
        '.artifacts/p17_20260930/references/manifest.json').read_text(encoding='utf-8'))}
    calendar_manifest = {r['exchange']: r for r in json.loads(
        (ROOT / 'calendar-reference-manifest.json').read_text(encoding='utf-8'))}
    artifacts = ArtifactStore(ROOT / 'artifacts')
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    checks, records, documents = [], {}, []
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, db, artifacts)
        for entry in run['results']:
            if entry['status'] != 'ingested':
                raise AssertionError('mandatory source request failed')
            req = request(entry['request'])
            ctx = QueryContext(AccessContext(run['scope'], frozenset({entry['request']['provider']})),
                               entry['snapshot_id'], datetime.fromisoformat(run['finished_at']) +
                               timedelta(seconds=1), PITMode.SYSTEM)
            visible = service.query(req, ctx).records
            if not visible:
                raise AssertionError('mandatory visible domain is empty')
            # Reuse bytes only inside this authorized query context.
            raw_cache = {}
            for r in visible:
                records[r.record_id] = r
                if r.availability_basis != 'observed_at' or r.available_at < r.retrieved_at:
                    raise AssertionError('unproven historical release')
                attrs = dict(r.attributes)
                values = {m.name: m.value for m in r.metrics}
                if r.dataset.value == 'financial_balance':
                    fields = ('total_assets', 'total_liabilities', 'total_equity')
                    if all(values[f] is not None for f in fields):
                        checks.append({'check':'balance_equation','record':r.record_id,
                                       'match':values[fields[0]] == values[fields[1]]+values[fields[2]]})
                if r.dataset.value == 'financial_cashflow':
                    checks.append({'check':'cash_change_equation','record':r.record_id,
                                   'match':values['cash_begin']+values['cash_net_change']==values['cash_end']})
                if r.dataset.value == 'trade_calendar':
                    source = calendar_manifest[r.subject.code]
                    content = artifacts.get(run['scope'], source['artifact_id'])
                    if source['url'] != refs['calendar']['references'][r.subject.code]:
                        raise AssertionError('calendar reference changed')
                    if hashlib.sha256(content).hexdigest() != source['artifact_id']:
                        raise AssertionError('calendar reference bytes changed')
                    checks.append({'check':'official_calendar_open_flag','record':r.record_id,
                                   'source_sha256':source['artifact_id'], 'source_url':source['url'],
                                   'match':attrs['is_open']==str(int(r.period.isoformat() in refs['calendar']['open_dates']))})
                if r.provider == 'tushare' and r.metrics:
                    if r.artifact_id not in raw_cache:
                        raw_cache[r.artifact_id] = json.loads(service.evidence(req, ctx, r.record_id))
                    raw = raw_cache[r.artifact_id]
                    candidates = [row for row in raw['items'] if
                                  row.get('trade_date', row.get('end_date'))==r.period.strftime('%Y%m%d')
                                  and (r.dataset.value != 'index_weight' or row['con_code']==r.fact_id)]
                    for raw_field, name, _, _, multiplier in MAPS[r.dataset]:
                        expected = {None if row[raw_field] is None else Decimal(str(row[raw_field]))*
                                    Decimal(str(multiplier)) for row in candidates}
                        checks.append({'check':'archived_response_unit_mapping','record':r.record_id,
                                       'field':name,'match':len(expected)==1 and values[name] in expected})
                if r.dataset.value == 'announcement':
                    pdf = service.evidence(req, ctx, r.record_id, attrs['pdf_artifact_id'])
                    documents.append({'dataset':r.dataset.value,'record':r.record_id,'title':attrs['title'],
                                      'sha256':attrs['pdf_artifact_id'], 'match':pdf.startswith(b'%PDF') and
                                      hashlib.sha256(pdf).hexdigest()==attrs['document_sha256']})
                if r.dataset.value == 'news_recent':
                    body = service.evidence(req, ctx, r.record_id, attrs['body_artifact_id'])
                    text = article_text(body, attrs['title'])
                    documents.append({'dataset':r.dataset.value,'record':r.record_id,'title':attrs['title'],
                                      'sha256':attrs['body_artifact_id'], 'match':bool(text.strip()) and
                                      (attrs['company_name'] in text or attrs['company_name'] in attrs['title']
                                       or r.subject.provider_symbol in text)})
        weights = [r for r in records.values() if r.dataset.value=='index_weight']
        checks.append({'check':'weight_grain_and_sum','constituent_count':len(weights),
                       'sum':str(sum(r.metrics[0].value for r in weights)),
                       'match':len({r.fact_id for r in weights})==300 and
                       abs(sum(r.metrics[0].value for r in weights)-1)<Decimal('0.0001')})
    financial = []
    for ref in refs['financial']:
        source = manifest[ref['label']]
        sha = hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()
        if sha != ref['sha256'] or sha != source['sha256']:
            raise AssertionError('official PDF changed')
        matched = [r for r in records.values() if r.subject.code==ref['code'] and
                   r.dataset.value==ref['dataset'] and r.period.isoformat()==ref['period']]
        if len(matched)!=1:
            raise AssertionError('reference financial grain ambiguous')
        r = matched[0]
        values = {m.name:m.value for m in r.metrics}
        for field, printed in ref['values'].items():
            expected = Decimal(printed)*Decimal(ref['multiplier'])
            actual = values[field]
            financial.append({'dataset':ref['dataset'],'code':ref['code'],'field':field,
                              'actual':str(actual),'reference':str(expected),'match':actual==expected,
                              'source_url':source['url'],'source_sha256':sha,'pdf_page':ref['pdf_page']})
    output = {'checked_at':datetime.now(timezone.utc).isoformat(),'run_label':args.label,
              'plan_sha256':run['plan_sha256'],
              'reference_values_sha256':hashlib.sha256(REFERENCES.read_bytes()).hexdigest(),
              'visible_record_count':len(records),'record_counts':dict(Counter(r.dataset.value for r in records.values())),
              'metric_cells':sum(len(r.metrics) for r in records.values()),
              'independent_financial_compared':len(financial),'independent_financial_matched':sum(c['match'] for c in financial),
              'financial_comparisons':financial,'integrity_and_mapping_checks':checks,'documents':documents,
              'all_checked_items_passed':all(c['match'] for c in checks+financial+documents),
              'market_wide_accuracy_verified':False,'historical_release_verified':False}
    path = ROOT / (args.label+'-quality.json')
    if args.verify_only:
        prior = json.loads(path.read_text(encoding='utf-8'))
        if {k:v for k,v in prior.items() if k!='checked_at'} != {k:v for k,v in output.items() if k!='checked_at'}:
            raise AssertionError('frozen quality evidence changed')
    else:
        with path.open('x',encoding='utf-8') as stream:
            json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k not in
                     {'financial_comparisons','integrity_and_mapping_checks','documents'}},ensure_ascii=False))
    return 0 if output['all_checked_items_passed'] else 2


if __name__=='__main__':
    raise SystemExit(main())
