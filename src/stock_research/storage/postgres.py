from importlib.resources import files

from ..errors import IntegrityError, PermissionDenied
from ..models import DataRecord, Snapshot, digest


class PostgresRepository:
    """Transactions are per operation; connections are never shared between threads.

    scope is an application authorization boundary. Database credentials are internal;
    this does not claim to provide untrusted direct-SQL tenant isolation.
    """

    def __init__(self, dsn: str):
        import psycopg
        from psycopg.types.json import Jsonb
        self._connect = lambda: psycopg.connect(dsn)
        self._jsonb = Jsonb

    def migrate(self):
        sql = files("stock_research.storage").joinpath("schema.sql").read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(638271001)")
            connection.execute(sql)
            connection.execute(files("stock_research.storage").joinpath("schema_v2.sql").read_text(encoding="utf-8"))

    def _snapshot(self, connection, scope, snapshot_id):
        row = connection.execute(
            "SELECT record_ids, created_at FROM stock_research.snapshots "
            "WHERE scope = %s AND snapshot_id = %s", (scope, snapshot_id)).fetchone()
        if row is None:
            raise PermissionDenied("snapshot not available in this scope")
        ids = tuple(row[0])
        if digest({"scope": scope, "record_ids": ids}) != snapshot_id:
            raise IntegrityError("snapshot manifest hash mismatch")
        return Snapshot(snapshot_id, scope, ids, row[1])

    def snapshot(self, scope, snapshot_id):
        with self._connect() as connection:
            return self._snapshot(connection, scope, snapshot_id)

    def commit(self, scope, records, parent_snapshot_id=None):
        with self._connect() as connection:
            ids = set()
            if parent_snapshot_id:
                ids.update(self._snapshot(connection, scope, parent_snapshot_id).record_ids)
            for record in records:
                connection.execute(
                    "INSERT INTO stock_research.records "
                    "(scope, record_id, security_id, dataset, period, provider, available_at, "
                    "retrieved_at, ingested_at, payload, record_kind) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (scope, record_id) DO NOTHING",
                    (scope, record.record_id, record.security_id, record.dataset.value, record.period,
                     record.provider, record.available_at, record.retrieved_at, record.ingested_at,
                     self._jsonb(record.to_dict()), record.to_dict().get("record_kind", "legacy_v1")))
                stored = connection.execute(
                    "SELECT payload FROM stock_research.records WHERE scope=%s AND record_id=%s",
                    (scope, record.record_id)).fetchone()[0]
                if DataRecord.from_dict(stored).identity_payload() != record.identity_payload():
                    raise IntegrityError("immutable record conflict")
                ids.add(record.record_id)
            ids = tuple(sorted(ids))
            sid = digest({"scope": scope, "record_ids": ids})
            connection.execute(
                "INSERT INTO stock_research.snapshots(scope, snapshot_id, record_ids) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (scope, sid, self._jsonb(list(ids))))
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO stock_research.snapshot_records(scope, snapshot_id, record_id) "
                    "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", [(scope, sid, rid) for rid in ids])
            return self._snapshot(connection, scope, sid)

    def read(self, scope, snapshot_id):
        with self._connect() as connection:
            snapshot = self._snapshot(connection, scope, snapshot_id)
            rows = connection.execute(
                "SELECT r.record_id, r.payload FROM stock_research.records r "
                "JOIN stock_research.snapshot_records s USING(scope, record_id) "
                "WHERE s.scope=%s AND s.snapshot_id=%s ORDER BY r.record_id", (scope, snapshot_id)).fetchall()
            if tuple(row[0] for row in rows) != snapshot.record_ids:
                raise IntegrityError("snapshot membership mismatch")
            records = tuple(DataRecord.from_dict(row[1]) for row in rows)
            if any(record.record_id != row[0] for record, row in zip(records, rows)):
                raise IntegrityError("record payload hash mismatch")
            return records
