# 0004 - Protocol, product, and label registry with a trial hierarchy

**Status:** Proposed (deferred; post-MVP, long-term). Direction adopted, not locked.

## Context

The MVP store is flat and trial-scoped: one trial, its treatments, assessments, and
observations (decision 0001). Field intel (`research/landscape.md`) shows the durable
value of the incumbent desktop tool is not analysis but a **registry** -- protocols,
product IDs, and labels associated to trials so results stay comparable and trackable
across many trials and many years. To be the one-stop-shop that bridges the
registry and the analysis layers, OpenFurrow has to model that registry, not just a
single trial in isolation. Decision 0001 already anticipated a hierarchy ("a project
contains studies, a study contains trials"); this record makes it a first-class
objective.

## Decision (proposed)

Extend the canonical relational model (still SQLite-canonical, PostgreSQL-portable,
per decision 0001) with:

- **Product** -- a stable product identity (product ID, name, formulation / active
  ingredient(s), registration status) reused across trials and years. Treatments
  reference a product rather than restating it.
- **Label** -- label information (rates, target crops/pests, use directions) tied to
  a product, so a trial's treatments can be checked and reported against the label.
- **Protocol** -- a reusable trial template (design defaults, treatment regime,
  assessment plan) that trials instantiate, so a multi-site or multi-year program
  runs many trials from one protocol and they remain comparable.
- **Hierarchy** -- program / project -> study -> trial, plus a season/year dimension,
  so trials roll up for across-trial and across-year summaries (the registry role).

Product IDs and protocol identity are stable across trials and years; that stability
is what makes comparability and tracking work.

## Consequences

- The content-hash / reproducibility model extends from a single trial to trials that
  reference shared registry entities; hashing must account for referenced product /
  protocol identity, not just inline data.
- Cross-trial and across-year analysis (summaries, trends) becomes possible and is a
  distinct analysis surface from the single-trial AOV Means Table.
- Import from the incumbent registry (its protocols and product catalog) becomes a
  concrete interoperability target so adoption does not require re-keying history.

## Open questions

- Exact hierarchy levels and whether "program" and "season" are separate axes.
- How a protocol template and its trial instances are allowed to diverge.
- Depth of the product/label model, and whether product identifiers should align to
  an external standard (regulatory registration numbers, a public product ontology).
- Migration path and identity reconciliation when importing an existing registry.
