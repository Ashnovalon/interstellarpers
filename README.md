# Pulp Riot Live Operations Control Tower

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

## Start the live experience

```powershell
cd C:\Users\srini\Downloads\interstellarpers
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
py -3 scripts/generate_sample.py --as-of 2026-10-24
```

The files appear in `data/operational_sample/` with a manifest explaining facts and synthetic choices. The live UI's **Data inputs** screen lets you download an example, preview and validate JSON/CSV, then import. New records recalculate the next plan; the page refreshes every minute. Same-type record IDs are upserted idempotently, while all changed versions remain in the database audit trail.

## Forecast model

The shipped `data/models/demand_model.json` is a trained, safe-to-load tree artifact; serving requires only Python's standard library. It learned from 300 days of **generated synthetic orders** and passed a chronological validation gate. On a later synthetic test period, its weighted absolute percentage error was **21.973%**, versus **28.661%** for repeating last week's demand and **31.402%** for the trailing seven-day mean. These numbers show that the training and evaluation pipeline works; they do not establish accuracy for Pulp Riot's real sales.

The **Demand forecast** screen shows 14 daily estimates per flavor, depot and channel, an empirical range, the backtest scores, the data source, and when the planner used the model. A missing 14-day order history, a mixed sample/real feed, failed validation, or a planning date before the training period ends falls back to the observed-order rule. Confirmed two-day viral demand has a conservative observed-order floor. Public attention is evidence to investigate, not a bottle multiplier. The scenario replay uses its own observed-order policy, so later-trained model knowledge cannot leak backward into it.

To retrain on a separate company database after at least 120 dated days of requested orders:

```powershell
py -3 -m pip install -r requirements-training.txt
py -3 scripts/train_forecast.py --db output/company.sqlite
```

To reproduce the synthetic artifact (default end date is 14 days before today):

```powershell
py -3 scripts/train_forecast.py --synthetic --end 2026-10-10
```

Training reports the train/validation/test date windows and scores. It replaces the artifact only after export parity checks; if the model fails its validation gate, the planner retains its baseline. Use a separate database for real inputs, since real-data training refuses sample or mixed records.

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
