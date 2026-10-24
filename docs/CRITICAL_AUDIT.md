# Critical implementation audit

The previous implementation was not fully correct. This audit reproduced defects
with regression tests and corrected the issues below. Passing tests is evidence
for the tested contracts, not proof that every possible scenario is correct.

## Corrected logic

| Area | Defect and correction |
|---|---|
| Co-packer output | An activation at the interval end could produce during that entire interval, adding an extra day's output at daily speed. Production now integrates only the overlap with the contracted operating window. |
| Plant repair | A repair arriving at the end of a tick could restore production retroactively. Capacity is now integrated over the actual repaired portion of the interval. |
| Batch freshness | Different production ticks shared a daily lot ID and could merge different expiry timestamps. Production IDs now preserve interval timestamps. |
| Delayed decisions | Replan/co-packer completion was measured from approval rather than execution. Completion now uses the actual execution date. |
| Realized references | Later quality quarantines were absent from the wait reference, while an approved feed restoration could leak into it. Exogenous input changes and quality holds now reach both worlds; managed interventions remain separate. |
| Outcome accounting | Costs of a deferred action executing exactly at the observation-window end could be omitted. Outcomes now include end-boundary execution costs. |
| Forecast calendar | Projections beginning midday advanced the trained horizon a day late. Horizon indices now follow business-midnight boundaries. |
| Forecast chart | The chart used the blended forecast even when another method was selected. It now uses the selected method. |
| Timed recovery | The interface could show recovery ending before the parameter actually reset. Conditions now settle at the displayed boundary. |
| Independent scenarios | Applying one edited field resubmitted all fields and could cancel unrelated recovery schedules. The form now sends only edited fields. |
| Transfer portfolio | Multiple aging-stock suggestions could reuse the same GT-eligible pool. The portfolio now deducts each planned aging-stock allocation. |
| Supply bookkeeping | Passionfruit air-order detection could count dragonfruit orders. Pending receipts are now filtered by material. Co-packer reservations also expire by operating end time. |
| Review consistency | Changed triggers could still be submitted through the API. Review, comparison and approval reject them. Evidence uses the same frozen state as its comparison. |
| UI robustness | Review/submit handlers prevent duplicate requests; resetting a run closes stale reviews; chart hover follows business time; branch colors use CSP-compatible CSS. |
| Ledger precision | Projection checkpoints are labeled with their actual business date instead of implying an exact match to the latest realized date after speed changes. |

## Verification scope

Final validation: all 75 Python tests passed, the existing UI contract test
passed, and all ten real-HTTP workflow groups below passed without DOM/runtime
errors. `git diff --check` passed. The workflow report is written to
`output/ui_audit.json`.

The refreshed benchmark completed all 24 runs and all recorded source hashes
match the corrected code. Aggregate daily-series WAPE was 3.274% for nowcast,
4.444% for blend, 9.508% for trained-only and 9.969% for seasonal. Nowcast also
had the highest aggregate simulated contribution in this experiment. These
results do not justify claiming trained-model superiority or automatically
changing the default without broader validation.

The Python suite checks simulation conservation, cash, decision execution,
forecasts, allocation constraints, persistence and HTTP behavior. The audit adds
13 focused regression tests, including the timing/reference defects and aging
stock portfolio limit.

`scripts/audit_ui.cjs` starts `scripts/serve_audit_app.py` with an in-memory
database and uses real HTTP/SSE responses. It exercises the shipped JavaScript
in jsdom, covering these ten workflow groups:

1. All seven live tabs.
2. Start/pause, step, all four speeds, new-run submit/cancel, welcome dismissal.
3. All ten disruption presets and four board shortcuts.
4. All thirteen scenario fields, timed recovery, independent schedules, restore
   defaults and invalid-duration feedback.
5. Incoming filters, expansion and freeze; network filters; all eight chart
   modes, hover and resize; forecast selector and benchmark display.
6. Wait, full, half, delay and reject; review close/Escape; clock locking and
   restoration; comparison and execution requests.
7. Ledger controls, event export and workbench link.
8. All six workbench tabs, shortcuts, refresh, forecast and inventory filters.
9. Template download, JSON/CSV validation, confirmed import, malformed input,
   preview invalidation, external-feed button and live/workbench isolation.
10. Workbench approve/reject/cancel and scenario replay.

The test adapts canvas, dialog and download platform functions. File selection
uses supplied test File-like objects and bypasses native file-required checking.
It does not verify actual browser rendering, layout, focus trapping, native file
pickers, download saving, responsive appearance or accessibility. No graphical
browser was available for this audit. External feed checks run without API keys;
successful third-party integration remains unverified. Tests never advance the
user's saved company database.

Run with Python 3 and Node dependencies installed:

```powershell
python -B -m unittest discover -s tests -q
python -B scripts/export_live_fixture.py
npm.cmd run test:ui
# Set PYTHON to your Python executable if `python` is unavailable.
node scripts/audit_ui.cjs
python -B scripts/benchmark_forecasts.py --days 28 --seeds 101,202 --cases normal,viral,compound
```

## Remaining modeling limitations

- This is a synthetic, rule-driven simulator. Forecasts influence stock cover,
  recommendations and allocation; the model does not choose the action menu or
  independently authorize purchases. Human choices execute deterministic rules.
- Better prediction does not guarantee better contribution. The paired benchmark
  compares four methods under one declared approval policy, three scenario
  families and two seeds. Its 28-day window is insufficient to validate
  long-term expiry behavior or establish company ROI.
- Trained forecasts cover 14 days. Longer action comparisons extrapolate the last
  horizon; their apparent numerical precision is not calibrated certainty.
  Known recovery schedules alter projected operating conditions, but projected
  demand remains the frozen forecast curve; it is not a causal weather or
  marketing response model that anticipates every scheduled demand recovery.
- Transfers use deterministic greedy allocation, not a globally optimal network
  plan. Supply proposals are alternatives, not a jointly optimized purchase plan.
- Later approvals affect realized results against earlier references. Those
  differences are explicitly flagged and cannot be attributed solely to the
  original action. References share forecast updates when their feeds are
  available, and freeze observations during their own feed outages.
- Goods receipts and sales settle within discrete simulation intervals. Exact
  intraday arrival/order sequencing is approximate. Changing tick speed also
  changes stochastic request batches, so speeds do not reproduce identical paths.
- Realized contribution is simulated accounting, not audited profit or actual
  dispatch. The operations workbench and live sandbox intentionally have separate
  data and decision effects.

These limitations should remain visible when demonstrating or interpreting the
application; they are not evidence of autonomous production readiness.
