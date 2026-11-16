# 0025 - Two-factor treatments in randomized complete blocks

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Efficacy and agronomy trials often cross two factors (product by rate, variety by nitrogen)
in ordinary randomized complete blocks. Decision 0020 made factors data for the split plot
and refused them on an RCBD until this analysis existed (worklist USR-10). Gomez and Gomez
(1984), section 3.3, lay the combinations out as an ordinary RCBD and split the treatment
sum of squares into the two factors and their interaction, all tested against one error.

## Decision

- **An RCBD may declare two factors.** Its treatments are then every combination once, as
  for a split plot. More than two factors are refused for now.
- **The layout is the plain RCBD shuffle** over the combinations; nothing changes in the
  randomization.
- **The analysis adds a factorial table** beside the usual RCBD table: replication, factor
  A, factor B, A x B, error, total, each line tested against the error. Each factor's means
  are separated by Fisher's (protected) LSD on that error, and the combination means are
  tabulated. The plain treatment line equals the sum of the three factorial lines.
- **Validated** against Gomez and Gomez Table 3.3 and the steps after Table 3.4, and
  against statsmodels at full precision.

## Consequences

- No schema or store change: the factors and the treatments' levels already exist.
- The book's sums of squares are short by 0.0005 because it subtracts a correction factor
  rounded to 1,474.014 (exactly 1,474.0135), and its F values divide mean squares cut to
  three decimals (its nitrogen F, 68.26, is 68.15 exactly). The tests reproduce the first
  and bound the second.
