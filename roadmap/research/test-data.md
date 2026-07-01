# Test-Data Registry

The registry of source and test material for validating OpenFurrow's analysis layer:
which datasets we use, what each is for, how to use it, and its license and citation. It
is chosen to cover a range of study types, response types, and data conditions.

**This file tracks references, not data.** Third-party datasets are not committed to the
repo. Each fixture is transcribed or exported from its cited source into a CSV under
`tests/fixtures/` with a provenance header (dataset name, source version, original
citation). Data values are facts; their selection, provenance, and intended use are what
we version here.

## Sourcing and licensing

Most fixtures come from **agridat** (Kevin Wright), an MIT-licensed collection of
agricultural datasets drawn from books and papers. MIT is cleanly Apache-2.0 compatible.
Per the package's request, any fixture derived from it cites **both agridat and the
original source**. Small datasets (tens of rows) are transcribed directly; larger ones
(hundreds to ~1300 rows) need an export step from the R package and are only needed for
future/stress scenarios, so they can wait.

## How known answers are anchored

Every analysis fixture is verified against **two independent oracles** so a shared bug
cannot hide:

1. A **published ANOVA table** from the literature, where one exists -- the strongest
   anchor, independent of any software.
2. **statsmodels** recomputation -- an independent implementation, a test-only dependency.

The self-authored ANOVA must match both within a documented tolerance. The primary
correctness anchor below has a published table; the agridat fixtures use statsmodels as
the oracle (and a published table where the source provides one).

---

## A. Published known-answer anchor (hand-encoded)

### Yates oats -- variety yields (RCBD)

The core correctness anchor: a single-factor RCBD, **3 oat varieties (Golden rain,
Marvellous, Victory) x 6 blocks**, one yield value per plot, fully balanced. Chosen
because its ANOVA table is published, so it pins our output independently of statsmodels.

Published ANOVA (target values):

| Source    | df | SS   | MS  | F    | p     |
|-----------|----|------|-----|------|-------|
| block     | 5  | 3969 | 794 | 5.28 | 0.012 |
| variety   | 2  | 447  | 223 | 1.49 | 0.272 |
| residuals | 10 | 1503 | 150 |      |       |

- **Study type:** single-factor RCBD
- **Response:** numeric (yield, 0.25 lb/plot)
- **Condition:** complete, balanced, small (18 rows)
- **Source:** Yates (1935), as reproduced in standard worked examples; values hand-encoded
  into the fixture and re-verified on load.
- **MVP scope:** yes -- the primary ANOVA + Protected LSD validation case.

---

## B. agridat fixtures

### B1. stirret.borers -- corn borer biological control (RCBD) [PRIMARY agridat case]

A crop-protection trial squarely in ARM's domain: control of European corn borer with the
fungus *Beauveria bassiana*. **One treatment factor (4 levels) x 15 blocks**, 60 rows,
with **two numeric assessments** (borer counts on two dates), so it also exercises
multi-assessment import. agridat's own example fits `count ~ trt + block` and notes the
counts are close enough to normal for a standard analysis.

- **Study type:** single-factor RCBD
- **Response:** numeric counts (two assessment dates: early, late)
- **Condition:** complete, small-to-moderate
- **Source:** Stirrett, Beall & Timonin (1937), *Scientific Agriculture* 17:587-591,
  Table 2; via agridat.
- **MVP scope:** yes -- the primary realistic ANOVA + Protected LSD case, and the
  multi-assessment import test.
- **Status:** SOURCED and IN USE. Fixture `tests/fixtures/stirretBorers.csv` (via
  the Rdatasets agridat CSV mirror); validated by `tests/testStirretBorers.py`,
  which reproduces the agridat published count1 means and matches statsmodels on
  both counts at the full 4 x 15 scale.
- **Confirmed on pull:** 4 treatments (None, Early, Late, Both), 15 blocks each,
  complete (60/60 cells, both dates). The count1 treatment effect is significant
  (F = 7.13, p = 0.0006), so this case also exercises the Protected LSD letter
  separation into two groups: {Early, None} vs {Both, Late}.

### B2. minnesota.barley.yield (subset) -- variety trial (RCBD)

A variety yield trial used to stress mean separation with **more treatments** (more LSD
letter groups than the 3-4 level cases). The full set is multi-environment (many
site-years, 647 rows) with **3 blocks per location**; subset to a **single site-year** for
a clean single-factor RCBD (varieties x 3 blocks).

