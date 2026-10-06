"""Fetch preselected official PDF originals without credentials or redirects."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


SOURCES = (
    ("sse_688590_historical_price_2024_09", "https://static.sse.com.cn/stock/disclosure/announcement/c/202508/688590_20250801_LOF8.pdf"),
    ("cninfo_600000_2024_annual_summary", "https://static.cninfo.com.cn/finalpage/2025-03-29/1222948223.PDF"),
    ("cninfo_000001_2024_annual", "https://static.cninfo.com.cn/finalpage/2025-03-15/1222806505.PDF"),
    ("cninfo_300750_2024_annual_summary", "https://static.cninfo.com.cn/finalpage/2025-03-15/1222806928.PDF"),
    ("cninfo_600519_2024_annual_summary", "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993909.PDF"),
)


def main():
    root = Path(".artifacts/p17_20260930/references")
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        raise ValueError("reference manifest already exists; refusing to overwrite originals")
    manifest = []
    for label, url in SOURCES:
        with requests.get(url, timeout=(8, 35), allow_redirects=False, stream=True) as response:
            if response.status_code != 200 or "pdf" not in response.headers.get("content-type", "").lower():
                manifest.append({"label": label, "url": url, "status": "failed",
                                 "http_status": response.status_code})
                continue
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > 30 * 1024 * 1024:
                    raise ValueError("reference PDF exceeds 30 MiB")
                chunks.append(chunk)
            content = b"".join(chunks)
            if not content.startswith(b"%PDF"):
                manifest.append({"label": label, "url": url, "status": "invalid_pdf"})
                continue
            sha = hashlib.sha256(content).hexdigest()
            path = root / f"{label}-{sha[:12]}.pdf"
            if path.exists() and path.read_bytes() != content:
                raise ValueError("existing PDF path has conflicting content")
            path.write_bytes(content)
            manifest.append({"label": label, "url": url, "status": "downloaded",
                             "http_status": response.status_code, "content_type": response.headers.get("content-type"),
                             "retrieved_at": datetime.now(timezone.utc).isoformat(),
                             "sha256": sha, "bytes": len(content), "path": str(path)})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{"label": x["label"], "status": x["status"],
                       "bytes": x.get("bytes"), "sha256": x.get("sha256")}
                      for x in manifest], ensure_ascii=False))


if __name__ == "__main__":
    main()
