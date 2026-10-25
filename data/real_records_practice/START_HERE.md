# Practice the imported-records flow

These files are **synthetic test data**, not actual company records. Each row
retains `synthetic: true`. Use the isolated practice workspace; the normal real
workspace rejects these labels. Your original synthetic simulation is independent.

## Open practice mode

In PowerShell, from `C:\Users\srini\Downloads\interstellarpers`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_real_records.ps1 -Practice
```

Open **http://127.0.0.1:3020/operations/real**. You should see **Practice workspace**
and a practice-mode notice. Starting practice pauses the real-record containers
to conserve this machine's RAM. Both databases persist in different volumes.
The original application at port 8765 and its synthetic simulation are unchanged.

## Where to upload the files

Choose **Import records** in the practice dashboard. For each file below:

1. Select its **Record type** from the dropdown.
2. Set **Source name** to `synthetic-practice-pack`.
3. Select the JSON file from this folder. The files are already in the right
   project folder; do not copy them into a database or code directory.
4. Click **Preview and validate** and inspect the rows.
5. Tick the practice-data acknowledgment and click **Import validated records**.

| Order | File | Record type | Rows |
|---|---|---|---:|
| 1 | `01_channel_master.json` | `channel_master` | 1 |
| 2 | `02_sku_master.json` | `sku_master` | 1 |
| 3 | `03_depot_master.json` | `depot_master` | 2 |
| 4 | `04_orders.json` | `order` | 42 |
| 5 | `05_finished_batches.json` | `lot` | 2 |
| 6 | `06_raw_material_batches.json` | `material_lot` | 1 |
| 7 | `07_confirmed_inbound.json` | `inbound` | 1 |
| 8 | `08_plant_capacity.json` | `capacity` | 1 |
| 9 | `09_open_route.json` | `route` | 1 |

Those nine files are sufficient for the whole planning/approval test: **52 rows**.
Files 10–13 are optional examples for `production`, `shipment`, `freight_quote`
and `signal`. Importing all files gives **56 rows**. Their planned/cancelled
statuses leave the baseline allocation below unchanged. Quote and attention
records are retained as evidence; this minimal optimizer uses confirmed inbound
supply rather than automatically buying from quotes or converting attention into
demand. The `csv` subfolder contains alternatives: use JSON OR CSV, not both.

## Test the flow and check the result

1. **System health:** wait for all 19 checks to show UP. It can take a minute or
   two for Airflow and Flink to finish their first startup.
2. **Live board:** wait for **Stream current**. The daily forecast should be
   **100 bottles**, with **30 bottles at PRACTICE-N and 70 at PRACTICE-S**.
   The network shows a confirmed open lane from south to north.
3. **History & models → Inspect history:** ClickHouse should show **42 order
   events**, plus the other imports. An Iceberg snapshot ID should appear.
4. **Train and evaluate model:** the pack has 42 consecutive order days, enough
   for lag features and the held-out evaluation. Check the model/run result.
   Constant demand is intentional for predictable tests; a low error here says
   nothing about real forecasting accuracy.
5. **Compare scenarios:** use horizon **7**, demand multiplier **1.25**, delay
   **2**, capacity loss **0.25**. Run comparisons. These charts are aggregate
   supply bounds; the optimizer additionally checks recipes and feasible lanes.
6. **Decision desk:** use horizon **7** and click **Optimize allocation**.
   Keep this first plan PENDING while doing the closure test below.

Expected baseline plan:

| Item | Expected |
|---|---:|
| Seven-day requested demand | 700 bottles |
| Existing stock allocated | 100 bottles |
| Production | 500 bottles |
| Confirmed inbound procurement used | 10 kg |
| Transfer from south to north | 70 bottles |
| Total allocated / unmet | 600 / 100 bottles |

The recipe uses 0.1 kg/bottle: 40 kg on hand plus 10 kg inbound supports 500
new bottles. Capacity alone would permit more, but the pulp constraint binds.

## Test disruption and stale approvals

Do this **before approving** a plan, so there is no outstanding dispatch request.

1. Import `checks/route_closed.json` as **route**. Wait for Stream current.
2. Optimize again for seven days: allocation should fall to **530 bottles**,
   with **no transfer**. The 70 bottles at the south depot are unreachable.
3. Try approving the older open-route plan: it should become **STALE**, because
   its input version changed. No dispatch should be created for that old plan.
4. Import `checks/route_open_again.json` as **route**, wait for Stream current,
   then generate a **new** plan. It should return to **600 bottles**.

## Test approval, reservation and dispatch request

1. Enter your name and a reason, then approve the newest open-route plan.
2. Wait for its status to become **REQUESTED**. A dispatch request with
   **AWAITING_ERP_ADAPTER** should appear. Inspect its payload: `physical_dispatch`
   is `false`; the system has not actually moved goods or placed a supplier order.
3. Generate and approve another plan without reconciling the first. The second
   must become **STALE**; it must not create a duplicate dispatch reservation.
4. To continue testing, enter a reason such as “Practice request cancelled; no
   physical execution” and click **Record reconciled outcome** on the request.
5. Reimport files 05–08 (and optional 10–11 if used) to confirm current physical
   snapshots. Identical content reports **0 changed** but records verification.
   You can then generate and approve the next plan.

## Check rejection, idempotence and forecast outcomes

- Reupload `04_orders.json`: **0 changed**, still 42 orders.
- Preview `checks/invalid_order_rejected.json` as **order**: rejection because
  fulfilled (101) exceeds requested (100); no records should be written.
- For a labeled synthetic next-day monitoring test, first open Live board to save
  a forecast, then import `checks/optional_next_day_outcome.json` as **order**.
  It represents a simulated next day, not an actual observation today. Open
  **History & models → Check observed outcomes**: the saved forecast is 100 and
  the supplied test requested quantity is 120. Do this last; it changes the
  baseline demand used by subsequent planning.

## Dates and returning to real records

The supplied files are dated **2026-10-25**. If testing on a later date, regenerate
them before starting; stale stock/orders intentionally block optimization:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" scripts/generate_real_records_practice.py
```

Return to the real workspace (pauses practice and retains both databases):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_real_records.ps1 -NoBuild
```

Then use http://127.0.0.1:3010/operations/real or Import real records at port 8765.
To stop practice completely while retaining its data:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_real_records.ps1 -Practice
```
