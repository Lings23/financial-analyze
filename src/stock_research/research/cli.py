import argparse
import json
from pathlib import Path

from ..errors import ValidationError
from ..model_adapters.chat import ChatModelAdapter, load_model_config
from ..models import AccessContext, digest
from ..providers.base import ProviderRegistry
from ..service import DataService
from ..storage.artifacts import ArtifactStore
from .checkpoints import CheckpointStore
from .contracts import ResearchRequest
from .report import markdown, text
from .runtime import ResearchRuntime, _unique_object, model_messages


class DomainVersionAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        namespace.domain_version_explicit = True


class ParallelVersionAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        namespace.parallel_version_explicit = True


class ReadArtifactStores:
    """Explicit local roots; DataService still enforces source/snapshot ownership first."""
    def __init__(self, roots):
        self.stores = [ArtifactStore(root) for root in roots]

    def get(self, scope, artifact_id):
        for store in self.stores:
            try:
                return store.get(scope, artifact_id)
            except FileNotFoundError:
                continue
        raise FileNotFoundError("research source artifact is unavailable")


def add_command(commands):
    command = commands.add_parser("research", help="bounded single-stock research from pinned snapshots; explicit model authorization")
    command.add_argument("--request", required=True, help="strict JSON request manifest")
    command.add_argument("--scope", required=True, help="trusted local identity namespace, not remote authentication")
    command.add_argument("--allow-provider", action="append", required=True)
    command.add_argument("--artifacts", action="append", required=True, help="explicit input artifact roots; repeatable")
    command.add_argument("--runs", default=".runtime/research")
    command.add_argument("--output", required=True, help="new output directory; existing directories are never overwritten")
    command.add_argument("--with-model", action="store_true", help="authorize configured DeepSeek calls for the selected bounded workflow")
    command.add_argument("--config", default="test_api.txt")
    command.add_argument("--resume", help="resume/revalidate a run without resetting budget or replaying paid calls")
    command.add_argument("--workflow", choices=("overview", "research", "dynamic"), default="overview",
                         help="overview (Phase 2), fixed research (Phase 3), or dynamic single-agent research (Phase 4 M1)")
    command.add_argument("--question", help="dynamic research question; must agree with a question already pinned in the manifest")
    command.add_argument("--dynamic-version", choices=("single-dynamic-v1", "single-dynamic-v2"),
                         default="single-dynamic-v2", help="v2 typed finish rejection; explicitly pin v1 for legacy dynamic checkpoint replay")
    command.add_argument("--financial-child", action="store_true",
                         help="opt into the dynamic v2 parent with one serial restricted Financial Child")
    command.add_argument("--domain-agents", action="store_true",
                         help="opt into the dynamic v2 parent routing serial Financial/Market direct tools or AgentTools")
    command.add_argument("--parallel-domains", action="store_true",
                         help="opt into P4.5 bounded DAG Financial/Market parallel Children on the shared Runtime")
    command.add_argument("--parallel-version", choices=("dynamic-parent-parallel-v1", "dynamic-parent-parallel-v2", "dynamic-parent-parallel-v3"),
                         default="dynamic-parent-parallel-v1", action=ParallelVersionAction,
                         help="explicit Parent execution feedback v2 or lossless metadata representation v3; default v1 preserves legacy inputs; requires --parallel-domains")
    command.set_defaults(parallel_version_explicit=False)
    command.add_argument("--child-protocol-version", choices=("v1", "v2", "v3"), default="v1",
                         help="explicit Child protocol; v1 preserves legacy inputs, v2 shows read execution, v3 adds exact current action schema; requires a Child parent mode")
    command.add_argument("--domain-version", choices=("dynamic-parent-domains-v1", "dynamic-parent-domains-v2"),
                         default="dynamic-parent-domains-v2", action=DomainVersionAction,
                         help="domain parent context version (default v2); pin v1 for original checkpoint replay; requires --domain-agents")
    command.set_defaults(domain_version_explicit=False)
    command.add_argument("--preview-model", action="store_true", help="save exact outbound messages locally without calling a model")
    command.add_argument("--study-version", choices=("single-research-v1", "single-research-v2", "single-research-v3", "single-research-v4", "single-research-v5"),
                         default="single-research-v4", help="v4 structured diagnostics; opt into v5 signed profit amounts; pin legacy versions for replay")


