# 0037 - Roles and permissions, checked in the facade

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Roles must reach every surface and every place of the hierarchy (`governance-plan.md`,
F4). A check written into each web route can be forgotten on the next one.

## Decision

- **Permissions**: view, enterValues, importValues, editRecord, editDesign, manageTrials,
  changeSettings, manageStructure, manageAccess, manageRetention, viewAudit.
- **Roles** are named sets of permissions. Built in: viewer (view), dataCollector (+ enter
  values), analyst (+ import values), trialManager (+ edit the record and the design, manage
  trials, change settings), administrator (all). An organization defines its own; a role
  still given to someone is not deleted.
- **A role is given to an account or a group at a scope** -- the server, a place or a trial
  -- and holds there and below. What an account may do at a scope is the union of the roles
  given to it and its groups along the scope's chain.
- **The facade checks.** Every Workspace method requires its permission at the scope it
  acts on before it touches the store, so no surface can skip it. Lists show only what the
  actor may view; a trial or place the actor cannot view answers "not found", as one that
  does not exist does, so codes cannot be probed. A refused permission is its own error
  (403 on the web and API): the API answers in JSON, a page of the web interface with a
  page in the reader's language that names the permission and where it is missing.

## Consequences

- An account given nothing sees nothing.
- The open mode and the operator hold every permission, so a single-user installation is
  unchanged.
