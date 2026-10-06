import random
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass

from ..errors import PermissionDenied, TransientProviderError, ValidationError
from ..models import digest
from .base import validate_records


@dataclass(frozen=True)
class ExecutionPolicy:
    total_timeout: float = 30.0
    attempt_timeout: float = 10.0
    max_attempts: int = 3
    min_interval: float = 1.0
    provider_concurrency: int = 2
    cache_ttl: float = 60.0
    cache_entries: int = 128
    retry_base: float = 0.25

    def __post_init__(self):
        if (self.total_timeout <= 0 or self.attempt_timeout <= 0 or self.max_attempts < 1
                or self.min_interval < 0 or self.provider_concurrency < 1 or self.cache_ttl < 0
                or self.cache_entries < 1 or self.retry_base < 0):
            raise ValidationError("invalid provider execution policy")


class ProviderExecutor:
    """Process-local coalescing; immutable captured results, never cross-scope reuse.

    Ingestion has no research cutoff: it captures current data. Query caching (if added)
    must additionally include cutoff, mode and snapshot. No query cache exists here.
    """

    def __init__(self, policy=None, workers=4):
        self.policy = policy or ExecutionPolicy()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="provider")
        self._lock = threading.RLock()
        self._inflight = {}
        self._cache = OrderedDict()
        self._limits = {}
        self._next_start = {}
        self._start_locks = {}
        self._stats = {"logical_calls": 0, "attempts": 0, "cache_hits": 0, "dedup_hits": 0, "retries": 0}

    @property
    def stats(self):
        with self._lock:
            return dict(self._stats)

    def _count(self, key):
        with self._lock:
            self._stats[key] += 1

    def fetch(self, provider, request, access, use_cache=True, timeout=None):
        if provider.capability.name not in access.allowed_providers:
            raise PermissionDenied("provider not authorized")
        key = digest({"scope": access.scope, "allowed_providers": sorted(access.allowed_providers),
                      "provider": provider.capability.name, "version": provider.capability.version,
                      "request": request.identity()})
        budget = self.policy.total_timeout if timeout is None else min(timeout, self.policy.total_timeout)
        if budget <= 0:
            raise TransientProviderError("provider total deadline exceeded")
        deadline = time.monotonic() + budget
        with self._lock:
            self._stats["logical_calls"] += 1
            cached = self._cache.get(key)
            if use_cache and cached and cached[0] > time.monotonic():
                self._cache.move_to_end(key)
                self._stats["cache_hits"] += 1
                return cached[1]
            prior = self._inflight.get(key)
            if prior is not None and prior.done():
                # A waiter may wake before the completion callback acquires this lock.
                self._completed(key, prior)
                cached = self._cache.get(key)
                if use_cache and cached and cached[0] > time.monotonic():
                    self._stats["cache_hits"] += 1
                    return cached[1]
            if key in self._inflight:
                future = self._inflight[key]
                self._stats["dedup_hits"] += 1
            else:
                future = self._pool.submit(self._run, provider, request, access.scope, deadline)
                self._inflight[key] = future
                future.add_done_callback(lambda completed: self._completed(key, completed))
        try:
            # Timing out this waiter never cancels work required by another waiter.
            return future.result(timeout=max(0, deadline - time.monotonic()))
        except FutureTimeout:
            raise TransientProviderError("provider total deadline exceeded") from None

    def _completed(self, key, future):
        with self._lock:
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)
            if not future.cancelled() and future.exception() is None:
                result = future.result()
                # Empty responses are not evidence of coverage, and are not cached.
                if result and self.policy.cache_ttl:
                    self._cache[key] = (time.monotonic() + self.policy.cache_ttl, result)
                    self._cache.move_to_end(key)
                    while len(self._cache) > self.policy.cache_entries:
                        self._cache.popitem(last=False)

    def _run(self, provider, request, scope, deadline):
        name = provider.capability.name
        with self._lock:
            semaphore = self._limits.setdefault(name, threading.BoundedSemaphore(self.policy.provider_concurrency))
            start_lock = self._start_locks.setdefault(name, threading.Lock())
        for attempt in range(self.policy.max_attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not semaphore.acquire(timeout=remaining):
                raise TransientProviderError("provider deadline expired in queue")
            try:
                if not start_lock.acquire(timeout=max(0, deadline-time.monotonic())):
                    raise TransientProviderError("provider start queue deadline exceeded")
                try:
                    start = self._next_start.get(name, time.monotonic())
                    if start >= deadline:
                        raise TransientProviderError("provider rate limit exceeds deadline")
                    while time.monotonic() < start:
                        time.sleep(max(0, start-time.monotonic()))
                    self._count("attempts")
                    # Anchor the next slot to the actual invocation, not an earlier reservation.
                    self._next_start[name] = time.monotonic() + self.policy.min_interval
                finally:
                    start_lock.release()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransientProviderError("provider deadline exceeded")
                result = provider.fetch(request, scope, min(self.policy.attempt_timeout, remaining))
                validate_records(provider, request, result)
                if time.monotonic() > deadline:
                    raise TransientProviderError("late provider result discarded")
                return result
            except TransientProviderError as exc:
                if attempt + 1 >= self.policy.max_attempts:
                    raise
                delay = max(exc.retry_after, self.policy.retry_base * 2 ** attempt * random.uniform(0.5, 1.5))
                if time.monotonic() + delay >= deadline:
                    raise TransientProviderError("retry would exceed provider deadline") from None
            finally:
                semaphore.release()
            self._count("retries")
            time.sleep(delay)
        raise AssertionError("unreachable")

    def close(self):
        self._pool.shutdown(wait=True, cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
