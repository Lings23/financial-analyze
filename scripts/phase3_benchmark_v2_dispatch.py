"""Execution adapter v2: preview the standard aggregated Tool output.

The first preview adapter lacked status/warnings. Its failure is retained; the
frozen cases, Agent implementation, prompt and scores are never changed here.
"""
import hashlib
import json

from phase3_benchmark_v2 import (OUT, SPEC, CampaignSources, checked_manifest,
    load_model_config, sha, read, write_new, ROOT, StudyRequest, StudyRuntime, study_messages, digest)
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import IntegrityError
from stock_research.research.contracts import DOMAINS
from stock_research.research.tools import read_domain


def main():
    manifest = checked_manifest()
    sources = CampaignSources()
    if validate_cases(manifest['cases'], sources.context) != manifest['contract_validation']:
        raise IntegrityError('whole frozen batch source contract differs')
    plans = []
    for case in manifest['cases']:
        service, access = sources.context(case)
        request = StudyRequest.from_dict(case['request'])
        outputs = {key: value for name in sorted({DOMAINS[b.dataset] for b in request.bindings})
            for key, value in read_domain(service, request, access, name).items()}
        frozen = read(ROOT / case['input_path'])
        if digest({key: {field: value[field] for field in ('provider', 'snapshot', 'records')}
                for key, value in outputs.items()}) != digest(frozen['datasets']):
            raise IntegrityError('standard Tool data differs from frozen source inputs')
        computed = StudyRuntime(None, None, spec=SPEC)._calculate(outputs, request)
        messages, context = study_messages(computed, request, SPEC.context_bytes, version=SPEC.version)
        plans.append({'case_id': case['id'], 'messages': messages, 'message_sha256': digest(messages),
                      'context': context, 'max_output_tokens': SPEC.output_tokens})
    config = load_model_config()
    if config.model != SPEC.model:
        raise IntegrityError('configured model differs from frozen model')
    write_new(OUT / 'model-dispatch-plan.json', {'manifest_sha256': sha(OUT / 'benchmark-manifest.json'),
        'endpoint_sha256': hashlib.sha256(config.endpoint.encode()).hexdigest(), 'model': SPEC.model,
        'execution_adapter': 'standard-aggregate-preview/v2', 'execution_adapter_sha256': sha(__file__),
        'max_dispatches': len(plans), 'max_token_reservations': manifest['evaluation_protocol']['max_token_reservations'], 'cases': plans})
    print(json.dumps({'planned_dispatches': len(plans), 'plan_sha256': sha(OUT / 'model-dispatch-plan.json'),
        'total_context_bytes': sum(plan['context']['bytes'] for plan in plans)}))


if __name__ == '__main__':
    main()
