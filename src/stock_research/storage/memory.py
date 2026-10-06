from threading import RLock

from ..errors import IntegrityError, PermissionDenied
from ..models import Snapshot, digest, utcnow


class MemoryRepository:
    """Test/reference repository; not the production persistence fallback."""

    def __init__(self):
        self._records = {}
        self._snapshots = {}
        self._lock = RLock()

    def commit(self, scope, records, parent_snapshot_id=None):
        with self._lock:
            ids = set()
            if parent_snapshot_id:
                parent = self.snapshot(scope, parent_snapshot_id)
                ids.update(parent.record_ids)
            for record in records:
                key = scope, record.record_id
                if key in self._records and self._records[key].identity_payload() != record.identity_payload():
                    raise IntegrityError("immutable record conflict")
                self._records.setdefault(key, record)
                ids.add(record.record_id)
            ids = tuple(sorted(ids))
            sid = digest({"scope": scope, "record_ids": ids})
            self._snapshots.setdefault(sid, Snapshot(sid, scope, ids, utcnow()))
            return self._snapshots[sid]

    def snapshot(self, scope, snapshot_id):
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot is None or snapshot.scope != scope:
                raise PermissionDenied("snapshot not available in this scope")
            return snapshot

    def read(self, scope, snapshot_id):
        with self._lock:
            snapshot = self.snapshot(scope, snapshot_id)
            return tuple(self._records[(scope, rid)] for rid in snapshot.record_ids)
