# 0001 - SQLite-canonical store

**Status:** Proposed (open -- not yet locked). Reversible.

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

## Why open

The store is not yet implemented, and two questions could still reshape it: how team mode
on PostgreSQL actually lands, and whether a DuckDB analytics path changes the layering.
Left open deliberately -- adopt the direction, but it is not locked until the store exists
and those questions are answered.

## Consequences

- A trial package is a single hashable file: hash the file, you have hashed the data, which
  serves the reproducibility manifest directly.
- The SQLAlchemy layer lets PostgreSQL back team mode without rewriting the schema.
- We carry an ORM dependency, and must keep the schema within the portable intersection of
  SQLite and PostgreSQL.
