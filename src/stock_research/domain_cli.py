"""Trusted local P1.8 CLI; provider allowlists are supplied by the local operator."""
import argparse
from datetime import date, datetime
from pathlib import Path

from .domains import DomainDataset, DomainRequest, Subject
from .errors import ValidationError
from .models import AccessContext, PITMode, QueryContext
from .providers.base import ProviderRegistry
from .providers.executor import ExecutionPolicy, ProviderExecutor
from .providers.documents import AkShareNewsProvider, CNInfoAnnouncementProvider
from .providers.tushare_domains import TushareDomainProvider
from .service import DataService
from .storage.artifacts import ArtifactStore


def add_commands(commands):
    for name in ("domain-ingest", "domain-query", "domain-evidence"):
        parser = commands.add_parser(name, help="P1.8 typed observation " + name.split("-")[1])
        parser.add_argument("--scope", required=True)
        parser.add_argument("--kind", required=True, choices=("equity", "index", "exchange"))
        parser.add_argument("--code", required=True, help="six-digit equity, qualified index, or exchange code")
        parser.add_argument("--exchange", default="", choices=("", "SSE", "SZSE", "BSE"))
        parser.add_argument("--dataset", required=True, choices=[d.value for d in DomainDataset])
        parser.add_argument("--start", required=True, type=date.fromisoformat)
        parser.add_argument("--end", required=True, type=date.fromisoformat)
        parser.add_argument("--selector", default="", help="exact title substring for announcements only")
        parser.add_argument("--artifacts", default=".artifacts")
        if name == "domain-ingest":
            parser.add_argument("--provider", required=True, choices=("tushare", "cninfo", "akshare"))
            parser.add_argument("--parent-snapshot")
            parser.add_argument("--timeout", type=float, default=90, help="total/attempt seconds, at most 120")
        else:
            parser.add_argument("--providers", required=True, help="trusted local comma-separated source allowlist")
            parser.add_argument("--snapshot", required=True)
            parser.add_argument("--as-of", required=True, type=datetime.fromisoformat)
            parser.add_argument("--mode", choices=[m.value for m in PITMode], default="public")
            if name == "domain-evidence":
                parser.add_argument("--record", required=True)
                parser.add_argument("--artifact", help="must belong to the authorized visible record")
                parser.add_argument("--output", required=True, help="new output file; existing files are never overwritten")


def run(args, repository, token_loader):
    request = DomainRequest(Subject(args.kind, args.code, args.exchange), DomainDataset(args.dataset),
                            args.start, args.end, args.selector)
    ingest = args.command == "domain-ingest"
    providers = {args.provider} if ingest else set(args.providers.split(","))
    if not providers or not providers <= {"tushare", "cninfo", "akshare"}:
        raise ValidationError("explicit supported source allowlist required")
    access = AccessContext(args.scope, frozenset(providers))
    artifacts = ArtifactStore(args.artifacts)
    registry = ProviderRegistry()
    if ingest:
        if not 0 < args.timeout <= 120:
            raise ValidationError("domain timeout must be in (0,120] seconds")
        constructors = {"tushare": lambda: TushareDomainProvider(token_loader(), artifacts),
                        "cninfo": lambda: CNInfoAnnouncementProvider(artifacts),
                        "akshare": lambda: AkShareNewsProvider(artifacts)}
        registry.register(constructors[args.provider]())
    policy = ExecutionPolicy(total_timeout=args.timeout, attempt_timeout=args.timeout,
                             max_attempts=1, min_interval=1.5) if ingest else ExecutionPolicy()
    with ProviderExecutor(policy) as executor:
        service = DataService(registry, executor, repository, artifacts)
        if ingest:
            result = service.refresh(request, access, (args.provider,), args.parent_snapshot)
            return {"snapshot_id": result.snapshot.snapshot_id, "provider": result.provider,
                    "record_count": result.record_count, "warnings": result.warnings,
                    "provider_stats": executor.stats}
        context = QueryContext(access, args.snapshot, args.as_of, PITMode(args.mode))
        if args.command == "domain-evidence":
            content = service.evidence(request, context, args.record, args.artifact)
            path = Path(args.output)
            with path.open("xb") as stream:
                stream.write(content)
            return {"status": "exported", "bytes": len(content), "path": str(path)}
        result = service.query(request, context)
        return {"status": result.status, "snapshot_id": result.snapshot_id, "coverage": result.coverage,
                "as_of_date": result.as_of_date.isoformat(), "warnings": result.warnings,
                "records": [r.to_dict() for r in result.records]}
