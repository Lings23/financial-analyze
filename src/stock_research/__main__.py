"""Trusted local CLI. --scope is not an authentication mechanism for remote users."""
import argparse
import json
import os
import sys
from pathlib import Path
from dataclasses import asdict
from datetime import date, datetime

from .errors import DataError, ValidationError
from .models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from .providers.base import ProviderRegistry
from .providers.executor import ProviderExecutor
from .providers.tushare import TushareProvider
from .service import DataService
from .storage.artifacts import ArtifactStore
from .storage.postgres import PostgresRepository


def _print_utf8_json(value):
    output = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(output.encode("utf-8"))
    else:
        sys.stdout.write(output)


def _project_tushare_token():
    """Use an explicit process token, or a local project .env when run from its root."""
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token
    path = Path(".env")
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            content = stream.read(4097)
    except OSError:
        raise ValidationError("project .env could not be read") from None
    if len(content) > 4096:
        raise ValidationError("project .env is too large")
    matches = [line.partition("=")[2].strip() for line in content.splitlines()
               if line.startswith("TUSHARE_TOKEN=")]
    if len(matches) != 1 or not matches[0] or any(c.isspace() for c in matches[0]):
        raise ValidationError("project .env needs one TUSHARE_TOKEN entry")
    return matches[0]


