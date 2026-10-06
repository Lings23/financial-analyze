"""Offline import of explicitly reviewed CNINFO document versions.

The trusted application pins the qualification manifest hash. A current index or
announcement date alone never grants historical availability to ordinary adapters.
"""
import hashlib
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..errors import IntegrityError, ProviderSchemaError, ValidationError
from ..models import DataRecord, Dataset, Metric, Security, aware, digest, utcnow
from .base import ProviderCapability
from .documents import document_url

SHANGHAI = timezone(timedelta(hours=8))
INDEX_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"


class QualifiedCNInfoIncomeProvider:
    """Only SHA-approved financial versions, with date precision and no network."""

    def __init__(self, manifest_path, expected_sha256, artifacts, *, labels=None, clock=utcnow):
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValidationError("trusted qualification manifest hash required")
        self.path = Path(manifest_path).resolve()
        self.manifest_bytes = self._read(self.path, expected_sha256, 1024 * 1024)
        self.manifest = json.loads(self.manifest_bytes)
        if (self.manifest.get("schema") != "cninfo_income_qualification_v1"
                or self.manifest.get("release_precision") != "date"
                or self.manifest.get("basis") != "consolidated_cumulative_cny"):
            raise ProviderSchemaError("unsupported qualification schema or financial basis")
        versions = self.manifest.get("versions")
        if not isinstance(versions, list) or not 1 <= len(versions) <= 128:
            raise ProviderSchemaError("bounded qualified document versions required")
        names = [v["label"] for v in versions]
        if len(set(names)) != len(names):
            raise ProviderSchemaError("duplicate qualified version labels")
        selected = tuple(sorted(names if labels is None else labels))
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(names):
            raise ValidationError("explicit approved version subset required")
        self.versions = tuple(v for v in versions if v["label"] in selected)
        self.artifacts, self.clock, self.manifest_sha = artifacts, clock, expected_sha256
        # Cache identity includes the approved manifest and exact subset.
        self.capability = ProviderCapability("cninfo", "qualified-date-1:" + digest(
            {"manifest": expected_sha256, "labels": selected}),
            frozenset({Dataset.FINANCIAL_INCOME}), frozenset({"consolidated_cumulative_cny"}), True)

    @staticmethod
    def _read(path, expected, limit):
        if path.stat().st_size > limit:
            raise ProviderSchemaError("qualified source exceeds size bound")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise IntegrityError("qualified source hash mismatch")
        return content

    def _asset(self, source, limit):
        relative = Path(source["path"])
        target = (self.path.parent / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(self.path.parent):
            raise ProviderSchemaError("qualified asset must remain in its manifest directory")
        return self._read(target, source["sha256"], limit)

    def fetch(self, request, scope, timeout):
        if timeout <= 0:
            raise ValidationError("positive bounded import timeout required")
        deadline = time.monotonic() + timeout
        # Recheck pin on every call, including after trusted constructor approval.
        self._read(self.path, self.manifest_sha, 1024 * 1024)
        if request.dataset != Dataset.FINANCIAL_INCOME:
            raise ValidationError("qualified importer supports income only")
        matching = [v for v in self.versions if Security(v["symbol"], v["exchange"]).security_id
                    == request.security.security_id and request.start <= date.fromisoformat(v["period"]) <= request.end]
        if not matching:
            raise ValidationError("security and period have no approved historical qualification")
        captured = aware(self.clock())
        prepared = []
        for version in matching:
            if time.monotonic() >= deadline:
                raise ProviderSchemaError("qualified import deadline exceeded")
            pdf = self._asset(version["pdf"], 30 * 1024 * 1024)
            index = self._asset(version["index"], 8 * 1024 * 1024)
            if not pdf.startswith(b"%PDF"):
                raise ProviderSchemaError("qualified document is not PDF")
            url = document_url(version["pdf"]["url"], "pdf")
            payload = json.loads(index)
            entries = [row for row in payload.get("rows", []) if str(row.get("announcementId")) == version["announcement_id"]]
            if payload.get("endpoint") != INDEX_URL or len(entries) != 1:
                raise ProviderSchemaError("official index must bind exactly one approved announcement")
            row = entries[0]
            millis = row.get("announcementTime")
            if type(millis) is not int:
                raise ProviderSchemaError("index date missing")
            indexed = datetime.fromtimestamp(millis / 1000, SHANGHAI)
            released = date.fromisoformat(version["release_date"])
            if (row.get("secCode") != request.security.symbol
                    or indexed.date() != released or indexed.time() != datetime.min.time()
                    or url != "https://static.cninfo.com.cn/" + row.get("adjunctUrl", "")
                    or f"/finalpage/{released.isoformat()}/{version['announcement_id']}." not in url
                    or not version.get("review_notes")
                    or type(version.get("pdf_page_one_based")) is not int
                    or version["pdf_page_one_based"] < 1):
                raise ProviderSchemaError("qualification does not bind document identity and date precision")
            values = version["values_cny"]
            if set(values) != {"revenue", "net_income_parent", "total_revenue"} or values["total_revenue"] is not None:
                raise ProviderSchemaError("qualified core income fields required; missing total revenue must remain explicit")
            metrics = []
            for name, raw in values.items():
                if raw is not None:
                    evidence = version.get("field_evidence", {}).get(name)
                    if (not isinstance(evidence, dict) or type(evidence.get("pdf_page")) is not int
                            or evidence["pdf_page"] < 1 or not evidence.get("column")
                            or not evidence.get("financial_context")):
                        raise ProviderSchemaError("per-field reviewed PDF page, column and context required")
                    if not isinstance(raw, str):
                        raise ProviderSchemaError("reviewed decimal transcription required")
                    try:
                        number = Decimal(raw)
                    except InvalidOperation:
                        raise ProviderSchemaError("invalid reviewed decimal") from None
                    if not number.is_finite():
                        raise ProviderSchemaError("nonfinite reviewed decimal")
                else:
                    number = None
                metrics.append(Metric(name, number, "CNY", raw, "CNY"))
            prepared.append((version, pdf, index, url, released, tuple(metrics)))
        proof = self.artifacts.put_bytes(scope, self.manifest_bytes)
        call_id = uuid.uuid4().hex
        records = []
        for version, pdf, index, url, released, metrics in prepared:
            pdf_id = self.artifacts.put_bytes(scope, pdf)
            index_id = self.artifacts.put_bytes(scope, index)
            envelope = self.artifacts.put(scope, {"schema": "qualified_cninfo_income_v1",
                "qualification_sha256": proof, "version": version, "retrieved_at": captured.isoformat(),
                "pdf_sha256": pdf_id, "index_sha256": index_id, "provider_call_id": call_id})
            boundary = datetime.combine(released + timedelta(days=1), datetime.min.time(), SHANGHAI)
            records.append(DataRecord(request.security.security_id, request.security.canonical_symbol,
                request.dataset, date.fromisoformat(version["period"]), request.basis, metrics,
                self.capability.name, self.capability.version, url, version["announcement_id"],
                digest({"qualification": proof, "version": version}), boundary, captured, captured,
                "verified_release_date", envelope, call_id, announcement_date=released,
                revision_order=int(version["revision_order"]),
                quality_flags=("release_date_conservative_boundary", "explicit_document_qualification", "total_revenue_unverified"),
                release_date=released, release_evidence_artifact_id=proof,
                supporting_artifact_ids=(pdf_id, index_id)))
        return tuple(records)
