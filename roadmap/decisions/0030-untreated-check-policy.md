# 0030 - The untreated check is in or out of an analysis by choice

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Whether the untreated check belongs in an assessment's analysis depends on the
assessment. Disease severity on the check is data like any other; percent control or a
rating scored relative to the check is near zero there by construction, and taking it in
inflates the treatment effect and the error alike. The second opinion on the readiness bar
asked for "an explicit policy for the untreated check (in the analysis or only in the
report, never dropped silently)" (worklist USR-3). ARM lets the user choose per assessment.

## Decision

- **Each assessment states `untreatedCheck`**: `included` (the check is one of the
  treatments analysed; the default and the behaviour until now) or `excluded`.
- **Excluded** leaves out the one treatment whose role is `untreatedControl`: the ANOVA, the
  mean separation, the assumption checks and percent control take in the other treatments
  only, and the check's values are not required. The report says that the check is left
  out and gives its mean as recorded.
- **Refused**: excluding without exactly one untreated control; excluding in a split plot or
  a factorial RCBD, whose analysis needs every combination; and Dunnett's test when the
  check is excluded, which the report names in place of the table.

## Consequences

- Schema 0.13.0, store version 13; every trial's content hash changed.
