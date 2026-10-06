"""Replay explicit identity qualification and authorized CNINFO reference bytes."""
import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, QueryContext, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.cninfo_identity import QualifiedCNInfoIdentity
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

ROOT=Path('.artifacts/p17_20261001/formal/bse_qualified_references')
PLAN=Path('evaluation/p17_20261001_bse_qualified_reference_plan.json')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    plan=json.loads(PLAN.read_bytes());run=json.loads((ROOT/'collection.json').read_bytes())
    assert run['plan_sha256']==hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert len(run['requests'])==len(plan['requests'])==11 and run['scope']==plan['scope']
    identity=QualifiedCNInfoIdentity(Path(plan['identity_manifest_path']).read_bytes(),plan['identity_manifest_sha256'])
    db=PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    store=ArtifactStore(ROOT/'artifacts');assert store.get(plan['scope'],run['plan_artifact'])==PLAN.read_bytes()
    access=AccessContext(plan['scope'],frozenset({'cninfo'}));after=datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1)
    groups=[];pdfs=0;old_codes=set()
    with ProviderExecutor() as executor:
        service=DataService(ProviderRegistry(),executor,db,store)
        for item,entry in zip(plan['requests'],run['requests']):
            assert entry['request']==item and entry['status']=='collected' and entry['files']
            req=DomainRequest(Subject('equity',item['code'],item['exchange']),DomainDataset.ANNOUNCEMENT,
                date.fromisoformat(item['start_date']),date.fromisoformat(item['end_date']),item['selector'])
            ctx=QueryContext(access,entry['snapshot_id'],after)
            rows=service.query(req,ctx).records;by_id={r.record_id:r for r in rows}
            assert set(by_id)=={f['record_id'] for f in entry['files']}
            for f in entry['files']:
                record=by_id[f['record_id']];attrs=dict(record.attributes)
                assert record.provider_version=='p18-identity-1' and record.availability_basis=='observed_at'
                assert record.available_at==record.retrieved_at>=identity.observed_at
                assert record.source_url==f['source_url'] and attrs['pdf_artifact_id']==f['sha256']
                path=Path(f['path']).resolve();assert path.is_relative_to(ROOT.resolve())
                content=service.evidence(req,ctx,record.record_id,f['sha256'])
                assert content==path.read_bytes() and hashlib.sha256(content).hexdigest()==f['sha256']
                index=json.loads(service.evidence(req,ctx,record.record_id,record.artifact_id))
                proof=index['identity_qualification'];assert proof['availability_not_upgraded'] is True
                assert proof['sha256']==identity.approved_sha256
                assert proof['reviewed_manifest_utf8'].encode('utf8')==identity.manifest_bytes
                for raw in index['rows']:
                    identity.validate(req,access.scope,index['subject_mapping'],raw)
                    if raw['secCode']!=item['code']:old_codes.add(raw['secCode'])
                assert not service.query(req,QueryContext(access,entry['snapshot_id'],record.available_at-timedelta(microseconds=1))).records
                for bad in (QueryContext(AccessContext(access.scope,frozenset({'tushare'})),entry['snapshot_id'],after),
                            QueryContext(AccessContext(access.scope+'-other',access.allowed_providers),entry['snapshot_id'],after)):
                    for aid in (record.artifact_id,f['sha256']):
                        try:service.evidence(req,bad,record.record_id,aid)
                        except PermissionDenied:pass
                        else:raise AssertionError('unauthorized identity/PDF evidence read accepted')
                pdfs+=1
            groups.append({'code':item['code'],'period':item['period'],'pdfs':len(rows),'snapshot_id':entry['snapshot_id'],
                           'identity_source_pdf_scope_pit_passed':True})
    assert pdfs==18 and old_codes=={'832110','430510','430489','832175'}
    out={'checked_at':utcnow().isoformat(),'plan_sha256':run['plan_sha256'],'qualification_sha256':identity.approved_sha256,
         'registered_periods':11,'verified_pdfs':pdfs,'original_source_codes':sorted(old_codes),
         'provider_attempts':run['provider_stats']['attempts'],'retries':run['provider_stats']['retries'],
         'original_registered_financial_cells':225,'numeric_comparisons_in_this_attachment_replay':0,
         'historical_publication_not_upgraded':True,'phase1_complete':False,'groups':groups}
    target=ROOT/'replay.json'
    if args.verify_only:
        prior=json.loads(target.read_bytes());assert {k:v for k,v in prior.items() if k!='checked_at'}=={k:v for k,v in out.items() if k!='checked_at'}
    else:
        with target.open('x',encoding='utf8') as stream:json.dump(out,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in out.items() if k!='groups'}))


if __name__=='__main__':main()
