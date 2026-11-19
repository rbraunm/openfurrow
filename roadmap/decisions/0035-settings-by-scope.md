# 0035 - Settings by scope

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The owner's direction (2026-11-16): policies such as missing plots, editing and retention
are settings configured per server, study or finer, not rules the project fixes
(`governance-plan.md`, F2). The analysis choices -- significance level and mean comparison
-- lived in the project's YAML file, one value for everything.

## Decision

- **One registry in code** defines every setting: its key, its type, its default, and the
  scopes it may be set at (server, place, trial). The first settings are
  `analysis.significanceLevel` (0.05), `analysis.meanComparison` (protected LSD) and
  `analysis.missingPlots` (refuse; estimate and least squares are decision 0043).
- **Values are stored by scope**: the server, a place (`place:<path>`) or a trial
  (`trial:<code>`). The nearest applies -- the trial, its places from the innermost out, the
  server, then the default -- and each effective value carries where it came from.
- **Refused**: an unknown key, a value outside the setting's type, a scope the setting does
  not allow, a place or trial that does not exist. A trial's and a place's values go when it
  is deleted.
- **The analysis follows the trial's settings.** The workspace reads them for every
  analysis and report; the report's reproducibility block lists each setting, its value
  and where it was set. The pure analysis functions keep explicit parameters.
- **The YAML file keeps the import profile and the service's binding**; an `analysis`
  section is refused. Settings are set with `openfurrow setting set`, read with
  `openfurrow setting show`.

## Consequences

- Who may change a setting is the permission `changeSettings` at the scope it is set at
  (decision 0037). The web interface's settings page shows every setting at a scope chosen
  from the hierarchy, with its value and where that value comes from, and sets and clears
  it there; a setting that takes one of a list is a choice among the registry's values.
- Further policies (editing, retention) enter as settings.
