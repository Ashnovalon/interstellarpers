CREATE SEQUENCE IF NOT EXISTS record_revision;
CREATE TABLE IF NOT EXISTS records (
 kind text NOT NULL, id text NOT NULL, data jsonb NOT NULL, hash text NOT NULL,
 revision bigint NOT NULL DEFAULT nextval('record_revision'), source text NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(kind,id));
ALTER TABLE records ADD COLUMN IF NOT EXISTS verified_at timestamptz NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS outbox (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE outbox REPLICA IDENTITY FULL;
CREATE TABLE IF NOT EXISTS projected (
 kind text NOT NULL, id text NOT NULL, data jsonb NOT NULL, revision bigint NOT NULL,
 PRIMARY KEY(kind,id));
CREATE TABLE IF NOT EXISTS processed_events (id uuid PRIMARY KEY, processed_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS sink_receipts (event_id uuid, sink text, PRIMARY KEY(event_id,sink));
CREATE TABLE IF NOT EXISTS quarantined (id uuid PRIMARY KEY, error text, payload jsonb, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS heartbeat (service text PRIMARY KEY, updated_at timestamptz DEFAULT now(), detail jsonb);
CREATE TABLE IF NOT EXISTS models (id uuid PRIMARY KEY, created_at timestamptz DEFAULT now(), data_version bigint,
 artifact text NOT NULL, metrics jsonb NOT NULL, promoted boolean NOT NULL, run_id text);
CREATE TABLE IF NOT EXISTS proposals (id uuid PRIMARY KEY, created_at timestamptz DEFAULT now(), data_version bigint NOT NULL,
 plan jsonb NOT NULL, status text NOT NULL DEFAULT 'PENDING', actor text, reason text);
CREATE UNIQUE INDEX IF NOT EXISTS single_approval_per_version ON proposals(data_version) WHERE status IN ('RESERVED','REQUESTED');
CREATE TABLE IF NOT EXISTS reservations (proposal_id uuid PRIMARY KEY REFERENCES proposals(id), plan jsonb NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS dispatch_requests (id uuid PRIMARY KEY REFERENCES proposals(id), payload jsonb NOT NULL,
 status text NOT NULL DEFAULT 'AWAITING_ERP_ADAPTER', created_at timestamptz DEFAULT now());
ALTER TABLE dispatch_requests ADD COLUMN IF NOT EXISTS reconciled_at timestamptz;
CREATE TABLE IF NOT EXISTS forecast_predictions (
 sku text, depot text, target_date date, data_version bigint, forecast double precision, source text,
 created_at timestamptz DEFAULT now(), PRIMARY KEY(sku,depot,target_date,data_version));
