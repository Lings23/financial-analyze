"""Freeze all eleven missing BSE periods using observed official identity proofs."""
import hashlib
import json
from pathlib import Path

from stock_research.providers.cninfo_identity import QualifiedCNInfoIdentity
from stock_research.storage.artifacts import ArtifactStore


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original = Path('evaluation/p17_20261001_formal_financial_reference_plan.json')
    plan = json.loads(original.read_bytes())
    missing_path = Path('.artifacts/p17_20261001/formal/konka_reference/comparison.json')
    missing = json.loads(missing_path.read_bytes())['missing']
    keys = {(r['code'],r['period']) for r in missing if r['exchange']=='BSE'}
    assert len(keys)==11
    requests = [r for r in plan['requests'] if (r['code'],r['period']) in keys]
    assert len(requests)==11
    table = json.loads(Path('evaluation/p17_20261001_bse_code_table_dom.json').read_bytes())
    switches = json.loads(Path('evaluation/p17_20261001_bse_switch_dom.json').read_bytes())
    code_rows = {r[4]:r for r in table['rows']}
    discovery_root = Path('.artifacts/p17_20261001/formal/bse_identity_discovery')
    discovery = json.loads((discovery_root/'run.json').read_bytes())
    store = ArtifactStore(discovery_root/'artifacts')
    mappings = {}
    for e in discovery['results']:
        if e['request']['code'] not in code_rows: continue
        assert e['status']=='collected'
        body = json.loads(store.get(discovery['scope'],e['artifact_id']))
        mappings[e['request']['code']]=body['mapping']
    scope='p17-bse-qualified-reference-20261001'
    approvals=[]
    for r in requests:
        row=code_rows[r['code']];mapping=mappings[r['code']]
        assert mapping['code']==r['code']
        approvals.append({'code':r['code'],'old_code':row[3],'org_id':mapping['orgId'],
                          'cutover_date':'2025-05-06' if r['code']=='920489' else '2025-10-09',
                          'start_date':r['start_date'],'end_date':r['end_date'],'selector':r['selector']})
    manifest={'schema':'cninfo-qualified-identity-v1','scope':scope,'proofs':[table,*switches],
              'approved_requests':approvals,'review':'Four observed official DOM code rows and separate pilot/general effective-date statements; explicit requests only. No historical availability upgrade or inferred suffix mapping.'}
    path=Path('evaluation/p17_20261001_bse_identity_qualification.json')
    content=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8')
    identity=QualifiedCNInfoIdentity(content,hashlib.sha256(content).hexdigest())
    with path.open('xb') as stream:stream.write(content)
    target=Path('evaluation/p17_20261001_bse_qualified_reference_plan.json')
    result={'scope':scope,'original_plan_sha256':sha(original),'previous_comparison_sha256':sha(missing_path),
            'identity_manifest_path':str(path),'identity_manifest_sha256':identity.approved_sha256,
            'min_interval_seconds':2.5,'requests':requests,'registered_financial_cells':225,
            'reason':'Preserve original twelve failures and empty result; collect eleven BSE periods with explicitly qualified old/new code identity.'}
    with target.open('x',encoding='utf8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'plan_sha256':sha(target),'identity_qualification_sha256':identity.approved_sha256,'requests':11}))


if __name__=='__main__': main()
