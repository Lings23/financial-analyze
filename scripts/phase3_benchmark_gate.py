"""Trusted, offline pre-freeze checks; never adapt or rescore legacy requests."""
from collections import Counter
import json
from pathlib import Path

from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import QueryContext, digest
from stock_research.providers.tushare import TushareProvider
from stock_research.research.benchmark_contracts import validate_service_contract
from stock_research.research.scoped import ScopedReadService
from stock_research.research.study_contracts import StudyRequest


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def snapshot_metadata(service, request, binding, access):
    """Called only after an authorized query. Resolve current grants on every read.

    Capabilities here describe the pinned provider's actual captured datasets;
    no registration, network refresh, source switch or model input is involved.
    Snapshot membership is metadata, not permission to read future values.
    """
    if binding.provider not in access.allowed_providers:
        raise PermissionDenied('benchmark provider not authorized')
    query = request.data_request(binding)
    context = QueryContext(access, binding.snapshot, request.as_of, request.mode)
    owner = service
    while isinstance(owner, ScopedReadService):
        owner, context = owner._resolve(query, context)
    # Revalidate the resolved authorization and all visible artifacts first.
    owner.query(query, context)
    records = owner.repository.read(context.access.scope, binding.snapshot)
    ids = sorted({r.record_id for r in records})
    if digest({'scope': context.access.scope, 'record_ids': ids}) != binding.snapshot:
        raise IntegrityError('benchmark snapshot membership hash differs')
    datasets = sorted({r.dataset.value for r in records if r.provider == binding.provider})
    provider_datasets = set(datasets)
    registered = owner.registry._providers.get(binding.provider)
    if registered is not None:
        provider_datasets.update(d.value for d in registered.capability.datasets)
    elif binding.provider == 'tushare':
        provider_datasets.update(d.value for d in TushareProvider.capability.datasets)
    result = {'trusted': True, 'authorized': True, 'scope': access.scope,
            'owner_scope': context.access.scope, 'snapshot': binding.snapshot,
            'provider': binding.provider, 'provider_datasets': sorted(provider_datasets),
            'snapshot_datasets': datasets, 'snapshot_record_ids': ids,
            'artifacts_verified': True}
    empty_reader = getattr(owner, 'benchmark_empty_capture_reader', None)
    if empty_reader is not None:
        proof = empty_reader(request, binding, context)
        if proof is not None:
            result['empty_dataset_capture'] = proof
    return result


def precheck_cases(cases, source_context):
    cases = list(cases)
    ids = [c['id'] for c in cases]
    if not cases or len(ids) != len(set(ids)):
        raise IntegrityError('benchmark requires nonempty unique cases')
    results = []
    for case in cases:
        service, access = source_context(case)
        if 'scope' in case and case['scope'] != access.scope:
            raise PermissionDenied('benchmark candidate scope differs from authorized source context')
        request = StudyRequest.from_dict(case['request'])
        validation = validate_service_contract(request, access, service,
            lambda req, binding, identity: snapshot_metadata(service, req, binding, identity))
        results.append({'id': case['id'], 'scope': access.scope,
                        'request_sha256': digest(case['request']), **validation})
    return {'schema': 'phase3-benchmark-precheck-v1',
            'candidate_sha256': digest(cases), 'case_count': len(cases),
            'valid_case_count': sum(c['valid'] is True for c in results),
            'invalid_case_count': sum(c['valid'] is False for c in results),
            'not_assessable_case_count': sum(c['valid'] is None for c in results),
            'issue_taxonomy': dict(Counter(i['code'] for c in results for i in c['issues'])),
            'all_cases_contract_valid': all(c['valid'] is True for c in results),
            'provider_network_calls': 0, 'generation_model_calls': 0, 'cases': results}


def require_valid_precheck(cases, precheck):
    if precheck['candidate_sha256'] != digest(cases):
        raise IntegrityError('benchmark candidates differ from prechecked inputs')
    expected = {c['id']: c for c in cases}
    actual = {c['id']: c for c in precheck['cases']}
    if (len(actual) != len(precheck['cases']) or set(actual) != set(expected)
            or precheck['case_count'] != len(cases)):
        raise IntegrityError('benchmark precheck denominator differs')
    for key, case in expected.items():
        if actual[key]['request_sha256'] != digest(case['request']):
            raise IntegrityError('benchmark request differs from precheck')
    if not all(c['valid'] is True for c in actual.values()):
        raise IntegrityError('benchmark_contract_invalid: invalid or unassessable inputs cannot freeze')


def freeze_benchmark(path, cases, precheck, *, benchmark_version, implementation_version,
                     parent_manifest_sha256, source_context):
    """Freeze the entire requested set or none. Never silently filter hard cases."""
    # Caller-supplied verdicts are not permission to freeze: reauthorize and
    # recompute from pinned sources, including current revocable source grants.
    fresh = precheck_cases(cases, source_context)
    require_valid_precheck(cases, fresh)
    if fresh != precheck:
        raise IntegrityError('precheck differs from freshly authorized source validation')
    if (not isinstance(benchmark_version, str) or not benchmark_version.strip()
            or not isinstance(implementation_version, str) or not implementation_version.strip()
            or not isinstance(parent_manifest_sha256, str)
            or len(parent_manifest_sha256) != 64
            or any(c not in '0123456789abcdef' for c in parent_manifest_sha256)):
        raise IntegrityError('new benchmark/version lineage is required')
    value = {'schema': 'phase3-contract-gated-benchmark-v1',
             'benchmark_version': benchmark_version, 'implementation_version': implementation_version,
             'parent_manifest_sha256': parent_manifest_sha256,
             'precheck_sha256': digest(precheck), 'candidate_sha256': digest(cases),
             'original_scores_modified': False, 'cases': cases, 'contract_validation': precheck}
    write_new(path, value)
    return value
