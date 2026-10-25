# Real-record operations platform

Open **Import real records** from http://127.0.0.1:8765/operations. The dashboard
also opens directly at http://127.0.0.1:3010/operations/real. This platform uses its
own PostgreSQL database and Docker volumes. It never opens the synthetic app's
SQLite database, resets a run, imports the demo, or replaces the shipped model.
The existing original `/api/*` workbench APIs remain separate.

## Start and stop

From the project folder in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_real_records.ps1
powershell -ExecutionPolicy Bypass -File scripts/stop_real_records.ps1
```

The start script supports Docker Desktop or Docker Engine in the existing
`Ubuntu-24.04` WSL distribution. The initial build downloads the images and Python
packages. Allocate approximately 12–16 GB RAM for this full development stack.
All published application ports bind to loopback. Stopping retains all volumes.
The WSL start path uses a hidden keepalive so systemd services remain available
after the launching shell exits. On this machine, setup also created
`/var/lib/pulp-real-records.swap` (4 GB) inside Ubuntu because the pre-existing
Windows swap-file setting is inaccessible. The start script activates that file
when it exists; it does not modify `.wslconfig` or require it on Docker Desktop.

The original Python server also supports a same-origin `/operations/real` proxy
after its next normal restart. The navigation uses the direct dashboard so no
restart or interruption to a running synthetic session is necessary.

## Use actual records

1. Open **Import records**, select the kind, enter a source, upload JSON or CSV,
   then **Preview and validate**. Download an empty CSV header for the exact fields.
2. Review the preview, confirm actual company provenance and import. The entire
   batch is validated before the transaction. Equal kind/ID/content is a no-op;
   changed content gets a new revision and retained outbox event.
3. Wait until **Stream current**. **Live board** shows demand evidence, freshness,
   inventory and the depot network. Missing values have no generated substitutes.
4. Import `channel_master` freshness rules and `sku_master` recipes. Orders,
   batches and capacities need current observations (at most two days old for
   planning); historical orders can still be imported for training.
5. **Compare scenarios** runs named what-if assumptions in Ray against the same
   imported snapshot. These comparisons are aggregate capacity bounds, not
   feasible execution plans or measured savings.
6. **Decision desk → Optimize allocation** creates an OR-Tools proposal. Expand
   allocations, production, procurement, transfers and assumptions. Supply your
   name and reason, then approve or reject.
7. Temporal waits for approval, checks the exact input revision, atomically
   reserves one plan, and creates an idempotent local dispatch request. Review
   the actual ERP outcome, record reconciliation, and import fresh physical
   snapshots before approving another plan.
8. **History & models** trains XGBoost after at least 35 consecutive dated order
   days. A chronological seven-day holdout compares it to the observed mean.
   MLflow records every run and model version. Only passing models are promoted.
   Airflow runs this daily; insufficient data causes a visible skipped task.
   Forecast outcomes compare saved predictions with actual target-day orders when
   those records subsequently arrive; the app never generates actual outcomes.

CSV numbers must be unformatted, dates `YYYY-MM-DD`, and booleans `true`/`false`.
`recipe` maps material IDs to positive kg/bottle. Arbitrary company SKU, depot,
material and facility IDs are accepted; no case/demo masters are injected.
For transfers, route records additionally need `from_depot`, `to_depot` and
optional whole `lead_days`. Only current, confirmed `OPEN` lanes are eligible.
Always reuse a batch's stable ID when replacing its balance.

There is deliberately no automatic seed. Tests use fixtures in a **different
Compose project**, never in this workspace. Explicit sample/synthetic flags are
rejected. Provenance confirmation is a user's assertion, not independent proof.

## Technology coverage

| Layer | Implementation and useful check |
|---|---|
| Next.js, TypeScript, Apache ECharts | `frontend/`: actual Next app, typed forms, interactive bar charts and a draggable/zoomable network graph |
| FastAPI | `api.py`: validation, imports, state, training, comparisons, proposals, decisions, history, services; OpenAPI in the API container |
| Kafka and Debezium | `bootstrap.py`: PostgreSQL logical-WAL CDC of the immutable outbox, `real.public.outbox` topic |
| Apache Flink | `flink/job.py`: independently validates CDC events, tracks versioned state and disruptions, publishes `real.validated`; ten-second checkpoints |
| PostgreSQL and Redis | `schema.sql`, `projector.py`: authoritative imports, projected balances, models, approvals, reservations, requests and latest-event cache |
| Object storage, Iceberg, ClickHouse | `sinks.py`: S3-compatible SeaweedFS, a PostgreSQL-backed Iceberg catalog, event table and ClickHouse `ReplacingMergeTree`; stable event IDs handle replay |
| XGBoost, MLflow, Airflow | `forecasting.py`, `airflow/demand_training.py`: actual train/evaluate/register pipeline and daily scheduling; XGBoost is the selected alternative to PyTorch |
| Google OR-Tools | `planning.py`: SCIP integer bottle allocations, facility capacity, recipe/material bounds, confirmed inbound procurement, batch-specific freshness and confirmed transfer lanes |
| Ray | `/scenarios`: fan-out of parallel what-if runs against a shared imported snapshot |
| Temporal | `workflows.py`: signal-based approval wait, durable retries, version checks, reservations and idempotent dispatch requests |
| Docker and Kubernetes | `compose.yaml` launches the complete local stack; `kubernetes.yaml` contains all service deployments/jobs/PVCs/configuration |
| OpenTelemetry, Prometheus, Grafana | `monitoring/`: API tracing, scrape metrics, provisioned datasource and operations dashboard |

**System health** actively probes each service, checks that the CDC connector and
Flink job are running, and checks recent projector/Temporal-worker heartbeats.
Installed solver/model libraries are distinguished in the check details. Service
availability alone is not evidence of accurate forecasts or correct company data.

## Execution boundaries of this minimal setup

The approved output is a durable **dispatch request**, not a physical dispatch.
No ERP, supplier, warehouse or logistics credentials/endpoints were provided.
Integrate an authorized adapter with an external idempotency key equal to the
proposal ID before sending real commands. Approval names are recorded local
claims; company SSO/RBAC is a separate shared-deployment integration.

Production uses aggregate facility capacity over the horizon and imported recipe
material requirements. Detailed facility/SKU qualification, shift scheduling,
cost objectives, vehicle routing, and within-horizon sequencing are outside this
minimal allocation model. Inventory and transfers must satisfy channel freshness
through the end of the horizon. Transfers reserve specific batches; a batch can
never be allocated twice. Missing recipes prevent production, missing channel
rules or stale orders/batches prevent planning. Only one plan can be outstanding
at a time until its dispatch request is reconciled.

The history projector serially archives each event before exposing it in the
operational projection. Kafka delivery is at least once. Object keys, Iceberg
upserts and ClickHouse `FINAL` reads deduplicate by event ID. A failed sink retains
the offset for retry. This favors inspectability and recoverability over
throughput and is intentionally not a high-volume deployment tuning.

Temporal uses a persistent local development server, Airflow uses its standalone
development configuration, and services have single replicas. Kubernetes
manifests are for a local development cluster, not an HA production claim.

## Verify

Unit checks (install `real_records/requirements.txt` with `-c real_records/constraints.txt` in an isolated venv):

```powershell
python -m unittest discover -s tests -p test_real_records.py -v
cd real_records/frontend
npm ci --ignore-scripts
npm run typecheck
npm run build
```

End-to-end verification uses separate test volumes and ports. Do not run a second
full stack simultaneously on a memory-constrained machine. With Docker Desktop:

```powershell
docker compose -p pulp-real-records-test -f real_records/compose.yaml -f real_records/compose.test.yaml up -d --build
python scripts/test_real_stack.py
docker compose -p pulp-real-records-test -f real_records/compose.yaml -f real_records/compose.test.yaml down
```

For WSL Docker, prefix Docker commands with
`wsl -d Ubuntu-24.04 -u root --` and use the `/mnt/c/.../real_records/compose.yaml`
paths. `test_real_stack.py` refuses writes unless the API on **8020** explicitly
reports test mode. It checks CDC/projection, storage, training/MLflow, Ray,
OR-Tools and Temporal and leaves its fixtures exclusively in the test volumes.

## Kubernetes

Regenerate with `python scripts/render_real_kubernetes.py` (requires PyYAML).
Build and tag the three local images:

```sh
docker build -t pulp-real-api:local -f real_records/Dockerfile .
docker build -t pulp-real-flink:local -f real_records/flink/Dockerfile .
docker build -t pulp-real-frontend:local real_records/frontend
# Load these images into your local cluster, for example with kind load docker-image.
kubectl apply -f real_records/kubernetes.yaml
kubectl -n pulp-real-records port-forward svc/frontend 3010:3000
kubectl -n pulp-real-records port-forward svc/grafana 3011:3000
```

Keep Compose stopped when using the same ports. Shared deployments need managed
Secrets and authentication, storage classes/backups, resources/HA, TLS, and real
execution adapters. These local manifests do not create a cloud cluster or spend
money. Local Grafana credentials default to `admin / local-real-monitoring`;
override with `GRAFANA_PASSWORD`. For an API token, set `REAL_RECORDS_TOKEN` in
`real_records/.env` before starting; the UI prompts for it and protects its proxy.

## References for connector behavior

- [Debezium PostgreSQL CDC](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)
- [Flink Kafka connector](https://nightlies.apache.org/flink/flink-docs-release-1.19/docs/connectors/datastream/kafka/)
- [PyIceberg catalog and writes](https://py.iceberg.apache.org/api/)
- [Temporal Python signals](https://docs.temporal.io/develop/python/message-passing)
- [Ray client connections](https://docs.ray.io/en/latest/cluster/running-applications/job-submission/ray-client.html)
