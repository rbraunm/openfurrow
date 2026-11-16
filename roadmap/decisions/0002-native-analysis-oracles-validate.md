# 0002 - Native analysis; oracles validate, they do not compute

**Status:** Accepted -- **Locked**. (Locked means an extra are-you-sure step before
reversal, never immutability; the record stays reviewable.)

## Context

The analysis math -- the RCBD ANOVA and the mean-separation tests -- has mature
implementations: statsmodels (Python, BSD), R's `stats` and `agricolae` (GPL), SAS, and
ARM itself. Depending on one would be the fast way to get an AOV Means Table.

The licensing fork is decisive. R and most of CRAN, including `agricolae`, are GPL;
shelling out to R for the core analysis drags copyleft into OpenFurrow's deployment and
reproducibility story. statsmodels is permissively licensed (BSD) and carries no copyleft
risk, but adopting it as the *runtime engine* means OpenFurrow reports a computation it did
not perform and couples its auditability to another library's internals. The mission is to
compute the analysis transparently and reproducibly and to be able to stand behind every
number with its own method on record.

The math here is small and well defined -- sums of squares, degrees of freedom, F, CV, and
the LSD -- so owning it is cheap, unlike a case where reimplementing a large numerical
kernel would be reckless.

## Decision

OpenFurrow **computes its ANOVA and mean separation itself** (numpy at runtime).
statsmodels, `agricolae`, SAS/ARM outputs, and published tables are **opt-in
known-answer oracles** -- and, for statsmodels, a **test-only** dependency -- used to
validate. They are never a runtime dependency of an analysis, never bundled, and never the
step that produces the answer. The runtime stays minimal and permissively licensed; GPL or
R tooling is never pulled into the compute path.

## Why locked

This is a mission-and-licensing decision, not an implementation detail. Reversing it --
adopting an R/GPL engine, or making statsmodels the runtime analyzer -- would change
OpenFurrow's license posture and dissolve the auditability guarantee that the project is
built on. Locking it forces that trade to be made deliberately, not drifted into.

## Consequences

- OpenFurrow installs and runs anywhere Python runs, permissively licensed, with no GPL
  entanglement and no external statistical runtime.
- We carry the cost of implementing the statistics ourselves -- which is the point, and is
  what makes every reported number auditable.
- Oracles can always be wired in as cross-checks (they already are, in the tests); this ADR
  forbids them as *runtime compute*, not as validation.
