"""Local Phase 6 delivery integrity; outputs counts and hashes, never credentials."""
import argparse
from pathlib import Path

import phase6_evaluate as phase6
from stock_research.errors import IntegrityError
from stock_research.model_adapters.chat import load_model_config


def run():
    root = phase6.OLD.ROOT
    plan_path = phase6.OUT / "plan.json"
    plan, _ = phase6.checked(phase6.OLD.sha(plan_path), replay=True)
    config = load_model_config(root / "test_api.txt")
    secret = config.api_key.encode("utf-8")
    if (config.model != plan["model"] or phase6.digest(config.endpoint) != plan["endpoint_sha256"]
            or phase6.history_hashes() != plan["history_hashes"]):
        raise IntegrityError("configured identity or retained historical evidence differs")
    paths = [p for directory in ("src", "scripts", "tests", "docs")
             for p in (root / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    paths += [root / "README.md", root / "AGENTS.md"]
    paths += [p for p in phase6.OUT.rglob("*") if p.is_file()]
    paths += [p for p in (root / ".runtime").glob("phase6*") if p.is_file()]
    matches = [p.relative_to(root).as_posix() for p in paths if secret in p.read_bytes()]
    forbidden = [p.relative_to(root).as_posix() for p in phase6.OUT.rglob("*")
                 if p.is_file() and p.name.lower() in {"test_api.txt", "tushare.txt", ".env"}]
    copied = phase6.OLD.read(phase6.OUT / "source-manifest.json")
    for name, checksum in copied["files"].items():
        if phase6.OLD.sha(phase6.OUT / "frozen-source" / name) != checksum:
            raise IntegrityError("frozen source copy changed")
    for name, checksum in plan["code_files"].items():
        if phase6.OLD.sha(root / name) != checksum:
            raise IntegrityError("current implementation differs from frozen candidate")
    if matches or forbidden:
        raise IntegrityError("credential or forbidden secret file entered delivery")
    return {"schema": "phase6-delivery-integrity/v1", "status": "passed",
        "plan_sha256": phase6.OLD.sha(plan_path), "source_files_scanned": len(paths),
        "secret_matches": 0, "forbidden_files": 0, "secret_contents_output": False,
        "frozen_code_files": len(plan["code_files"]), "frozen_source_copies": len(copied["files"]),
        "current_code_matches_freeze": True, "historical_files_unchanged": True,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "phase6_file_sha256": phase6.original.file_hashes(phase6.OUT),
        "no_distribution_built_or_published": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    phase6.OLD.write_new(args.output, result)
    print({key: value for key, value in result.items() if key != "phase6_file_sha256"})


if __name__ == "__main__":
    main()
