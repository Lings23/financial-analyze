"""Reauthorize frozen reads and probe recipient/snapshot/revoked-grant boundaries."""
from phase3_benchmark_v2 import OUT, CampaignSources, checked_manifest, write_new, StudyRequest
from stock_research.models import AccessContext, QueryContext
from stock_research.errors import PermissionDenied


def main():
    manifest = checked_manifest()
    sources = CampaignSources()
    results = []
    for case in manifest['cases']:
        service, access = sources.context(case)
        request = StudyRequest.from_dict(case['request'])
        binding = request.bindings[0]
        query = request.data_request(binding)
        correct = QueryContext(access, binding.snapshot, request.as_of, request.mode)
        rows = service.query(query, correct).records
        checks = {}
        for name, context in (
                ('wrong_recipient_rejected', QueryContext(AccessContext(access.scope + '/wrong', access.allowed_providers), binding.snapshot, request.as_of, request.mode)),
                ('wrong_snapshot_rejected', QueryContext(access, '0' * 64, request.as_of, request.mode))):
            try:
                service.query(query, context)
                checks[name] = False
            except PermissionDenied:
                checks[name] = True
        service.current_grants = lambda: ()
        try:
            service.query(query, correct)
            checks['revoked_grant_rejected'] = False
        except PermissionDenied:
            checks['revoked_grant_rejected'] = True
        results.append({'case_id': case['id'], 'positive_read_record_count': len(rows), 'checks': checks})
    write_new(OUT / 'authorization-boundary-checks.json', {'cases': results,
        'probe_count': sum(len(item['checks']) for item in results),
        'passed': all(all(item['checks'].values()) for item in results), 'model_calls': 0, 'provider_calls': 0})


if __name__ == '__main__':
    main()