- **Study type:** single-factor RCBD (after subsetting one site-year)
- **Response:** numeric (yield)
- **Condition:** complete within a site-year; moderate treatment count
- **Source:** Immer (1934), via agridat (`minnesota.barley.yield`).
- **MVP scope:** yes -- mean-separation stress with several treatments.

### B3. beall.webworms -- insecticide trial (factorial, counts)

Classic beet-field insecticide experiment: a **2x2 factorial (contact spray x lead
arsenate, i.e. 4 treatments) in 13 blocks**, with **25 subsamples per plot** (1300 rows).
Counts, often modeled as Poisson / negative binomial.

- **Study type:** factorial RCBD with subsampling
- **Response:** numeric counts (non-normal)
- **Condition:** complete, large
- **Source:** Beall (1940), *Ecology* 21:460-474, Table 6; via agridat.
- **MVP scope:** **future** -- factorial analysis and count/GLM handling are beyond the
  single-factor MVP. Useful now as a **large tidy-data import stress test**.

### B4. durban.splitplot -- fungicide x variety (split-plot)

A split-plot with **2 whole-plot fungicide treatments x 70 barley varieties in 4 blocks**
(560 rows). Another crop-protection design in ARM's wheelhouse.

- **Study type:** split-plot
- **Response:** numeric (yield)
- **Condition:** complete, large
- **Source:** Durban et al. (2003), *JABES* 8:48-66; via agridat.
- **MVP scope:** **future** -- earmarked for when split-plot designs are added.

### B5. fisher.barley -- multi-environment trial (MET)

The classic Immer/Fisher barley MET: **5 varieties x 6 locations x 2 years** (60 rows),
yields given as totals of 3 reps.

- **Study type:** multi-environment trial (genotype x environment)
- **Response:** numeric (yield)
- **Condition:** balanced across environments; no within-location replication retained
- **Source:** Fisher (1935), *The Design of Experiments*; Yates & Cochran (1938),
  *J. Agric. Sci.* 28:556-580, Table 1; via agridat.
- **MVP scope:** **future** -- earmarked for multi-environment analysis.

---

## C. Derived fixture (negative test)

### missing-data variants of stirret.borers

A family of copies of B1, each with cells removed in a specific pattern, exercising the MVP
missing-data policy (decision 0003): the analyzer must **reject and fail loud**, naming the
missing cell(s), rather than silently analyzing an incomplete table. The full pattern matrix
-- a single cell, several scattered cells, a whole treatment absent from one block, a
non-estimable pattern, and the complete-table control -- lives in decision 0003; the
fixtures derive from B1 (stirret.borers) by removing cells in each pattern. Documented as
derived -- the deletions are the test condition, not real data.

- **Study type:** single-factor RCBD with an induced gap
- **Condition:** intentionally incomplete
- **MVP scope:** yes -- the reject-on-missing path.

---

## Coverage matrix

| Fixture                       | Study type          | Response        | Condition            | MVP    |
|-------------------------------|---------------------|-----------------|----------------------|--------|
| Yates oats (anchor)           | single-factor RCBD  | numeric         | complete, small      | yes    |
| stirret.borers                | single-factor RCBD  | count (2 dates) | complete             | yes    |
| minnesota.barley.yield subset | single-factor RCBD  | numeric         | complete, more trts  | yes    |
| missing-data variants         | RCBD + gap          | count           | incomplete (induced) | yes    |
| beall.webworms                | factorial + subsamp | count           | complete, large      | future |
| durban.splitplot              | split-plot          | numeric         | complete, large      | future |
| fisher.barley                 | MET (g x e)         | numeric         | balanced across env  | future |

Categorical/ordinal assessment import (the `allowedValues` path) is currently exercised by
a synthetic disease-severity fixture (none/low/moderate/high); a real rated-disease
dataset with a treatment+block structure can be adopted later if a clean one is identified.

## What we build against first

For the analysis MVP, the active fixtures are the **Yates oats anchor** (published table),
**stirret.borers** (realistic single-factor RCBD, ARM domain, multi-assessment),
**minnesota.barley.yield subset** (mean-separation stress), and the **missing-data
variants** (reject path). The factorial, split-plot, and MET datasets are recorded now so
they are ready when those study types are added.
