"""Preserve one exploratory official original/restated filing pair and index dates."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


FILES = (
    ("300122_2024_original_summary", "https://static.cninfo.com.cn/finalpage/2025-04-22/1223198218.PDF"),
    ("300122_2025_summary_with_2024_restated", "https://static.cninfo.com.cn/finalpage/2026-04-28/1225212821.pdf"),
    ("300122_restated_financial_notes", "https://static.cninfo.com.cn/finalpage/2026-04-28/1225212849.PDF"),
)


def main():
    root = Path(".artifacts/p17_20260930/revision")
    root.mkdir(parents=True, exist_ok=True)
    target = root / "manifest.json"
    if target.exists():
        raise ValueError("revision evidence already exists; refusing overwrite")
    files = []
    for label, url in FILES:
        with requests.get(url, timeout=(8, 35), allow_redirects=False) as response:
            if response.status_code != 200 or not response.content.startswith(b"%PDF"):
                files.append({"label": label, "url": url, "status": "failed", "http_status": response.status_code})
                continue
            if len(response.content) > 30 * 1024 * 1024:
                raise ValueError("revision PDF exceeds 30 MiB")
            sha = hashlib.sha256(response.content).hexdigest()
            path = root / f"{label}-{sha[:12]}.pdf"
            path.write_bytes(response.content)
            files.append({"label": label, "url": url, "status": "downloaded",
                          "sha256": sha, "bytes": len(response.content), "path": str(path),
                          "retrieved_at": datetime.now(timezone.utc).isoformat()})

    index = []
    for day in ("2025-04-22", "2026-04-28"):
        payload = {"pageNum": "1", "pageSize": "100", "column": "szse", "tabName": "fulltext",
                   "plate": "", "stock": "", "searchkey": "智飞生物", "secid": "", "category": "",
                   "trade": "", "seDate": f"{day}~{day}", "sortName": "", "sortType": "",
                   "isHLtitle": "true"}
        with requests.post("https://www.cninfo.com.cn/new/hisAnnouncement/query", data=payload,
                           headers={"Referer": "https://www.cninfo.com.cn/"},
                           timeout=(8, 20), allow_redirects=False) as response:
            if response.status_code != 200:
                index.append({"day": day, "status": "failed", "http_status": response.status_code})
                continue
            body = response.json()
            for row in body.get("announcements") or []:
                if row.get("secCode") == "300122" and any(
                        row.get("adjunctUrl", "").lower().endswith(url.rsplit("/", 1)[-1].lower())
                        for _, url in FILES):
                    index.append({"day": day, "sec_code": row.get("secCode"),
                                  "announcement_id": row.get("announcementId"),
                                  "announcement_time_ms": row.get("announcementTime"),
                                  "adjunct_url": row.get("adjunctUrl"),
                                  "source": "https://www.cninfo.com.cn/new/hisAnnouncement/query"})
    target.write_text(json.dumps({"files": files, "official_index": index},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"downloaded": sum(x["status"] == "downloaded" for x in files),
                      "index_matches": len(index),
                      "files": [{"label": x["label"], "status": x["status"],
                                 "sha256": x.get("sha256")} for x in files],
                      "index": index}, ensure_ascii=False))


if __name__ == "__main__":
    main()
