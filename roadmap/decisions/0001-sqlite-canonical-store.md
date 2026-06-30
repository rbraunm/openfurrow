# 0001 - SQLite-canonical store

**Status:** Accepted. The store now exists; the open questions below were resolved in its favor and portability is confirmed as the deciding rationale.

## Context

The trial package needs a system of record. The data model is relational: a project
contains studies, a study contains trials, a trial contains plots, a plot carries
observations, treatments join to plots through the layout, and an append-only audit log
records changes. Both portability and scale matter -- a solo researcher copies a trial
around like a file, and the format must survive growth past the volumes a spreadsheet or
Access file holds.

Four candidate stores, with a real alternative rejected at each step:

- **Loose files (CSV/JSON).** Portable, but no integrity constraints, no transactions, and
  they corrupt and de-sync as a trial grows. Fine as interchange, wrong as the record.
- **NoSQL / document store.** Fights the relational model -- the integrity constraints and
  the append-only audit log that reproducibility depends on are exactly what a document
  store gives up.
- **PostgreSQL-first.** Sound stats and scale, but it imposes a running server, which is
  the wrong default for the solo/portable case and reintroduces the operational weight the
  project exists to avoid.
- **SQLite.** A single file -- copyable and hashable like the loose-file story, but with
  real SQL, constraints, and transactions, and it scales well past the modest volumes
  here.

## Decision

The canonical store is a single **SQLite file accessed through SQLAlchemy**, with a schema
written to be **portable to PostgreSQL** so team mode can adopt a server later without a
schema rewrite. The store is relational, not NoSQL. Open formats (long-format CSV) are the
import/export interchange only, never the system of record. Pydantic stays at the
interchange boundary; the ORM owns the store. DuckDB is noted as a possible future
*analytics* escape hatch (columnar, Apache-2.0, reads SQLite), not the transactional record.

## Implementation

The MVP implements a flat, trial-scoped subset of the relational model above:
`trial` (metadata and design folded 1:1), `treatment`, `assessment`, and
`observation`. The project/study hierarchy and the append-only audit log are
deferred -- they are real parts of the eventual model but not needed to prove the
reproducible loop. Three concrete decisions were made building it:

- **The layout is not stored.** It is a pure function of the package -- the seed,
  the design, and the treatment order -- so per "derive, don't duplicate" it is
  regenerated on demand. This also keeps the input hash (over package and
  observations) a complete description: there is no separately-stored layout that
  could disagree with the seed. Observations carry a `plotNumber`, which the
  deterministic regeneration reproduces exactly.
- **Treatments and assessments carry an explicit `ordinal`.** Their order is
  significant -- the randomizer permutes treatments in package order, and the input
  hash preserves list order -- and SQL row order is not guaranteed, so the order is
  stored and restored explicitly.
- **An observation value is split across two nullable columns,** `numericValue`
  (REAL) and `textValue`, with the assessment's data type selecting which is
  populated and both NULL meaning missing. Native REAL keeps floats bit-exact across
  a round trip, which keeps the hash stable; a single text column would stringify
  them. `allowedValues` (a short list) is stored as a JSON text column rather than a
  child table.

Portability and ownership are served by SQLite **plus** a tested lossless exchange,
not by the file format alone: the database and a JSON export round-trip to the same
input hash, and a CSV export (long format, annotated with block and treatment)
covers the spreadsheet/R path. Moving a trial is copying one file or exporting one
JSON document.

## Still open

Two questions remain genuinely unsettled and will be revisited with evidence rather
than locked now: how team mode on PostgreSQL actually lands (the schema is written
to the portable intersection, but the migration has not been exercised), and whether
a DuckDB analytics path changes the layering. The core direction -- SQLite-canonical
through SQLAlchemy -- is locked.

## Consequences

- A trial package is a single hashable file: hash the file, you have hashed the data, which
  serves the reproducibility manifest directly.
- The SQLAlchemy layer lets PostgreSQL back team mode without rewriting the schema.
- We carry an ORM dependency, and must keep the schema within the portable intersection of
  SQLite and PostgreSQL.
