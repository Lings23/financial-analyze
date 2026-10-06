import hashlib
import os
import tempfile
from pathlib import Path

from ..errors import IntegrityError, ValidationError
from ..models import canonical_json


class ArtifactStore:
    """Trusted internal interface; callers supply the authenticated scope."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, scope: str, artifact_id: str) -> Path:
        if len(artifact_id) != 64 or any(c not in "0123456789abcdef" for c in artifact_id):
            raise ValidationError("invalid artifact ID")
        namespace = hashlib.sha256(scope.encode()).hexdigest()
        return self.root / namespace / artifact_id[:2] / artifact_id

    def put(self, scope: str, payload: dict) -> str:
        content = canonical_json(payload).encode("utf-8")
        return self.put_bytes(scope, content)

    def put_bytes(self, scope: str, content: bytes) -> str:
        if not isinstance(content, bytes):
            raise ValidationError("immutable artifact bytes required")
        artifact_id = hashlib.sha256(content).hexdigest()
        target = self._path(scope, artifact_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self.get(scope, artifact_id)
            return artifact_id
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".pending-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return artifact_id

    def get(self, scope: str, artifact_id: str) -> bytes:
        content = self._path(scope, artifact_id).read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact_id:
            raise IntegrityError("artifact hash mismatch")
        return content
