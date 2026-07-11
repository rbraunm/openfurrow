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
