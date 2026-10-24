# Pulp Riot — Demand × Inventory Control Tower (legacy model notes)

The current operational application is documented in [PRODUCTION_SYSTEM.md](PRODUCTION_SYSTEM.md) and run with `py -3 server.py --demo`. This document describes the original offline model. Its references to a deck, workbook, and builder scripts are historical plans; those artifacts are not present in this repository.

## Files

- **Pulp_Riot_10_Slide_Case_Deck.pptx** — 10-slide jury presentation, with opening and closing.
- **Pulp_Riot_Live_Demo.html** — offline interactive dashboard. Open in Chrome/Edge. Change QC, closure, or pulp-cover inputs and watch the risks update. Use the Pending/Approved/Rejected controls to demonstrate a human veto. Approvals are *demo-only, in-browser*; **they do not place orders or dispatch freight**.
- **Pulp_Riot_Control_Tower.xlsx** — formula-driven workbook. Start with **READ ME**, change **Controls** B5 (QC), B6 (closure), B7 (pulp cover), and inspect **Depot Watch**, **Five-Area Radar**, **Replay**, and **Approvals**. Approval statuses in this sample are editable, but no execution connector exists.
- **pulp_riot_model.py** — runnable reference decision engine using only Python standard library. On each run generates updated **depot_flavor_sample.csv**, **proposed_transfers.csv**, **alerts_and_approvals.csv**, and **replay_results.json**.
- **build_workbook.py** / **build_deck.js** — source build scripts for reproducibility. Workbook builder needs `artifact_tool`; deck builder needs `pptxgenjs`.

## Fast demo (90 seconds)

1. Open the HTML control tower. State that **Demand and Inventory** are the two deep modules; Supply, Distribution, and Transportation form an operational risk perimeter.
2. Show the **4×** QC order signal leading to **4.32 lakh** incremental Dragon Passion bottles/week and **1.82 lakh** beyond available in-house capacity slack/week (illustrative all-depot interpretation).
3. Point to **4 service-critical** and **12 age-watch** depot–flavor rows, then show the costed, approval-gated inventory transfer recommendation.
4. Press **No viral spike**; Demand-linked red positions disappear. Press **Last summer** to restore them.
5. Press **3-week pulp buffer**; the **within-closure** exposure falls from **1 unprotected week to 0**. Stress this ignores a further normal 3-day inbound road transit after reopening; a full safeguard may require **24 days** of cover, conditional on cold-storage and funding validation.
6. Show the approval queue. Explain that no stock is shipped by the prototype.

## Calculation checks

| Quantity | Formula | Case-grounded result |
|---|---|---:|
| Summer revenue | ₹1,200 crore × 48% | ₹576 crore |
| Summer bottle volume | ₹576 crore / ₹60 per bottle | 9.6 crore bottles |
| Case-wide stock-out revenue loss | ₹576 crore × 8% | ₹46.08 crore |
| Contribution opportunity, not guaranteed recovery | ₹46.08 crore × 32% | ₹14.7456 crore |
| Dragon Passion average weekly baseline | 9.6 crore × 12% / 16 modeled weeks | 7.20 lakh bottles |
| Viral QC uplift, stress interpretation | 7.20 lakh × 20% QC share × (4−1) | 4.32 lakh extra/week |
| Assumed plant capacity slack/week | 2.5 crore / 4 weeks − 9.6 crore / 16 weeks | 2.50 lakh bottles |
| Viral capacity deficit before SKU trade-offs | MAX(0, 4.32 − 2.50 lakh) | 1.82 lakh bottles/week |
| Pulp exposure with only-road closure | MAX(0, 3 weeks road closed − 2 weeks pulp cover) | 1 week of **time exposure** |
| Buyer freshness window | 90-day bottled shelf life − 60-day minimum remaining | 30 days from bottling, at receipt |
| Illustrative donor transfers | Same flavor; donor cover >14d and receiver cover <14d; 1,000-bottle lot | 101,000 Dragon Passion bottles |
| Transfer cost | 101,000 × ₹1.50 | ₹1,51,500 |
| Break-even vs stockout contribution alone | ₹2.42 crore / ₹14.7456 crore | 16.4% recovery threshold |

