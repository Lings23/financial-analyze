"""Collect missing official filings for ALL financial rows of the frozen P1.7 pilot."""
import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.models import AccessContext, PITMode, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.documents import CNInfoAnnouncementProvider
from stock_research.providers.cninfo_identity import QualifiedCNInfoIdentity
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

PLAN = Path('evaluation/p17_20261001_reference_plan.json')
ROOT = Path('.artifacts/p17_20261001/reference_extension')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, default=PLAN)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    root = args.root
    root.mkdir(parents=True,exist_ok=True)
    output = root/'collection.json'
    if output.exists():
        raise ValueError('original collection exists; refusing to overwrite')
    artifacts = ArtifactStore(root/'artifacts')
    plan_aid = artifacts.put_bytes(plan['scope'],args.plan.read_bytes())
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    registry = ProviderRegistry()
    identity = None
    if 'identity_manifest_path' in plan:
        identity = QualifiedCNInfoIdentity(Path(plan['identity_manifest_path']).read_bytes(),plan['identity_manifest_sha256'])
    registry.register(CNInfoAnnouncementProvider(artifacts,identity=identity))
    access = AccessContext(plan['scope'],frozenset({'cninfo'}))
    result = {'plan_sha256':hashlib.sha256(args.plan.read_bytes()).hexdigest(),'plan_artifact':plan_aid,
              'scope':plan['scope'],'started_at':datetime.now(timezone.utc).isoformat(),'requests':[]}
    with ProviderExecutor(ExecutionPolicy(total_timeout=90,attempt_timeout=90,
                                         min_interval=plan.get('min_interval_seconds',1.5),max_attempts=1)) as executor:
        service = DataService(registry,executor,db,artifacts)
        for item in plan['requests']:
            evidence = root / (item['code']+'_'+item['period']+'_capture.json')
            if evidence.exists():
                prior = json.loads(evidence.read_text(encoding='utf-8'))
                if prior['request'] != item:
                    raise ValueError('preserved capture belongs to another plan')
                for source in prior.get('files',[]):
                    if hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()!=source['sha256']:
                        raise ValueError('preserved source bytes changed')
                result['requests'].append(prior)
                continue
            day = date.fromisoformat(item['announcement_date'])
            start = date.fromisoformat(item.get('start_date',day.isoformat()))
            end = date.fromisoformat(item.get('end_date',day.isoformat()))
            req = DomainRequest(Subject('equity',item['code'],item['exchange']),
                                DomainDataset.ANNOUNCEMENT,start,end,item['selector'])
            entry = {'request':item}
            try:
                batch = service.refresh(req,access,('cninfo',),use_cache=False)
                visible = service.query(req,QueryContext(access,batch.snapshot.snapshot_id,
                                        datetime.now(timezone.utc),PITMode.SYSTEM)).records
                files = []
                for r in visible:
                    attrs = dict(r.attributes)
                    content = service.evidence(req,QueryContext(access,batch.snapshot.snapshot_id,
                                               datetime.now(timezone.utc),PITMode.SYSTEM),r.record_id,attrs['pdf_artifact_id'])
                    pdf = root / (item['code']+'_'+item['period']+'_'+r.fact_id+'.pdf')
                    with pdf.open('xb') as stream: stream.write(content)
                    files.append({'path':str(pdf),'record_id':r.record_id,'source_url':r.source_url,
                                  'title':attrs['title'],'sha256':attrs['pdf_artifact_id'],
                                  'source_index_artifact':r.artifact_id,'source_date':attrs['source_date'],
                                  'captured_at':r.retrieved_at.isoformat()})
                entry.update(status='collected' if files else 'empty',snapshot_id=batch.snapshot.snapshot_id,files=files)
            except Exception as exc:
                entry.update(status='failed',error_type=type(exc).__name__)
            result['requests'].append(entry)
            # Append-only per-request evidence survives an interrupted batch.
            with evidence.open('x',encoding='utf-8') as stream: json.dump(entry,stream,ensure_ascii=False,indent=2)
            print(json.dumps({'code':item['code'],'period':item['period'],'status':entry['status'],
                              'files':len(entry.get('files',[]))}),flush=True)
        result['provider_stats'] = executor.stats
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    with output.open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'requests':len(result['requests']),'collected':sum(e['status']=='collected' for e in result['requests']),
                      'pdf_count':sum(len(e.get('files',[])) for e in result['requests'])}))


if __name__=='__main__':
    main()
