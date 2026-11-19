# 0043 - Missing plots: least squares, Yates' estimates, and what is refused

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Decision 0003 refused any table with a missing plot and named the path to follow: adjusted
means by least squares, an estimability check that says why, Yates' estimates as the
classical option, and a record of what was done. The owner made the policy a setting
(`governance-plan.md`, F2; decision 0035). Decision 0029 left Dunnett's test with unequal
replication open, which only a missing plot brings about.

What the field's tools report was read where it could be. SAS PROC GLM prints sequential
(Type I) and adjusted (Type III) sums of squares and says "Type III sums of squares
correspond to differences between LS-means"; its comparisons of LS-means from unbalanced
data are headed "Tukey-Kramer" (SAS/STAT User's Guide, The GLM Procedure, example
"Unbalanced ANOVA for Two-Way Design with Interaction"). ARM's own documentation of its
unbalanced table could not be read; decision 0003 records that it runs a least-squares
analysis of the SAS GLM kind and prints adjusted means. The classical procedure was read
in Gomez and Gomez (1984), sections 7.1.2.1 and 7.1.2.6.

## Decision

- **`analysis.missingPlots` takes `refuse` (the default), `estimate` or `leastSquares`**, at
  the server, a place or a trial like every analysis setting. An analysis result records
  the policy it ran under and every missing plot with how it was handled, and the report's
  reproducibility block repeats both, so a result does not depend on a setting changed
  since. A plot is missing when it has no recorded value; a value outside a transform's
  domain is still refused as that value, and the plots of an untreated check left out of
  an assessment (decision 0030) are not wanted, so they are not missing.
- **Covered: the single-factor RCBD and the completely randomized design.** A two-factor
  RCBD, a split plot, a trial with untreated checks beside its plots and an assessment that
  takes subsamples refuse a missing plot under every policy, naming the plots and the
  designs that are covered.
- **Estimability comes before any number.** Refused, each with its reason and the plots,
  treatments or blocks concerned: a treatment with no value; a block with no value (means
  adjusted to all blocks of the design cannot be estimated without it); a disconnected
  design, whose plots with values fall into sets sharing no block; and no degrees of
  freedom left for error. Connectedness is found from the plots themselves and checked
  against the rank of the design's indicator matrix. A fit that leaves no residual
  variation is refused as having no error, as a complete table is.
- **Least squares** fits blocks and treatments (treatments alone for a CRD) to the plots
  present, natively with numpy.
  - **Sums of squares are Type III and labelled so**: each term adjusted for the other,
    as the rise in the error sum of squares when the term is dropped. For a single-factor
    RCBD the treatment line, the test that matters, is the same whether sequential with
    blocks first, Type II or Type III; the choice only decides the block line, and Type
    III is the one that goes with adjusted means. The lines then do not add up to the
    total, which the report says. With one factor (the CRD) Type III is the sequential
    sum of squares.
  - **Adjusted means** are the fitted values averaged over every block of the design
    alike. Their covariance matrix, in units of the error variance, is part of the result
    and gives the standard error of every mean and of every difference.
  - **The coefficient of variation is on the adjusted grand mean**, the mean of the
    adjusted treatment means, and both are labelled so. SAS's "Coeff Var" and the cv of
    Gomez and Gomez for a CRD divide by the mean of the values present instead.
- **Pairs are compared on their own standard errors.** Fisher's LSD has a critical
  difference for each pair. Tukey's test becomes the Tukey-Kramer test, named so in the
  report; for adjusted means in blocks it holds its error rate only approximately, which
  the report states. A letter is a largest set of means no two of which differ, found as
  the maximal cliques of the pairs that do not differ, because with a difference for each
  pair those sets need not be runs of sorted means; with one difference they are the same
  runs as before.
