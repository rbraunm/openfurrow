# 0013 - Interoperability

**Status:** Accepted. Direction adopted, not locked. Reversible.

## Context

The platform plan (Lane E) makes OpenFurrow field-capable and archive-ready through the
existing ecosystem rather than in isolation. The grounding note
(`../research/platform-and-interop.md`) establishes the targets: Field Book (file and
BrAPI), BrAPI v2 (a scoped subset; agronomy is in scope), MIAPPE 1.1 metadata, and
deposit into endowed archives with DOIs (the near-term step toward the archive north star
in `vision.md`). The audience (ADR 0008) already uses these; the standards are integration
targets, not competitors.

## Decision

- **Field Book interop in two rungs.** (1) File-based first: OpenFurrow exports a Field
  Book-compatible layout file (entry identifiers plus the plot map) and a trait file, and
  ingests the collected CSV back into the trial -- fully offline, no server. (2) BrAPI
  next: a scoped BrAPI server subset that Field Book and other BrAPI tools import fields
  and traits from and push observations back to.
- **A scoped BrAPI v2 subset, not the whole specification.** Core (studies, trials,
  programs, locations) plus Phenotyping (observation variables, observation units,
  observations), read and write per BrAPI v2. OpenFurrow's studies map to Field Book
  fields, observation variables to traits, and observations to collected data. The
  genotyping and germplasm modules are out of scope.
- **MIAPPE 1.1** is the metadata vocabulary for archive-ready export and for structuring
  what a trial records; BrAPI can carry MIAPPE-conformant metadata.
- **Deposit and DOIs.** OpenFurrow can deposit a trial package into an existing endowed
  archive (for example Dryad or Zenodo) and mint a DOI -- durability and discovery now,
  and the near-term first step toward the owned archive (`vision.md`). The content hash
  (ADR 0006) is the fixity anchor for a deposited package.
- **Export and exchange, never lock-in.** Open, portable formats out (the portability
  principle of ADR 0001); nothing re-locks the data.

## Consequences

- Field capability arrives via interop -- the file rung first, needing only the core --
  before any first-party app (ADR 0014) and before a server.
- The BrAPI server subset is bounded, and it pairs with the self-hostable server (ADR
  0011) for live sync.
- MIAPPE plus deposit make trials archive-ready, connecting the tool to the
  reproducibility and archive thesis (`vision.md` and the reproducibility research note).
- The standards evolve (BrAPI versions, MIAPPE revisions); the targeted versions are
  tracked and updated as needed.

## Open questions

- The exact Field Book file-schema mapping (unique, primary, and secondary identifiers
  plus plot) onto our layout.
- Which BrAPI endpoints beyond the minimal set are worth implementing, and how BrAPI
  versions are tracked.
- The deposit target(s) and DOI provider, and how a redacted or embargoed deposit
  interacts with the content-hash identity (ties to the ADR 0005 redaction tension).
