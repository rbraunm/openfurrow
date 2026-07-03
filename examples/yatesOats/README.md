# Worked example: Yates oat variety trial

A complete run of the OpenFurrow loop on a real, published dataset -- Yates's 1935
oat variety trial, a randomized complete block design with three varieties in six
blocks. Its analysis of variance is documented in the literature, so this example
doubles as a check that the tool reproduces a known result.

Files:

- `trial.json` -- the trial package: metadata, three varieties, the RCBD (six blocks,
  seed 1), and one numeric assessment (grain yield).
- `observations.csv` -- one yield value per plot, in long format
  (`plotNumber, assessmentCode, value`). The plot numbers come from the randomized
  layout for seed 1.

## Run it

From the repository root (the `openfurrow` command is available after
`pip install .`; here we use the module form so no install is needed):

```bash
of="python -m openfurrow.cli.main"

$of init oats.db
$of add oats.db examples/yatesOats/trial.json
$of randomize oats.db yatesOats1935          # the field plan: plot -> block, variety
$of import oats.db yatesOats1935 examples/yatesOats/observations.csv
$of report oats.db yatesOats1935             # the AOV Means Table
$of export oats.db yatesOats1935 --json oats.json --csv oats-obs.csv
$of verify oats.db yatesOats1935             # round-trip reproducibility check
```

## What you should see

The analysis reproduces the published Yates table:

```
### Analysis of variance

| Source | df | SS | MS | F | P |
|---|---:|---:|---:|---:|---:|
| Block | 5 | 3968.8194 | 793.7639 | 5.28 | 0.0124 |
| Treatment | 2 | 446.5903 | 223.2951 | 1.49 | 0.2724 |
| Error | 10 | 1503.3264 | 150.3326 | - | - |
| Total | 17 | 5918.7361 | - | - | - |

- Grand mean: 103.972 (qtr-lb/plot)
- Coefficient of variation: 11.79%
```

The variety effect is **not** significant (P = 0.27), so the protected LSD performs
no separation and all three varieties share one letter -- the correct, honest
outcome rather than a spurious ranking.

The report ends with a reproducibility block. The **input hash** is
environment-independent:

```
- Input hash (SHA-256): 50fbfb3a9d27652346db28631b55ebdbee91204a003a7a2b88e77d4db4a94ded
```

`verify` re-exports and re-imports the trial and confirms this same hash, and
`import-json oats2.db oats.json` into a fresh database yields a trial with an
identical hash: the JSON export is a faithful, movable copy of the record. (The
library-version line in the report varies by environment; the input hash does not.)

## Data provenance

The yields are Yates's 1935 oat variety trial as reproduced in standard worked RCBD
examples; see `tests/fixtures/README.md` and `roadmap/research/test-data.md`. The
data is transcribed for illustration, not vendored from any product.
