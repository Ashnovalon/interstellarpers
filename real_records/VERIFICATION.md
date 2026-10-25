# Verification — 2026-10-25

- Existing regression suite: **81 passed**. No live simulation controls or
  synthetic application records were modified during verification.
- New import, allocation and proxy checks: **17 passed**, including atomic
  validation, duplicate IDs, stale feeds, missing rules/recipes, expired stock,
  raw-material bounds, confirmed receipts, closed lanes and shared fresh batches.
- Next.js production builds passed on Windows and inside the Linux image.
  TypeScript checks passed; the frontend dependency audit reported **0 vulnerabilities**.
- Dedicated `pulp-real-records-test` integration project passed actual
  PostgreSQL → Debezium → Kafka → Flink → projector processing, idempotent imports,
  S3/Iceberg/ClickHouse history, XGBoost held-out evaluation and MLflow registration,
  Ray parallel comparisons, OR-Tools allocations, Temporal approval/reservation and
  dispatch-request creation. A duplicate approval was blocked, and reconciliation
  plus fresh identical snapshots allowed the next request without changing record
  content. All **19** service/capability/worker health checks passed.
- Next.js HTML and its API proxy returned valid responses. Edge did not grant
  computer-use access, so an interactive visual browser inspection was not performed.
- Kubernetes manifests were rendered and structurally checked for every workload,
  service, configuration and persistent volume. No Kubernetes cluster deployment
  was performed; Docker Compose is the running local deployment.

Test fixtures were confined to the test project's volumes. Its containers and
network were stopped and removed after testing; its volumes were retained for
inspection. The real workspace is separate and has no preloaded company records.
No external ERP, supplier or logistics system was called. Workflow execution ends
at a durable dispatch request awaiting an authorized adapter.

Final real-workspace check: **19/19 UP**, zero imported records, no proposals or
models preloaded, working Next.js API proxy, and original app health HTTP 200.
The captured result is in `output/real-stack-health.json`.
