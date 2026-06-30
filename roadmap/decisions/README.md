# Decision Records

Short records of choices that must be settled before or during code, because the code
keys off them. Format: **Status / Context / Decision / Consequences**. They are reversible
where noted; "locked" means an extra are-you-sure step, never immutability -- every record
stays reviewable.

Individual records are added to this folder as `NNNN-title.md` as they are written up. The
ledger below is the current authority and the index: it captures each decision made so far
with its status and rationale in brief.

## Ledger

| #    | Decision                              | Status   | Reversible | Summary |
|------|---------------------------------------|----------|------------|---------|
| 0001 | Decision-record process               | Accepted | --         | This format; locked = extra confirmation, not immutability. |
| 0002 | Python 3.13 target                    | Accepted | yes        | Runtime targets Python 3.13. A sandbox or CI may run 3.12, but the declared target stays 3.13 rather than being weakened to match a tooling quirk. |
| 0003 | SQLite-canonical store                | Accepted | yes        | The canonical store is a single SQLite file via SQLAlchemy, schema-portable to PostgreSQL. Relational, not NoSQL. CSV/JSON/spreadsheets are interchange only, never the system of record. |
| 0004 | Reproducible by default               | Accepted | no         | Randomization seed is mandatory; results carry method, library versions, input hash, and validation status. A layout or result that cannot be reproduced is not valid output. |
| 0005 | Native analysis; oracles validate only| Accepted | yes        | ANOVA and mean separation are computed natively (numpy). statsmodels, agricolae, and published tables are opt-in known-answer oracles and test-only dependencies -- never a runtime dependency, never the step that produces the answer. The runtime stays permissively licensed; GPL/R tooling is not pulled into the compute path. |
| 0006 | RCBD-first scope                      | Accepted | yes        | The MVP analyzes single-factor randomized complete block designs. Factorial, split-plot, and multi-environment designs are recorded as future scope, not built. |
| 0007 | Missing-data: reject (MVP)            | Accepted | yes        | Missing observation cells are rejected with a loud, cell-naming error rather than silently imputed. Yates' missing-plot technique and least-squares adjusted means (ARM parity) are deferred as explicit, opt-in settings -- never silent fallbacks. |
| 0008 | Long canonical, wide supported        | Accepted | yes        | Long-format is the canonical observation atom; wide is a first-class accepted input, converted to long. Two-tier config: a stored import profile plus per-import overrides. The resolved column mapping is recorded for reproducibility. Grounded in BrAPI / Field Book / ARM. |
| 0009 | Analysis follows ARM, configurably    | Accepted | yes        | The analysis mirrors ARM's AOV Means Table: ANOVA, treatment means, Fisher's Protected LSD, and CV. Significance level defaults to 0.05; the mean-comparison test and significance level are configurable per study. |

## Backfill

Each ledger row will graduate into a full `NNNN-title.md` record (Context / Decision /
Consequences) as it is expanded, the way `brief.md` sections deepen into design. Until
then, the ledger row is the record. New decisions are added to the ledger first, then
written up.
