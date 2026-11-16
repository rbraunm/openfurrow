# 0022 - Untreated checks beside the plots, in every arrangement in use

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The research specialist named the "paired plot" among the arrangements in use (worklist
REC-7). Sources use the name for different things. EPPO PP 1/152 describes imbricated
controls (untreated strips between plots, left out of the analysis) and adjacent controls
(each plot halved, one half left untreated, the halves analysed together as a split
plot); on-farm guides pair a treated plot with a check and use a paired t-test; ARM works
out percent control plot by plot against a paired untreated check. The owner's decision
(2026-11-15): support all of them rather than choose one.

## Decision

- **A design states its check arrangement**: none, imbricated, adjacent or paired. Checks
  apply to an RCBD for now.
- **Check plots are recorded** beside the layout, each with its block and the treated plot
  or plots it serves. Every treated plot has exactly one check in its own block; a strip
  may serve several plots, a half or a partner only one. A generated layout puts one check
  beside each plot, numbered 10000 + the plot's number. Check plots are stored, exported,
  covered by the content hash, written to the Field Book file and take observations like
  any plot.
- **The main analysis uses the treated plots.** Check values never enter it.
- **What each arrangement adds**: imbricated, the level of the checks (the pest
  pressure); adjacent, a two-stratum analysis of the treated and untreated halves;
  paired, a paired t-test of each treatment against its checks.
- **Percent control**, when an assessment asks for it: Abbott, 100 (1 - T / C), or
  Henderson-Tilton, 100 (1 - (Ta Cb) / (Tb Ca)) with a named assessment before
  application, worked out plot by plot against the plot's own check and analysed as an
  RCBD with its means separated. A zero divisor stops the analysis and names the plot.
- **Validated**: the formulas against values worked by hand, the ANOVAs against
  statsmodels, the paired test against scipy.

## Consequences

- Schema 0.9.0, store version 9; every trial's content hash changed.
- The field map does not draw the check plots yet (worklist USR-13).
