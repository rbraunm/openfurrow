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
| 0007 | Localization-ready architecture       | Accepted          | yes        | Build for localization now, localize later, via an LLM-assisted human-reviewed pipeline. The unit is a locale (BCP-47 code plus CLDR formatting), not a language. In force now for all code: no hardcoded user-facing strings (external keyed catalogs), locale-aware number/date formatting, translatable report templates, analyst core kept separable from community-facing surfaces, and the load-bearing display-only guardrail -- locale affects display only; stored data, exchange, and content hash stay locale-neutral (ISO 8601, dot-decimal) so a trial hashes identically across locales. Locales: en-US and en-GB committable now (no translation); a broad pulled tier led by fr, pt-BR, es-419, then regional anchors ar, hi, id and a secondary pool (bn, vi, tr, ur, fa), broadened beyond the initial Latin-script/Western set for mission fit; zh-Hans explicitly out for now (reach yes, mission no); the GUI to be built bidirectional- and complex-script-capable (RTL for ar/ur/fa). Method: a curated, version-controlled agronomic glossary is the first-class artifact; the LLM drafts and humans sign off; every string carries a status (source / machine-draft / human-approved) and no locale is authoritative until reviewed -- provenance for auditability and journal credibility. Build-time only; no runtime translation call (0002). Audience not committed here. |
| 0008 | Primary early audience (global South) | Accepted          | yes        | Name resource-constrained global-South public-sector agronomy, efficacy, variety-evaluation, and on-farm trial research a primary early audience -- scoped to the analysis and trial-management wedge, explicitly NOT breeding-pipeline or germplasm management (occupied by well-funded platforms: BMS, BreedBase, EBS). Grounded in research/global-south-audience.md: the free purpose-built analysis tool for this audience (GenStat Discovery Edition) was discontinued ~2020, reopening a gap, and its launch rationale (unaffordable stats, incorrect analysis, invisible results) matches the tool's thesis. A design lens and positioning commitment now, gated on partner validation (NARS / RUFORUM / CGIAR center) before heavy build. Localization via an LLM-assisted, human/partner-reviewed pipeline is a deliberate HIGH-VALUE first pass, not a shortcut, with no locale authoritative until reviewed (0007). Reaffirms offline/low-spec, localization-readiness including RTL and GUI mirroring (0007), and CARE-plus-FAIR data sovereignty (0005). |
| 0009 | Service, API, and entry points       | Accepted          | yes        | One bundled application, multiple entry points: a CLI for local analysis and a Flask web/HTTP API that also serves the web UI. The Flask API is the single interface behind every non-CLI surface (web, mobile, server), so the core stays the one implementation of the math (0002). A serve command runs the web app locally; the app installs and uninstalls itself as an OS service (Windows via PowerShell 5.1, systemd on Linux, launchd on macOS) for a personal GUI or a private server. Auth and sessions arrive at the service boundary (deferring to 0005); the local single-user case needs none. |
| 0010 | Core packaging shape                  | Accepted          | yes        | Fixes the invariant -- exactly one implementation of the math (the core), reached through a stable API (0009), never reimplemented per surface (0002) -- and deliberately leaves the packaging and deployment shape open: importable library, embedded in the service, or on-device via native Python, chosen per surface and revisitable. Fixed now: settle a stable internal core API and package the core for reuse. On-device execution stays a legitimate open option. |
| 0011 | Storage, sync, self-hostable server   | Accepted          | yes        | Local-first is the floor (local file plus SQLite, fully offline and owned; 0001). An optional user-owned self-hostable server (the Flask service in server mode, multi-user, with the 0005 privacy, access, audit, and encryption features) provides team collaboration without surrendering data -- self-hosted, not our cloud. A sync model (mechanism open) moves trials and observations between device/analyst and server, with the content hash as a free fixity check. Delivery: a CloudFormation template first (the user's own account, no seller burden), a free AWS Marketplace AMI later (no banking/tax for free products, but support, patch, scan, and hardening obligations). Realizes 0005; evolves 0001. |

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
