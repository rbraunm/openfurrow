# 0031 - Spreadsheet import with a preview and an explicit column mapping

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Trial data mostly lives in Excel workbooks laid out by whoever collected it: a plot column
under some name, one column per assessment under names that are not the trial's codes,
notes and dates beside them, sometimes several sheets. The brief lists Excel import second
after CSV, and the readiness bar (worklist USR-6) asks for "the export they actually have,
with a preview, an explicit column mapping, and every observation reconciled". Until now
observations came only from a CSV whose shape the project configuration fixed, uploaded
blind.

Reading `.xlsx` is the question of a dependency. openpyxl is the usual library, but the
runtime stays minimal (decision 0002), and what an import needs from a workbook is small:
the sheet names and each cell's text. An Office Open XML workbook is a zip of XML parts that
the standard library reads.

## Decision

- **One table for every file.** A `.csv` (UTF-8, with or without a byte-order mark) or one
  sheet of an `.xlsx` workbook is read into a header and rows of cell text; the import that
  follows does not know which it came from. Blank rows are skipped and row numbers keep the
  file's own. Other formats (`.xls`, `.ods`) are refused with the advice to save as `.xlsx`.
- **The `.xlsx` reader is native.** Number cells give the shortest text that reads back to
  the same double, a formula cell the value Excel last computed, shared strings their text
  without phonetic runs. Refused by name: an error cell, a formula with no computed value, a
  repeated header, a column with values but no header, a row longer than the header, a
  workbook that unpacks to more than 64 MiB.
- **The page previews, then imports.** The file is uploaded and shown (the first ten rows,
  the row count, a sheet choice); the person states the layout -- one row per plot with a
  column per assessment, or one row per value -- and which column holds what, and the
  decimal mark. A first mapping is suggested from column names (plot, an assessment's code,
  a Field Book export's columns) and shown for confirmation; nothing is saved until Import
  is pressed with every choice made. The file travels with the form, so the server keeps no
  state between the steps.
- **A wide mapping names the assessment of each column** (`assessmentColumns` maps a column
  name to an assessment code), so "Yield kg" can feed assessment `Y`. Two columns for one
  assessment, or the plot column as an assessment, are refused.
- **After the import, a reconciliation**: for each assessment, the values imported, those
  marked missing, and the plots the file left out, against the trial's plot count.
- **An import adds values and never replaces them.** A plot and assessment the trial already
  holds a value for refuses the whole file, naming the clashes; stored values are changed on
  the entry page.
- **One import page.** It replaces the trial page's CSV and Field Book upload; a Field Book
  export is recognised by its columns. The JSON API keeps its CSV endpoints.
- **openpyxl is a test oracle only**: workbooks it writes are read back and compared with
  what it reads.

## Consequences

- No schema or store change; the content hash of every trial is unchanged.
- The configuration's `import.wide.assessmentColumns` is a mapping, no longer a list.
- The file as received and the mapping used are kept with the trial (decision 0044).
