# Operational system and evidence boundaries

This implementation is a runnable vertical slice of the Pulp Riot control tower. It keeps Demand and Inventory as the two deep modules while checking capacity, ingredients, depot movement and the sole supplier road. It is explicit about what is observed, estimated and approved.

## Data flow

`source record → schema/unit/date validation → versioned SQLite record → current plan → risk/recommendation → exact-version human decision → audit`.

SKU recipes, depot weights and channel acceptance rules can be uploaded as master records. Shares must sum to one after each batch of master edits. Order feeds, warehouse lot snapshots, production commitments, in-transit shipments, plant availability, raw batches and supplier receipts have separate record types. A committed production or in-transit shipment contributes to a receiver's projected supply only until the receiving warehouse reports it as a physical lot. Data owners must update its status to `COMPLETED`/`RECEIVED` when the lot is ingested; the application does not silently create warehouse stock from an ETA.

The web client uses the Python API as the sole calculation source. A one-minute refresh displays newly imported inputs. Files can be validated without a database write, inspected, then imported. Optional public feeds poll every 15 minutes when credentials and verified source identifiers exist. Neither feed executes a logistics action.

Orders have separate requested and fulfilled quantities. Multiple transaction IDs for one day are aggregated. Valid requested orders are used to detect demand even when stock has suppressed fulfillment. Two consecutive observed days above 1.5 times a median earlier baseline create a demand-shift alert; the last two order days become its conservative floor. Missing observations do not count as zero. With fewer than five older in-stock days, the case-mix baseline is used and identified as a sample assumption. The 1.5 threshold is a starting policy requiring shadow-run calibration.

The optional trained demand model pools SKU/depot/channel series. For each 1–14-day horizon it uses only the 14 observed daily values available at prediction time, a weekday encoding and the horizon. Training purges split-crossing windows, fitting on older dates, validating on the next 28 days and holding out the final 42 days. The model must beat both trailing-week baselines on validation by at least 2% relative WAPE to activate. The exported JSON trees run without scikit-learn on the server; an export parity check tests identical predictions. Only a matching sample/real provenance, complete 14-day history and a current-as-of date activate it. The planner uses the mean of days 1–7 for daily network calculations and shows all 14 dates in the UI. A two-day observed viral spike remains a floor while the shock is investigated. Per-horizon ranges are the 90th percentile of validation absolute errors on the normalized scale; these are empirical and can fail under drift. The shipped synthetic test WAPE is 21.973%; it is **not real demand accuracy**. Real-data retraining must preserve requested orders, not only fulfilled sales.

Physical stock is held by batch with manufacture and expiry dates. A transfer proposal checks the same SKU, arrival in four days (conservative end of the case's 2–4-day range), and at least 60 days of life remaining at that arrival for MT/QC. A separate GT-only action can use aging stock with at least seven days of life at arrival, but requires a verified distributor order and buyer acceptance. Donors keep a ten-day projected floor after transit; recipients seek fourteen days after arrival. These are business policy choices, not case facts. Exact batch, reservations and carrier details require revalidation before release. The prototype never releases an order.

Raw-material requirements use per-bottle recipes. **All recipes in the sample are synthetic** because the case provides no bill of materials. A production authorization cannot rely on them until Procurement and the plants replace them with approved values. Confirmed inbound receipts contribute to a 14-day balance. A confirmed closure removes road receipts for passionfruit from that projected balance. A 24-day passionfruit stress target combines a 21-day closure and three-day normal road receipt lead. It is a scenario target conditional on storage and working-capital feasibility, not an automatic purchase instruction.

Capacity uses 2.5 crore bottles per 28-day modeling month. This period assumption is explicit because the case's 95% utilization and 9.6 crore summer volume are rounded. Co-packer availability is reported only after 14 days' notice, up to 10% additional capacity; the 25% premium cannot be monetized without the true in-house unit cost. Where the material position is unknown, the system flags the data gap instead of asserting production feasibility.

## Public feeds

TomTom's incident category 8 denotes a road closure. The adapter queries a supplied bounding box and produces a watch. The case's only approved cooperative road remains the only road in the plan; neither a map detour nor an incident outside that road becomes an operational route decision. Human logistics confirmation supplies `CONFIRMED_CLOSED`. Route reports older than one day become `UNKNOWN`. A freight recommendation requires confirmed closure, insufficient pulp cover and a current, cold-chain-confirmed quote. Without a quote the action is to request one.

The YouTube adapter monitors campaign-verified video IDs. Three observations with a positive earlier interval can flag view-growth acceleration; the growth comparison is normalized by observation interval so a short poll interval does not look like a sudden trend by itself. This is attention evidence; daily bottle demand changes only on the basis of operational orders. API errors are stored as `UNKNOWN` and shown in data health. No scraping or unapproved social account access is required.

## Replay

`engine/replay.py` runs two policies on identical deterministic orders. The synthetic event clock starts 2026-03-01; a 14-day QC spike starts at day 15, with the second-day order alert at day 16. The single cooperative road closes at day 64 for 21 days; ordinary road receipts resume three days later. Both policies use the same Python planner at decision points with trained inference disabled to avoid future-data leakage. The proposed policy assumes immediate approvals, eligible four-day transfers, extra in-house output when feasible, and a pre-season 24-day pulp buffer. The historical-style policy continues static allocation and a 14-day pulp buffer.

The comparison reports fulfilled and unfulfilled bottles, write-offs, transfer units/cost and timeline. It does **not** reproduce the known case-wide 8% revenue loss or ₹6 crore write-off/discount figure: daily orders, recipe, batch ages, production-to-depot transit and local shares are synthetic. It therefore does **not** estimate actual Pulp Riot savings. Funding for the extra pulp buffer, cold storage and inventory holding must be estimated before using an ROI claim. The replay's deterministic results are useful to verify causal behavior and catch physically impossible advice.

## Remaining production integration gates

The working local service still needs these real-company inputs and controls before acting as a shared production system:

1. Approved SKU recipes, depot/customer masters, actual stock batches, supplier contract/quote data and exact approved road geometry.
2. Written feed agreements for QC, distributor orders, warehouse, plants and suppliers. Confirm each feed's latency, schema, corrections and ownership.
3. Authenticated company identities and roles, a managed database with tested backup/restore, worker monitoring, encrypted transport, and an authorized execution system. The current decision log records a claimed user but does not issue instructions.
4. A two-depot shadow run measuring service, forecast calibration, stale feeds, false alerts, expiry acceptance and planner workload before expanding to all nine depots.
5. Vendor quotations and a full first-year budget within ₹2.5 crore, including integrations, external-source charges, training, support, storage and any chosen extra stock or freight measure.

An eight-month rollout can use months 1–2 for data contracts/master correction, months 3–4 for shadow running, months 5–6 for a two-depot controlled pilot and disruption rehearsals, and months 7–8 for broader monitored operation after acceptance gates pass.
