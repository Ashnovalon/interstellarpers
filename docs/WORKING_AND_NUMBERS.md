# How the live app works, and how to interpret its numbers

## Using the revised interface

Start a fresh run if the old one reached day 112. Start live, or keep the clock paused and inject a disruption: the studio produces one affected batch immediately while paused. A manual change cancels remaining guided surprises and hands control to the operator. The confirmation banner names the changed parameters and links to Incoming data.

Incoming data shows 135 series per batch: five flavors × nine depots × three channels. Filter Dragon Passion / QC to inspect an attention event. Expand a record to see every generator factor and its exact calculation. Freeze table holds that batch for inspection while the business keeps running. Stopped-feed records are explicitly marked hidden audit truth; the forecaster does not receive them.

Click Compare & decide to pause the server clock automatically. Each available comparison card is selectable. Choose one, enter an operator name and reason, confirm operational checks for an intervention, then submit. Closing without a decision restores the previous running/paused state. A minimum ten-tick review window gives roughly ten wall-clock seconds before opening; the clock stays paused indefinitely once the review opens. Physical stockout urgency is separate: extra review time does not reverse stockouts already incurred.

Wait records a deliberate no-action decision without spending money or moving stock. Full and half execute the chosen amount. Delayed action reserves cash now, revalidates stock, freshness and budget after two business days, then executes or records a clear failure and releases its reservation. An already infeasible branch is disabled with its reason. Non-quantity actions have three paths because half a repair or half a QA release is not meaningful.

## Where input values come from

The case gives the national summer quantity, flavor shares, channel shares, capacity and logistics constraints. It does not supply actual transactions, recipes, batch ages, warehouse coordinates or local depot shares. Those are declared synthetic assumptions.

For each flavor/depot/channel:

`baseline bottles/day = 96,000,000 / 112 × flavor share × depot share × channel share`

The generator then multiplies this rate by spatial redistribution, converted attention, weather, competitor pressure, a small channel-specific calendar component, seeded network/regional/product demand regimes and local noise. The correlated regimes move in both directions and prevent 135 independent noise terms from averaging into an almost identical weekly curve. They are stress-test behavior, not observed company history.

`requested this batch = round(generated daily rate × interval days)`

At the default speed one second represents six business hours, so interval days = 0.25. Fulfillment is determined from actual eligible stock after receipts and expiry checks. It cannot exceed requested quantity. MT/QC require 60 days remaining; GT is distributor demand and does not invent outlet observations.

The old fast/slow-depot redistribution used an incorrect residual factor of 0.964. With fast depots representing 45% and slow depots 14%, the correct residual is:

`(1 − 1.30 × 0.45 − 0.65 × 0.14) / 0.41 = 0.7902439024`

This preserves national volume when redistributing it: `1.30 × 0.45 + 0.65 × 0.14 + 0.7902439024 × 0.41 = 1`. The old factor inflated the two affected flavors' demand by 7.124%. This numerical issue is corrected and tested. Other scenario factors deliberately change national demand.

The exact original model-training data is in `data/training/synthetic_orders.csv` (40,500 daily rows, 300 days × 135 series). Runtime event inputs are generated on the server, stored in SQLite `live_events`, and exportable. New runs use generator version `v2-correlated`; older event logs retain their historical observations.

## What the forecasting model receives and produces

The trained model is gradient-boosted decision trees, not deep learning. It consumes 14 complete observed days of requested orders, normalized lag values for days 1/2/3/7/14, rolling means, volatility, recent-versus-earlier demand, target weekday and forecast horizon. It outputs direct daily-demand estimates for horizons 1–14 for every flavor/depot/channel.

The intraday nowcast consumes only observed requested quantities divided by their actual interval. Its smoothing weight is `1 − exp(−interval_days / 0.65)`. The current demand estimate blends 35% trained estimate with 65% nowcast; future nowcast influence decays over four days. These are starting calibration choices. The tree weights do not retrain every second. Complete observed days extend lag history; partial and missing days are not treated as completed zero-demand days.

Attention-to-order conversion is a hidden simulator setting visible in the audit, not a model feature. Attention with zero conversion must not increase the forecast. Feed loss freezes observed demand and marks stock stale while the simulated physical business continues.

