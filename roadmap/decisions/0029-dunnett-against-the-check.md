# 0029 - Dunnett's test against the untreated check

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The usual question of an efficacy trial is whether each product differs from the untreated
check. The second opinion on the readiness bar named Dunnett against a check beside Tukey
(worklist USR-3). Dunnett's critical values come from a multivariate t distribution, which
decision 0002 says the tool computes itself.

## Decision

- **`dunnett` is a mean comparison** beside the protected LSD, the LSD and Tukey's HSD.
  It compares every treatment with the one treatment whose role is `untreatedControl`; a
  trial with none or several is refused by name.
- **The distribution** is that of equally replicated comparisons, correlated 1/2: the
  chance that none exceeds d is an expectation over one shared normal factor (64-point
  Gauss-Hermite) inside the same integral over the error standard deviation as the
  studentized range (decision 0028). The critical difference is
  d * sqrt(2 MS error / n), two-sided.
- **The report** lists each treatment's mean, its difference from the check and whether it
  differs, with the critical difference. Factor levels of a split plot or a factorial RCBD
  are not treatments against a check, so under Dunnett they are lettered by the protected
  LSD, and the report names that method where it is used.
- **Validated**: equal to the two-sided t with one comparison (to 1e-10), the critical
  value of Dunnett's table for six comparisons on 24 df (2.76), and scipy.stats.dunnett's
  p-values within its own quasi-Monte Carlo accuracy.

## Consequences

- Unequal replication, where the correlations differ, is not handled; the CRD and the RCBD
  here are equally replicated.
- An explicit policy for the untreated check in the analysis (in it, beside it, or out of
  it) remains with worklist USR-3.
