# 0005 - Configurable data privacy and access (IAM) layer

**Status:** Proposed (deferred; long-term, gated on team mode). Direction adopted, not locked.

## Context

OpenFurrow's differentiator is ownership and portability: a trial is a file the
researcher holds and can move. But field intel (`research/landscape.md`) is that
companies sometimes need to **restrict** trial and product data -- blind product
identities, restrict cooperator or site information, scope access by role -- and not
everything is meant to be shared even within an organization. The cloud incumbents
provide access control only inside their walls and not in a portable form. So
ownership must coexist with controlled confidentiality; "you hold the file" is
necessary but not sufficient.

## Decision (proposed)

A **configurable** privacy / access layer, expressed as policy in configuration and
enforced at the access boundary, not scattered through call sites. Two enforcement
contexts, matching the storage modes in decision 0001:

- **Local / single-user mode.** Confidentiality is file custody plus optional
  at-rest encryption of the SQLite store, plus field-level masking on export (e.g.
  export a trial with product identities blinded or cooperator data omitted).
- **Team mode (PostgreSQL).** Real identity, roles, and row/entity-level access
  control (e.g. PostgreSQL row-level security) scoped to trials, projects, and
  products, plus an append-only audit log of access and change (decision 0001 already
  anticipated an audit log).

Fail loud: a policy that cannot be enforced blocks the operation rather than silently
exposing restricted data. Exports respect the active restrictions.

## Consequences and the reproducibility tension

This interacts directly with the content-hash reproducibility model, and the
interaction must be designed, not left implicit:

- A **masked or redacted export no longer matches the full-record content hash.** A
  redacted document is a *different* document. The layer must define how the two
  coexist -- for example, the full-record hash stays internal to the owning
  organization, and a redacted export carries its own provenance and its own hash,
  clearly marked as redacted rather than masquerading as the full record.
- Reproducibility within the trust boundary (same full inputs, same hash) is
  preserved; reproducibility of a redacted artifact is reproducibility of the
  redaction, which is a weaker and explicitly-labeled claim.

## Open questions

- Policy model: role-based (RBAC) vs. attribute-based (ABAC).
- Granularity: trial / project / product / field-level restriction.
- Masking vs. omission semantics on export, and how each is provenance-labeled.
- Encryption approach for the local store, and key custody.
- How this reconciles with the migrate-in / bridge goal (imported data may carry the
  incumbent's own access assumptions).
