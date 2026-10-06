"""Explicit authorized projection of a pinned Tushare v2 income archive.

No network, credentials, fallback or historical-release promotion. New normalized
rows retain the proved capture time and receive the actual projection ingestion time.
Callers persist a new snapshot; the old one is never rewritten.
"""
from datetime import datetime, timedelta, timezone
import json

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import DataRecord, DataRequest, Dataset, QueryContext, aware, digest, utcnow
from ..providers.tushare import TushareProvider, _date, _metric


def project_archived_income(service, request, access, *, ingested_at=None):
    binding = next(b for b in request.bindings if b.dataset == 'financial_income')
    if binding.provider != 'tushare' or binding.provider not in access.allowed_providers:
        raise PermissionDenied('archived income source is not authorized')
    context = QueryContext(access, binding.snapshot, request.as_of, request.mode)
    rows = service.query(request.data_request(binding), context).records
    if not rows:
        raise ValidationError('archived income requires a visible source record')
    anchor = max(rows, key=lambda r: r.period)
    if anchor.provider_version != '2' or anchor.availability_basis != 'observed_at':
        raise ValidationError('only pinned Tushare v2 observations support archive projection')
    raw = service.evidence(request.data_request(binding), context, anchor.record_id, anchor.artifact_id)
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        raise IntegrityError('income archive is not valid JSON') from None
    if (not isinstance(body,dict) or body.get('archive_schema') != 'tushare_requested_response_v2' or body.get('api_name') != 'income'
            or body.get('business_code') != 0 or body.get('fields') != list(TushareProvider.INCOME_FIELDS)
            or body.get('params') != {'ts_code':request.security.provider_symbol,'report_type':'1'}
            or not isinstance(body.get('items'), list) or not 1 <= len(body['items']) < 1000
            or body.get('response_row_count') != len(body['items'])):
        raise IntegrityError('income archive schema or binding differs')
    capture = aware(datetime.fromisoformat(body['finished_at']))
    started = aware(datetime.fromisoformat(body['started_at']))
    if capture != anchor.retrieved_at or capture != anchor.available_at or started > capture:
        raise IntegrityError('income archive capture time differs from visible record')
    ingestion = aware(ingested_at or utcnow())
    if ingestion < anchor.ingested_at or ingestion < capture:
        raise ValidationError('archive projection ingestion cannot be backdated')
    try:
        prior = anchor.period.replace(year=anchor.period.year-1)
    except ValueError:
        raise ValidationError('prior same-period date is invalid') from None
    expanded = DataRequest(request.security, Dataset.FINANCIAL_INCOME, prior, anchor.period)
    records, anchor_seen = [], False
    today = capture.astimezone(timezone(timedelta(hours=8))).date()
    for cells in body['items']:
        if (not isinstance(cells, list) or len(cells) != len(body['fields'])
                or any(type(v) not in {str,int,float,bool,type(None)} for v in cells)):
            raise IntegrityError('income archive row schema differs')
        row = dict(zip(body['fields'],cells))
        if row['ts_code'] != request.security.provider_symbol:
            raise IntegrityError('income archive security differs')
        period = _date(row['end_date'])
        if period > today:
            raise IntegrityError('income archive contains a future observed period')
        if not expanded.start <= period <= expanded.end:
            continue
        ann = _date(row['ann_date'])
        f_ann = _date(row['f_ann_date']) if row['f_ann_date'] else ann
        if str(row['report_type']) != '1' or max(ann,f_ann)>today:
            raise IntegrityError('income archive report type or disclosure date differs')
        metrics = (_metric(row,'revenue','revenue','CNY','CNY'),
                   _metric(row,'total_revenue','total_revenue','CNY','CNY'),
                   _metric(row,'n_income_attr_p','net_income_parent','CNY','CNY'))
        revision = digest(row)
        if revision == anchor.revision_id and period == anchor.period:
            if metrics != anchor.metrics and tuple(sorted(metrics,key=lambda m:m.name)) != anchor.metrics:
                raise IntegrityError('income archive values differ from anchor')
            anchor_seen = True
        records.append(DataRecord(request.security.security_id,request.security.canonical_symbol,
                                  Dataset.FINANCIAL_INCOME,period,expanded.basis,metrics,'tushare','2-archive-projection-1',
                                  anchor.source_url,f'archive_income:{request.security.provider_symbol}:{period}',revision,
                                  capture,capture,ingestion,'observed_at',anchor.artifact_id,anchor.provider_call_id,
                                  announcement_date=ann,revision_order=int(max(ann,f_ann).strftime('%Y%m%d')),
                                  quality_flags=tuple(sorted(set(anchor.quality_flags)|{'archived_observation_projection','historical_release_not_verified'}))))
    if not anchor_seen:
        raise IntegrityError('income archive does not contain the visible anchor version')
    return expanded, tuple(records), {'source_request':request.to_dict(),'source_snapshot':binding.snapshot,
                                     'source_record_id':anchor.record_id,'source_artifact_id':anchor.artifact_id,
                                     'source_provider_call_id':anchor.provider_call_id,
                                     'captured_at':capture.isoformat(),'projection_ingested_at':ingestion.isoformat(),
                                     'historical_release_verified':False,'financial_provider_network_calls':0}
