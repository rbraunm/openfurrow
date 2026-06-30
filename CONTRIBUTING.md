# Contributing to OpenFurrow

OpenFurrow is open, reproducible management for agricultural trials -- a portable,
auditable alternative to Excel/Access and single-vendor (ARM-style) trial workflows. The
mission shapes the rules below: results must be reproducible and validated, and the data
they are validated against must be honestly sourced.

The authoritative design and engineering rules live in `brief.md` (the design brief),
`CLAUDE.md`, and `roadmap/decisions/`. Read those for the data model, the reproducibility
policy, the no-silent-fallback rule, and the field conventions (ARM's AOV Means Table,
BrAPI/Field Book import). This file covers the norm that is easiest to forget: keeping
validation and its test data honest.

## Oracles: every reported number is validated

OpenFurrow never presents an unvalidated statistic as a fact. Each analysis result is
checked against at least one oracle and carries its method, library versions, and
validation status. The oracles, strongest first:

- **Published tables** -- an ANOVA table from the literature, independent of any software,
  and the strongest anchor. The primary anchor is the Yates oats RCBD (see the registry).
- **statsmodels** -- an independent implementation, used as a cross-check oracle and a
  test-only dependency. It validates; it is never part of the runtime analysis path
  (decision 0002).
- **agricolae** (R) -- a reference for mean-separation behavior (Fisher's Protected LSD,
  alpha 0.05), consulted for parity, not vendored.

A result that matches no oracle is not trustworthy: the self-authored computation must
agree with an oracle within a documented tolerance.

## Test data: referenced by provenance, never vendored

`roadmap/research/test-data.md` is the registry of source and test material -- which
datasets we use, what each one is for, how to use it, and its license and citation. The
rule: **track the reference, not the data.** Third-party datasets are not committed into
the repo. Each fixture is transcribed or exported from its cited source with a provenance
header (dataset name, source version, original citation); agridat-derived material cites
both agridat (MIT) and the original publication. Data values are facts; their selection,
provenance, and intended use are what we version here.

When a dataset becomes usable for a new study type, add it to the registry with its
coverage role before wiring tests against it -- the registry should always reflect what
the suite actually validates against.

## Where things live

- **Design:** `brief.md` -- the design brief / specification.
- **Roadmap:** `roadmap/README.md` and `roadmap/milestones.md` -- the planning trail and
  the MVP build state.
- **Decisions (ADRs):** `roadmap/decisions/` -- short Status / Context / Decision /
  Consequences records; `roadmap/decisions/README.md` defines the process and indexes the
  decisions made so far.
- **Research:** `roadmap/research/` -- findings gathered by exercising the field and the
  tools, including the test-data registry.

## Engineering norms

Reproducible by default; fail loud with no silent fallbacks; own the core math (oracles
validate only); open and portable storage; exact-and-auditable before fast-or-convenient.
These are stated in `CLAUDE.md` and recorded in `roadmap/decisions/`. One commit per
logical checkpoint; work lands on the `claude` branch and is merged by the owner via PR.
