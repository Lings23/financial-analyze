"""Archive the official correction notice containing before/after 2024 values."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


def main():
    root = Path(".artifacts/p17_20260930/revision")
    root.mkdir(parents=True, exist_ok=True)
    url = "https://static.cninfo.com.cn/finalpage/2026-04-28/1225212850.PDF"
    manifest_path = root / "supplement.json"
    if manifest_path.exists():
        raise ValueError("supplement already exists; refusing overwrite")
    with requests.get(url, timeout=(8, 35), allow_redirects=False) as response:
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            raise ValueError("official correction PDF could not be fetched")
        if len(response.content) > 30 * 1024 * 1024:
            raise ValueError("correction PDF exceeds 30 MiB")
        sha = hashlib.sha256(response.content).hexdigest()
        path = root / f"300122_correction_before_after-{sha[:12]}.pdf"
        path.write_bytes(response.content)
        manifest = {"url": url, "sha256": sha, "bytes": len(response.content),
                    "path": str(path), "retrieved_at": datetime.now(timezone.utc).isoformat()}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"sha256": sha, "bytes": len(response.content)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
