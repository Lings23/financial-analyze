"""Bounded official SZSE historical-page discovery; QA only, no financial scoring."""
import argparse
from datetime import date, datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode

ROOT = Path('.artifacts/p17_20261001/szse_history_discovery')
PAGE = 'https://www.szse.cn/market/trend/index.html?code=002363'


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            source = dict(attrs).get('src')
            if source:
                self.sources.append(urljoin(PAGE, source))


def validate(url):
    parts = urlsplit(url)
    assert parts.scheme == 'https' and parts.hostname in {'www.szse.cn', 'res.szse.cn'}
    assert parts.port in {None, 443} and not parts.username and not parts.password and not parts.fragment
    report = parts.hostname == 'www.szse.cn' and parts.path in {'/api/report/ShowReport/data', '/api/report/ShowReport'}
    assert (parts.hostname == 'www.szse.cn' and parts.path in {'/market/trend/index.html', '/market/trend/archive/index.html', '/disclosure/index/index.html', '/disclosure/deal/block/equity/index.html'}) or parts.path.endswith('.js') or report
    if report:
        params = parse_qs(parts.query)
        assert params.get('SHOWTYPE') in [['JSON'], ['XLSX']] and params.get('CATALOGID') in [['1815_stock_snapshot'], ['1815_stock'], ['1932_dzjyzqjy_after'], ['1265']]
        assert set(params) <= {'SHOWTYPE', 'CATALOGID', 'TABKEY', 'PAGENO', 'txtDMorJC', 'txtBeginDate', 'txtEndDate', 'txtStart', 'txtEnd', 'txtkey2', 'txtKsrq', 'txtZzrq'}
        assert (parts.path.endswith('/data') and params['SHOWTYPE'] == ['JSON']) or (parts.path.endswith('/ShowReport') and params['SHOWTYPE'] == ['XLSX'])
        if params['CATALOGID'] == ['1265']:
            assert set(params) == {'SHOWTYPE','CATALOGID','TABKEY','txtkey2','txtKsrq','txtZzrq'}
            assert params['TABKEY'] == ['tab1'] and re.fullmatch(r'\d{6}', params['txtkey2'][0])
            assert date.fromisoformat(params['txtKsrq'][0]) == date.fromisoformat(params['txtZzrq'][0])
            return
        if 'txtDMorJC' in params:
            assert params['TABKEY'] in [['tab1'], ['tab2'], ['tab3']] and params['PAGENO'] == ['1']
            assert re.fullmatch(r'\d{6}', params['txtDMorJC'][0])
            if params['CATALOGID'] == ['1932_dzjyzqjy_after']:
                assert 'txtBeginDate' not in params and 'txtEndDate' not in params
                first = date.fromisoformat(params['txtStart'][0])
                last = date.fromisoformat(params['txtEnd'][0])
                assert first == last
                return
            assert params['TABKEY'] == ['tab1'] and 'txtStart' not in params and 'txtEnd' not in params
            first = date.fromisoformat(params['txtBeginDate'][0])
            if params['CATALOGID'] == ['1815_stock_snapshot']:
                last = date.fromisoformat(params['txtEndDate'][0])
                assert 0 <= (last-first).days <= 4
            else:
                assert 'txtEndDate' not in params


