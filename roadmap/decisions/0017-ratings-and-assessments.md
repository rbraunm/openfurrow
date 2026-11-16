# 0017 - A rating says what is rated; an assessment is one occasion it is taken

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

An assessment was one object holding both what is measured (a name, a data type, a unit,
limits or categories, a measurement kind and a transform) and when (a free-text timing).
An efficacy trial rates the same thing several times: disease severity before the first
spray and then 7, 14 and 21 days after it. With one object each date had to repeat the
whole definition, and nothing tied the dates to the applications they are counted from.
The research specialist asked for definitions of assessments (worklist REC-8). EPPO PP
1/181, Appendix 1, section 3.2 asks for the type, date, method and scale of each
assessment. The incumbent tool's assessment header carries a rating type, part rated,
crop and pest stage, sample size and days after application. MIAPPE and BrAPI define a
variable once (trait, method, scale) and record observations against it per occasion
(`../research/trialRecord.md`).

## Decision

- **A rating is what is rated**: its code, name, rating type, part rated, method, data
  type, unit, limits or categories, measurement kind and transform. Every rule an
  observed value obeys lives here, once.
- **An assessment is one occasion a rating is taken**: its code, the rating, the planned
  timing, the date, the crop and target stage, the application it is timed from, who
  assessed, the sample size and notes.
- **Observations stay keyed by plot and assessment code**, so each occasion is analysed
  on its own and the analysis and import read the rules through the assessment's rating.
- **Days after application are derived**, never stored: the assessment's date less the
  application's, shown once both have one. A negative count is allowed; a count taken
  before spraying is ordinary.
- **References must resolve**: an assessment names a declared rating and, when timed, a
  declared application. A rating no assessment takes is allowed, as a protocol may define
  one before it is scheduled.
- A categorical or ordinal rating has no unit; that rule is new.

## Deferred

- **Subsamples**: several values within a plot, with the plot's value derived from them
  (worklist REC-11).
- **The target of a rating** (which pest or weed) waits for pests (REC-2), so that it is
  linked by code rather than written as text that would have to be replaced.
- **Keeping a confirmed out-of-range value** comes with entry in the tool (REC-9); import
  still refuses it.

## Consequences

- Schema 0.4.0, store version 4; every trial's content hash changed, the worked
  example's included.
- The report lists the ratings and the assessments before the analyses, with the days
  after application in the field's own notation (14 DA-A).
