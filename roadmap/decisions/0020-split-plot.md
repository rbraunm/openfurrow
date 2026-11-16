# 0020 - Split plots: factors, main plots and two error strata

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The research specialist named the split plot among the arrangements in use (worklist
REC-7). Until now a trial had one list of treatments, one design (the RCBD) and one error
term. A split plot puts the levels of one factor on main plots in complete blocks and
splits each main plot into subplots for the levels of a second factor, so it needs
treatments that are combinations of two factors, plots that know their main plot, and an
analysis with two error strata. ARM calls the two factors A (main unit) and B (subunit)
and expands their combinations into treatments; agricolae's `design.split` and `sp.plot`
take the two factors separately. Gomez and Gomez (1984), section 3.4.2, set out the
analysis.

## Decision

- **Factors are data.** A trial may declare factors, each with a code, a name and its
  levels. A treatment states its level of each factor, keeps its own code and may still
  carry product lines.
- **A split-plot design names its main-plot and subplot factor.** Its treatments must be
  every combination of the two, each once. Factors are refused on an RCBD for now rather
  than kept and ignored; the factorial RCBD is worklist USR-10.
- **Each plot records its main plot.** Main plot m holds positions (m - 1)b + 1 to mb of
  its block; plot numbers stay block x 100 + position. A layout whose main plot mixes
  main-plot levels, or lacks a subplot level, is rejected, whether generated or imported.
- **The randomization is the project's own** (`sha256FisherYates1`, now with a split-plot
  rule): in each block the main-plot levels are shuffled, then the subplot levels of each
  main plot in turn, on the same SHA-256 stream. RCBD layouts are unchanged. The first
  block may be left in factor order.
- **The analysis has two error strata**: Replication, A tested against Error(a), Error(a),
  B and A x B tested against Error(b), Error(b), Total, with a coefficient of variation for
  each error. Each factor's means are separated by Fisher's (protected) LSD on its own
  error. Inside the interaction, two subplot means at one main-plot level are compared on
  sqrt(2 Eb / r) and two main-plot means at one subplot level on
  sqrt(2 [(b - 1) Eb + Ea] / rb) with the weighted t of Gomez and Gomez Table 5.6, and the
  combination table is lettered within rows when the interaction is significant (USR-11).
  Assumption checks are not computed (USR-12); the report says so.
- **Validated** against Gomez and Gomez Table 3.10 to its printed precision, and against
  statsmodels at full precision.

## Consequences

- Schema 0.8.0, store version 8; every trial's content hash changed.
- `Workspace.analyze` runs the analysis the design calls for; `separateFactorMeans`
  separates a split plot's factors, and `separateMeans` refuses a split plot by name.
- The book's printed Error(a), 1,419,678, is its subtraction of already-rounded sums of
  squares; the exact value is 1,419,678.81. Its printed replication mean square, 541,228,
  is a misprint for 541,288.