def child(url):
    import requests
    validate(url)
    deadline = time.monotonic() + 12
    payload = bytearray()
    with requests.get(url, headers={'Referer': PAGE}, timeout=(3, 5),
                      stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            return response.status_code if response.status_code < 256 else 2
        for chunk in response.iter_content(16384):
            if time.monotonic() > deadline or len(payload) + len(chunk) > 3 * 1024 * 1024:
                return 3
            payload.extend(chunk)
    sys.stdout.buffer.write(payload)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['page', 'assets', 'res-assets', 'res-min-assets', 'report-metadata', 'report-probe', 'archive-page', 'archive-metadata', 'archive-probe', 'archive-xlsx-probe', 'disclosure-page', 'block-page', 'block-metadata', 'block-probe', 'block-detail-probe'], default='page')
    parser.add_argument('--child')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.child:
        try:
            return child(args.child)
        except Exception:
            return 4  # Do not log proxy URLs, credentials, headers, or upstream errors.
    if args.verify_only:
        checked = 0
        failed = 0
        for manifest in sorted(ROOT.glob('*-manifest.json')):
            report = json.loads(manifest.read_bytes())
            for entry in report['results']:
                validate(entry['url'])
                if entry['status'] == 'collected':
                    artifact = Path(entry['path'])
                    assert artifact.resolve().is_relative_to(ROOT.resolve())
                    payload = artifact.read_bytes()
                    assert len(payload) == entry['byte_length'] and hashlib.sha256(payload).hexdigest() == entry['sha256']
                    checked += 1
                else:
                    failed += 1
        assert checked
        print(json.dumps({'verified_source_files': checked, 'preserved_failed_resource_requests': failed,
                          'financial_comparisons': 0, 'phase1_complete': False}))
        return 0
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / (args.stage + '-manifest.json')
    if path.exists():
        raise ValueError('discovery evidence already exists')
    urls = [PAGE]
    if args.stage == 'disclosure-page':
        urls = ['https://www.szse.cn/disclosure/index/index.html']
    if args.stage == 'block-page':
        assert '../../disclosure/deal/block/equity/index.html' in (ROOT/'disclosure-page.html').read_text(encoding='utf-8')
        urls = ['https://www.szse.cn/disclosure/deal/block/equity/index.html']
    if args.stage == 'block-metadata':
        assert 'data-s-catalog-id="1932_dzjyzqjy_after"' in (ROOT/'block-page.html').read_text(encoding='utf-8')
        urls = ['https://www.szse.cn/api/report/ShowReport/data?' + urlencode({'SHOWTYPE':'JSON','CATALOGID':'1932_dzjyzqjy_after'})]
    if args.stage == 'block-probe':
        payload = (ROOT/'block-metadata.json').read_bytes()
        assert hashlib.sha256(payload).hexdigest() == '789d86d2851872e096a7fe2548d6e6a99c085bdb5cda7dc8ec11b5b190e7600d'
        tab = next(t for t in json.loads(payload) if t['metadata']['tabkey'] == 'tab1')
        assert {'txtDMorJC','txtStart','txtEnd'} <= {c['name'] for c in tab['metadata']['conditions']}
        urls = ['https://www.szse.cn/api/report/ShowReport/data?' + urlencode({
            'SHOWTYPE':'JSON','CATALOGID':'1932_dzjyzqjy_after','TABKEY':'tab1','PAGENO':'1',
            'txtDMorJC':'300750','txtStart':'2024-09-26','txtEnd':'2024-09-26'})]
    if args.stage == 'block-detail-probe':
        payload = (ROOT/'block-probe.json').read_bytes()
        assert hashlib.sha256(payload).hexdigest() == '01724210cf4b874d5605d94121f92774a9a8455cfd46c6f30e3b6f0d7c9ed277'
        tab = next(t for t in json.loads(payload) if t['metadata']['tabkey'] == 'tab1')
        assert tab['metadata']['recordcount'] == 1 and tab['metadata']['pagecount'] == 1 and len(tab['data']) == 1
        row = tab['data'][0]
        assert row['zqdm'] == '300750' and row['dqrq'] == '2024-09-26'
        matches = re.findall(r"a-param='([^']+)'", row['bz'])
        assert len(matches) == 1
        urls = ['https://www.szse.cn/api/report' + matches[0]]
    if args.stage == 'archive-xlsx-probe':
        report_js = (ROOT / 'res-min-assets-script0.js').read_text(encoding='utf-8')
        assert '"?SHOWTYPE=XLSX&CATALOGID="' in report_js
        urls = ['https://www.szse.cn/api/report/ShowReport?' + urlencode({
            'SHOWTYPE': 'XLSX', 'CATALOGID': '1815_stock', 'TABKEY': 'tab1', 'PAGENO': '1',
            'txtDMorJC': '000016', 'txtBeginDate': '2024-09-18'})]
    if args.stage == 'archive-page':
        js = (ROOT / 'res-min-assets-script0.js').read_text(encoding='utf-8')
        assert 'location.pathname.match' in js and '+"archive/index.html"' in js
        urls = ['https://www.szse.cn/market/trend/archive/index.html']
    if args.stage in {'report-metadata', 'report-probe', 'archive-metadata', 'archive-probe'}:
        page = (ROOT / 'page.html').read_text(encoding='utf-8')
        assert "catalogIdSec: '1815_stock_snapshot'" in page
        report_js = (ROOT / 'res-min-assets-script0.js').read_text(encoding='utf-8')
        assert '"/ShowReport/data"' in report_js
        params = {'SHOWTYPE': 'JSON', 'CATALOGID': '1815_stock_snapshot'}
        if args.stage.startswith('archive-'):
            archive_page = (ROOT / 'archive-page.html').read_text(encoding='utf-8')
            assert "catalogIdSec: '1815_stock'" in archive_page
            params['CATALOGID'] = '1815_stock'
        if args.stage in {'report-probe', 'archive-probe'}:
            archive = args.stage == 'archive-probe'
            metadata_bytes = (ROOT / ('archive-metadata.json' if archive else 'report-metadata.json')).read_bytes()
            expected = '24edb7f602d32fd16eb48853eda994e29f50f201049f089038453c96996ab5fb' if archive else '4e1cd006fc827e02b324ce1f22733c8f827dee1e06c6f70660dbf4ef7b2e05cb'
            assert hashlib.sha256(metadata_bytes).hexdigest() == expected
            tab = next(t for t in json.loads(metadata_bytes) if t['metadata']['tabkey'] == 'tab1')
            assert {'txtDMorJC', 'txtBeginDate'} <= {c['name'] for c in tab['metadata']['conditions']}
            params.update(TABKEY='tab1', PAGENO='1', txtDMorJC='002363', txtBeginDate='2024-09-18')
            if not archive:
                params['txtEndDate'] = '2024-09-20'
        urls = ['https://www.szse.cn/api/report/ShowReport/data?' + urlencode(params)]
    if args.stage in {'assets', 'res-assets', 'res-min-assets'}:
        prior = json.loads((ROOT / 'page-manifest.json').read_text(encoding='utf-8'))
        assert prior['results'][0]['status'] == 'collected'
        page_bytes = (ROOT / 'page.html').read_bytes()
        assert hashlib.sha256(page_bytes).hexdigest() == prior['results'][0]['sha256']
        # The official page writes script elements dynamically. Read literal
        # changeVertion paths without running downloaded JavaScript.
        dynamic = [urljoin(PAGE, item) for item in re.findall(
            r"changeVertion\('([^']+\.js)',\s*'js'\)", page_bytes.decode('utf-8'))]
        urls = list(dict.fromkeys(url for url in prior['script_urls'] + dynamic
                if urlsplit(url).hostname == 'www.szse.cn'
                and any(part in urlsplit(url).path.lower() for part in ['trend', 'market', 'report'])))
        if args.stage in {'res-assets', 'res-min-assets'}:
            assert "var _path = 'https://res.szse.cn'" in page_bytes.decode('utf-8')
            urls = ['https://res.szse.cn' + urlsplit(url).path for url in urls
                    if not urlsplit(url).path.endswith(('mLineChart.js', 'kLineChart.js'))]
        if args.stage == 'res-min-assets':
            loader = Path('.artifacts/p17_20261001/exchange_discovery/script6.js').read_bytes()
            assert hashlib.sha256(loader).hexdigest() == 'eebde357d093a18f59506deab8d0cc93c0899df45000f5bfd4eab3c54fced0f0'
            assert "url=url.replace('.'+type,'.min.'+type)" in loader.decode('utf-8')
            urls = [url[:-3] + '.min.js' for url in urls if not url.endswith('.min.js')]
        assert 0 < len(urls) <= 6
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'page_url': PAGE,
              'phase1_complete': False, 'financial_comparisons': 0, 'results': []}
    for index, url in enumerate(urls):
        validate(url)
        entry = {'url': url, 'attempts': 1, 'retries': 0,
                 'started_at': datetime.now(timezone.utc).isoformat()}
        try:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', url],
                                 capture_output=True, timeout=16, check=False)
            if run.returncode:
                entry.update(status='failed', worker_exit=run.returncode)
            else:
                assert len(run.stdout) <= 3 * 1024 * 1024
                destination = ROOT / ('page.html' if args.stage == 'page' else args.stage + '.html' if args.stage in {'archive-page', 'disclosure-page', 'block-page'} else
                                      'archive-xlsx-probe.xlsx' if args.stage == 'archive-xlsx-probe' else
                                      args.stage + '.json' if args.stage.startswith(('report-', 'archive-', 'block-')) else f'{args.stage}-script{index}.js')
                with destination.open('xb') as stream:
                    stream.write(run.stdout)
                entry.update(status='collected', http_status=200, path=destination.as_posix(),
                             byte_length=len(run.stdout), sha256=hashlib.sha256(run.stdout).hexdigest())
                if args.stage == 'page':
                    scripts = Scripts()
                    scripts.feed(run.stdout.decode('utf-8'))
                    report['script_urls'] = scripts.sources
        except Exception as exc:
            entry.update(status='failed', error_type=type(exc).__name__)
        entry['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['results'].append(entry)
        print(json.dumps(entry), flush=True)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    return 0 if all(e['status'] == 'collected' for e in report['results']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
