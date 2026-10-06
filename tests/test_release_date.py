"""Synthetic qualification fixtures test contracts, not live financial truth."""
import hashlib
import json
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_research.errors import IntegrityError, PermissionDenied, ProviderSchemaError, ValidationError
from stock_research.models import AccessContext, DataRecord, DataRequest, Dataset, PITMode, QueryContext, digest
from stock_research.providers.base import ProviderCapability, ProviderRegistry, validate_records
from stock_research.providers.executor import ProviderExecutor
from stock_research.providers.qualified_income import QualifiedCNInfoIncomeProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository
from helpers import SECURITY, financial_record


def at(value):
    return datetime.fromisoformat(value + "+08:00")


def qualification(root):
    root = Path(root)
    versions = []
    for label, released, ann, revenue, order in (("synthetic-original", "2025-03-20", "100001", "100", 0),
                                              ("synthetic-correction", "2025-04-20", "100002", "90", 1)):
        pdf = b"%PDF synthetic qualification fixture " + label.encode()
        url = f"https://static.cninfo.com.cn/finalpage/{released}/{ann}.PDF"
        index = json.dumps({"endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query", "rows": [
            {"secCode": SECURITY.symbol, "announcementId": ann,
             "announcementTime": int(at(released + "T00:00:00").timestamp() * 1000),
             "adjunctUrl": f"finalpage/{released}/{ann}.PDF"}]}).encode()
        (root / (label + ".pdf")).write_bytes(pdf)
        (root / (label + ".json")).write_bytes(index)
        versions.append({"label": label, "symbol": SECURITY.symbol, "exchange": SECURITY.exchange,
            "period": "2024-12-31", "release_date": released, "announcement_id": ann,
            "pdf": {"path": label + ".pdf", "sha256": hashlib.sha256(pdf).hexdigest(), "url": url},
            "index": {"path": label + ".json", "sha256": hashlib.sha256(index).hexdigest()},
            "pdf_page_one_based": 1, "review_notes": "synthetic fixture only",
            "values_cny": {"revenue": revenue, "net_income_parent": "10", "total_revenue": None},
            "field_evidence": {name: {"pdf_page": 1, "column": "synthetic", "financial_context": "synthetic"}
                               for name in ("revenue", "net_income_parent")},
            "revision_order": order})
    manifest = {"schema": "cninfo_income_qualification_v1", "release_precision": "date",
                "basis": "consolidated_cumulative_cny", "synthetic": True, "versions": versions}
    path = root / "qualification.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseDateTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.path, self.pin = qualification(self.root)
        self.provider = QualifiedCNInfoIncomeProvider(self.path, self.pin, self.artifacts,
            clock=lambda: at("2025-05-01T00:00:00"))
        self.request = DataRequest(SECURITY, Dataset.FINANCIAL_INCOME, date(2024, 12, 31), date(2024, 12, 31))
        self.access = AccessContext("synthetic", frozenset({"cninfo"}))
        self.repo = MemoryRepository()

    def test_date_boundary_revision_system_and_authorized_attachments(self):
        rows = self.provider.fetch(self.request, self.access.scope, 5)
        snapshot = self.repo.commit(self.access.scope, rows)
        with ProviderExecutor() as executor:
            service = DataService(ProviderRegistry(), executor, self.repo, self.artifacts)
            def context(cutoff):
                return QueryContext(self.access, snapshot.snapshot_id, at(cutoff))
            self.assertFalse(service.query(self.request, context("2025-03-20T23:59:59.999999")).records)
            old = service.query(self.request, context("2025-03-21T00:00:00"))
            self.assertEqual(old.records[0], rows[0])
            self.assertIn("release_date_conservative_boundary", old.warnings)
            self.assertEqual(service.query(self.request, context("2025-04-20T23:59:59.999999")).records, (rows[0],))
            current = context("2025-04-21T00:00:00")
            self.assertEqual(service.query(self.request, current).records, (rows[1],))
            self.assertFalse(service.query(self.request, replace(current, mode=PITMode.SYSTEM)).records)
            self.assertIsNone(rows[1].published_at)
            for aid in rows[1].artifact_ids:
                self.assertTrue(service.evidence(self.request, current, rows[1].record_id, aid))
            with self.assertRaises(PermissionDenied):
                service.evidence(self.request, current, rows[0].record_id)
            unauthorized = replace(current, access=AccessContext(self.access.scope, frozenset({"tushare"})))
            self.assertFalse(service.query(self.request, unauthorized).records)
            with self.assertRaises(PermissionDenied):
                service.evidence(self.request, unauthorized, rows[1].record_id)
            wrong_scope = replace(current, access=AccessContext("other", frozenset({"cninfo"})))
            with self.assertRaises(PermissionDenied):
                service.query(self.request, wrong_scope)
            aid = rows[1].supporting_artifact_ids[0]
            self.artifacts._path(self.access.scope, aid).write_bytes(b"corrupt synthetic evidence")
            with self.assertRaises(IntegrityError):
                service.query(self.request, current)

    def test_legacy_payload_identity_and_date_roundtrip(self):
        old = financial_record(self.artifacts)
        payload = old.to_dict()
        self.assertNotIn("release_date", payload)
        self.assertNotIn("supporting_artifact_ids", payload)
        identity = {k: v for k, v in payload.items() if k != "ingested_at"}
        self.assertEqual(old.record_id, digest(identity))
        self.assertEqual(DataRecord.from_dict(json.loads(json.dumps(payload))), old)
        row = self.provider.fetch(self.request, self.access.scope, 5)[0]
        self.assertEqual(DataRecord.from_dict(json.loads(json.dumps(row.to_dict()))), row)

    def test_date_only_cannot_claim_intraday_or_omit_proof(self):
        row = self.provider.fetch(self.request, self.access.scope, 5)[0]
        for changes in ({"available_at": at("2025-03-20T12:00:00")},
                        {"published_at": at("2025-03-20T00:00:00")},
                        {"release_evidence_artifact_id": None}, {"release_date": None},
                        {"supporting_artifact_ids": ("invalid",)},
                        {"availability_basis": "observed_at", "available_at": row.retrieved_at}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                replace(row, **changes)
        unqualified = type("Unqualified", (), {"capability": replace(self.provider.capability, historical_release_verified=False)})()
        with self.assertRaises(ProviderSchemaError):
            validate_records(unqualified, self.request, (row,))

    def test_pin_tampering_asset_tampering_and_subset_cache_identity(self):
        original = QualifiedCNInfoIncomeProvider(self.path, self.pin, self.artifacts,
            labels=("synthetic-original",), clock=lambda: at("2025-05-01T00:00:00"))
        self.assertNotEqual(original.capability.version, self.provider.capability.version)
        self.assertEqual(len(original.fetch(self.request, "synthetic", 5)), 1)
        with self.assertRaises(IntegrityError):
            QualifiedCNInfoIncomeProvider(self.path, "f" * 64, self.artifacts)
        with self.assertRaises(ValidationError):
            QualifiedCNInfoIncomeProvider(self.path, self.pin, self.artifacts, labels=("unapproved",))
        (self.root / "synthetic-original.pdf").write_bytes(b"%PDF synthetic tamper")
        with self.assertRaises(IntegrityError):
            self.provider.fetch(self.request, "synthetic", 5)
        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaises(IntegrityError):
            self.provider.fetch(self.request, "synthetic", 5)

    def test_official_binding_and_asset_path_checked_even_with_reviewed_pin(self):
        for change in ("symbol", "date", "url", "path"):
            path, _ = qualification(self.root)
            manifest = json.loads(path.read_bytes())
            version = manifest["versions"][0]
            if change == "symbol":
                index_path = self.root / version["index"]["path"]
                index = json.loads(index_path.read_bytes())
                index["rows"][0]["secCode"] = "600001"
                index_path.write_text(json.dumps(index), encoding="utf-8")
                version["index"]["sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
            elif change == "date":
                version["release_date"] = "2025-03-19"
            elif change == "url":
                version["pdf"]["url"] = version["pdf"]["url"].replace("100001", "100003")
            else:
                version["pdf"]["path"] = "../outside.pdf"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            provider = QualifiedCNInfoIncomeProvider(path, hashlib.sha256(path.read_bytes()).hexdigest(), self.artifacts,
                clock=lambda: at("2025-05-01T00:00:00"))
            with self.subTest(change=change), self.assertRaises((ProviderSchemaError, ValidationError)):
                provider.fetch(self.request, "synthetic", 5)

    def test_refresh_append_keeps_old_snapshot_and_evidence(self):
        original = QualifiedCNInfoIncomeProvider(self.path, self.pin, self.artifacts,
            labels=("synthetic-original",), clock=lambda: at("2025-05-01T00:00:00"))
        first_rows = original.fetch(self.request, self.access.scope, 5)
        first = self.repo.commit(self.access.scope, first_rows)
        registry = ProviderRegistry()
        registry.register(self.provider)
        with ProviderExecutor() as executor:
            service = DataService(registry, executor, self.repo, self.artifacts)
            second = service.refresh(self.request, self.access, ("cninfo",), first.snapshot_id, False)
            self.assertEqual(self.repo.read(self.access.scope, first.snapshot_id), first_rows)
            self.assertEqual(second.record_count, 2)
            self.assertEqual(len(self.repo.read(self.access.scope, second.snapshot.snapshot_id)), 3)
            context = QueryContext(self.access, first.snapshot_id, at("2025-05-02T00:00:00"))
            self.assertEqual(service.query(self.request, context).records, first_rows)
