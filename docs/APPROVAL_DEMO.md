# Approval persistence in the offline demo

The dashboard in `web/index.html` now stores simulated approval choices and a history of decision events in browser `localStorage`.

## Try it

1. Open `web/index.html` in VS Code Live Server or a browser.
2. In **Human approval queue**, approve one proposed recommendation.
3. Refresh the page; its demo state remains saved in this browser.
4. Select **Export decision history (CSV)** to download audit events.
5. Change the QC multiplier. Prior approvals are automatically invalidated, with the invalidation recorded in the audit history.
6. Select **Last summer** to reset the original scenario and approval states.

## Safety and scope

This is a **single-browser demonstration**, not secure multi-user approval storage. Browser data can be cleared or edited by the operator; timestamps and user identity are not authenticated. No external action is performed, and no freight, stock transfer or purchasing instruction is sent to any service.

Production implementation should place immutable approval events in a transactional database, bind each approval to a versioned recommendation and a verified user identity, enforce roles, and re-check availability/expiry/capacity immediately before execution.
