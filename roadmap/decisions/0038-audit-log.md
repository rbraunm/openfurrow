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
  Read at the server it is every event; at a place the place's own, those of the places
  inside it and of the trials in them; at a trial the trial's. The web interface's audit
  page shows it newest first, a page at a time, narrowed by who acted, the action (or its
  beginning), where and the days (UTC).
- **The tool never updates an event.** The audit log is outside the trial's content hash;
  how long it is kept is a retention setting, and an event leaves only when that rule lets
  it go (decision 0044).

## Consequences

- Imported values are counted, not listed, in the event, which names the file as received
  that holds them (decision 0044).
