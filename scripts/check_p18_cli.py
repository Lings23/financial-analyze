"""Check actual read-only CLI and authorized PDF export against the frozen live run."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from stock_research.storage.postgres import PostgresRepository


def main():
    root = Path('.artifacts/p18_20261001')
    run = json.loads((root/'attempt2.json').read_text(encoding='utf-8'))
    env = dict(os.environ, PYTHONPATH='src', STOCK_RESEARCH_DSN=Path(
        '.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    db = PostgresRepository(env['STOCK_RESEARCH_DSN'])
    entry = next(r for r in run['results'] if r['request']['dataset']=='announcement')
    rows = [r for r in db.read(run['scope'],entry['snapshot_id']) if r.dataset.value=='announcement']
    record = rows[0]
    after = (datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1)).isoformat()
    before = (record.available_at-timedelta(microseconds=1)).isoformat()
    item = entry['request']
    common = ['--scope',run['scope'],'--kind',item['kind'],'--code',item['code'],
              '--exchange',item['exchange'],'--dataset',item['dataset'],'--start',item['start'],
              '--end',item['end'],'--selector',item['selector'],'--snapshot',entry['snapshot_id'],
              '--artifacts',str(root/'artifacts')]
    def call(command, args):
        result = subprocess.run([sys.executable,'-m','stock_research',command]+common+args,
                                capture_output=True,env=env,timeout=20)
        body = json.loads((result.stdout or result.stderr).decode('utf-8'))
        return result.returncode,body
    rc, body = call('domain-query',['--providers','cninfo','--as-of',after,'--mode','system'])
    assert rc==0 and len(body['records'])==2
    rc, body = call('domain-query',['--providers','cninfo','--as-of',before])
    assert rc==0 and not body['records']
    target = root/'cli-authorized-announcement.pdf'
    aid = dict(record.attributes)['pdf_artifact_id']
    evidence_args = ['--as-of',after,'--mode','system','--record',record.record_id,
                     '--artifact',aid,'--output',str(target)]
    rc, body = call('domain-evidence',['--providers','tushare']+evidence_args)
    assert rc==2 and body['error']=='PermissionDenied'
    if not target.exists():
        rc, body = call('domain-evidence',['--providers','cninfo']+evidence_args)
        assert rc==0 and body['status']=='exported'
    assert hashlib.sha256(target.read_bytes()).hexdigest()==aid
    rc, body = call('domain-evidence',['--providers','cninfo']+evidence_args)
    assert rc==3 and body['error']=='FileExistsError'
    output = {'checked_at':datetime.now(timezone.utc).isoformat(),'authorized_query_count':2,
              'before_capture_query_count':0,'unauthorized_evidence_denied':True,
              'exported_pdf_sha256':aid,'existing_export_not_overwritten':True,
              'all_checks_passed':True}
    report = root/'attempt2-cli.json'
    if report.exists():
        prior = json.loads(report.read_text(encoding='utf-8'))
        assert {k:v for k,v in prior.items() if k!='checked_at'}=={k:v for k,v in output.items() if k!='checked_at'}
    else:
        with report.open('x',encoding='utf-8') as stream: json.dump(output,stream,indent=2)
    print(json.dumps(output))


if __name__=='__main__':
    main()
