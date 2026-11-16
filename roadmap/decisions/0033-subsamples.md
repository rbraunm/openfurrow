# 0033 - Subsamples within a plot

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Many assessments take several values in one plot on one occasion: severity on ten leaves,
counts in four quadrats (worklist REC-11). Industry practice, checked at the source:

- ARM keeps every subsample ("Number of Subsamples" on the assessment) and analyses one
  value per plot: "AOV analyzes the plot means and not the individual subsample values"
  (ARM 2021 release notes, which also moved its automatic transforms to the plot mean). The
  plot value is the mean by default; a sum is selectable (SUMSUB, ARM 2017). "Average,
  Count, and Sum Subsamples functions automatically ignore missing data" (ARM product page).
- EPPO PP 1/152(4) section 1.7 treats sampling as estimating the plot mean and compares
  treatments "at between-plot scale"; PP 1/181(5) asks for the raw values of samples within
  plots to be available.
- Gomez and Gomez (1984) section 6.1: the subsample-level ANOVA tests treatments against the
  experimental error, which with every subsample present gives the same F as the ANOVA of
  plot means.

## Decision

- **An assessment may declare `subsamples`**: a `count` (two or more) and a `rule`, `mean`
  or `sum`. Only a numeric rating takes them.
- **Every value is kept as entered**, numbered 1 to the count (`subsample` on the
  observation); a value of an assessment without subsamples has none. A plot, assessment and
  subsample appears once. Stored, exported to JSON and CSV, and hashed.
- **The analysis runs on plot values** derived by the rule, for every design, the checks and
  percent control; the transform applies to the plot value, as in ARM.
- **A mean is taken over the subsamples recorded**, as ARM does, and the report names every
  plot short of some and how many. A plot with none has no value, so the analysis refuses it
  as any missing plot (decision 0003).
- **A sum needs every subsample.** A plot short of one stops the analysis, naming it. This
  departs from ARM, whose sum skips the gap: a total over fewer units is not comparable with
  the others.
- **Entry and import**: the entry page takes a row of the count's boxes per plot; a long
  file names the subsample in a column of its own; a wide file gives an assessment that
  takes subsamples one column per subsample, in the order of the file.

## Consequences

- Schema 0.14.0, store version 14; every trial's content hash changed (each observation now
  states its subsample, empty for none).
- The trial form does not offer subsamples yet; they are declared in the trial file (worklist
  USR-14).
- The subsample-level ANOVA with a sampling-error line, and Field Book's repeated measures,
  are not built.