- **Dunnett's test is computed where the correlations among the comparisons with the check
  are products of one loading per treatment**, and refused by name where they are not;
  never approximated. That form always holds without blocks (loadings
  sqrt(n_i / (n_i + n_0))) and with one missing plot in blocks; with several missing plots
  it depends on the pattern. The expectation over the shared factor is now taken by the
  trapezoid rule on a grid whose step follows the steepest comparison and the number of
  comparisons, in place of the 64-point Gauss-Hermite rule of decision 0029. That rule
  serves equal replication, but a loading of 0.97 (a check on 2 plots against treatments
  on 30) put its probability out by 6e-4; the new one holds 1e-12 there.
- **Yates' estimates** complete an RCBD's table for the classical arithmetic.
  - One missing value is the closed form X = (r B + t T - G) / ((r - 1)(t - 1)). Several
    are found by cycling that formula over the missing plots, block by block in treatment
    order, from the mean of each plot's treatment and block means, until no estimate moves
    by more than 1e-12 of the largest value present; 10,000 cycles without settling is an
    error. Start, order and stopping rule are fixed, so the estimates are reproducible.
  - Error and total lose one degree of freedom for each estimate.
  - The treatment sum of squares is corrected for the estimates' upward bias: what
    treatments account for, adjusted for blocks, is the sum of squares of the values
    present about their block means less the error sum of squares. For one missing value
    this is Gomez and Gomez's B = (B0 - (t - 1) X)^2 / (t (t - 1)); for several the book
    leaves the bias in and this does not. The amount taken off is reported, the total is
    reduced with it, and the block line, which is not corrected, is given without a test.
  - An estimate is shown as an estimate, on the analysed scale, and is never stored.
  - A CRD has no table of blocks to complete, so `estimate` refuses its missing plots by
    name and points to `leastSquares`.
- **The two methods agree where they overlap.** The completed table's treatment means are
  the adjusted means, its error is the least-squares error, and its corrected treatment
  line is the Type III one, so `estimate` and `leastSquares` give the same test and the
  same comparisons, on the same exact standard errors. They differ in the table shown and
  in showing the estimates.
- **The assumption checks run on the plots present**, never on an estimate: Brown-Forsythe
  on each treatment's own values, Tukey's one degree of freedom on the fit, Shapiro-Wilk
  on its residuals.
- **Validated** against statsmodels fitting the same model (sums of squares, F, means,
  standard errors and every pairwise difference within 1e-9, P within 1e-6) across the
  M1 to M3 patterns of decision 0003 on the registry's datasets and on generated tables;
  Yates' estimates against the same fit's predictions; Gomez and Gomez's worked examples
  (Tables 7.1 to 7.3, 7.9 and 7.10, 2.3 and 2.4); Tukey-Kramer against statsmodels pair by
  pair; Dunnett's distribution against scipy's Dunnett test and multivariate t within 5e-4,
  their own accuracy.

## Consequences

- No schema or store change. The JSON of an analysis gains `missingPlotPolicy`,
  `missingCells`, `sumsOfSquares`, `estimation` and `meanCovariance`; a separation lists
  every pair, and its `criticalDifference` and `standardError` are null when they differ by
  pair or by mean.
- Gomez and Gomez round each estimate to the whole kg/ha before their analysis of
  variance. The error and corrected treatment lines are unmoved by that (within 1 of the
  printed figures); the replication and total lines move with it (2,188,657 here against
  the printed 2,188,739 in Table 7.3), and the tests reproduce the printed figures from
  the rounded estimate.
- For two treatments each short of a plot the book's rule of effective replications gives
  a standard error of 301.93 where the exact one is 285.30; the exact one is used.
- Dunnett's critical values for equal replication moved with the integration rule by less
  than 1e-11 for up to ten comparisons, and by 1e-8 for thirty on six error df.
- Not built, each refused by name meanwhile: missing plots in a two-factor RCBD, a split
  plot, a trial with checks beside its plots or an assessment with subsamples; Dunnett's
  test for correlations that are not of the product form.
- ARM's printed table for a trial with a missing plot has not been compared with this one.
