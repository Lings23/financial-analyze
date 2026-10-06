"""Build/check local sdist; secret values stay in memory and are never printed."""
import argparse
import json
from pathlib import Path
import tarfile
from urllib.parse import urlsplit, unquote

from stock_research.model_adapters.chat import load_model_config


def check(output):
    output.mkdir(parents=True, exist_ok=False)
    import setuptools.build_meta
    name = setuptools.build_meta.build_sdist(str(output))
    secrets = []
    if Path("test_api.txt").is_file():
        secrets.append(load_model_config().api_key.encode())
    if Path(".env").is_file():
        for line in Path(".env").read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                secrets.append(line.partition("=")[2].strip().encode())
    if Path(".runtime/p17-dsn.txt").is_file():
        password = urlsplit(Path(".runtime/p17-dsn.txt").read_text().strip()).password
        if password:
            secrets.append(unquote(password).encode())
    secrets = [v for v in secrets if v]
    files = [p for root in ("src", "tests", "scripts", "evaluation", "docs", ".artifacts/phase3")
             for p in Path(root).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += [Path("README.md"), Path("pyproject.toml"), Path("MANIFEST.in")]
    source_matches = sum(any(v in p.read_bytes() for v in secrets) for p in files)
    with tarfile.open(output/name, "r:gz") as archive:
        members = [m for m in archive.getmembers() if m.isfile()]
        names = [m.name for m in members]
        forbidden = [n for n in names if any(part in {".runtime", ".artifacts", ".env"} for part in Path(n).parts)
                     or Path(n).name in {"test_api.txt", "tushare.txt", "cninfo_key.txt"}
                     or Path(n).name.startswith(("test_api.", "tushare.")) and n.endswith(".txt")]
        package_matches = sum(any(v in archive.extractfile(m).read() for v in secrets) for m in members)
        modules = ("study.py", "study_contracts.py", "hypotheses.py", "verification.py", "context.py", "archive.py", "scoped.py", "selection.py")
        complete = all(any(n.endswith("/research/"+module) for n in names) for module in modules)
    result = {"source_files_checked":len(files), "source_exact_secret_matches":source_matches,
              "package_files":len(names), "package_exact_secret_matches":package_matches,
              "forbidden_files_count":len(forbidden), "phase3_modules_included":complete,
              "sdist":str(output/name), "wheel_verified":False}
    with (output/"check.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result))
    return 0 if source_matches == package_matches == len(forbidden) == 0 and complete else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(check(args.output))
