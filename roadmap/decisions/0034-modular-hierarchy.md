# 0034 - A modular hierarchy of places

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Roles and settings need places to attach to (`governance-plan.md`, F1). Decision 0004
proposed a program / project / study / trial hierarchy. The owner's direction (2026-11-16):
organization, project, study and trial by default, with levels added or removed to simplify
or refine the permission groups -- usable defaults, customization at scale.

## Decision

- **Levels are data.** A store holds an ordered list of levels; a new store has
  organization, project and study. The trial is always the last level and is not listed.
  An administrator replaces the list -- adding a program or a season, removing a project,
  or removing every level so trials stand on their own -- while the store holds no places
  and no trials. Reshaping a populated hierarchy is not built.
- **Places** sit at each level, each below the first inside one place of the level above,
  and are named by their path, the codes from the top joined by `/`
  (`station/fungicides/wheat2025`). A code is letters, digits, `.`, `_` and `-`. Built-in
  levels are named by the message catalog; a custom level names itself.
- **Every trial belongs to one place of the last level**, named when it is added (`--place`
  on the command line, a place picker on the forms, `?place=` on the API), and can be moved.
  A store without levels takes no place.
- **A trial's place is not part of the trial.** It is not in the trial document or its
  content hash: moving a trial, or importing its document into another store's place,
  leaves its hash unchanged.
- Only an empty place is deleted.

## Consequences

- Store version 15.
- Settings (decision 0035) and, next, roles attach to places.
