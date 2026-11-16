# Test Fixtures

Provenance for the data fixtures used by the test suite. These are references
transcribed from cited sources, not vendored datasets; see
`roadmap/research/test-data.md` for the full registry and selection rationale.

## yatesOatsVariety.csv

A single-factor randomized complete block design: 3 oat varieties (Golden rain,
Marvellous, Victory) across 6 blocks, one yield value per plot (long format:
`treatment, block, yield`). This is the published-table anchor for the RCBD ANOVA
-- its ANOVA table is documented, so it pins the analyzer's output independently of
statsmodels.

- Source: Yates (1935), as reproduced in standard worked RCBD examples.
- Published ANOVA: block df 5 SS 3969 MS 794 F 5.28 p 0.012; variety df 2 SS 447
  MS 223 F 1.49 p 0.272; residuals df 10 SS 1503 MS 150.

## stirretBorers.csv

A single-factor randomized complete block design from a crop-protection trial:
4 treatments (None, Early, Late, Both) across 15 blocks, with two numeric borer
counts per plot (long format: `block, trt, count1, count2`). This is the primary
realistic case -- real count data at a larger scale than Yates, exercising
multi-assessment analysis and, because the count1 treatment effect is
significant, the Protected LSD letter separation into multiple groups.

- Source: Stirrett, Beall & Timonin (1937), Scientific Agriculture 17:587-591,
  Table 2; obtained via the Rdatasets agridat CSV mirror (Vincent Arel-Bundock),
  dataset `agridat/stirret.borers`. Block labels B1-B15 mapped to integers 1-15.
- Known answer (count1 treatment means, from the agridat documentation): None
  61.13333, Early 62.93333, Late 40.93333, Both 47.86667.
- Cross-check: statsmodels on the same data reproduces the analyzer's full ANOVA
  table for both counts (block/treatment/error SS, df, F, p).

## fieldbook_database_export.csv

A Field Book database (long) format data export for the Field Book ingest test
(E1b). One row per observation for a 4-treatment, 3-block trial: YIELD (numeric)
for all 12 plots and SEV (ordinal) for the first 3. The row layout matches Field
Book's database export exactly -- entry attribute columns (`plotNumber, block,
treatment`) followed by `trait, value, timestamp, person, location, number,
attached_photo, attached_video, attached_audio, device_name` -- per
`roadmap/research/fieldbook-formats.md`.

- Source: OpenFurrow-authored, not vendored. Field Book is GPL-2.0, so we do not
  commit its shipped samples; this file is our own, written to conform to the
  documented format. It exists to pin the ingest column mapping (unique-id -> plot,
  `trait` -> assessmentCode, `value` -> value; provenance columns ignored).
- Known answer: 15 observations -- YIELD value equal to the plot number for the 12
  plots (101-104, 201-204, 301-304), and SEV low, moderate, high for plots 101,
  102, 103. Plot numbers are block*100 + position, per the RCBD layout.

## clewerWheat.csv

A randomized complete block design comparing three new wheat varieties (V2, V3, V4) with
a standard (V1) in 3 blocks, grain yield in t/ha, with the row and column of every plot
(`row, col, block, gen, yield`). The second published-table anchor, and the one trial in
the suite entered with the layout it was grown in instead of a generated one.

- Source: Clewer & Scarisbrick (2001), Practical Statistics and Experimental Design for
  Plant and Crop Science, Example 10.1, Table 10.1; via agridat 1.27 (MIT),
  `data/clewer.wheat.txt`.
- Published ANOVA: block df 2 SS 9.78 MS 4.89 F 12.22; variety df 3 SS 6.63 MS 2.21
  F 5.52; error df 6 SS 2.40 MS 0.40; variety means 6.50, 7.60, 6.60, 8.30.

## gomezSeedRate.csv

A randomized complete block design of six rice seeding rates (25 to 150 kg seed/ha) in 4
blocks, grain yield in kg/ha (`rate, rep, yield`). A published table with its CV, and a
treatment effect that is not significant.

- Source: Gomez & Gomez (1984), Statistical Procedures for Agricultural Research, Tables
  2.5 and 2.6; obtained via the Rdatasets agridat CSV mirror, dataset
  `agridat/gomez.seedrate`. agridat notes the data are used with permission of K. A. Gomez.
- Published ANOVA: treatment SS 1,198,331; error df 15 SS 1,658,376 MS 110,558; F 2.17;
  CV 6.7%.

## gomezSplitPlot.csv

A split-plot trial of six nitrogen levels (main plots) and four rice varieties (subplots)
in three replications, grain yield in kg/ha (`nitrogen, variety, replication, yield`).

- Source: Gomez & Gomez (1984), Statistical Procedures for Agricultural Research, Table
  3.7; the ANOVA it is checked against is Table 3.10. Transcribed from the book; the
  transcription is checked against the book's printed replication, factor and cell
  totals.

## gomezFactorial.csv

A factorial trial of three rice varieties and five nitrogen rates in a randomized complete
block design with four replications, grain yield in t/ha (`variety, nitrogen, replication,
yield`).

- Source: Gomez & Gomez (1984), Statistical Procedures for Agricultural Research, Table
  3.3; the analysis it is checked against follows in section 3.3. Transcribed from the
  book; the transcription is checked against the book's printed replication, factor, cell
  and grand totals.

## gomezLarvae.csv

Living larvae on rice under nine insecticide treatments in four replications of a
randomized complete block design (`treatment, replication, larvae`), analysed as
log10(count + 1).

- Source: Gomez & Gomez (1984), Statistical Procedures for Agricultural Research, Table
  7.14; obtained via the Rdatasets agridat CSV mirror, dataset `agridat/gomez.nonnormal1`.
  The analysis it is checked against is Tables 7.16 and 7.17.

## gomezInsecticide.csv

Rice grain yield under seven insecticide treatments in a completely randomized design
with four replications (`treatment, replicate, yield`).

- Source: Gomez & Gomez (1984), Statistical Procedures for Agricultural Research, Table
  2.1; the ANOVA it is checked against is Table 2.2. Transcribed from the book and checked
  against its printed treatment totals and grand total.
