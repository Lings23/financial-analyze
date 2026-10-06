"""Hard deadline for public exchange QA requests; no runtime provider registration."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit


def _validate(url):
    parts = urlsplit(url)
    sse = (parts.hostname=='yunhq.sse.com.cn' and parts.port==32042
           and re.fullmatch(r'/v1/sh1/dayk/\d{6}',parts.path))
    szse = (parts.hostname=='www.szse.cn' and parts.port in {None,443}
            and parts.path=='/api/market/ssjjhq/getHistoryData')
    if parts.scheme!='https' or parts.username or parts.password or parts.query or parts.fragment or not (sse or szse):
        raise ValueError('reference URL outside verified official endpoints')


def get_reference(url, params, referer):
    _validate(url)
    # subprocess.run kills and waits for its child on TimeoutExpired; a slowly
    # streamed response therefore cannot keep the acceptance process running.
    try:
        result = subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child',url,
                                 json.dumps(params,separators=(',',':')),referer],
                                capture_output=True,timeout=16,check=False)
    except subprocess.TimeoutExpired:
        raise TimeoutError('official reference worker exceeded deadline') from None
    if result.returncode!=0:
        raise RuntimeError('official reference request failed')
    if len(result.stdout)>3*1024*1024:
        raise ValueError('official reference exceeds size limit')
    return result.stdout


def child(url, params, referer):
    import requests
    _validate(url)
    deadline = time.monotonic()+12
    body = bytearray()
    with requests.get(url,params=params,timeout=(3,5),allow_redirects=False,
                      headers={'Referer':referer},stream=True) as response:
        if response.status_code!=200:
            return 2
        for chunk in response.iter_content(16384):
            if time.monotonic()>deadline or len(body)+len(chunk)>3*1024*1024:
                return 3
            body.extend(chunk)
    sys.stdout.buffer.write(body)
    return 0


if __name__=='__main__':
    try:
        if len(sys.argv)!=5 or sys.argv[1]!='--child':
            raise SystemExit(2)
        raise SystemExit(child(sys.argv[2],json.loads(sys.argv[3]),sys.argv[4]))
    except Exception:
        # Never emit a proxy URL, credentials, upstream headers or error body.
        raise SystemExit(4)
