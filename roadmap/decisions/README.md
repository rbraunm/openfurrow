# Decision Records

Short records of choices that must be settled before or during code, because the code
keys off them. Format: **Status / Context / Decision / Consequences**. They are reversible
where noted; "locked" means an extra are-you-sure step, never immutability -- every record
stays reviewable.

An ADR earns a record only when there was a real fork with consequences -- an alternative
that was rejected for a reason that future work would otherwise relitigate. Choices with no
contested alternative, and conclusions reached by field research rather than by weighing
options, are recorded in their natural home (a principle in `CLAUDE.md`, a sequencing call
in `milestones.md`, a finding in `research/`), not turned into busywork ADRs.

## Ledger

| #    | Decision                              | Status            | Reversible | Summary |
|------|---------------------------------------|-------------------|------------|---------|
| 0001 | SQLite-canonical store                | Proposed (open)   | yes        | Single SQLite file via SQLAlchemy, schema-portable to PostgreSQL; relational, not NoSQL; CSV/JSON/spreadsheets are interchange only. Left open until the store is built and the team-mode/DuckDB questions resolve. |
| 0002 | Native analysis; oracles validate only| Accepted -- Locked| no (locked)| ANOVA and mean separation computed natively (numpy); statsmodels/agricolae/published tables are opt-in oracles and test-only, never runtime, never the step that produces the answer. Runtime stays permissively licensed; no GPL/R in the compute path. Locked: reversing it changes the license posture and the auditability guarantee. |
| 0003 | Missing-data policy                   | Accepted          | yes        | MVP rejects any missing cell with a loud, cell-naming error. Missing data is a first-class, tested future use case (see the matrix in the record): transparent least-squares adjusted means plus a fail-loud estimability check -- the auditability/reproducibility differentiator over ARM's opaque adjustment, not a stat ARM lacks. |

## Recorded elsewhere (not ADRs)

These were settled, but not by rejecting a real alternative, so they live where they belong
rather than as ADRs:

- **Python 3.13 target** -- no contested alternative; it is the operator's target.
  `pyproject.toml` and `CLAUDE.md`.
- **Reproducible by default** -- the project's premise, not a decision among options.
  `CLAUDE.md` core principles.
- **RCBD-first scope** -- a roadmap sequencing call, not an architecture decision.
  `roadmap/milestones.md`.
- **Long-canonical / wide-supported import model** -- settled by field research
  (BrAPI / Field Book / ARM); the research note is the better record. `roadmap/research/`.
- **ARM-aligned analysis conventions** (AOV Means Table, Fisher's Protected LSD, alpha 0.05,
  configurable per study) -- field convention, not a rejected-alternative fork.
  `roadmap/research/` and `CLAUDE.md`.

## Backfill

New decisions are added to the ledger first, then written up as `NNNN-title.md`. The
process record itself is this file; it is not a numbered ADR.
