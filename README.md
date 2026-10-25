# Pulp Riot Operations Control Tower

A decision-support application for the Pulp Riot demand, inventory and supply-chain case. The workflow is **observe demand → inspect constraints → compare options → record a human decision → inspect its outcome**. Demand and inventory are the primary modules; ingredients, production capacity, freshness, routes and transport lead times constrain their recommendations.

The repository offers three independent workflows and a practice environment:

| Workspace | Purpose | Default address | Storage and dependencies |
|---|---|---|---|
| Live simulation | Rehearse disruptions, timed decisions and outcomes on generated demand | `http://127.0.0.1:8765/` | Python standard library; SQLite live tables |
| Local operations workbench | Validate imports, inspect demand/inventory and review recommendations | `http://127.0.0.1:8765/operations` | Same Python server and SQLite file; separate operational tables |
| Imported company records | Stream imported facts, train models and approve constrained allocations | `http://127.0.0.1:3010/operations/real` | Docker services; dedicated PostgreSQL database and volumes |
| Imported-records practice | Learn the import-to-approval workflow with labeled sample files | `http://127.0.0.1:3020/operations/real` | Separate Compose project and volumes; test-mode validation |

**All supplied case, training and practice data is synthetic.** Forecast scores and scenario gains demonstrate software behavior on generated inputs, not accuracy or savings at a company. The imported-records workspace starts empty. Approved full-stack allocations produce local dispatch requests awaiting an external adapter; the repository does not place supplier orders or move physical goods.

## Contents

