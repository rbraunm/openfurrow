# 0003 - Missing-data policy

**Status:** Accepted. The reject is the default of the setting `analysis.missingPlots`
(decision 0035); the least-squares path and Yates' estimates named below are built
(decision 0043).

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

Missing data is therefore a first-class use case, not a permanent limitation. The
missing-data scenarios are encoded as tests, so the behavior is verified per pattern.

## Decision

- **By default** (`analysis.missingPlots` = `refuse`) any missing observation cell makes
  the analysis **reject with a loud error that names every missing plot x assessment
  cell**. No silent imputation, no silent fallback. This is the exact, auditable baseline.
- **By choice** (`leastSquares`): transparent, reproducible least-squares adjusted means
  (matching the ARM/SAS GLM result for the math), **plus** an explicit **estimability check
  that fails loud with the specific reason** when the missing pattern makes effects
  non-estimable (improving on a bare `na`), **plus** a recorded, reproducible account of
  which cells were missing and how they were handled. Yates' missing-plot estimation is
  the opt-in classical mode (`estimate`).
- Built for the single-factor RCBD and the completely randomized design, as decision 0043
  records with every statistical choice: `openfurrow/analysis/rcbd.py` and `crd.py` apply
  the policy, `leastSquares.py` fits and checks estimability, `yates.py` estimates, and
  `missingPlots.py` holds the policy and the record. Every other design refuses a missing
  cell under every policy.
- The differentiator versus ARM is auditability, reproducibility, and estimability clarity,
  consistent with the mission -- not a claim that ARM lacks the statistics.

### Missing-data test matrix

Encoded in `tests/testMissingPlots.py`. Fixtures derive from `stirret.borers` by removing
cells in each pattern (see `roadmap/research/test-data.md`). In a single-factor RCBD a
treatment has one plot in each block, so M3 is one cell, the untreated control's.

| Case | Pattern | Under `refuse` | Under `leastSquares` or `estimate` |
|------|---------|----------------|------------------------------------|
| M1 | one missing cell | reject, naming the cell | adjusted means; result flagged as adjusted |
| M2 | several scattered missing cells (still estimable) | reject, listing all | adjusted means |
| M3 | a whole treatment absent from one block (present in others) | reject, naming the cell | adjusted means (still estimable) |
| M4 | non-estimable: a treatment absent from every block, a whole block absent, a disconnected design, or residual df exhausted | reject, naming the cells | **fail loud as non-estimable with the specific reason -- never produce numbers** |
| M5 | complete table (control) | analyze normally | analyze normally |

## Consequences

- Results under the default are exact and unambiguous; an incomplete table can never
  produce a silently wrong analysis, and under either method it is analysed only by an
  owned, recorded choice.
- The matrix holds the implementation to the fail-loud-on-non-estimable guarantee (M4).
- The Type I/III choice is made, and labelled in the output, by decision 0043.
- OpenFurrow's missing-data handling is auditable and reproducible where ARM's is opaque
  -- the honest differentiator.
