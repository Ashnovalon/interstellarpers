# Live operating rehearsal

The live home page is an event-driven, persistent simulation of Pulp Riot's network. Every visible figure comes from the Python engine. All operating observations, depot identities, recipes, lab outcomes and prices beyond supplied case facts are synthetic. No real procurement, dispatch or supplier contact takes place.

For the revised input audit, selectable decision paths, automatically paused reviews, financial examples and numerical corrections, read `docs/WORKING_AND_NUMBERS.md`.

## User workflow

Start the clock, watch daily-rate demand and forecasts, inject a disruption, compare actions, then approve or reject before the business deadline. Pause or step the clock for careful review. Rejected, missed and badly chosen actions can leave shortages unresolved or consume budget. A run ends after 112 modeled business days. Creating another run archives the previous state and event log without clearing company imports.

The seven screens are Live board, Decision desk, Stock & network, Incoming data, Disruption studio, Outcomes & ledger, and Model & evidence. The original operational input workbench remains at `/operations`. Opening a review pauses the server clock; selecting and submitting a path restores its previous state. Offers remain visible for at least ten active ticks, with physical urgency shown separately. Manual disruptions switch guided runs to sandbox and cancel remaining guided shocks. Applying a disruption while paused generates one affected input batch.

Each tick emits 135 series: five flavors × nine depots × three channels. GT observations are distributor requests, never invented outlet sell-through. A tick's order quantity is for the chosen business interval; chart rates normalize it to bottles/day. Changing speed aligns ticks to midnight so partial business days cannot be promoted to complete training days.

## Clock and stream

The server worker targets one wall-clock tick per second with a monotonic schedule. The business clock advances 0.125, 0.25, 0.5 or 1 day per tick. A single worker owns the run for all connected users, so opening a second browser does not generate another business. API mutations and ticks use the same lock. The browser receives the latest full snapshot by SSE, reconnects after disconnection and preserves unfinished scenario-form edits.

Restarts restore the newest state paused. The HTTP server uses exclusive binding where available to prevent old/new processes sharing a port. A configured bearer token protects snapshots, streams, mutations and exports. This is local deployment protection; approver names in a synthetic run are not company-authenticated identities.

## Physical state

Opening finished goods are 21 case-baseline days per flavor/depot. Slow-depot Mango Peach Basil and Guava Chilli lots have older synthetic ages, creating a real acceptance-window problem. Opening raw cover is 14 passionfruit days, 21 dragonfruit days and 30 days for other materials. Booked routine receipts represent existing supply contracts. Dragonfruit supply is split into domestic 60% and imported 40%, with the latter modeled at 42 days plus the injected delay.

For each interval the engine receives due shipments, handles eligible quality outcomes, consumes oldest eligible stock against MT/QC then GT requests, records unfulfilled demand, consumes raw ingredients to produce finite output and schedules production-to-depot transit. Expired bottles leave usable stock and generate a write-off charge. Lot identity, manufacture and expiry travel with a transfer. New shipments cannot appear at the destination before their ETA.

Conservation is checked with:

`opening bottles + production = fulfilled + expired + physical stock + in-transit stock`

Raw material is separately balanced as opening plus received minus consumed/disposed equals available plus held. Frozen pulp remains inside six-month life for this 112-day rehearsal. Ingredient batch expiry after a longer horizon would require an extended batch ledger; this simulation stops before that boundary.

## Prediction and information boundaries

Stored boosted trees create direct 1–14-day demand estimates from completed observed history. Current requested orders update an exponential nowcast with a 0.65-day time constant. The current daily rate blends 35% trained estimate and 65% nowcast; future nowcast influence decays over four days. These are explicit starting calibration choices, not measured company parameters.

The engine never passes attention-to-order conversion, hidden future orders or future guided shocks into model features. Attention without converted orders leaves predictions unchanged. A feed outage freezes visible demand and warehouse observations while the hidden synthetic business continues. Missing days prevent a complete-history model from being treated as fresh. Trained-only and adaptive daily forecasts are saved at day start and scored only against completed observed days. The artifact itself does not retrain every second.

The shipped artifact has a synthetic held-out WAPE of 21.973%; this is unrelated to a claim of production accuracy. The UI reports live-run scores separately and claims no calibrated live prediction interval. Retraining is an explicit offline operation with chronological validation and test gates.

## Decision types