def run(args, repository):
    preview = getattr(args, "preview_model", False)
    workflow = getattr(args, "workflow", "overview")
    question = getattr(args, "question", None)
    financial_child = getattr(args, "financial_child", False)
    domain_agents = getattr(args, "domain_agents", False)
    parallel_domains = getattr(args, "parallel_domains", False)
    parallel_version = getattr(args, "parallel_version", "dynamic-parent-parallel-v1")
    parallel_version_explicit = getattr(args, "parallel_version_explicit", hasattr(args, "parallel_version"))
    child_protocol_version = getattr(args, "child_protocol_version", "v1")
    domain_version = getattr(args, "domain_version", "dynamic-parent-domains-v2")
    domain_version_explicit = getattr(args, "domain_version_explicit", hasattr(args, "domain_version"))
    dynamic_version = getattr(args, "dynamic_version", "single-dynamic-v2")
    if preview and args.with_model:
        raise ValidationError("model preview and live model execution are mutually exclusive")
    if question is not None and workflow != "dynamic":
        raise ValidationError("--question requires --workflow dynamic")
    if sum((financial_child, domain_agents, parallel_domains)) > 1:
        raise ValidationError("--financial-child, --domain-agents and --parallel-domains are mutually exclusive")
    if child_protocol_version not in {"v1", "v2", "v3"}:
        raise ValidationError("invalid Child protocol version")
    if child_protocol_version != "v1" and not any((financial_child, domain_agents, parallel_domains)):
        raise ValidationError("--child-protocol-version v2/v3 requires a Child parent mode")
    if domain_version_explicit and not domain_agents:
        raise ValidationError("--domain-version requires --domain-agents")
    if parallel_version_explicit and not parallel_domains:
        raise ValidationError("--parallel-version requires --parallel-domains")
    if financial_child and (workflow != "dynamic" or dynamic_version != "single-dynamic-v2"):
        raise ValidationError("--financial-child requires --workflow dynamic and --dynamic-version single-dynamic-v2")
    if domain_agents and (workflow != "dynamic" or dynamic_version != "single-dynamic-v2"):
        raise ValidationError("--domain-agents requires --workflow dynamic and --dynamic-version single-dynamic-v2")
    if parallel_domains and (workflow != "dynamic" or dynamic_version != "single-dynamic-v2"):
        raise ValidationError("--parallel-domains requires --workflow dynamic and --dynamic-version single-dynamic-v2")
    if workflow == "dynamic":
        if not args.with_model and not preview:
            raise ValidationError("dynamic research requires --with-model or --preview-model")
        if preview and args.resume:
            raise ValidationError("dynamic model preview supports the first decision only; cannot resume")
    path = Path(args.request)
    if path.stat().st_size > 32000:
        raise ValidationError("research manifest too large")
    try:
        request_type = ResearchRequest
        if workflow == "research":
            from .study_contracts import StudyRequest
            request_type = StudyRequest
        elif workflow == "dynamic":
            from .dynamic_contracts import DynamicRequest
            request_type = DynamicRequest
        manifest = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
        if workflow == "dynamic" and question is not None:
            if not isinstance(manifest, dict):
                raise ValidationError("invalid dynamic research JSON")
            if "question" in manifest and manifest["question"] != question:
                raise ValidationError("--question differs from the pinned manifest question")
            manifest = {**manifest, "question": question}
        request = request_type.from_dict(manifest)
    except (ValueError, UnicodeError):
        raise ValidationError("invalid research JSON") from None
    target = Path(args.output)
    if target.exists():
        raise ValidationError("research output already exists; select a new directory")
    service = DataService(ProviderRegistry(), None, repository, ReadArtifactStores(args.artifacts))
    access = AccessContext(args.scope, frozenset(args.allow_provider))
    runtime_options = {}
    if workflow == "dynamic":
        from .dynamic_contracts import DynamicSpec
        if parallel_domains:
            from .dynamic_contracts import ParallelParentSpec
            runtime_options["spec"] = ParallelParentSpec(version=parallel_version)
        elif domain_agents:
            from .dynamic_contracts import DomainParentSpec
            runtime_options["spec"] = DomainParentSpec(version=domain_version)
        elif financial_child:
            from .dynamic_contracts import FinancialParentSpec
            runtime_options["spec"] = FinancialParentSpec()
        else:
            runtime_options["spec"] = DynamicSpec(version=dynamic_version)
        if child_protocol_version != "v1":
            from .dynamic_contracts import FinancialChildSpec, MarketChildSpec
            child_model = runtime_options["spec"].model
            if financial_child:
                runtime_options["child_spec"] = FinancialChildSpec(version="financial-child-" + child_protocol_version, model=child_model)
            else:
                runtime_options["domain_child_specs"] = {
                    "financial": FinancialChildSpec(version="financial-child-" + child_protocol_version, model=child_model),
                    "market": MarketChildSpec(version="market-child-" + child_protocol_version, model=child_model)}
    if workflow == "dynamic" and preview:
        from .dynamic import DynamicRuntime
        runtime = DynamicRuntime(service, None, None, **runtime_options)
        messages = runtime.preview(request, access)
        target.mkdir(parents=True, exist_ok=False)
        with (target / "model-messages.json").open("x", encoding="utf-8") as stream:
            json.dump(messages, stream, ensure_ascii=False, indent=2, allow_nan=False)
        preview_report = {"schema": "dynamic-research-preview/v1", "status": "preview",
                          "request": request.to_dict(), "run_id": None,
                          "spec_version": runtime.spec.version, "spec_identity": runtime.spec.identity,
                          "financial_child_enabled": financial_child or domain_agents or parallel_domains,
                          "execution_strategy": "dynamic", "model": {"status": "not_called"},
                          "usage": {"tool_calls": 0, "model_attempts": 0, "tokens_reserved": 0,
                                    "total_tokens": 0, "tokens_accounted": 0, "unknown_usage_calls": 0,
                                    "financial_provider_network_calls": 0}}
        if domain_agents or parallel_domains:
            preview_report["domain_agents_enabled"] = True
        if parallel_domains:
            preview_report["parallel_domains_enabled"] = True
        if child_protocol_version != "v1":
            preview_report["child_protocol_version"] = child_protocol_version
            preview_report["child_spec_identities"] = {
                domain: runtime._role_spec(domain).identity
                for domain in (("financial",) if financial_child else ("financial", "market"))}
        if parallel_domains or domain_agents and domain_version == "dynamic-parent-domains-v2":
            context_view = json.loads(messages[1]["content"]).get("context")
            if isinstance(context_view, dict):
                preview_report["context_representation"] = {
                    **{key: context_view[key] for key in ("schema", "catalog_ref") if key in context_view},
                    "bytes": sum(len(message["content"].encode("utf-8")) for message in messages),
                    "byte_budget": runtime.spec.context_bytes, "message_sha256": digest(messages),
                }
        with (target / "preview.json").open("x", encoding="utf-8") as stream:
            json.dump(preview_report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        with (target / "preview.md").open("x", encoding="utf-8") as stream:
            stream.write("# 动态单股研究首轮消息预览\n\n"
                         + "研究问题：" + text(request.question) + "\n\n"
                         + "仅生成首轮待发送消息；未调用模型或执行研究工具，未创建运行或付费调用账本。"
                         + ("未启动 Financial / Market Child。" if domain_agents else
                            "未启动 Financial Child。" if financial_child else "")
                         + "后续动作与消息由实际 Observation 决定。\n"
                         + ("\n上下文表示：" + text(preview_report["context_representation"].get("schema", ""))
                            + "；目录引用 " + text(preview_report["context_representation"].get("catalog_ref", ""))
                            + "；首轮消息 " + text(preview_report["context_representation"]["bytes"])
                            + " / " + text(preview_report["context_representation"]["byte_budget"]) + " 字节。\n"
                            if "context_representation" in preview_report else ""))
        return {"run_id": None, "status": "preview", "model": preview_report["model"],
                "report": str((target / "preview.md").resolve()),
                "messages": str((target / "model-messages.json").resolve()), "usage": preview_report["usage"]}
    model = ChatModelAdapter(load_model_config(args.config)) if args.with_model else None
    runtime_type = ResearchRuntime
    if workflow == "research":
        from .study import StudyRuntime
        runtime_type = StudyRuntime
    elif workflow == "dynamic":
        from .dynamic import DynamicRuntime
        runtime_type = DynamicRuntime
    if workflow == "research":
        from .study_contracts import StudySpec
        runtime_options["spec"] = StudySpec(version=getattr(args, "study_version", "single-research-v4"))
    runtime = runtime_type(service, CheckpointStore(args.runs), model, **runtime_options)
    report = runtime.run(request, access, resume=args.resume)
    target.mkdir(parents=True, exist_ok=False)
    with (target / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (target / "report.md").open("x", encoding="utf-8") as stream:
        stream.write(markdown(report))
    if preview:
        if workflow == "research":
            from .context import study_messages
            messages, _ = study_messages(report, request, runtime.spec.context_bytes, version=runtime.spec.version)
        else:
            messages = model_messages(report["facts"])
        with (target / "model-messages.json").open("x", encoding="utf-8") as stream:
            json.dump(messages, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return {"run_id": report["run_id"], "status": report["status"], "model": report["model"],
            "report": str((target / "report.md").resolve()), "usage": report["usage"]}
