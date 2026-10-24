# Decision evidence and operating comparisons

The live simulator now implements comparison timing, recommendation evidence,
outcome tracking, paired forecast benchmarks, timed disruptions, and allocation
improvements. All evidence remains synthetic.

## Comparison timing and horizons

Live ticks and projections use the same selected interval, business-midnight
boundaries, season end, known recovery boundaries and deferred-action times.
The two-day branch reserves cash at the origin and revalidates at execution,
just as a submitted deferred decision does.

The comparison window is `max(14, action lead + 16)` days. Co-packer comparisons
use notice + operating duration + four days, currently 32 days, to include the
delayed start and final plant-to-depot arrivals. Every branch for an offer uses
the same window. Day 112 caps the window and the UI labels truncated comparisons.

Only 14 trained daily forecast horizons exist. Longer projections explicitly
hold the last trained horizon while the nowcast influence decays. They are
extrapolations, not newly trained long-range forecasts. Future guided surprises
and future hidden generated demand remain excluded. Known timed recoveries are
included. Branch curves show cumulative projected contribution over the window.

## Recommendation calculations

Each offer records the observation date/age, tick, forecast mode and revision,
available cash, and calculations behind its trigger. Transfer evidence includes
receiver cover/need, donor floor, freshness, quantity bounds and alternative
donor positions. Evidence is refreshed for the comparison and frozen before
execution; it is not recalculated from stock after a transfer has removed it.

Transfers can use multiple donors. They rank usable donor surplus and share
planned stock and cash within the transfer portfolio. These are deterministic
planning rules, not a claim of global profit optimization. Supply/capacity offers
remain alternatives to the portfolio; displaying an offer never commits cash.
Approval still revalidates physical stock, freshness and actual available cash.

## Projected versus realized outcomes

On approval, the app saves the selected projection and its evidence. It also
starts a reference world immediately before the approval. This world retains
previously approved work but receives no further new decisions. It faces the
same subsequently realized requests and scenario conditions as the managed run.

The ledger shows projected contribution at a labeled checkpoint and realized
total contribution to date, the final
projected gain versus waiting, and the realized gain versus that reference to
date. The observation stops at the original comparison horizon. Later approvals
are counted and explicitly flagged: their effects are present in managed
results, so this is not isolated attribution to the first action. No actual
company savings or physical dispatch is asserted.

Exogenous scenario changes, including quality holds, reach the reference world.
Managed feed restoration does not restore its feed. Forecast updates are shared
only while that reference's observations are available. Deferred costs executing
at the observation boundary are included before the outcome is finalized.

Old saved runs remain readable. Historical approvals without a projection do
not receive invented retrospective evidence. New outcome references and timed
recoveries persist across restarts. Restarting still pauses the clock.

## Timed disruptions

Disruption Studio adds active duration (0 = no timed recovery) and recovery
duration. These apply to the next preset or custom change, not retroactively.
Numeric settings interpolate back to their previous values during recovery;
attention still has its existing onset ramp. Boolean/categorical settings switch
at the end of recovery, except a road reopens at the end of its active duration.
Quality quarantine cannot recover on a timer and still requires test and QA.

Manual changes supersede recovery schedules for the submitted fields. Presets
only replace their own fields and accumulate with other conditions. Restoring
normal conditions cancels superseded schedules, but does not undo booked travel
delays, historical costs, expired stock, or quality holds. Road closure retains
its existing closure-duration timer even when generic active duration is zero.

API examples:

```json
POST /api/live/inject
{"preset":"heatwave","lifecycle":{"duration_days":3,"recovery_days":2},"step_if_paused":true}
```

```json
POST /api/live/inputs
{"changes":{"plant_availability":0.65},"lifecycle":{"duration_days":4,"recovery_days":2}}
```

The board adds disruption/recovery/decision markers and event labels, plus stock
cover, fulfillment and installed available capacity views. Non-demand views are
network totals; the flavor selector is disabled for them. Network stock cover
can hide local shortages, so inspect depot pressure as well.

## Forecast benchmark

Run from the repository root:

```powershell
python scripts/benchmark_forecasts.py --days 28 --seeds 101,202 --cases normal,viral,compound
```

The runner uses isolated in-memory engines and never opens the active live DB.
It compares blend, nowcast, trained trees and a seasonal weekday baseline.
Every paired run uses identical seeds, business intervals, shock schedules and
a deterministic daily approval rule. Request-stream SHA-256 equality is checked
across methods. The rule approves feasible allocation/evidence/maintenance and
at most one transfer daily; it does not approve air, buffer or co-packer actions.

Daily WAPE uses 135 series forecasts saved before each business day, not a
within-day estimate scored after seeing that day's requests. The report also
includes service, shortages, expiry, contribution, costs and action counts.
Identical decision rules may choose different actions under different forecasts;
that operating effect is part of the experiment. Results depend on this policy,
scenario coverage and synthetic assumptions. No statistical significance or
real-world model superiority is claimed.

The report at `data/forecast_benchmark.json` includes source/model hashes captured
at the start of the experiment. `GET /api/live/benchmarks` reports whether it
still matches current source. Model & evidence displays the results and flags
stale evidence. Models are not automatically promoted based on this report.

## Shared-resource production allocation

Approved adaptive allocation now uses deterministic weighted progressive filling
over all flavor/depot positions. It enforces shared plant capacity, per-position
targets and all recipe ingredient balances simultaneously. Capacity released by
an ingredient-blocked product is redistributed to feasible positions. Scarce
shared ingredients are divided by weights instead of product iteration order.
Quantities are floored to whole bottles to preserve constraints.

A reproducible diagnostic in the benchmark demonstrates the need: with plant
capacity 100, one blocked product and another feasible product, the old
one-pass weighted allocation produces 50, while progressive filling produces
100. A separate test checks equal-weight products share a scarce ingredient
25/25 regardless of dictionary order. These are constraint diagnostics, not
claims of production savings. The no-intervention policy retains its fixed
baseline allocation, and finite capacity, recipes and freshness still apply.

## Verification

```powershell
python -B -m unittest discover -s tests -q
python -B scripts/export_live_fixture.py
npm.cmd run test:ui
```

Tests cover conservation, comparison arithmetic/timing and season truncation,
known recovery, superseding edits, quarantine restrictions, frozen approval
evidence, realized references, allocation constraints/order invariance, HTTP
interfaces and browser interaction contracts.

See [the critical audit](CRITICAL_AUDIT.md) for corrected defects, real-HTTP UI
coverage and remaining modeling/visual-verification limits. Run
`node scripts/audit_ui.cjs` for the isolated live and workbench workflow audit.
