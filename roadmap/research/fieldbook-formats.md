# Field Book interop formats (grounding for E1)

Pinned against Field Book **5.4** and the current `main` source of `PhenoApps/Field-Book`
(docs: `docs.fieldbook.phenoapps.org`). This note is the format reference the file-based
round-trip (implementation-plan unit **E1**) builds against, so the exact columns are not
re-derived each session. Field Book is **GPL-2.0**; this is our own description of the
formats, not vendored content, and we do not commit Field Book's own sample files into this
Apache-2.0 repo (see "Fixtures and licensing").

## What Field Book is, in one line

An Android app that replaces the paper field book: import a field layout + a trait list,
walk the field entering trait values per plot, export the collected data. The interop
surface is therefore three files -- a **field import**, a **trait list**, and a **data
export** -- plus a BrAPI path we defer to E2.

## Field import file (we produce this: E1a)

CSV (also XLS/XLSX). Each row is one entry (a plot). Columns are arbitrary; at import the
user designates three of them:

- a **unique identifier** -- unique across all of the user's fields, used internally to
  attach data to the entry;
- a **primary** identifier and a **secondary** identifier -- together they set the walk
  order through the field.

Any remaining columns ride along as entry attributes (shown as InfoBars in Collect, and
echoed back on export). Column headers and file names must exclude `/ ? < > \ * | "`.

The shipped sample header (a wheat breeding field): `plot_id, row, column, plot, tray_row,
tray_id, seed_id, seed_name, pedigree`.

**OpenFurrow mapping (proposed for E1a):** emit one row per plot with
`plotNumber` (unique id), `block` (primary), `positionInBlock` (secondary), and `treatment`
as a carried attribute. All derived from the package + regenerated layout via the facade.
Open: whether to also emit `row`/`column` plot geometry (we do not model it yet).

## Trait file `.trt` (we produce this: E1a)

Legacy format is a quoted CSV, one row per trait, header:

`trait, format, defaultValue, minimum, maximum, details, categories, isVisible, realPosition`

- `format` is one of Field Book's trait formats: `numeric, categorical, percent, date,
  boolean, text, counter, photo, location, angle` (and others). We only emit the ones we
  can round-trip.
- `categories` is a slash-joined value list for `categorical` (e.g. `Red/Orange/Yellow`).
- `details` is a free-text note; Field Book uses it for the unit/description shown in Collect.
- `isVisible` is `true`/`false`; `realPosition` is a 1-based display order.

A newer **JSON `.trt`** variant also exists (a `{"traits": [ ... ]}` document with richer
per-trait options). Broadly-compatible target is the legacy CSV `.trt`; the JSON variant is
a follow-up once the CSV round-trip is proven.

**OpenFurrow mapping (proposed for E1a):** one trait row per assessment.
`numeric` assessment -> `numeric` (unit -> `details`, `minValue`/`maxValue` ->
`minimum`/`maximum`); `ordinal`/`categorical` assessment -> `categorical` with
`allowedValues` slash-joined into `categories`. `realPosition` follows assessment order.

## Data export (we ingest this: E1b)

Field Book writes `<field>_database.csv` and/or `<field>_table.csv`.

- **Database (long) format** -- one row per observation. The row is the entry's attribute
  columns (the unique id, or all attributes) followed by exactly, in order:
  `trait, value, timestamp, person, location, number, attached_photo, attached_video,
  attached_audio, device_name`. This is the natural match for our canonical long
  observation model.
- **Table (wide) format** -- one row per entry (unique id + attributes), one column per
  trait.

**OpenFurrow mapping (proposed for E1b):** ingest the **database (long)** export. Map the
unique-id column -> `plotNumber`, `trait` -> `assessmentCode`, `value` -> the observation
value; validate against the trial's layout and package through the existing importer
(long-format profile + a Field Book column mapping). `timestamp`, `person`, `location`,
`device_name`, `number`, and the attachment columns are provenance/extra: carried or
ignored per a build decision in E1b, never silently coerced. The table (wide) export is a
possible secondary path, deferred.

## Fixtures and licensing

Field Book is GPL-2.0. To keep this repo's licensing clean (Apache-2.0, SPDX on every
file) we do **not** commit Field Book's shipped sample files. Instead:

- E1's committed fixtures are **OpenFurrow-authored** files that conform to the formats
  above exactly (a field import we generate, a `.trt` we generate, and a hand-built
  database-format export that mimics a real collection round).
- A real Field Book export can be used as an **uncommitted local conformance check** during
  development; when a real sanctioned sample is available it is recorded per the test-data
  registry conventions (`research/test-data.md`) with its provenance, not vendored blindly.

## Sourcing note

Formats confirmed by reading the current `PhenoApps/Field-Book` source: the field-import
sample under `assets/field_import/`, the trait sample under `assets/trait/`, and the export
header assembled in `CSVWriter.writeDatabaseFormat` (the trailing observation columns) and
`ExportUtil` (database vs table selection). Field Book 5.4 docs corroborate the import rules
and the two export layouts.
