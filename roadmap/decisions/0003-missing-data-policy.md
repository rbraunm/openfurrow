# 0003 - Missing-data policy

**Status:** Accepted (the MVP behavior). Reversible -- the MVP reject is a stopgap that
matures into the least-squares path below.

## Context

Classical RCBD ANOVA assumes a complete table -- one observation per plot x assessment
cell. Real trials lose plots to weather, pests, and recording errors, so missing cells are
normal, not exceptional. Three routes exist:

- **Reject** and require complete data. Exact and unambiguous, but refuses real data.
- **Yates' missing-plot estimation.** Classical: estimate the missing value to minimize
  error SS, analyze as complete, reduce total and error df by the count of missing values,
  leave treatment SS slightly biased.
- **Least-squares / GLM adjusted means.** What ARM and SAS GLM do; handles imbalance, but
  Type I vs Type III sums of squares diverge under missing data, so "the ANOVA" becomes a
  modeling choice.

We checked what ARM actually does, because the question was whether there is a coverage gap
to fill. There is not a *functional* one: ARM runs a least-squares analysis (SAS GLM-style)
and prints adjusted means for unbalanced/missing data, and in degenerate cases it refuses
outright -- when the error mean square is zero it shows `na` and performs no analysis. Its
statistics are sound.

The real opening is the project's own thesis. ARM's adjustment is correct but **opaque and
locked in a proprietary format**, and its non-analyzable signal is a bare `na`. OpenFurrow
can do the same math while emitting an **auditable, reproducible record** of which cells
were missing and how they were handled, and **fail loud with a clear, specific reason** on
non-estimable patterns instead of a terse code. The differentiator is transparency,
reproducibility, and estimability clarity -- not a statistic ARM lacks.

Missing data is therefore a first-class use case that still needs a working solution; it is
not a permanent limitation. We want the missing-data scenarios encoded as tests now, so the
MVP's behavior is verified per pattern and the future solution has concrete targets.

## Decision

- **MVP:** any missing observation cell makes the analysis **reject with a loud error that
  names every missing plot x assessment cell**. No silent imputation, no silent fallback.
  This is the exact, auditable baseline.
- Missing-data handling is on the roadmap as a first-class, tested use case. The patterns
  below are encoded as tests now; for the MVP each missing-data case rejects loud, and the
  matrix records the behavior the future solution must produce.
- **Future solution:** transparent, reproducible least-squares adjusted means (matching the
  ARM/SAS GLM result for the math), **plus** an explicit **estimability check that fails
  loud with the specific reason** when the missing pattern makes effects non-estimable
  (improving on a bare `na`), **plus** a recorded, reproducible account of which cells were
  missing and how they were handled. Yates' missing-plot stays available as an opt-in
  classical mode.
- The differentiator versus ARM is auditability, reproducibility, and estimability clarity,
  consistent with the mission -- not a claim that ARM lacks the statistics.

### Missing-data test matrix

Encoded now. For the MVP every missing-data case rejects loud; the future column is the
target the eventual implementation must hit. Fixtures derive from `stirret.borers` by
removing cells in each pattern (see `roadmap/research/test-data.md`).

| Case | Pattern | MVP behavior | Future behavior |
|------|---------|--------------|-----------------|
| M1 | one missing cell | reject, naming the cell | LS-adjusted means; result flagged as adjusted |
| M2 | several scattered missing cells (still estimable) | reject, listing all | LS-adjusted means |
| M3 | a whole treatment absent from one block (present in others) | reject, naming the cell | LS-adjusted means (still estimable) |
| M4 | non-estimable: a treatment absent from every block, a whole block absent, or residual df exhausted | reject, naming the cause | **fail loud as non-estimable with the specific reason -- never produce numbers** |
| M5 | complete table (control) | analyze normally | analyze normally |

## Consequences

- MVP results are exact and unambiguous; an incomplete table can never produce a silently
  wrong analysis.
- The matrix gives the future implementation concrete targets, and locks in the
  fail-loud-on-non-estimable guarantee (M4) from the start rather than bolting it on later.
- We defer the Type I/III modeling work, but it is recorded, not forgotten.
- When built, OpenFurrow's missing-data handling is auditable and reproducible where ARM's
  is opaque -- the honest differentiator.
