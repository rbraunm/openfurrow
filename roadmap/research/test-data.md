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
- **Status:** NOT YET IN USE. No fixture or test draws on it.

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

## C. Derived fixtures (missing plots)

### missing-data variants

Copies of a complete trial with cells removed in a specific pattern, exercising the
missing-plot policy (decisions 0003 and 0043): under `refuse` the analyzer must **reject
and fail loud**, naming the missing cell(s); under `leastSquares` and `estimate` it must
analyze an estimable pattern and refuse a non-estimable one with its reason. In use:

- the pattern matrix of decision 0003 -- a single cell, several scattered cells, a whole
  treatment absent from one block, the non-estimable patterns (a treatment absent from
  every block, a whole block absent, a disconnected design, no degrees of freedom left for
  error), and the complete-table control -- removed from B1 (stirret.borers), both counts,
  in `tests/testMissingPlots.py`;
- the first three patterns removed from every RCBD dataset in use (stirret.borers, Yates
  oats, clewer.wheat, gomez.seedrate, and gomez.nonnormal1 on its log10(count + 1) scale),
  and from generated tables of random size, each checked against statsmodels under both
  methods;
- generated completely randomized trials with unequal numbers of plots, against
  statsmodels and scipy;
- three patterns removed from the Yates oats data in `tests/testAnovaRcbd.py` (one cell,
  one value recorded as missing, a whole treatment), on the reject path.

Documented as derived -- the deletions are the test condition, not real data. The
published missing-data examples are D2 and D10.

- **Study type:** single-factor RCBD or CRD with an induced gap
- **Condition:** intentionally incomplete
- **Role:** the missing-plot policy and both methods.

---

## D. From the 2026-11 survey

Finished trials that are openly available with both the plot-level data and a published
analysis of the same data. They were found through assisted web research. D1 and D2 have
been pulled, confirmed and put to use; the rest are recorded as reported, and each is
confirmed on pull, as B1 was, before a test relies on it.

### D1. clewer.wheat -- wheat varieties (RCBD)

**4 varieties x 3 blocks**, grain yield in t/ha. The source prints the ANOVA and the
variety, block and grand means.

- **Source:** Clewer & Scarisbrick (2001), *Practical Statistics and Experimental Design
  for Plant and Crop Science*, Example 10.1, Table 10.1; via agridat.
- **Role:** a second published-table anchor for the single-factor RCBD.
- **Status:** SOURCED and IN USE. Fixture `tests/fixtures/clewerWheat.csv` (agridat 1.27,
  MIT), validated by `tests/testPublishedOracles.py`, which reproduces the printed table
  to its precision and matches statsmodels at full precision. The fixture keeps the row
  and column of every plot, so the trial is entered with the layout it was grown in
  (decision 0015) rather than re-randomized.
- **Confirmed on pull:** 4 varieties x 3 blocks, complete. The variety effect is
  significant (F = 5.52, p = 0.037), and the LSD leaves one variety in both groups, so the
  case exercises overlapping letters.

### D2. gomez.seedrate -- rice seeding rates (RCBD)

**6 seeding rates x 4 blocks**, grain yield in kg/ha. The book prints the observations,
the treatment means, the ANOVA and the CV.

- **Source:** Gomez & Gomez (1984), *Statistical Procedures for Agricultural Research*,
  Tables 2.5 and 2.6; via agridat.
- **Role:** a published CV, and a treatment effect that is not significant, so the
  protected LSD must perform no separation.
- **Status:** SOURCED and IN USE. Fixture `tests/fixtures/gomezSeedRate.csv` (via the
  Rdatasets agridat CSV mirror; agridat notes the data are used with permission of K. A.
  Gomez), validated by `tests/testPublishedOracles.py`.
- **Confirmed on pull:** 6 rates x 4 blocks, complete. The ANOVA computed from the data
  gives a treatment sum of squares of 1,198,331, an error sum of squares of 1,658,376, an
  error mean square of 110,558, F = 2.17 and a CV of 6.7%, the values reported from the
  book's tables.
- **Also the book's worked example of missing data.** Section 7.1.2.1 (pages 276 to 279,
  Tables 7.1 to 7.3) takes the value of the 100 kg seed/ha treatment in replication II
  (4,831) as missing: estimate 5,265 kg/ha, bias correction 546, error 1,540,726 on 14 df,
  adjusted treatment sum of squares 1,139,955, F = 2.07, standard error of a difference
  with that treatment 257, LSD 551 at 5% and 765 at 1%. Section 7.1.2.6 (pages 287 to
  292, Tables 7.9 and 7.10) takes the 25 kg treatment's value in replication I (5,113) as
  missing as well: estimates 5,244 and 5,422 by iteration, error 1,481,374 on 13 df. Read
  from an openly posted scan of the book. `tests/testMissingPlotsPublished.py` holds
  OpenFurrow to these and reproduces the printed replication and total lines from the
  book's estimates, which it rounds to the whole kg/ha before its analysis of variance
  (decision 0043).

