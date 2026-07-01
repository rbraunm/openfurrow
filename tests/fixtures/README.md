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
