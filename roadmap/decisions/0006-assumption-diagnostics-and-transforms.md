# 0006 - Assumption diagnostics and variance-stabilizing transforms

**Status:** Accepted. Direction adopted, not locked.

## Context

The RCBD ANOVA assumes three things about the errors: additivity of block and
treatment effects, homogeneous error variance, and normality. The MVP checks
none of them. On non-normal count or percentage data it will return an analysis
a statistician would transform or reject first -- and it will do so silently.

This surfaced in the stirret.borers hardening pass. We compute that dataset
correctly (treatment means match the agridat published values and the full ANOVA
matches statsmodels on both counts), but it is the *friendly* count case: its
curator notes the counts are close enough to normal for a standard analysis. Real
count and percentage data often are not, and then the classical, auditable remedy
-- the one ARM and standard field-trial practice use -- is to apply a
variance-stabilizing transform and analyze on the transformed scale.

There is a real statistical fork here. The modern preference for counts is often a
Poisson or negative-binomial GLM, and for proportions a binomial GLM, rather than
transform-then-Gaussian ANOVA. But a GLM is a much larger native build (iteratively
reweighted least squares, deviance, chi-square inference) with its own
oracle-validation surface, whereas transforms reuse the ANOVA machinery we already
have and keep the classical, transparent workflow we are matching.

## Decision

Two separable capabilities, governed by one rule: neither acts silently.

**Diagnostics are always-on and report-only.** They are pure information about
whether the assumptions hold. They never alter the analysis, so adding them cannot
hide anything. Slice 1 ships three, computed on every numeric analysis and shown in
a report "Assumptions" block:

- **Equal variance: Brown-Forsythe** -- Levene's test using absolute deviations
  from the per-treatment *median* (robust to non-normality). It is itself an F-test
  on those deviations, so it reuses the native F-distribution with no new special
  functions.
- **Non-additivity: Tukey's one-degree-of-freedom test** -- RCBD-specific, cheap,
  reuses the F-distribution. It is the assumption most easily forgotten in a blocked
  design.
- **Normality of residuals: Shapiro-Wilk** -- computed on the model residuals, which
  is standard practice (equivalent to `shapiro.test(residuals(m))`), with the usual
  caveat, stated in the block, that residuals are constrained rather than
  independent. SW is the gold-standard normality test and is what a reviewer expects.

**Transforms are explicit, never inferred.** A per-assessment transform -- `none`,
`sqrt`, `log`, `arcsinSqrt`, `logit` -- is declared by the owner on the assessment
definition. When set, the analysis runs on the transformed scale, the transform is
recorded in the reproducibility block **and enters the content hash** (a transformed
analysis is a different, self-labeled document), and treatment means are
back-transformed to the original scale and labeled as such. The tool may *recommend*
a transform from the diagnostics; it never applies one on its own. This keeps us
inside the fail-loud rule: diagnostics are honest reporting, a transform is an owned,
recorded decision.

**Classical now, GLM later.** Poisson / negative-binomial / binomial GLMs are a
separate future track with their own ADR. This record commits only to the classical
transform-then-ANOVA workflow.

**New native functions, under ADR 0002.** Slice 1 adds only two new special
functions, both dependency-free and validated against oracles as test-only
cross-checks:

- **Normal CDF** -- a thin wrapper over the standard library's `math.erf`, exact to
  double precision.
- **Inverse normal quantile** -- Wichura's AS 241 rational approximation, the gold
  standard, no dependencies.

Shapiro-Wilk's W statistic and p-value use Royston's AS R94 (the algorithm R and
scipy use), which needs only the normal CDF and its inverse -- **not** the
order-statistic covariance matrix and **not** an incomplete gamma function.
Brown-Forsythe and Tukey reuse the existing F-distribution. Incomplete gamma does not
enter until the heavier diagnostics (Bartlett's chi-square), which stay deferred. SW
is oracle-validated against `scipy.stats.shapiro` (same algorithm); Brown-Forsythe and
Tukey against statsmodels or hand-computed references.

**No silent skips.** Below Shapiro-Wilk's minimum valid residual count, the normality
line reports "not computed" with the reason rather than being omitted or defaulting to
a pass.

## Consequences

- The report gains an "Assumptions" block. It is diagnostic only; the AOV Means Table
  is unchanged by its presence.
- Declaring a transform changes the content hash **by design**: the full-record hash
  identifies the analysis actually performed, and an analysis on a transformed scale
  is a distinct, self-labeled document (the same principle the 0005 redaction case
  turns on).
- Back-transformed treatment means are labeled point estimates on the original scale;
  they are not symmetric confidence intervals, and the block says so.
- Diagnostics can flag a problem that the owner then chooses not to remedy. That is
  allowed and intended: the tool reports, the owner decides.
- GLM support stays open as a separate track; nothing here forecloses it.

## Slice order

1. **Distribution functions + Shapiro-Wilk**, with oracle tests: normal CDF, inverse
   normal (AS 241), SW W and p (AS R94), validated vs scipy/statsmodels.
2. **Diagnostics wired into the report**: Brown-Forsythe, Tukey non-additivity,
   Shapiro-Wilk on residuals, in an always-on report-only Assumptions block.
3. **Heavier native diagnostics** (future): Bartlett's test, needing a native
   incomplete gamma.
4. **GLMs** (future, separate ADR): Poisson / negative-binomial / binomial.
