# CLAUDE.md -- OpenFurrow

Open, reproducible, auditable management for agricultural trials -- field, greenhouse,
and efficacy research. In practice the workflow is split across two silos: a registry tool
(protocols, product IDs, labels, cross-year tracking -- ARM's role) and a separate cloud
analysis/visualization suite, neither easily portable. OpenFurrow's long-term goal is to
bridge both on one open, portable, owned foundation, with the data portability and
configurable privacy the incumbents lack (see `roadmap/research/landscape.md`). One
validated schema, open formats, reproducible by default.

Authoritative design and contributor rules live in `brief.md` (the design brief),
`CONTRIBUTING.md`, `roadmap/decisions/` (the decision records), and `roadmap/README.md`.
**Read `CONTRIBUTING.md` first** -- it names the validation oracles, the test-data
registry, and the design/roadmap/decision paths. Those govern on any conflict with this
file.

## Core principles (these are the project, not preferences)
- **Reproducible by default.** Every trial layout is regenerable from a
  recorded seed, and every analysis result carries its method, library versions, input
  hash, and a validation status. A layout or result that cannot be reproduced is not
  valid output.
- **Never present an unvalidated number as a fact.** Each reported statistic is checked
  against an oracle -- a published table and/or an independent implementation
  (statsmodels) -- and carries that provenance. See `CONTRIBUTING.md` and
  `roadmap/research/test-data.md`.
- **Own the core math; oracles validate, they do not compute (decision 0002).** The
  ANOVA and mean separation are computed natively (numpy). statsmodels, agricolae, and
  published tables are opt-in validators / known-answer oracles ONLY -- never a runtime
  dependency of an analysis, never the step that produces the answer. The runtime stays
  minimal and permissively licensed; GPL/R tooling is not pulled into the compute path.
- **Open, portable storage (decision 0001).** The canonical store is a single SQLite
  file via SQLAlchemy, schema-portable to PostgreSQL. Open formats (long-format CSV) are
  the interchange; spreadsheets and JSON are import/export, never the system of record.
  Portability is the wedge against the cloud-locked incumbents: import from their formats
  so adoption never means re-keying, and export openly so data is never re-locked. The
  database and a JSON export agree on the content hash -- data is never trapped in the
  store.
- **Fail loud, no silent fallbacks.** Invalid data is rejected at the boundary it enters.
  Missing observation cells are rejected (decision 0003), not silently imputed. No
  second-strategy fallback runs behind a failed primary path.

## Match the field, configurably
The analysis mirrors what agricultural researchers expect from ARM's AOV Means Table: the
ANOVA, treatment means, mean separation (Fisher's Protected LSD by default), and CV, with
the significance level (default 0.05) and the mean-comparison test configurable per study
in the project config. The import model follows BrAPI/Field Book conventions: long-format
is canonical, wide is accepted and converted, and the resolved column mapping is recorded
for reproducibility.

## Scope
The MVP analyzes single-factor randomized complete block designs. Factorial, split-plot,
and multi-environment designs are recorded as future scope (`roadmap/milestones.md`,
`roadmap/research/test-data.md`), not built yet. Build the exact, auditable balanced
analysis first; reach ARM's unbalanced behavior (least-squares means) as a later, explicit
setting.

Beyond the analysis engine, the long-term direction (`roadmap/research/landscape.md`) is the
bridge: a protocol/product/label registry with a project/study/trial hierarchy (decision
0004), analysis-and-visualization, interoperability that imports from the incumbent tools,
and a configurable privacy/IAM layer (decision 0005) whose redaction must be reconciled with
the content-hash model. These are recorded and proposed, not built. ARM feature parity is the
long-term target, filtered through the reproducibility/openness/ownership differentiators --
some ARM features are deliberately not worth building.

## Testing
Tests make real assertions about computed results, validated against the oracles and the
provenanced datasets in `roadmap/research/test-data.md`. No monkeypatching the logic under
test. Tests verify behavior; they never drive design. Known-answer fixtures pin results
against published tables; statsmodels is the independent cross-check.

## Python
Invoke as `python`, not `python3`. Inside Debian containers and provisioning scripts the
system interpreter is `python3`.

---
Global engineering standards (git workflow, fail-loud philosophy, no dead code, naming
conventions, PowerShell rules) are the operator's cross-project conventions and apply here;
repo-specific rules live in this file, `CONTRIBUTING.md`, and `roadmap/decisions/`.
Transient session state and host-specific notes live in `CLAUDE.local.md` (gitignored),
not here.
