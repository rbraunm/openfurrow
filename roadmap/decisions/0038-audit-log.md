# 0038 - The audit log

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

"Who changed a value" (worklist USR-8, decision 0023) needs a who, and EPPO PP 1/181 asks
for changes to the record to be traceable (`governance-plan.md`, F5).

## Decision

- **Every change the facade makes writes an event in the same transaction**, so a change
  cannot be committed without it: when (UTC), who (the account, or everyone, or the
  operator), from which surface (web, api, cli, library), the action, the scope, and the
  detail.
- **The detail says what changed.** Entered values list each plot and subsample with the
  value before and after; a setting gives its value and source before and after; an import
  names the file, the sheet and the number of values; a move names both places.
- **Refused sign-ins are recorded**, with the user name tried and never the password.
- **Reading it needs viewAudit** at the scope read; `openfurrow audit` shows the latest.
- **The tool never updates or deletes an event.** The audit log is outside the trial's
  content hash; how long it is kept is a retention setting (worklist GOV-5).

## Consequences

- Imported values are counted, not listed, in the event; the file as received is kept by
  retention's received-files area (REC-16).
