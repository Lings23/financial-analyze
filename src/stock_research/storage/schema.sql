CREATE SCHEMA IF NOT EXISTS stock_research;

CREATE TABLE IF NOT EXISTS stock_research.schema_versions (
    version integer PRIMARY KEY,
    installed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_research.records (
    scope text NOT NULL,
    record_id text NOT NULL CHECK (record_id ~ '^[0-9a-f]{64}$'),
    security_id text NOT NULL,
    dataset text NOT NULL,
    period date NOT NULL,
    provider text NOT NULL,
    available_at timestamptz NOT NULL,
    retrieved_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL CHECK (ingested_at >= retrieved_at),
    payload jsonb NOT NULL,
    PRIMARY KEY (scope, record_id)
);

CREATE INDEX IF NOT EXISTS records_pit_idx ON stock_research.records
    (scope, security_id, dataset, period, available_at);

CREATE TABLE IF NOT EXISTS stock_research.snapshots (
    scope text NOT NULL,
    snapshot_id text NOT NULL CHECK (snapshot_id ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    record_ids jsonb NOT NULL CHECK (jsonb_typeof(record_ids) = 'array'),
    PRIMARY KEY (scope, snapshot_id)
);

CREATE TABLE IF NOT EXISTS stock_research.snapshot_records (
    scope text NOT NULL,
    snapshot_id text NOT NULL,
    record_id text NOT NULL,
    PRIMARY KEY (scope, snapshot_id, record_id),
    FOREIGN KEY (scope, snapshot_id) REFERENCES stock_research.snapshots(scope, snapshot_id),
    FOREIGN KEY (scope, record_id) REFERENCES stock_research.records(scope, record_id)
);

CREATE OR REPLACE FUNCTION stock_research.reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'research records and snapshots are immutable';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'research_records_immutable'
                   AND tgrelid = 'stock_research.records'::regclass) THEN
        CREATE TRIGGER research_records_immutable BEFORE UPDATE OR DELETE
            ON stock_research.records FOR EACH ROW EXECUTE FUNCTION stock_research.reject_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'research_snapshots_immutable'
                   AND tgrelid = 'stock_research.snapshots'::regclass) THEN
        CREATE TRIGGER research_snapshots_immutable BEFORE UPDATE OR DELETE
            ON stock_research.snapshots FOR EACH ROW EXECUTE FUNCTION stock_research.reject_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'research_members_immutable'
                   AND tgrelid = 'stock_research.snapshot_records'::regclass) THEN
        CREATE TRIGGER research_members_immutable BEFORE UPDATE OR DELETE
            ON stock_research.snapshot_records FOR EACH ROW EXECUTE FUNCTION stock_research.reject_mutation();
    END IF;
END;
$$;

INSERT INTO stock_research.schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
