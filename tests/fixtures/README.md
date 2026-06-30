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
