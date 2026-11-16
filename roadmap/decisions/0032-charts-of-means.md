# 0032 - Charts of separated means

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

A trial report in this field shows the treatment means as a bar chart with the letters of
the mean separation above the bars and an error bar on each (worklist USR-2; ARM and the
cloud suites all draw one). The report had tables only.

## Decision

- **One chart under every table of means with letters**: the treatment means of an RCBD or
  a CRD, percent control, and each factor's level means in a split plot or a factorial RCBD.
  Under Dunnett's test the treatment means are charted without letters, and the caption
  points to the table's comparisons with the check.
- **Bars are the means in the table's order, from a zero baseline**; a negative mean hangs
  below it. The value axis starts at zero (or below it) and steps by 1, 2, 2.5 or 5 times a
  power of ten.
- **The error bar is one standard error of a mean on the analysis' own error**: the square
  root of the error mean square over the plots in a mean (the subplot or main-plot error for
  a split plot's factors). Each separation result carries that standard error beside its
  critical difference. After a transform, bars and error bars are back-transformed, so the
  error bar need not be symmetric; the part of the interval outside the transform's range
  (below zero on the square-root scale, outside 0 to pi/2 on the angular scale) is cut, since
  it has no value on the original scale. The caption says which.
- **Drawn natively as SVG** (decision 0002) on the report page, styled by the page, with
  each bar's mean, error bar ends and letters as its tooltip. The table above is the
  chart's text view. The Markdown report is unchanged: charts are a page feature, placed by
  a random per-request marker line so no trial text can place or forge one.

## Consequences

- No schema or store change; no content hash changes.
- Interaction plots of two-factor combination means, and charts across assessments or
  trials, are not drawn yet (milestones, "Visualization").