- [Live capabilities and evidence](#live-capabilities-and-evidence)
- [Full stack for imported real records](#full-stack-for-imported-real-records)
- [Start the live experience](#start-the-live-experience)
- [Live data, model and verification](#live-data-model-and-verification)
- [Run the working app](#run-the-working-app)
- [Forecast model](#forecast-model)
- [Operating workflow](#operating-workflow)
- [Architecture and persistence](#architecture-and-persistence)
- [API overview](#api-overview)
- [Development and full-stack verification](#development-and-full-stack-verification)
- [Troubleshooting](#troubleshooting)
- [Main files](#main-files)
- [Deployment boundaries](#deployment-boundaries)

## Live capabilities and evidence

Disruption visibility: **Disruption studio** now captures operating values before
and immediately after a change and plots the selected measure as subsequent ticks
arrive. Quarantine shows held/usable passionfruit and links to the next lab or QA
decision. Select any ingredient for a supplier delay; the configured-lanes table
explains the affected route. Increasing a delay shifts booked arrivals; reducing
it restores normal lead times for new bookings, without reversing existing ETAs.
The imported dragonfruit preset remains a shortcut to its 40% sea lane.
**Stock & network** shows finished-goods freshness buckets and expired write-offs.
GT fulfillment and rescue transfers both require seven days remaining; MT/QC
requires 60. Raw stock remains aggregated under the six-month-life assumption.
The Decision Desk only shows currently supported offers; superseded offers are
recorded as `OFFER_WITHDRAWN` events rather than disabled recommendation cards.

Decision evidence update: comparisons now share live timing and use action-specific
horizons (32 days for co-packer review), approvals record projected/realized
outcomes, and Model & evidence includes a paired forecast benchmark. Disruption
Studio supports timed recovery and the board marks events. Adaptive production
uses shared-resource allocation. See [Decision evidence and verification](docs/DECISION_EVIDENCE.md)
for the current calculations, limits and reproduction commands; it supersedes
the older fixed 14-day comparison descriptions below.

A working Python and browser decision system for the Pulp Riot case. The home page is now a **second-by-second operating simulation**: synthetic order batches arrive, model forecasts and stock update, disruptions change the business, and a named user's timed approvals reserve stock, commit cash and execute simulated interventions. Demand and Inventory are the two deep modules; Supply, Distribution and Transportation constrain their decisions.

**The included data is synthetic and case-constrained.** The case provides no real SKU recipe, actual batch ledger, supplier corridor coordinates, transactions, or API credentials. The sample is for testing the pipeline; its scenario improvements are not measured savings. Nothing in this app orders ingredients, dispatches freight or moves stock.

## Full stack for imported real records

The Next.js/FastAPI workspace imports company facts into its own PostgreSQL database and Docker volumes. It never opens the synthetic app's SQLite file, replaces its shipped model or resets a live run. The Python server is optional when opening the dashboard directly.

### Prerequisites and startup

Use Docker Desktop with its **Linux engine** running, or Docker Engine in the supported `Ubuntu-24.04` WSL distribution. Allocate approximately **12–16 GB RAM** for the complete development stack. The first build downloads images and dependencies. Practice/test mode requires a Docker Compose release supporting the `!override` syntax in its override file.

From the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_real_records.ps1
```

Open **Import real records** from `/operations`, or go directly to **http://127.0.0.1:3010/operations/real**. Wait for **System health** and **Stream current** before reviewing data-dependent plans.

| Service | Real workspace | Practice/test workspace |
|---|---|---|
| Dashboard | `http://127.0.0.1:3010/operations/real` | `http://127.0.0.1:3020/operations/real` |
| API health | `http://127.0.0.1:8010/health` | `http://127.0.0.1:8020/health` |
| Grafana | `http://127.0.0.1:3011/d/real-records` | `http://127.0.0.1:3021/d/real-records` |

Stop services while retaining their persistent volumes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_real_records.ps1
```

The start script accepts `-NoBuild` to reuse existing images. Starting the real workspace pauses practice containers, and starting practice pauses real containers to conserve memory; both retain their data. The original Python simulation continues independently.

The WSL fallback starts Docker inside `Ubuntu-24.04`, uses a hidden keepalive process, and activates `/var/lib/pulp-real-records.swap` if that file already exists. It does not create or require the swap file on a new installation. See [the platform setup guide](real_records/README.md) for further details.

### Record contracts

The workspace accepts arbitrary company SKU, depot, material and facility IDs. It injects no company masters, inventory or forecasts. Explicit `synthetic: true` and `sample: true` rows are rejected outside practice/test mode. Provenance confirmation records a user's assertion rather than independent verification.

In **Import records**, choose a type, enter a source name and download an empty CSV header for its exact fields. JSON uploads contain arrays of objects. Dates use `YYYY-MM-DD`; CSV numbers are unformatted and booleans use `true`/`false`.

| Record type | Purpose and important fields |
|---|---|
| `channel_master` | Channel rule: `id`, `date`, `min_remaining_days` |
| `sku_master` | Recipe: `id`, `date`, `recipe` mapping material IDs to positive kilograms per bottle |
| `depot_master` | Depot identity: `id`, `date`, `city`, `region` |
| `order` | Requested and fulfilled bottles by SKU, depot and channel, with `in_stock` |
| `lot` | Finished batch quantity, observation date, manufacture and expiry |
| `material_lot` | Raw-material kilograms and expiry |
| `inbound` | Material quantity, ETA, status and transport mode |
| `capacity` | Facility capacity in bottles and availability status |
| `production` | SKU/facility/depot commitment, quantity, production date and depot ETA |
| `shipment` | SKU transfer, origin/destination, quantity, ETA, expiry and status |
| `route` | Corridor status and confirmation; transfers also need `from_depot`, `to_depot` and optional whole `lead_days` |
| `freight_quote` | Material, maximum kg, incremental cost, lead time, validity and cold-chain confirmation |
| `signal` | SKU, source, observed value and baseline |

Every type has stable `id` and `date` fields. Reuse a physical batch's ID when replacing its balance. Full fields and enums are in [real_records/contracts.py](real_records/contracts.py) and exposed by `/contracts`. These contracts differ from the original SQLite workbench schemas.

The entire upload is validated before its transaction. Files contain **1–10,000 records**, without duplicate IDs in one batch. Quantities must be finite and nonnegative; bottle counts are whole numbers. Fulfilled cannot exceed requested. Batch, production and shipment dates must be internally consistent.

### Import, compare, approve and reconcile

1. **Preview:** choose the type, source and file, then **Preview and validate**. Inspect the rows and confirm provenance before importing.
2. **Import:** equal kind/ID/content is a no-op; changed content creates a retained revision and outbox event. Identical reimports also record snapshot verification.
3. **Wait:** continue when **Stream current** appears. Imported and projected versions must agree before training or planning.
4. **Inspect:** review observed demand, inventory, freshness and the network. Import channel rules and recipes. Planning checks relevant current feeds for freshness, currently with a two-day threshold; historical orders remain useful for training.
5. **Compare:** Ray evaluates named what-if assumptions over the same snapshot. Results are aggregate supply bounds; recipe, lane and batch feasibility are checked by the optimizer.
6. **Optimize:** choose a horizon in **Decision desk** and inspect allocations, production, confirmed inbound procurement, transfers, unmet demand and assumptions.
7. **Decide:** enter a name and reason, then approve or reject. Temporal checks the exact input revision and atomically reserves eligible resources.
8. **Reconcile:** accepted work produces an idempotent request with `AWAITING_ERP_ADAPTER`. Record the external outcome and import/reverify fresh physical snapshots before another approval.

Only one plan may be outstanding. Replacement imports are blocked while a proposal is reserved/requested, pending reconciliation. Changed inputs invalidate old proposals. Missing recipes prevent production; missing channel rules or stale required feeds prevent planning. Transfers require current confirmed open lanes and reserve specific batches to prevent double allocation.

The allocation model enforces shared facility capacity, material bounds, confirmed inbound supply and freshness through the horizon. Detailed shift scheduling, facility/SKU qualification, vehicle routing and within-horizon sequencing remain outside this model.

### Practice with labeled synthetic records

Practice uses project `pulp-real-records-practice` with separate volumes. Regenerate the dated files before later sessions because stale observations intentionally block allocation:

```powershell
py -3 scripts/generate_real_records_practice.py
powershell -ExecutionPolicy Bypass -File scripts/start_real_records.ps1 -Practice
```

Open **http://127.0.0.1:3020/operations/real** and confirm **Practice workspace** is visible. In **Import records**, use source `synthetic-practice-pack` and upload files **01–09** from [data/real_records_practice](data/real_records_practice/), in order, choosing the types in [START_HERE.md](data/real_records_practice/START_HERE.md). Preview each file and acknowledge its synthetic provenance.

The nine baseline files contain **52 rows**; optional files 10–13 add four examples. CSV alternatives are under `csv/`; choose JSON or CSV for each upload. With a fresh baseline and a seven-day horizon:

| Measure | Expected value |
|---|---:|
| Daily requested demand | 100 bottles |
| Seven-day requested demand | 700 bottles |
| Existing stock allocated | 100 bottles |
| New production | 500 bottles |
| Confirmed inbound material used | 10 kg |
| South-to-north transfer | 70 bottles |
| Total allocated / unmet | 600 / 100 bottles |

The recipe uses 0.1 kg/bottle: 40 kg on hand plus ten inbound supports 500 new bottles. Closing the lane before approval reduces allocation to 530 and invalidates the old proposal. The walkthrough also covers reopening, invalid imports, idempotence, duplicate approvals, reconciliation and forecast outcomes. Follow its sequence before adding optional outcome rows, which change the baseline.

Return to the real workspace or stop practice while retaining data:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_real_records.ps1 -NoBuild
# Alternatively, stop practice without starting the real workspace:
powershell -ExecutionPolicy Bypass -File scripts/stop_real_records.ps1 -Practice
```

Practice and integration tests share override ports 8020/3020/3021 and must run separately.

### Platform configuration

Copy the example before changing local settings:

```powershell
Copy-Item real_records/.env.example real_records/.env
```

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Local PostgreSQL credential used by Compose |
| `GRAFANA_PASSWORD` | Grafana password; local default `local-real-monitoring` |
| `REAL_RECORDS_TOKEN` | Optional bearer protection for the API and frontend proxy |

Grafana's local username is `admin`. Object-store development credentials are configured in `real_records/compose.yaml` and `real_records/storage/s3.json`. `.env` is ignored by Git. Recreate affected services after environment changes. Existing database volumes retain initialized credentials; editing a variable alone does not rotate a stored database password.

## Start the live experience

Requirements: **Python 3.11 or newer**. Serving the lightweight app needs no Node.js, Docker or third-party Python packages. Run commands from the repository root. On Linux/macOS, use `python3` instead of `py -3`.

```powershell
py -3 server.py --demo
```

Open **http://127.0.0.1:8765** and select **Start live**. Each wall-clock second advances 3, 6, 12 or 24 business hours. The default is six hours. Every tick processes 135 flavor/depot/channel order series, finite production, ingredients, shipments and batch aging. The browser receives snapshots through an authenticated Server-Sent Events stream, without page polling.

1. Watch **Live board**: observed demand, trained-model + adaptive-nowcast predictions, stock cover, contribution and the comparison policy.
2. Use a quick disruption or **Disruption studio**. It supports viral attention, attention with no conversion, road closure, traffic delay, plant outage, imported-pulp delay, heatwave, competitor pressure, feed loss and quality quarantine. The guided run introduces viral demand at day 1, closure at day 6 and a plant outage at day 12. Sandbox mode leaves every disruption to you.
3. Open **Compare & decide**. The server automatically pauses the whole simulation while you review. Click a feasible path card: wait, full quantity, half where supported, or execute after two business days. Supply your name and reason; confirm checks for an intervention. Offers get at least ten active simulation ticks (normally ten wall-clock seconds), while physical urgency is tracked separately. Closing or submitting restores the prior clock state.
4. **Outcomes & ledger** shows dispatched/received shipments, scheduled/completed repairs and tests, budget commitments and contribution against the identical no-intervention policy. A bad or late decision can reduce contribution.
5. **New run** creates a separate seeded season; previous runs remain archived. Restarts resume the latest saved state **paused**. The simulation never resets imported operational records.
6. **Incoming data** exposes all 135 latest order records, their baseline, generator factors, interval quantities, fulfillment and whether the model actually observed them. Filter by flavor/channel/depot and use **Freeze table** to inspect a record without stopping the business. Every disruption gets an explicit before/after receipt. Applying one while paused produces one affected batch; manual changes switch guided mode to sandbox so later scripted events cannot override your controls.

The board now offers separate cumulative and interval charts. Cumulative gross sales normally rise; interval sales/contribution and unfulfilled-demand rate expose worsening performance. A completed 112-day season cannot advance further—use **New run**. Detailed calculations and model limitations are in `docs/WORKING_AND_NUMBERS.md`.

The original operational import/forecast workbench is at **http://127.0.0.1:8765/operations**. Real imported records and the synthetic live run use separate tables; importing a company record does not silently alter a synthetic scenario.

## Live data, model and verification

- The exact **40,500 generated training rows** are now saved in `data/training/synthetic_orders.csv`; `manifest.json` verifies their SHA-256 against the shipped model. Regenerate with `py -3 scripts/export_training_data.py`.
- Every tick's 135 requested/fulfilled batches, source-observed flag, 45 stock snapshots, scenario inputs, production and raw balances are stored in SQLite's `live_events` table. **Export event data** downloads the current run as JSON. Data is generated on the server, not in the chart.
- The trained gradient-boosted trees stay fixed. An exponential nowcast updates from observed requests every tick. Only complete, observed business days extend model history. Missing feeds freeze demand observations and mark stock stale; no hidden demand-generation parameters enter prediction. The model screen compares trained-only and adaptive completed-day errors.
- Conditional branches use the current forecast and known disruptions, not the simulator's future hidden demand. The no-intervention policy receives exactly the same actual demand and exogenous disruptions as the managed policy.
- Finance is a contribution proxy, not audited profit. Declared synthetic quotes and a first-year cash envelope govern approvals. The example reserves ₹1.2 crore of the ₹2.5 crore ceiling for build/run; buffer cash and maximum co-packer premiums are committed before other actions.

```powershell
py -3 -B -m unittest discover -s tests -v
py -3 scripts/smoke_live.py
py -3 scripts/export_live_fixture.py
npm.cmd ci --ignore-scripts
npm.cmd run test:ui
py -3 scripts/evaluate_live.py --days 28
```

`smoke_live.py` advances the active synthetic run for three pushed ticks and restores its previous pause state. The test suite checks conservation, delayed arrivals, approval freshness, budget commitments, fixed plant capacity, 14-day co-packer notice, quality release, feed failure, source authentication and streaming. `evaluate_live.py` exercises ten independent scenario families with an explicitly scripted offline test planner; it is never an auto-approver in the live app. Full guide: `docs/LIVE_GUIDE.md`.

Serving needs Python 3.11+ only. Node/jsdom are development test dependencies. A shared company deployment still needs verified identities/roles, TLS/gateway, managed storage and backups, monitoring and authorized execution adapters. The live mode is a persistent operational rehearsal; its public attention and traffic inputs are explicitly simulated.

## Run the working app

From this folder, with Python 3.11 or newer:

```powershell
py -3 server.py --demo
```

Open **http://127.0.0.1:8765/operations** for the import workbench. `--demo` seeds operational sample records at `output/control_tower.sqlite`. Decisions and imported records persist in SQLite. Omit `--demo` for an empty operational workbench, or set a different `--db` path. The live mode still creates its own isolated synthetic run. The service binds to loopback by default.

| Server option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address; non-loopback binding requires `CONTROL_TOWER_TOKEN` |
| `--port` | `8765` | HTTP port |
| `--db` | `output/control_tower.sqlite` | SQLite database path |
| `--demo` | Off | Seed an empty workbench with labeled synthetic records |

Use a separate database for company inputs: `py -3 server.py --db output/company.sqlite`. Stop a foreground server with **Ctrl+C**. Relative database paths resolve from the working directory.

Run the verification suite:

```powershell
py -3 -B -m unittest discover -s tests -v
node --check web/operations.js
node --check web/operations-v2.js
py -3 scripts/smoke_app.py --replay
node scripts/smoke_ui.js
```

Generate inspectable CSV sample inputs:

```powershell
py -3 scripts/generate_sample.py --as-of 2026-10-25
```

The files appear in `data/operational_sample/` with a manifest explaining facts and synthetic choices. The live UI's **Data inputs** screen lets you download an example, preview and validate JSON/CSV, then import. New records recalculate the next plan; the page refreshes every minute. Same-type record IDs are upserted idempotently, while all changed versions remain in the database audit trail.

## Forecast model

The shipped `data/models/demand_model.json` is a trained, safe-to-load tree artifact; serving requires only Python's standard library. It learned from 300 days of **generated synthetic orders** and passed a chronological validation gate. On a later synthetic test period, its weighted absolute percentage error was **21.973%**, versus **28.661%** for repeating last week's demand and **31.402%** for the trailing seven-day mean. These numbers show that the training and evaluation pipeline works; they do not establish accuracy for Pulp Riot's real sales.

The **Demand forecast** screen shows 14 daily estimates per flavor, depot and channel, an empirical range, the backtest scores, the data source, and when the planner used the model. A missing 14-day order history, a mixed sample/real feed, failed validation, or a planning date before the training period ends falls back to the observed-order rule. Confirmed two-day viral demand has a conservative observed-order floor. Public attention is evidence to investigate, not a bottle multiplier. The scenario replay uses its own observed-order policy, so later-trained model knowledge cannot leak backward into it.

To retrain on a separate company database after at least 120 dated days of requested orders:

```powershell
py -3 -m pip install -r requirements-training.txt
py -3 scripts/train_forecast.py --db output/company.sqlite --out output/company-demand-model.json
```

To reproduce the synthetic artifact (default end date is 14 days before today):

```powershell
py -3 scripts/train_forecast.py --synthetic --end 2026-10-10
```

Training reports the train/validation/test date windows and scores. It replaces the artifact only after export parity checks; if the model fails its validation gate, the planner retains its baseline. Use a separate database for real inputs, since real-data training refuses sample or mixed records.

The company example uses `--out` to preserve the shipped artifact. Serving does not automatically switch to this alternate file; the default inference path remains `data/models/demand_model.json`.

### Independent full-stack model

The imported-records platform has a separate XGBoost pipeline. It needs at least **35 consecutive dated order days**, including 28 feature days, and holds out the last seven feature dates. MLflow records runs/model versions; promotion requires WAPE no worse than the observed-mean baseline. Airflow runs daily and visibly skips when history is insufficient. Saved predictions are compared with actual target-day orders when later imported. The workspace supplies no preloaded company model and never generates actual outcomes.

### Paired forecast benchmark

```powershell
py -3 scripts/benchmark_forecasts.py --days 28 --seeds 101,202 --cases normal,viral,compound
```

The benchmark uses isolated in-memory engines, checks identical request-stream hashes, scores forecasts saved before each business day, and reports service, expiry, contribution and actions. It writes `data/forecast_benchmark.json`; the UI checks source hashes for stale evidence.

Live comparisons share the same origin, interval timing and known disruptions. Their usual horizon is `max(14, action lead + 16)` days; co-packer comparisons currently use 32 days. Season end caps the window. Beyond the model's 14 trained horizons, the app holds the last trained horizon with decaying nowcast influence and labels the extrapolation.

Approval saves evidence and starts a reference world immediately before the action. It receives the same subsequently realized requests and exogenous disruptions without further approvals. Later approvals affect managed results and are flagged, so realized differences cannot be attributed solely to the first action. See [decision evidence](docs/DECISION_EVIDENCE.md) for the evaluation policy and attribution limits.

## Operating workflow

1. Import approved SKU recipes, depot/channel masters, current orders, finished-goods batches, raw-material batches, confirmed inbound receipts, plant capacity, committed production, in-transit shipments, route reports and freight quotes. Each kind has a checked schema in `engine/operations.py` and is described in **Data inputs**. Updated SKU, depot and channel shares must still total 1.0; send the related changes in one upload.
2. Inspect **Overview**, **Inventory & supply**, and **Decisions**. Public attention starts a watch; validated order shifts change the demand forecast. A map incident requires corridor/transport confirmation.
3. A named user records approval or rejection, with a role and reason. The decision applies to the exact recommendation version. Changed inputs can cause a new pending version.
4. Open **Scenario lab** to compare two policies on the same daily synthetic demand and route events. The proposed case assumes a 24-day pre-season pulp buffer and immediate human approvals; these are counterfactual assumptions.

### Optional official public observations

Set the appropriate environment variables before starting the server:

| Connector | Variables | Result |
|---|---|---|
| TomTom Traffic Incidents | `TOMTOM_API_KEY`, `PULP_ROUTE_BBOX=minLon,minLat,maxLon,maxLat` | A closure incident inside the verified corridor box raises a **watch**. Logistics must confirm that it affects the actual approved road. |
| YouTube campaign-video stats | `YOUTUBE_API_KEY`, `PULP_YOUTUBE_VIDEO_IDS` (comma-separated, marketing-verified) | Repeated observations measure attention acceleration. They never convert views directly to bottle demand. |

Configured feeds poll when the server starts and every 15 minutes. **Check configured public feeds** also polls on demand. Unknown API failures remain `UNKNOWN`; they never imply an open road or zero demand. The supplied case has no corridor coordinates or video IDs, so the demo runs without calling either provider. Google Trends API access is restricted and is therefore not a required production dependency.

For local bearer-token protection set `CONTROL_TOWER_TOKEN`; the browser prompts for it when needed. A shared deployment needs an authenticated gateway, managed database, durable workers and vendor operations before real company data or execution integrations are introduced. The server refuses non-loopback binding unless the token is set. Current role labels record the claimant; they do not independently verify company identity.

For example, configure a local token before startup:

```powershell
$env:CONTROL_TOWER_TOKEN = 'replace-with-a-local-random-token'
py -3 server.py --demo
```

`REAL_RECORDS_UI_URL` controls the Python server's `/operations/real` proxy upstream, defaulting to `http://127.0.0.1:3010`. The original server reads its settings from the process environment; copying the full-stack `.env` does not configure the Python server's token.

### Optional process mining

`GET /api/process-mining` uses PM4Py to summarize operational audit activity as a directly-follows graph, activity counts and start/end activities. It groups imports by kind, external observations by source and decisions by action. The current implementation reads up to the first 500 audit entries and returns up to 25 edges.

PM4Py is optional and included in `requirements-training.txt`. Without its dependencies the endpoint reports `unavailable`; an empty audit returns `empty`. This summarizes audit activity rather than a discovered physical order-to-delivery process.

## Architecture and persistence

### Lightweight application

```text
Browser: live board / operational workbench
                    |
         Python HTTP API + SSE
                    |
        +-----------+------------+
        |                        |
   LiveEngine              Operational planner
   synthetic clock         validated imports
   decisions/outcomes      forecasts/audit
        |                        |
        +---- separate tables ---+
                    |
        output/control_tower.sqlite
```

The live simulator and operational workbench share a default database file, with separate tables. Imported company data does not alter synthetic demand. Current-run event exports are available through **Export event data**.

### Imported-records pipeline

```text
Next.js / TypeScript / ECharts
              |
           FastAPI
              |
PostgreSQL records + immutable outbox
              |
Debezium -> Kafka -> Flink -> validated topic
                                   |
                                Projector
                                   |
                  Archive sinks, then operational projection
                                   |
           +-----------------------+----------------------+
           |                       |                      |
    XGBoost / MLflow         Ray comparisons      OR-Tools proposals
    Airflow schedule                                      |
                                              Temporal approval workflow
                                                          |
                                           Reservation + dispatch request
```

| Component | Responsibility |
|---|---|
| PostgreSQL | Authoritative records/revisions, outbox, projections, models, proposals, reservations and requests |
| Redis | Latest-event cache |
| Debezium / Kafka | PostgreSQL WAL capture and durable event transport |
| Flink | Independent validation, versioned state, disruption processing and validated output; ten-second checkpoints |
| SeaweedFS / Iceberg / ClickHouse | S3-compatible event objects, table snapshots and analytical history |
| XGBoost / MLflow / Airflow | Training, evaluation, registry and daily scheduling |
| Ray / OR-Tools | Parallel comparisons and constrained integer allocation |
| Temporal | Durable approval waits, retries, revision checks and request creation |
| OpenTelemetry / Prometheus / Grafana | API tracing, service/worker metrics and operations dashboard |

The projector archives each event before exposing its operational projection. Kafka delivery is at least once. Stable event IDs, object keys, Iceberg upserts and ClickHouse deduplication support replay. Failed sinks retain the offset for retry. The serial archival path favors inspectability over high-volume throughput.

**System health** checks services, connector/job state and recent worker heartbeats. A responsive API does not establish input quality or a current stream; inspect imported/projected versions too.

SQLite databases and generated local reports live under ignored `output/`. Compose named volumes survive normal stops. Real, practice and integration projects use separate volumes. Back up the relevant database and volumes before maintenance; stopping containers does not create a backup.

## API overview

Selected endpoints are listed below. Exact request payloads are defined in [server.py](server.py) and [real_records/api.py](real_records/api.py); the two services have different contracts.

| Python route | Purpose |
|---|---|
| `GET /api/health` | Workbench health and record counts |
| `GET /api/catalog`, `GET /api/records?kind=order` | Input catalog and records |
| `POST /api/validate`, `POST /api/ingest` | Preview/import `{kind, records, source}` |
| `GET /api/plan` | Current plan with optional `date` query |
| `POST /api/decide` | Version-specific workbench decision |
| `GET /api/audit`, `GET /api/process-mining` | Audit history and optional activity graph |
| `GET /api/live/state`, `GET /api/live/stream` | Snapshot and SSE stream |
| `POST /api/live/control` | Clock/run controls |
| `POST /api/live/inputs`, `POST /api/live/inject` | Custom conditions and presets |
| `POST /api/live/compare`, `POST /api/live/decide` | Path comparison and decision |
| `POST /api/live/review/open`, `POST /api/live/review/close` | Review pause lifecycle |
| `GET /api/live/events`, `GET /api/live/benchmarks` | Run export and benchmark evidence |

| FastAPI route, port 8010 | Purpose |
|---|---|
| `GET /health`, `GET /services`, `GET /metrics` | API/database readiness, service probes and Prometheus metrics |
| `GET /contracts`, `POST /validate` | Contracts and import preview |
| `POST /imports`, `GET /records` | Provenance-confirmed imports and source records |
| `GET /state`, `GET /monitoring`, `GET /history` | Projection, forecast outcomes and archival evidence |
| `POST /train`, `POST /scenarios`, `POST /optimize` | Training, comparisons and proposals |
| `POST /proposals/{proposal_id}/decide` | Approval/rejection |
| `POST /requests/{request_id}/reconcile` | Request reconciliation |

FastAPI exposes `/openapi.json` and `/docs`. Include bearer authorization when configured. The Next.js proxy uses `/operations/real/api/`. The Python proxy returns an explained HTTP 503 if the upstream frontend is offline.

## Development and full-stack verification

The root `package.json` provides jsdom-based live UI tests. Node.js 22 matches CI. The Next.js frontend has its own package manifest and lockfile. On Linux/macOS use `python3` and `npm` instead of `py -3` and `npm.cmd`.

GitHub Actions runs the legacy model self-test, Python suite, JavaScript syntax checks and streamed UI fixture checks on pushes and pull requests. Full Docker integration is a separate local check.

### Imported-records unit and frontend checks

Use an isolated Python 3.11/3.12 environment for the pinned platform dependencies; the service image uses Python 3.11. This example keeps the environment under ignored `output/`:

```powershell
py -3.11 -m venv output/real-venv
& .\output\real-venv\Scripts\python.exe -m pip install -r real_records/requirements.txt -c real_records/constraints.txt
& .\output\real-venv\Scripts\python.exe -m unittest discover -s tests -p 'test_real*.py' -v
Push-Location real_records/frontend
npm.cmd ci --ignore-scripts
npm.cmd run typecheck
npm.cmd run build
Pop-Location
```

### End-to-end service checks

Stop practice first because it uses the same ports. Avoid simultaneous full stacks on a memory-constrained machine. Use the dedicated test project:

```powershell
docker compose -p pulp-real-records-test -f real_records/compose.yaml -f real_records/compose.test.yaml up -d --build
py -3 scripts/test_real_stack.py
docker compose -p pulp-real-records-test -f real_records/compose.yaml -f real_records/compose.test.yaml down
```

The runner refuses writes unless the API on **8020** reports test mode. It exercises CDC/projection, archival history, training/MLflow, Ray, OR-Tools and Temporal with fixtures confined to test volumes. Normal `down` retains volumes. For WSL Docker, prefix Docker commands with `wsl -d Ubuntu-24.04 -u root --` and translate file paths to `/mnt/c/...`.

[real_records/VERIFICATION.md](real_records/VERIFICATION.md) records a previous verification session and its limits; those results do not replace rerunning checks after changes.

### Kubernetes development manifests

[real_records/kubernetes.yaml](real_records/kubernetes.yaml) contains local-cluster deployments, jobs, services, configuration and persistent-volume claims. Regenerate with `py -3 scripts/render_real_kubernetes.py` after installing PyYAML. Build and load the three local images into an existing cluster, then apply:

```sh
docker build -t pulp-real-api:local -f real_records/Dockerfile .
docker build -t pulp-real-flink:local -f real_records/flink/Dockerfile .
docker build -t pulp-real-frontend:local real_records/frontend
kubectl apply -f real_records/kubernetes.yaml
kubectl -n pulp-real-records port-forward svc/frontend 3010:3000
```

Keep Compose stopped when sharing ports. The manifests do not provision a cluster or establish high availability or a verified production rollout.

## Troubleshooting

| Symptom | Next step |
|---|---|
| `python` opens the Windows Store or cannot run | Use `py -3` or an installed executable's full path; check `py -3 --version`. |
| Port 8765 is occupied | Stop the existing instance or use `--port 8766`. Binding is exclusive where supported. |
| Clock appears frozen after restart | Select **Start live**. Restarts deliberately pause; after day 112, create a new run. |
| Imported-records page returns 503 | Start Docker services and open port 3010 directly. Check `REAL_RECORDS_UI_URL` for the Python proxy. |
| Stack fails to start | Check Linux-engine readiness/memory, then `docker compose -f real_records/compose.yaml ps` and `logs --tail 100`. |
| API responds but records are absent | Check CDC/Flink, worker heartbeats and imported/projected versions; wait for Stream current. |
| Synthetic flag is rejected | Use practice mode for supplied files and retain their provenance labels. |
| Planning rejects stale/missing data | Import current observations, recipes and channel rules; regenerate dated practice files. |
| Proposal becomes STALE | Reconcile outstanding work, refresh physical snapshots and generate a proposal on current inputs. |
| Reimport says 0 changed | Equal kind/ID/content is idempotent; verification metadata can still refresh. |
| Training skips | Import enough consecutive requested-order history and wait for projection; the pipelines have different thresholds. |
| API returns 401 | Supply its configured token. Python and full-stack tokens are independent. |
| Process mining unavailable | Install PM4Py dependencies in the environment running `server.py`. |

For practice logs select project `pulp-real-records-practice` with both Compose files; for integration logs select `pulp-real-records-test`. Explicit project names help inspect the intended workspace.

## Main files

See [the critical audit](docs/CRITICAL_AUDIT.md) for corrected logic defects,
control coverage, verification commands and remaining simulation limitations.

- `server.py` — local HTTP API, persistent store, authenticated event stream and web serving.
- `engine/live.py` — server-clocked simulation, conservation, adaptive forecasts, timed decisions, execution and financial counterfactuals.
- `web/live.*` — live board, disruption studio, decision branches, inventory, outcomes and model evidence.
- `engine/operations.py` — schemas, versioned inputs, demand/inventory calculations and recommendations.
- `engine/forecast.py` and `scripts/train_forecast.py` — model inference and reproducible temporal training/backtest.
- `engine/external.py` — optional official public-source adapters.
- `engine/replay.py` — daily synthetic counterfactual using the same planner.
- `web/operations.*` and `web/operations-v2.*` — browser workbench, forecast exploration and guided imports.
- `tests/test_operations.py` — validation, eligibility, approval-version, connector, replay and HTTP checks.
- `docs/PRODUCTION_SYSTEM.md` — full system boundaries, calculations and rollout gates.

The original offline model and dashboard remain at `engine/pulp_riot_model.py` and `web/index.html` as legacy references. They are independent of the new operational API.

Additional repository areas:

- `real_records/` — full-stack API, validation, streaming, history, forecasting, allocation and workflow services.
- `real_records/frontend/` — Next.js, TypeScript and ECharts dashboard.
- `real_records/monitoring/` and `real_records/storage/` — observability and storage configuration.
- `real_records/compose*.yaml` and `real_records/kubernetes.yaml` — development deployments.
- `data/real_records_practice/` — labeled JSON/CSV practice pack and [walkthrough](data/real_records_practice/START_HERE.md).
- `scripts/start_real_records.ps1` and `scripts/stop_real_records.ps1` — real/practice lifecycle helpers.
- `tests/test_real_records.py` and `tests/test_real_proxy.py` — imported-record validation/planning and offline-proxy checks.
- `web/assets/` — locally served fonts with their license notices.
- `output/` — ignored local databases and generated reports.

## Deployment boundaries

The default setup is a persistent local development and rehearsal environment. Published Compose application ports bind to loopback. Temporal uses its persistent development server, Airflow uses standalone development configuration, and services use single replicas.

A shared company deployment needs verified identities/authorization, TLS and an authenticated gateway, managed secrets, durable storage/backups, service resources and monitoring, and authorized ERP/warehouse/logistics adapters. Recorded names and roles are local claims rather than independently verified identities.

The full-stack execution boundary is a durable dispatch request. An external adapter must use an idempotency key tied to the proposal ID and return a reconciled outcome before new physical snapshots support another plan. No vendor execution credentials, physical dispatch integration or measured business savings are included.
