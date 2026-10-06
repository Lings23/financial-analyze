-- P1.8 typed domain payloads reuse the immutable envelope and membership tables.
-- security_id remains a compatibility column containing an explicitly typed subject ID.
ALTER TABLE stock_research.records ADD COLUMN IF NOT EXISTS record_kind text NOT NULL DEFAULT 'legacy_v1';
CREATE INDEX IF NOT EXISTS records_domain_pit_idx ON stock_research.records
    (scope, record_kind, security_id, dataset, period, available_at);
INSERT INTO stock_research.schema_versions(version) VALUES (2) ON CONFLICT DO NOTHING;