| Action | Approval effect | Main constraint |
|---|---|---|
| TRANSFER | Removes/reserves donor stock and dispatches a shipment | Same flavor; 60 remaining days at arrival; donor floor |
| GT_TRANSFER | Routes eligible aging batches to distributor demand | At least seven days at arrival; buyer acceptance |
| REPLAN | Authorizes seven days of demand/cover-based allocation | Existing plant and ingredient capacity |
| BUFFER | Commits working capital and schedules extra pulp by road | Sole road open; quantity/cash ceiling |
| AIR | Schedules a quoted passionfruit air receipt | Simulated confirmed road closure; two-day lead |
| AIR_DRAGON | Expedites already-qualified dragonfruit supply | Explicit synthetic quote; five-day lead |
| COPACKER | Reserves maximum premium and books extra production | 14-day notice, 14-day term, at most 10% extra |
| REPAIR_PLANT | Schedules a two-day repair | Restores existing capacity, never adds a line |
| LAB_TEST | Schedules a one-day quality test | Held pulp stays unavailable until a result |
| RELEASE_QA | Returns passed material to usable stock | Separate human QA approval |
| RESTORE_FEED | Reconnects and reconciles the current stock snapshot | Missing historical days remain missing |

Action IDs are stable by kind and target, while versions include run identity, proposal generation, amount, lead and deadline. Every approval requires a name, reason and confirmed checks. Execution revalidates freshness, remaining donor stock, batch age and cash. A previous run's approval cannot apply to a new run. Competing proposals cannot spend the same budget or reserve the same bottles twice. Missed offers are recorded as expired; later proposals can mitigate later loss but cannot reverse earlier stockouts.

Transfers dispatch immediately in the synthetic ledger and become RECEIVED only after transit. Co-packer, maintenance and tests are SCHEDULED until their dates. Replanning is ACTIVE for its seven-day authorization. QA release needs passing evidence, so no user button bypasses the test.

## Decisions and money

Operating contribution is `fulfilled × ₹19.20 − modeled incremental costs − write-offs`. The ₹19.20 is case price ₹60 × contribution margin 32%. This excludes company overheads, taxes and financing and is not audited net profit.

Synthetic cost assumptions are ₹1.50/bottle transfer, ₹40.80/bottle write-off basis, ₹180/kg passionfruit buffer/disposal, ₹80/kg incremental passionfruit air, ₹100/kg incremental dragonfruit air, ₹20,000 lab test, ₹2.5 lakh repair and ₹0.10/kg/day holding above the 14-day passionfruit baseline. Co-packer premium is 25% of the assumed ₹40.80 in-house unit-cost proxy. The assumed prices and recipe need approved replacements before real use.

The first-year envelope is ₹2.5 crore, with an illustrative ₹1.2 crore build/run reserve. Buffer cash is treated as working capital rather than charged twice through contribution. Maximum co-packer premium is reserved when approved and released as actual production is charged or the term ends. Ordinary baseline COGS belongs to company operations, not the digital-program envelope. Unexpected write-offs are reported as asset losses rather than fresh cash commitments.

The continuous comparison world starts identically and faces exactly the same generated requests, closures, delays and quality shocks. It makes no new interventions. A user's maintenance, transfer or other response changes only the managed world. The UI can therefore show negative contribution lift when a discretionary action is premature or too expensive.

## Conditional decision branches

Each review clones current managed state, including booked shipments and commitments. Four paths are projected for 14 days: wait, approve, approve half where meaningful, and wait two days before acting. Demand follows only the current forecast plus a decaying nowcast. Known reopening is modeled; future surprise events and hidden conversion are excluded. Branch computation does not mutate the live state or approve anything.

Amounts are conditional scenario outcomes, not guaranteed benefits. The chosen action can perform differently when the actual synthetic future diverges from its forecast. A lab test alone cannot earn the benefit of a future QA approval, and a co-packer arriving after two weeks cannot fix today's shortage.

## Data and verification

`data/training/synthetic_orders.csv` contains the exact 40,500 generated rows behind the artifact and a matching fingerprint manifest. `live_runs` holds durable run state. `live_events` stores every tick's 135 order batches, source-observed flag, 45 stock snapshots, inputs, production and raw balances. Export event data downloads the current run; archived runs remain in SQLite.

`tests/test_live.py` verifies stock and raw conservation, no hidden attention leakage, partial-day handling, feed failure, reservation/arrival, approval replay protection, closure, imports, budget, co-packer notice, repair, quality, persistence and authenticated streaming. `scripts/test_live_ui.cjs` executes all six views and decision/input interactions in jsdom. Browser screenshots require a connected browser; DOM verification does not establish visual layout correctness.

`scripts/evaluate_live.py` runs independent normal, viral, false-hype, closure, plant, traffic, import, quality, feed-loss and compound scenarios. Its named scripted test planner is only a regression experiment; the running app never approves recommendations automatically.

## Shared production deployment

Before handling company data or physical execution, add verified identities and roles, TLS/reverse proxy, managed database/backups, monitored workers, authorized ERP/WMS adapters and signed source contracts. Configure external sources only with approved coordinates and campaign IDs; public provider errors stay UNKNOWN. The current live screen deliberately labels every source as synthetic rather than claiming a public-service integration is operating.
