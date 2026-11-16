# 0028 - Tukey's HSD, on a studentized range of our own

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The tool separated means by Fisher's LSD only, protected or not. The second opinion on the
readiness bar ranked "Tukey for all pairs or Dunnett against a check before Duncan and SNK"
among the first things a pilot needs (worklist USR-3). Tukey's honestly significant
difference needs the studentized range distribution, which decision 0002 says the tool
computes itself, with scipy only as an oracle.

## Decision

- **The comparison is a method, not a flag.** `MeanComparison` is protectedLSD (the
  default), lsd or tukeyHSD, chosen in the project config as before, and passed through
  the analysis, the report, the workspace, the command line and the service in place of
  the old `protected` flag. A separation's threshold is its `criticalDifference`.
- **Tukey's HSD** is q(1 - alpha; means, error df) * sqrt(MS error / n). It is applied
  regardless of F, as it holds the chance of any false difference at alpha itself. For a
  split plot or a factorial RCBD each factor's levels use their own error. The comparisons
  inside a two-factor interaction stay on their LSDs (decision 0020) and are lettered when
  the interaction is significant, unless the unprotected LSD is chosen.
- **The studentized range** is computed by the Copenhaver and Holland method that R's
  ptukey follows, with Gauss-Legendre nodes from numpy and the first interval of the outer
  integral graded towards zero, where the integrand grows like a square root and an
  ungraded rule is inaccurate for small error df. The quantile is found by the Illinois
  method.
- **Validated**: the distribution against scipy within 1e-7 from 2 to 2,000 error df; the
  separation against statsmodels' pairwise_tukeyhsd, pair by pair, on Gomez and Gomez
  Table 2.1.

## Consequences

- The JSON of a separation names its threshold `criticalDifference`.
- A quantile takes about half a second; a report computes one per separation.
- Dunnett against a check is still to come (worklist USR-3).
