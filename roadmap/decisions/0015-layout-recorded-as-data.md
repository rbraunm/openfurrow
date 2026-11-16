# 0015 - The field layout is recorded data

**Status:** Accepted. Replaces the "layout is not stored" choice made when decision 0001
was implemented, and settled shape 2 of the implementation plan. Reversible while no trial
exists outside development.

## Context

Until now a trial's plot map -- which treatment is on which plot, in which block -- was
never stored. It was regenerated on demand from the randomization seed with numpy's
`Generator.permutation`, and neither the database, the exported document nor the content
hash carried it. Two things are wrong with that.

**It can change without notice.** numpy allows the methods of its `Generator` to produce
different results in a new feature release, and the project accepts any numpy from 1.26.
R made exactly such a change to its sampler in version 3.6.0. Observations are keyed by
plot, so a changed map still finds every observation and still has every treatment in
every block: the analysis runs on the wrong treatments, the content hash is unchanged, and
the reproducibility check passes.

**It is not what a layout is.** Once a plan is issued, and certainly once the trial is
planted, the layout is a fact about a field. The first replicate is often left in
treatment order, layouts are made in other tools, plans are adjusted before planting. A
function of a seed can hold none of these, so a trial that already exists could not be
entered at all.

The evidence is in `../research/layoutPractice.md`. The data standards (BrAPI, MIAPPE)
carry the treatment and block of every plot as data. EPPO PP 1/181, the standard behind
good experimental practice, puts the assignment of plots to treatments and blocks in the
trial record. The tools surveyed store the realized design or hand it over as a fieldbook.
None keeps only a seed.

Two narrower options were rejected:

- **Keep deriving, with a shuffle of our own.** Removes the dependence on numpy. A later
  correction to our own shuffle would recreate the problem, and a layout made elsewhere
  still could not be held.
- **Keep deriving, and store a fingerprint to compare against.** Detects a change, but
  cannot recover from it: the trial becomes unreadable exactly when the check fails.

## Decision

- **The plot map is canonical.** Plot number, block, position in the block and treatment
  are stored in the database, written in the exported document and covered by the content
  hash.
- **The seed is provenance.** A generated layout records its seed and the name of the
  method that produced it. A layout supplied with the trial records the method `imported`
  and no seed.
- **The project owns its randomization.** New layouts come from an algorithm specified
  exactly and built only on SHA-256: a counter-mode byte stream, unbiased integers by
  rejection, and a Fisher-Yates shuffle for each block. The method is named with a
  version (`sha256FisherYates1`). No library defines the result, so any implementation in
  any language can reproduce it. A changed algorithm gets a new name, and old names stay
  implemented.
- **Regeneration is a check.** A document that names a generated method must contain
  exactly the layout that method produces from its seed; otherwise it is rejected where it
  enters.
- **Derive, don't duplicate, still holds.** What follows from the stored plots and the
  package (treatment order, counts, the number of plots) is not stored again.

## Consequences

- The content hash of every existing trial changes, and layouts generated from a given
  seed differ from those of earlier development builds. Nothing outside development is
  affected.
- A trial laid out elsewhere can be represented: as a trial document today, through the
  interface later (worklist USR-7).
- The store gains a plot table and a version stamp, so a database written by an earlier
  build is refused with a clear message instead of failing obscurely.
- The principle in `CLAUDE.md` changes from "every layout is regenerable from a recorded
  seed" to "every layout is recorded, and a generated one is reproducible from its seed".
- Not designed here: what happened to a plot after the plan was issued (as planted against
  as planned, lost plots, misapplied treatments). EPPO asks for such deviations to be
  reported; it is a record of its own.