**Do not add ₹46.08 crore lost revenue, ₹14.75 crore lost contribution, ₹6 crore write-offs and ₹3.2 crore freight spend as if mutually exclusive losses.** Revenue and contribution are alternate views of the same stock-outs. The case does not provide a causal loss split by module. The ₹3.2 crore air-freight payment at five times normal price implies a possible **₹2.56 crore incremental freight premium if the same volume would otherwise have moved by road**, not necessarily a realizable saving.

## Synthetic sample data / limitations

The case does not give any SKU-by-depot history, source recipe BOM, SKU-age batches, cold-storage ceiling, number of imported shipments, GT outlet sell-through, or actual daily demand trace. The 45 model rows therefore use **explicit synthetic** choices:

- Summer weeks = 16 equally sized modeling periods (a convenient approximation, not a claim that March–June has exactly 16 calendar weeks).
- All 9 depots are given illustrative demand shares: Delhi 13%, Jaipur 9%, Mumbai 16%, Pune 12%, Ahmedabad 8%, Bengaluru 16%, Chennai 12%, Kolkata 8%, Bhubaneswar 6%.
- The national QC multiplier is 4×. Spatial heterogeneity is synthetic: 5× in D1/D3/D4/D6; ~2.674× elsewhere, weighted exactly 4×. For QC multiplier 1×, all depots have 1×.
- The 3-week initial stock target is extended to the new Dragon Passion launch purely for comparison; the case has no actual opening stock quantity for that launch.
- Mango Peach Basil / Guava Chilli demand is synthetically 30% above old mix in D1/D3/D6, 35% below in D8/D9, with the remainder normalized so the national flavor total does not change.
- Opening bottle age = 7 days only for freshness screening. The modeled ~4.49 lakh MT/QC age-exposed bottles are **not the observed write-off quantity or monetary cost**.
- Inventory transfers are preliminary suggestions; no route carrier rate other than ₹1.50/bottle is assumed. Moves take 2–4 days. Each recommendation still needs donor, receiver, buyer, ETA, production age and handling validation.
- Pulp gap is given **in weeks**, not fabricated kilograms or bottles: the case does not give passionfruit-per-bottle formulation.
- Four-week model months are simplifying; production capacity and 95% utilization and actual 9.6 crore summer bottles are rounded case figures and differ slightly.

## Rules and root-cause bridge

**Demand → Inventory:** Viral QC growth is visible in platform daily reports but not the month-end planning dataset; fixed baseline depots and monthly allocations delay replenishment. Rule: two consecutive days >1.5× baseline produce a *pending* anomaly alert, confirmation prompt, and 2-week flavor/depot/channel projection; do not confuse selling-out with low demand.

**Inventory → Demand:** Understocked depots and aged, unsellable channel inventory suppress recorded sales and feedback into the forecast as false low demand. Rule: compute forward service cover using an uncensored proxy (on-hand + actual orders + unavailable/SKU stockout flag); separately flag receiving-age eligibility. Donors and receivers are balanced *within a flavor*, not substituted across flavors.

**Supply:** Track cooperative supply dependency, raw-pulp cover, source lead, domestic/import dragon split (60/40), quarterly orders and import lead of 6–8 weeks. Three of five summers had >=1-week road closures; that is a history-based contingency signal, **not a calibrated probability of a three-week event**. Confirm physically possible buffer before accepting the proposal.

**Production:** Two in-house plants are fixed at 2.5 crore bottles/month in summer; do not assume adding a line. Co-packer has up to 10% extra capacity, needs two weeks’ notice and costs 25% more than in-house production per bottle. CFO/COO approve a mix substitution only after examining service, stock age and contribution economics.

**Distribution:** 9 depots and 4 regions; stale weekly spreadsheet files receive a missing-feed flag. Rank same-flavor transfer pairs by receiver risk, donor age, recipient eligibility and ₹1.50/bottle 2–4-day shipment. Manual check required; no automatic transfers.

