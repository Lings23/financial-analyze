"""Two predeclared current observations for retrospective chronology, no retries.

Records remain in an explicit reference capture, not the production database.
The one-shot intent file prevents silently repeating either request.
"""
from datetime import date
from pathlib import Path
import json

from accept_phase2_real import write
from stock_research.__main__ import _project_tushare_token
from stock_research.models import AccessContext, DataRequest, Dataset, Security, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare import TushareProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository


ROOT = Path('.artifacts/phase3/followup-20261002/event-prices')
SCOPE = 'phase3-retrospective-event-prices-20261002'
WINDOWS = [('original', '2025-04-18', '2025-04-30'), ('correction', '2026-04-24', '2026-05-08')]


def collect():
    ROOT.mkdir(parents=True, exist_ok=False)
    write(ROOT/'plan.json', {'scope':SCOPE, 'symbol':'300122.SZ', 'windows':WINDOWS,
                           'max_calls':2, 'timeout_seconds':30, 'max_attempts':1,
                           'endpoint':'https://api.tushare.pro', 'availability':'observed_at_only'})
    artifacts = ArtifactStore(ROOT/'artifacts')
    registry = ProviderRegistry(); registry.register(TushareProvider(_project_tushare_token(), artifacts))
    access = AccessContext(SCOPE, frozenset({'tushare'}))
    repo = MemoryRepository()
    result = []
    with ProviderExecutor(ExecutionPolicy(total_timeout=30, attempt_timeout=30, max_attempts=1,
                                         min_interval=2.5, provider_concurrency=1)) as executor:
        svc = DataService(registry, executor, repo, artifacts)
        for label, start, end in WINDOWS:
            request = DataRequest(Security('300122','SZSE'), Dataset.MARKET_DAILY,
                                  date.fromisoformat(start), date.fromisoformat(end))
            write(ROOT/(label+'-intent.json'), {'started_at':utcnow().isoformat(), 'request':request.identity(),
                                             'attempt':1, 'unknown_outcome_must_not_retry':True})
            try:
                captured = svc.refresh(request, access, ('tushare',), use_cache=False)
                records = repo.read(SCOPE, captured.snapshot.snapshot_id)
                item = {'label':label, 'start':start, 'end':end, 'snapshot':captured.snapshot.snapshot_id,
                        'status':'captured' if records else 'empty', 'records':[r.to_dict() for r in records]}
            except Exception as exc:
                item = {'label':label, 'start':start, 'end':end, 'status':'failed', 'error_type':type(exc).__name__}
            write(ROOT/(label+'.json'), item)
            result.append(item)
            print(json.dumps({'label':label, 'status':item['status'], 'records':len(item.get('records',[]))}), flush=True)
        write(ROOT/'result.json', {'scope':SCOPE, 'finished_at':utcnow().isoformat(), 'provider_stats':executor.stats,
                                  'results':result, 'historical_pit_or_source_accuracy_certified':False})


if __name__ == '__main__':
    collect()