The artifact's 21.973% WAPE was measured on held-out synthetic history. It is neither 78% accuracy nor proof of real-company performance. The online table compares daily forecasts saved at day start with completed observed requests, including a separate adaptive score. Current live scenarios are deliberately more varied than training. Real deployment requires independent company periods, segment/horizon evaluation, calibration, drift monitoring and comparison with simpler baselines.

## How recommendations are generated

Forecasting estimates demand; explicit business rules generate actions. Cover is usable stock divided by forecast daily demand. Below 14 days triggers service-risk review. Transfers keep a donor floor after transit and aim to cover the receiver after arrival. Exact batch age, current stock and cash are rechecked at execution. A seven-day allocation approval uses existing finite plant capacity and available ingredients. It cannot create a new production line.

Passionfruit buffer/air decisions compare usable pulp with the 21-day closure plus normal three-day lead. Imported dragonfruit is split 60% domestic / 40% imported with a synthetic six-week lead. Co-packer capacity is limited to 10% extra after 14 days' notice. Maintenance restores installed capacity after two days. Quarantined pulp needs a lab test and a separate QA release. These rules also check the declared first-year funding envelope.

The comparison engine clones the same current network and projects each choice for fourteen days using current forecasts and known conditions. It does not receive future hidden demand or guided surprises. Earlier delayed-transfer projections failed to refresh future warehouse-observation timestamps; that could incorrectly make a delayed transfer appear unavailable. Future projected observations now advance when the feed is available.

## Financial arithmetic and the user's example

Contribution per fulfilled bottle is `₹60 × 32% = ₹19.20`.

`modeled contribution = fulfilled bottles × ₹19.20 − incremental transport/air/co-packer/test/repair/holding costs − modeled write-offs`

This is network operating contribution for the projected period, not net company profit. Buffer working capital is committed separately so ordinary costs are not subtracted twice.

In the quoted example, full action reduces unfilled quantity from 1,515,339 to 1,459,339: 56,000 additional fulfilled bottles. For a 56,000-bottle transfer at the case's ₹1.50/bottle:

| Calculation | Rupees |
|---|---:|
| Additional service contribution: 56,000 × ₹19.20 | 1,075,200 |
| Transfer cost: 56,000 × ₹1.50 | 84,000 |
| Contribution gain versus waiting | 991,200 = ₹9.912 lakh |
| Half quantity gain: 28,000 × (₹19.20 − ₹1.50) | 495,600 = ₹4.956 lakh |

Those round to the displayed ₹9.91 L and ₹4.96 L. ₹24.14 crore and ₹24.24 crore are rounded total 14-day network contribution, while ₹9.91 lakh is their more precise difference; subtracting rounded crore displays can appear inconsistent. Each revised card separates action cash from contribution gain and shows additional fulfillment × ₹19.20 minus extra costs.

Service is `100 × fulfilled / requested`, not a model confidence score. Branches share the same forecast requests and starting state. Tests verify requested = fulfilled + unfulfilled, the service ratio and the financial identity against every branch's underlying quantities.

## Why revenue keeps increasing and charts used to repeat

Cumulative gross revenue is the sum of completed sales. Without returns, it cannot decrease, even if performance deteriorates. It is therefore a poor isolated control-room signal. Cumulative contribution can decrease when costs or losses are recognized, but generally still rises while profitable sales continue.

Use Sales this interval, Contribution this interval and Unfulfilled demand/day to assess deterioration. Interval contribution includes costs paid between ticks, so an emergency action can produce a negative interval. Demand charts show rates, not cumulative sales. The original shared weekly sine and small independent noise largely canceled when aggregated; new correlated demand regimes produce repeatable but less uniform, non-periodic movement. The interface never invents frontend volatility merely to look live.

## Limits

The mathematical identities and constraints can be verified. Forecast accuracy, recipes, commercial prices and supplier availability remain synthetic assumptions. The comparison is conditional and can be wrong when future demand or disruptions differ. No actual freight, order, supplier communication or public traffic observation is executed by this live simulation.
