"""Inspect safe redirect destination metadata from the observed public script."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urljoin,urlsplit

from discover_p17_bse_quotes import ROOT,PAGE,SCRIPT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--child',action='store_true');args=parser.parse_args()
    if args.child:
        try:
            import requests
            response=requests.head(SCRIPT,headers={'Referer':PAGE,'User-Agent':'Mozilla/5.0'},timeout=(3,5),allow_redirects=False)
            report={'http_status':response.status_code}
            if response.headers.get('Location'):
                parts=urlsplit(urljoin(SCRIPT,response.headers['Location']))
                report['redirect_metadata']={'scheme':parts.scheme,'hostname':parts.hostname,
                    'path':parts.path if len(parts.path)<=256 else '[path too long]',
                    'query_present':bool(parts.query),'credentials_present':bool(parts.username or parts.password)}
            print(json.dumps(report));return 0
        except Exception:return 4
    target=ROOT/'redirect-diagnosis.json'
    if target.exists():raise ValueError('redirect diagnosis exists')
    report={'source_url':SCRIPT,'method':'HEAD','attempts':1,'retries':0,'redirect_followed':False,
            'started_at':datetime.now(timezone.utc).isoformat(),'financial_comparisons':0,'phase1_complete':False}
    try:
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child'],capture_output=True,timeout=16,check=False)
        if run.returncode:report.update(status='failed',worker_exit=run.returncode)
        else:
            diagnostic=json.loads(run.stdout);assert set(diagnostic)<={'http_status','redirect_metadata'}
            assert type(diagnostic['http_status']) is int and 100<=diagnostic['http_status']<=599
            report.update(status='diagnosed',**diagnostic)
    except Exception as exc:report.update(status='failed',error_type=type(exc).__name__)
    report['finished_at']=datetime.now(timezone.utc).isoformat()
    with target.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report));return 0 if report['status']=='diagnosed' else 2


if __name__=='__main__':raise SystemExit(main())