### D7. gomez.splitplot -- rice nitrogen by variety (split plot)

**6 nitrogen levels (main plots) x 4 varieties (subplots) x 3 replications**, grain yield
in kg/ha.

- **Source:** Gomez & Gomez (1984), *Statistical Procedures for Agricultural Research*,
  Table 3.7 (data) and Table 3.10 (ANOVA), section 3.4.2. Read from an openly posted scan
  of the book and transcribed.
- **Role:** the known answer for the split-plot analysis: both error strata, F values,
  and the two coefficients of variation.
- **Status:** IN USE. Fixture `tests/fixtures/gomezSplitPlot.csv`, validated by
  `tests/testSplitPlot.py`, which reproduces Table 3.10 to its printed precision and
  matches statsmodels at full precision.
- **Confirmed on transcription:** the replication totals (128,873; 135,604; 130,004), the
  totals of N0 and N5, of V1 and V4 and of two cells agree with the book's printed totals.
  The book's Error(a) is computed from rounded sums (exact 1,419,678.81, printed
  1,419,678), and its replication mean square is misprinted (541,228 for 541,288).

### D8. gomez.factorial -- rice variety by nitrogen (factorial RCBD)

**3 varieties x 5 nitrogen rates x 4 replications** in a randomized complete block design,
grain yield in t/ha.

- **Source:** Gomez & Gomez (1984), *Statistical Procedures for Agricultural Research*,
  Table 3.3 (data), Table 3.4 and the steps after it (the factorial partition), section
  3.3. Read from an openly posted scan of the book and transcribed.
- **Role:** the known answer for the factorial RCBD.
- **Status:** IN USE. Fixture `tests/fixtures/gomezFactorial.csv`, validated by
  `tests/testFactorial.py` against the book and statsmodels.
- **Confirmed on transcription:** the replication, variety and nitrogen totals, two cell
  totals and the grand total (297.390) agree with the book. The book subtracts a rounded
  correction factor and divides mean squares cut to three decimals; see decision 0025.

### D9. gomez.insecticide -- rice insecticides (completely randomized)

**7 treatments x 4 replications**, grain yield in kg/ha, in a completely randomized design.

- **Source:** Gomez & Gomez (1984), Tables 2.1 (data) and 2.2 (ANOVA). Read from an openly
  posted scan of the book and transcribed; one value the scan garbles (2,211) is fixed by
  its printed treatment total.
- **Status:** IN USE. Fixture `tests/fixtures/gomezInsecticide.csv`, validated by
  `tests/testCrd.py` against the book and statsmodels.

### D10. gomez herbicides -- postemergence herbicides in dryland rice (completely randomized, unequal replication)

**11 treatments on 4 or 3 plots each, 40 values**, grain yield in kg/ha: the book's worked
example of a completely randomized design with unequal replication, which is what a CRD
with missing plots is.

- **Source:** Gomez & Gomez (1984), *Statistical Procedures for Agricultural Research*,
  section 2.1.2.2, Table 2.3 (data) and Table 2.4 (ANOVA), pages 17 to 20. Read from an
  openly posted scan of the book and transcribed; three values the scan leaves unclear
  (3,001, 3,103 and 2,470) are settled by their printed treatment totals.
- **Role:** the known answer for a CRD analysed by least squares on unequal numbers of
  plots: treatment 15,090,304 on 10 df, error 5,119,420 on 29 df, total 20,209,724,
  F = 8.55, cv 16.3%.
- **Status:** IN USE. Fixture `tests/fixtures/gomezHerbicide.csv`, validated by
  `tests/testMissingPlotsPublished.py`, which enters it as a trial of four plots per
  treatment with four plots missing.
- **Confirmed on transcription:** every treatment total and the grand total (103,301)
  agree with the book's. The book's cv divides by the mean of the 40 values; OpenFurrow's
  is on the mean of the treatment means and is labelled so; both are 16.3%.

### D3. sweetpotato -- virus conditions (completely randomized)

