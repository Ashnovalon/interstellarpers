# Pulp Riot Control Tower

Case-competition prototype for **Demand + Inventory**, with supply, distribution, and transportation guardrails. All 9 depot assignments and local demand weights are **synthetic samples**, not production data.

## Quick start in VS Code

1. Open this folder in VS Code.
2. In the file explorer, open `web/index.html` in a browser (double-click is sufficient); alternatively use the VS Code **Live Server** extension. The page is an offline interactive simulator, not a deployed application.
3. Test the Python model:
   ```bash
   python engine/pulp_riot_model.py --test
   ```
4. Replay the case without overwriting tracked samples:
   ```bash
   python engine/pulp_riot_model.py --qc-multiplier 4 --closure-weeks 3 --pulp-cover-weeks 2 --out ./output
   ```
   `output/` contains the generated CSV/JSON outputs and can be deleted.

## Current behavior

- Editable viral QC multiplier, road closure duration, passionfruit cover
- 45 depot-flavor positions and stock-cover alerts
- Capacity headroom and road risk calculations
- In-memory human approval choices (reset on refresh)
- Python same-flavor transfer recommendations and pending approvals

## Important limitations

- **Not** connected to live retailer, warehouse, supplier, or GitHub data.
- Website approval states are **not persisted** and dispatches never execute.
- The offline HTML and Python model are separate implementations; spreadsheet and CSV outputs are not bidirectionally synced to the webpage.
- No actual ingredient BOM, depot batch ages, user authentication, or demand-estimation accuracy claims.

## Next engineering milestone

Build the multi-user app in `frontend/` (React/TypeScript) and `backend/` (FastAPI/PostgreSQL), making the Python engine the single calculation source. Add secure auth, CSV ingestion, batch-expiry validation, action IDs, approval audit log and REST APIs. Keep every recommendation in pending state until a named authorized human approves it. Retain the web demo as a reference during migration.

See `docs/MODEL_LOGIC.md` for case assumptions and equations.