**Transportation:** There is no alternate cooperative road. A 3-week interruption vs 2-week raw-pulp cover is at least a 1-week within-closure exposure, potentially followed by 3 days of ordinary road receipt lead. Validate buffer for 3 weeks + 3 days (24 days) and prebuild stock and contingency source. If incomplete, approve *targeted* air cargo after cost/service trade-off, not indiscriminate air freight.

## Human approvals and 8-month plan

Each risk action has a named accountable approver. Marketing/Sales validate promotions and order signals; Planning/Regional Sales authorize demand forecast changes; Distribution authorizes transfers; Procurement validates pulp cover and import timing; COO/Finance decide mix, co-packer premium and exceptional freight. An approval is a recorded event; this prototype cannot dispatch a purchase or transfer order.

| Month | Gate |
|---|---|
| M1–2 | SKU/depot master, case historical files, ingestion contracts, vendor and business owner |
| M3–4 | Daily QC feed, GT order proxy, freshness and stockout-censor tests; manual CSV fallback |
| M5–6 | Controlled 2-depot pilot; W3 viral and W10 closure game days; user feedback integrated |
| M7–8 | Expand to 9 depots; vendor-run monitored operation; go-live with 95% data timeliness / all human sign-offs |

### First-year cost (₹ crore)

| Item | Type | Amount |
|---|---|---:|
| Source adapters and data QA/UAT | Build | 0.42 |
| Explainable rules engine + UI/approvals | Build | 0.45 |
| Security, integration testing | Build | 0.30 |
| Planner training / operating-change sessions | Build | 0.18 |
| Source-qualification pilot workflows | Build | 0.15 |
| Managed hosting, monitoring | Run | 0.22 |
| Vendor IT support, data feed incident response | Run | 0.38 |
| Operational test reserve, handling and contingency | Run | 0.32 |
| **TOTAL** | **Build 1.50 + run 0.92** | **2.42** |

₹0.08 crore below the ₹2.50 crore ceiling. This is a **proposed vendor price cap**, not an actual quotation. It covers prototype-to-production software and first-year running costs; extraordinary fresh-pulp purchases, unpriced cold-storage expansion or material working capital must be reviewed against existing operations budgets and approved separately **before adoption**, rather than hidden in software ROI.

## Scenarios and tests

```bash
python pulp_riot_model.py --test
python pulp_riot_model.py --qc-multiplier 4 --closure-weeks 3 --pulp-cover-weeks 2
python pulp_riot_model.py --qc-multiplier 1 --closure-weeks 2 --pulp-cover-weeks 2 --out ./normal_test
```

Success tests: a QC spike triggers within 2 validated days; depot under-cover and age watches correctly react; closure 3/2 flags 1 week during closure while 2/2 flags none during closure (both still need a 3-day inbound receipt check); increased shock may exceed fixed in-house capacity; every proposed decision defaults to `PENDING`; a stale feed is flagged instead of interpreted as zero orders in the full-rollout acceptance test. The current offline prototype computes scenario risks; it does not yet ingest live APIs or maintain transaction audit history.

## Questions judges may ask

- **Why not pick Supply + Transportation?** They share the same highway risk. But Demand + Inventory show the two-way self-reinforcing failure that the planning operating system can address on *every* flavor and depot, while supply/transport remain mandatory constraints.
- **Can a model guarantee availability?** No. It alerts when physical cover, fixed factory capacity or lead time makes a request infeasible. It may recommend rationing or accepting a stock-out rather than promising an impossible delivery.
- **Is the savings target proved?** No. As an illustrative threshold, recapturing >16.4% of the case's last-summer lost contribution would cover the proposed ₹2.42 crore program price before additional execution costs. Holdout depots and approval audit results determine actual benefit.
- **Why no heavyweight ML?** 30% forecast error, new flavor cold-start, 15 Excel planners and two prior failed pilots favor transparent ratios, freshness buckets and source reliability checks. Upgrade only after labeled actuals and feed timeliness are established.
- **What about the 60/40 dragonfruit sourcing mix?** Risk scoring tracks quarterly imports and 6–8-week replenishment; a two-week viral uplift cannot magically fix import shortages. The approval queue prioritizes confirmed pulp availability before schedule change.
