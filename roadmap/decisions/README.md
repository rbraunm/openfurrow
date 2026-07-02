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
| 0001 | SQLite-canonical store                | Accepted          | yes        | Single SQLite file via SQLAlchemy, schema-portable to PostgreSQL; relational, not NoSQL; CSV/JSON/spreadsheets are interchange only. Store implemented (flat trial-scoped subset); layout regenerated not stored, ordinal preserves order, value split numeric/text for float exactness. Team-mode/DuckDB remain open. |
| 0002 | Native analysis; oracles validate only| Accepted -- Locked| no (locked)| ANOVA and mean separation computed natively (numpy); statsmodels/agricolae/published tables are opt-in oracles and test-only, never runtime, never the step that produces the answer. Runtime stays permissively licensed; no GPL/R in the compute path. Locked: reversing it changes the license posture and the auditability guarantee. |
| 0003 | Missing-data policy                   | Accepted          | yes        | MVP rejects any missing cell with a loud, cell-naming error. Missing data is a first-class, tested future use case (see the matrix in the record): transparent least-squares adjusted means plus a fail-loud estimability check -- the auditability/reproducibility differentiator over ARM's opaque adjustment, not a stat ARM lacks. |
| 0004 | Registry and trial hierarchy          | Proposed          | yes        | Extend the store with first-class Product, Label, and Protocol entities and a program/project/study/trial (+season) hierarchy, so trials are comparable and trackable across trials and years -- the registry role the incumbent desktop tool actually fills (`research/landscape.md`). Deferred, post-MVP. Open: hierarchy levels, protocol/instance divergence, product-ID standard, migrate-in reconciliation. |
| 0005 | Configurable privacy / IAM layer      | Proposed          | yes        | Policy-driven data restriction enforced at the access boundary: file custody + at-rest encryption + export masking locally; identity, roles, row-level access, and an audit log in PostgreSQL team mode. Must define how redaction coexists with the content-hash model (a redacted export is a different, self-labeled document). Deferred, gated on team mode. |
| 0006 | Assumption diagnostics and transforms | Accepted          | yes        | Always-on, report-only ANOVA assumption diagnostics (Brown-Forsythe equal variance, Tukey one-df non-additivity, Shapiro-Wilk normality on residuals) plus explicit per-assessment variance-stabilizing transforms (none/sqrt/log/arcsinSqrt/logit) that run the analysis on the transformed scale and enter the content hash; means back-transformed and labeled. Diagnostics never alter the analysis; a transform is an owned, recorded decision, never inferred. New native functions (normal CDF via erf, inverse normal AS 241, Shapiro-Wilk AS R94) under 0002, oracle-validated. Classical transforms now; GLMs a separate future track. |
| 0007 | Localization-ready architecture       | Accepted          | yes        | Build for localization now, localize later. In force now for all code: no hardcoded user-facing strings (external keyed message catalogs), locale-aware number/date formatting, translatable report templates, and analyst-core vs community-facing surfaces kept separable so the field-facing parts can be localized first. Deferred and partner-pulled: actual language packs, the first language (likely French, plus field languages such as Swahili/Amharic/Hausa), the i18n mechanism (GUI-era), and glossary stewardship (owned by the partner). Readiness is audience-independent and does NOT commit the project to the global-South audience; that call is separate. Non-ASCII rendering is a UTF-8/Web-UI-era concern, not today. |

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
