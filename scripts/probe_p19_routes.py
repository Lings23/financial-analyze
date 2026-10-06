"""One bounded first-page request per AKShare spot endpoint and proxy route.

Diagnostic responses are not accepted as complete market capture or truth.
The request parameters come from the installed AKShare function source.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import time

import akshare as ak
import requests

from stock_research.storage.artifacts import ArtifactStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--spot-host', choices=['82.push2.eastmoney.com'])
    args = parser.parse_args()
    label = 'routes82' if args.spot_host else 'routes'
    root = Path('.artifacts/p19_20261001')/label
    root.mkdir(parents=True, exist_ok=True)
    target = root/'run.json'
    if target.exists():
        raise ValueError('diagnostic evidence already exists')
    scope = 'p19-'+label+'-20261001'
    store = ArtifactStore(root/'artifacts')
    names = ['stock_cy_a_spot_em', 'stock_kc_a_spot_em'] if args.spot_host else [
        'stock_zh_a_spot_em', 'stock_cy_a_spot_em', 'stock_kc_a_spot_em']
    plan = {'scope':scope, 'akshare_version':ak.__version__, 'requests':[],
            'routes':['environment_proxy'] if args.spot_host else ['environment_proxy', 'direct_process_only'],
            'explicit_spot_host_override':args.spot_host,
            'page_size':1, 'max_attempts':1, 'connect_timeout':3, 'read_timeout':5,
            'first_page_only':True, 'not_full_market_validation':True}
    for name in names:
        source = inspect.getsource(getattr(ak, name))
        values = {}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Assign):
                for assignment in node.targets:
                    if isinstance(assignment, ast.Name) and assignment.id in {'url', 'params'}:
                        values[assignment.id] = ast.literal_eval(node.value)
        url, params = values['url'], values['params']
        assert url in {'https://82.push2.eastmoney.com/api/qt/clist/get',
                       'https://7.push2.eastmoney.com/api/qt/clist/get'}
        original_url = url
        if args.spot_host:
            url = 'https://'+args.spot_host+'/api/qt/clist/get'
        params = dict(params, pn='1', pz='1')
        plan['requests'].append({'endpoint':name, 'url':url, 'original_url':original_url, 'params':params,
                                 'installed_source_sha256':hashlib.sha256(source.encode()).hexdigest()})
    plan_aid = store.put(scope, plan)
    results = []
    for entry in plan['requests']:
        for route in plan['routes']:
            started = time.monotonic()
            result = {'endpoint':entry['endpoint'], 'route':route,
                      'started_at':datetime.now(timezone.utc).isoformat()}
            try:
                with requests.Session() as session:
                    session.trust_env = route == 'environment_proxy'
                    with session.get(entry['url'], params=entry['params'],
                                     timeout=(3,5), allow_redirects=False, stream=True) as response:
                        result['http_status'] = response.status_code
                        content = bytearray()
                        for chunk in response.iter_content(16384):
                            if time.monotonic()-started > 10 or len(content)+len(chunk) > 1024*1024:
                                raise ValueError('diagnostic response exceeds bounds')
                            content.extend(chunk)
                        if response.status_code != 200:
                            result['status'] = 'http_rejected'
                        else:
                            body = json.loads(content)
                            data = body.get('data') or {}
                            rows = data.get('diff') or []
                            result.update(status='returned', row_count=len(rows),
                                          reported_total=data.get('total'),
                                          raw_artifact_id=store.put(scope, body))
            except Exception as exc:
                result.update(status='failed', error_type=type(exc).__name__)
            result['elapsed_seconds'] = round(time.monotonic()-started, 3)
            result['finished_at'] = datetime.now(timezone.utc).isoformat()
            results.append(result)
            print(json.dumps(result), flush=True)
            time.sleep(1.5)
    output = {'scope':scope, 'plan_artifact_id':plan_aid, 'results':results,
              'full_market_capture_verified':False,
              'checked_at':datetime.now(timezone.utc).isoformat()}
    with target.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)


if __name__=='__main__':
    main()
