"""Local append-only checkpoints with a process lock; SQLite never stores credentials."""
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import canonical_json, digest


class CheckpointStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS checkpoints (scope TEXT, run TEXT, seq INTEGER, "
                       "previous TEXT, hash TEXT, payload TEXT, PRIMARY KEY(scope,run,seq))")

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.root / "checkpoints.sqlite3", timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate(run):
        if not isinstance(run, str) or not re.fullmatch(r"[0-9a-f]{32}", run):
            raise ValidationError("invalid research run ID")

    @contextmanager
    def lock(self, scope, run):
        self._validate(run)
        path = self.root / (digest({"scope": scope, "run": run}) + ".lock")
        with path.open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValidationError("research run is already active") from None
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def read(self, scope, run):
        return self.history(scope, run)[-1]

    def history(self, scope, run):
        """Verified append-only states, used to bind recovery to original limits."""
        self._validate(run)
        with self._connection() as db:
            rows = db.execute("SELECT seq, previous, hash, payload FROM checkpoints "
                              "WHERE scope=? AND run=? ORDER BY seq", (scope, run)).fetchall()
        if not rows:
            raise PermissionDenied("checkpoint not available in this scope")
        previous, states = "", []
        for expected, (seq, parent, checksum, payload) in enumerate(rows):
            state = json.loads(payload)
            if (seq != expected or parent != previous
                    or digest({"previous": parent, "state": state}) != checksum):
                raise IntegrityError("checkpoint chain changed")
            previous = checksum
            states.append(state)
        return states

    def append(self, scope, run, state):
        self._validate(run)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT seq, hash FROM checkpoints WHERE scope=? AND run=? "
                              "ORDER BY seq DESC LIMIT 1", (scope, run)).fetchone()
            seq, previous = (last[0] + 1, last[1]) if last else (0, "")
            checksum = digest({"previous": previous, "state": state})
            db.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?,?)",
                       (scope, run, seq, previous, checksum, canonical_json(state)))
