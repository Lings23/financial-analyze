"""Bounded official BSE page-script discovery; QA only, never financial scoring."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('.artifacts/p17_20261001/bse_quote_discovery')
PAGE = 'https://www.bse.cn/products/neeq_listed_companies/company_time_sharing.html?companyCode=920510&typename=G'
SCRIPT = 'https://www.bse.cn/template/6/bluewise/_files/js/products/neeq_listed_companies/company_time_share.min.js'


def child(browser_header=False):
    import requests
    deadline = time.monotonic() + 12
    payload = bytearray()
    headers={'Referer':PAGE}
    if browser_header:headers['User-Agent']='Mozilla/5.0'
    with requests.get(SCRIPT,headers=headers,timeout=(3,5),stream=True,allow_redirects=False) as response:
        sys.stderr.write(json.dumps({'http_status':response.status_code}))
        if response.status_code != 200:
            return 2
        for chunk in response.iter_content(16384):
            if time.monotonic()>deadline or len(payload)+len(chunk)>3*1024*1024:
                return 3
            payload.extend(chunk)
    sys.stdout.buffer.write(payload)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--browser-header',action='store_true')
    parser.add_argument('--post-head',action='store_true')
    args = parser.parse_args()
    if args.child:
        try:return child(args.browser_header)
        except Exception:return 4
    assert not args.post_head or args.browser_header
    name='script-post-head' if args.post_head else 'script-browser-header' if args.browser_header else 'script'
    target = ROOT/(name+'-manifest.json')
    if args.verify_only:
        report=json.loads(target.read_bytes())
        assert report['url']==SCRIPT and report['attempts']==1 and report['retries']==0
        if report['status']=='collected':
            payload=(ROOT/(name+'.js')).read_bytes()
            assert hashlib.sha256(payload).hexdigest()==report['sha256'] and len(payload)==report['byte_length']
        print(json.dumps({'source_status':report['status'],'financial_comparisons':0,'phase1_complete':False}))
        return 0
    ROOT.mkdir(parents=True,exist_ok=True)
    if target.exists():raise ValueError('BSE discovery already exists')
    report={'page_url':PAGE,'url':SCRIPT,'discovery_basis':'Actual script src observed in official company page DOM after clicking daily K line',
            'started_at':datetime.now(timezone.utc).isoformat(),'attempts':1,'retries':0,'financial_comparisons':0,'phase1_complete':False,
            'user_agent_header': 'Mozilla/5.0' if args.browser_header else 'requests_default'}
    if args.post_head:
        data=(ROOT/'redirect-diagnosis.json').read_bytes();prior=json.loads(data)
        assert prior['method']=='HEAD' and prior['http_status']==200 and prior['source_url']==SCRIPT
        report['head_evidence_sha256']=hashlib.sha256(data).hexdigest()
    try:
        command=[sys.executable,str(Path(__file__).resolve()),'--child']
        if args.browser_header:command.append('--browser-header')
        run=subprocess.run(command,capture_output=True,timeout=16,check=False)
        if run.stderr:
            diagnostic=json.loads(run.stderr)
            assert set(diagnostic)=={'http_status'} and isinstance(diagnostic['http_status'],int) and 100<=diagnostic['http_status']<=599
            report.update(diagnostic)
        if run.returncode:
            report.update(status='failed',worker_exit=run.returncode)
        else:
            assert len(run.stdout)<=3*1024*1024
            with (ROOT/(name+'.js')).open('xb') as stream:stream.write(run.stdout)
            report.update(status='collected',http_status=200,byte_length=len(run.stdout),sha256=hashlib.sha256(run.stdout).hexdigest())
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__)
    report['finished_at']=datetime.now(timezone.utc).isoformat()
    with target.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report))
    return 0 if report['status']=='collected' else 2


if __name__=='__main__':raise SystemExit(main())