def parser():
    root = argparse.ArgumentParser(description="Stock research data and bounded single-agent CLI")
    commands = root.add_subparsers(dest="command", required=True)
    from .domain_cli import add_commands
    add_commands(commands)
    from .research.cli import add_command
    add_command(commands)
    commands.add_parser("demo", help="run offline synthetic PIT demo")
    commands.add_parser("migrate", help="create PostgreSQL tables; DSN from STOCK_RESEARCH_DSN")
    ak = commands.add_parser("akshare-check", help="capture approved AKShare endpoints (uses network)")
    ak.add_argument("--scope", required=True, help="trusted local data namespace")
    ak.add_argument("--endpoint", choices=(
        "stock_sse_summary", "stock_szse_summary", "stock_zh_a_spot_em",
        "stock_cy_a_spot_em", "stock_kc_a_spot_em",
        "stock_comment_detail_zlkp_jgcyd_em",
        "stock_comment_detail_scrd_focus_em"))
    ak.add_argument("--symbol", default="600000")
    ak.add_argument("--date", type=date.fromisoformat,
                    help="required when checking SZSE summary; YYYY-MM-DD")
    ak.add_argument("--timeout", type=float, default=45.0, help="seconds per endpoint, maximum 120")
    ak.add_argument("--artifacts", default=".artifacts")
    read = commands.add_parser("akshare-read", help="read a captured AKShare snapshot with PIT checks")
    read.add_argument("--scope", required=True)
    read.add_argument("--snapshot", required=True)
    read.add_argument("--as-of", required=True, type=datetime.fromisoformat)
    read.add_argument("--mode", choices=[x.value for x in PITMode], default="public")
    read.add_argument("--artifacts", default=".artifacts")
    for name in ("llm-check", "llm-chat"):
        command = commands.add_parser(name, help="call configured DeepSeek model (uses API quota)")
        command.add_argument("--config", default="test_api.txt")
        command.add_argument("--timeout", type=float, default=30.0)
        if name == "llm-chat":
            command.add_argument("--prompt", required=True)
            command.add_argument("--max-tokens", type=int, default=256)
    for name in ("ingest", "query"):
        command = commands.add_parser(name)
        command.add_argument("--scope", required=True, help="trusted local data namespace")
        command.add_argument("--symbol", required=True)
        command.add_argument("--exchange", required=True, choices=("SSE", "SZSE", "BSE"))
        command.add_argument("--dataset", required=True, choices=[x.value for x in Dataset])
        command.add_argument("--start", required=True, type=date.fromisoformat)
        command.add_argument("--end", required=True, type=date.fromisoformat)
        command.add_argument("--artifacts", default=".artifacts")
        if name == "ingest":
            command.add_argument("--parent-snapshot")
        else:
            command.add_argument("--snapshot", required=True)
            command.add_argument("--as-of", required=True, type=datetime.fromisoformat)
            command.add_argument("--mode", choices=[x.value for x in PITMode], default="public")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "demo":
        from .demo import main as demo
        demo()
        return 0
    try:
        if args.command in {"akshare-check", "akshare-read"}:
            from .providers.akshare import AkShareCaptureProvider, COMMENT, SOURCES

            provider = AkShareCaptureProvider(ArtifactStore(args.artifacts))
            access = AccessContext(args.scope, frozenset({"akshare"}))
            if args.command == "akshare-read":
                capture = provider.read(args.snapshot, access, args.as_of, PITMode(args.mode))
                _print_utf8_json({"snapshot_id": capture.snapshot_id, "endpoint": capture.endpoint,
                                  "captured_at": capture.captured_at.isoformat(),
                                  "ingested_at": capture.ingested_at.isoformat(),
                                  "row_count": capture.row_count, "columns": capture.columns,
                                  "completion_basis": capture.completion_basis,
                                  "source_artifact_ids": capture.source_artifact_ids,
                                  "quality_flags": capture.quality_flags})
                return 0
            endpoints = [args.endpoint] if args.endpoint else list(SOURCES)
            if "stock_szse_summary" in endpoints and args.date is None:
                raise ValidationError("--date is required when checking stock_szse_summary")
            results = []
            for endpoint in endpoints:
                try:
                    capture = provider.capture(
                        endpoint, access,
                        symbol=args.symbol if endpoint in COMMENT else None,
                        trade_date=args.date if endpoint == "stock_szse_summary" else None,
                        timeout=args.timeout)
                    results.append({"endpoint": endpoint, "status": "captured",
                                    "snapshot_id": capture.snapshot_id,
                                    "captured_at": capture.captured_at.isoformat(),
                                    "row_count": capture.row_count, "columns": capture.columns,
                                    "completion_basis": capture.completion_basis,
                                    "source_artifact_ids": capture.source_artifact_ids,
                                    "quality_flags": capture.quality_flags})
                except DataError as exc:
                    results.append({"endpoint": endpoint, "status": "failed",
                                    "error": type(exc).__name__, "message": str(exc)})
            _print_utf8_json({"provider": "akshare", "results": results})
            return 0 if all(r["status"] == "captured" for r in results) else 2
        if args.command in {"llm-check", "llm-chat"}:
            from .model_adapters.chat import ChatModelAdapter, load_model_config
            adapter = ChatModelAdapter(load_model_config(args.config))
            checking = args.command == "llm-check"
            prompt = "Reply with exactly OK and no other text." if checking else args.prompt
            result = adapter.complete([{"role": "user", "content": prompt}],
                                      max_tokens=16 if checking else args.max_tokens, timeout=args.timeout)
            output = asdict(result)
            if checking:
                verified = (result.content.strip() == "OK" and result.finish_reason == "stop"
                            and result.returned_model == result.requested_model)
                output["status"] = "verified" if verified else "unexpected_response"
            else:
                verified = result.finish_reason == "stop"
                output["status"] = "completed" if verified else "truncated"
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if verified else 2
        dsn = os.environ.get("STOCK_RESEARCH_DSN")
        if not dsn:
            raise ValidationError("STOCK_RESEARCH_DSN is required")
        repository = PostgresRepository(dsn)
        if args.command == "research":
            from .research.cli import run
            output = run(args, repository)
            _print_utf8_json(output)
            return 0 if output["status"] in {"completed", "preview"} else 2
        if args.command == "migrate":
            repository.migrate()
            print(json.dumps({"status": "migrated", "schema_version": 2}))
            return 0
        if args.command.startswith("domain-"):
            from .domain_cli import run
            _print_utf8_json(run(args, repository, _project_tushare_token))
            return 0
        request = DataRequest(Security(args.symbol, args.exchange), Dataset(args.dataset), args.start, args.end)
        access = AccessContext(args.scope, frozenset({"tushare"}))
        artifacts = ArtifactStore(args.artifacts)
        registry = ProviderRegistry()
        with ProviderExecutor() as executor:
            service = DataService(registry, executor, repository, artifacts)
            if args.command == "ingest":
                registry.register(TushareProvider(_project_tushare_token(), artifacts))
                result = service.refresh(request, access, parent_snapshot_id=args.parent_snapshot)
                output = {"snapshot_id": result.snapshot.snapshot_id, "provider": result.provider,
                          "record_count": result.record_count, "warnings": result.warnings,
                          "provider_stats": executor.stats}
            else:
                result = service.query(request, QueryContext(access, args.snapshot, args.as_of, PITMode(args.mode)))
                output = {"status": result.status, "snapshot_id": result.snapshot_id,
                          "as_of_date": result.as_of_date.isoformat(), "coverage": result.coverage,
                          "warnings": result.warnings, "records": [r.to_dict() for r in result.records]}
            print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except DataError as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        # DSNs and raw provider payloads must not leak through exception messages.
        print(json.dumps({"error": type(exc).__name__, "message": "operation failed; verify configuration and service availability"}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
