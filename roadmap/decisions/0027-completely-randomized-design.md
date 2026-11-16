# 0027 - The completely randomized design

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

EPPO PP 1/152 names the completely randomized design beside the randomized complete block
as the two principal designs of efficacy trials, and glasshouse and pot trials use it
where the units are uniform. The tool had only blocked designs (worklist USR-3).

## Decision

- **Design type `crd`**: every treatment on `replications` plots, with no blocks. Its
  layout keeps every plot in block 1, so the record and the analysis need no second shape;
  a layout is refused unless each treatment stands on exactly that many plots.
- **Generated layouts** list every treatment as often as it is replicated and shuffle the
  whole list once on the `sha256FisherYates1` stream; plot k of the list is 100 + k.
- **The analysis** is treatment against experimental error, with the means separated on
  the error as for the RCBD. The assumption checks are Brown-Forsythe and Shapiro-Wilk
  on the departures from the treatment means (decision 0006).
- **Not with a CRD yet:** factors, untreated checks beside plots, spatial balance and a
  first block left in order, each refused by name.
- The trial form offers the CRD beside the RCBD.
- **Validated** against Gomez and Gomez Table 2.2 and statsmodels.

## Consequences

- No store change; the design type is a new value of an existing column.
- The book subtracts a correction factor rounded to 116,484,004 (exactly 116,484,003.57);
  the tests reproduce its arithmetic.