**4 virus conditions x 3 plots**, no blocks, harvested weight. The agricolae tutorial
prints the means, the LSD, the letters, the error mean square and the CV, and the Tukey
grouping beside them.

- **Source:** International Potato Center data, in the R package agricolae and its
  tutorial.
- **Role:** the closest open match to an AOV Means Table with letters. Needs the
  completely randomized design.
- **License flag:** agricolae is GPL. The values are transcribed from the cited source
  with their citation; package files are not copied.

### D4. gomez.nonnormal1 -- insecticide efficacy counts (RCBD, transformed)

**9 treatments including a control x 4 replicates**, counts of living larvae, analysed as
log10(count + 1).

- **Source:** Gomez & Gomez (1984), Table 7.16; via agridat.
- **Role:** an efficacy trial with counts and a transform with an offset, the slice
  decision 0006 deferred.
- **Status:** IN USE. Fixture `tests/fixtures/gomezLarvae.csv` (via the Rdatasets agridat
  CSV mirror), validated by `tests/testTransformOffset.py` against Tables 7.16 and 7.17.

### D5. Designs beyond the RCBD

Recorded so they are ready when each design is added, all via agridat unless noted:
gomez.stripplot (strip-plot; Gomez & Gomez Table 3.15, with the CVs), gomez.splitsplit
(split-split-plot, the same experiment as agriTutorial's rice), goulden.latin (a Latin
square of fungicide timings on wheat), cochran.wireworms (a Latin square of fumigants,
counts analysed as the square root of count + 1), cochran.factorial (a confounded 2^4
factorial), cochran.lattice (a lattice square, boll weevil damage), burgueno.alpha (an
alpha-lattice variety trial with a published ASReml analysis), gomez.nitrogen (eight
treatments over three assessments), and the worked examples of the R package agriTutorial
(beet, greenrice, sorghum, turnip).

### D6. An ARM-format reference without a license

One public combined trial report prints ARM AOV Means Tables together with the plot-level
tables behind them (a commercial greenhouse lettuce comparison, ARM 2021.7). It carries no
reuse license, so it is not a fixture. It is useful for reading how the incumbent rounds
and lays out its table.

### What the survey did not find

No openly licensed collection of ARM-style reports with their plot-level data. Several
recent deposits that accompany efficacy and agronomy papers were opened; none is yet
confirmed as a pair of plot-level data and a matching published analysis.

---

## Coverage matrix

| Fixture                       | Study type          | Response        | Condition            | MVP    |
|-------------------------------|---------------------|-----------------|----------------------|--------|
| Yates oats (anchor)           | single-factor RCBD  | numeric         | complete, small      | yes    |
| stirret.borers                | single-factor RCBD  | count (2 dates) | complete             | yes    |
| minnesota.barley.yield subset | single-factor RCBD  | numeric         | complete, more trts  | not yet in use |
| clewer.wheat                  | single-factor RCBD  | numeric         | complete, own layout | yes    |
| gomez.seedrate                | single-factor RCBD  | numeric         | complete, not signif.| yes    |
| missing-data variants         | RCBD or CRD + gap   | count, numeric  | incomplete (induced) | yes    |
| gomez.seedrate, values missing| RCBD + gap          | numeric         | incomplete, published| yes    |
| gomez herbicides              | CRD, unequal reps   | numeric         | published            | yes    |
| beall.webworms                | factorial + subsamp | count           | complete, large      | future |
| gomez.splitplot               | split-plot          | numeric         | complete, published  | yes    |
| gomez.factorial               | factorial RCBD      | numeric         | complete, published  | yes    |
| durban.splitplot              | split-plot          | numeric         | complete, large      | future |
| fisher.barley                 | MET (g x e)         | numeric         | balanced across env  | future |

Categorical/ordinal assessment import (the `allowedValues` path) is currently exercised by
a synthetic disease-severity fixture (none/low/moderate/high); a real rated-disease
dataset with a treatment+block structure can be adopted later if a clean one is identified.

## What we build against first

The fixtures in use are the **Yates oats anchor** (published table), **stirret.borers**
(realistic single-factor RCBD, ARM domain, multi-assessment), **clewer.wheat** (published
table, a layout from the field, overlapping letters), **gomez.seedrate** (published table
with its CV, no separation under protection, and the book's own missing-data examples),
the **missing-data variants** (the missing-plot policy and both of its methods), and the
**gomez herbicides** (a published CRD with unequal replication). The
**minnesota.barley.yield subset** (mean-separation stress) is registered and not yet used. The factorial, split-plot, and MET datasets are recorded now so
they are ready when those study types are added.
