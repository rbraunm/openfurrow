# SPDX-License-Identifier: Apache-2.0
"""Read a CSV or an Excel workbook into one table of text cells (decision 0031).

Both shapes come out the same: a header row and data rows of cell text, so the import
that follows, its preview and its column mapping do not care where the file came from.
The .xlsx reader is native (decision 0002): an Office Open XML workbook is a zip of XML
parts, read here with the standard library. Number cells come out in the shortest text
that reads back to the same double; a formula cell gives the value Excel last computed.

Anything the reader cannot take exactly is refused by name: another workbook format, an
error cell, a formula with no computed value, a header that repeats, a column with values
but no header, a row longer than the header.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict

maximumUnpackedBytes = 64 * 1024 * 1024
_cellReference = re.compile(r"^([A-Z]+)([0-9]+)$")
_relationshipNamespace = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_strictRelationshipNamespace = "http://purl.oclc.org/ooxml/officeDocument/relationships"


class SpreadsheetError(ValueError):
  """A file that cannot be read as a table exactly."""


class SheetTable(BaseModel):
  """A header and the data rows of one CSV or worksheet, every cell as text."""

  model_config = ConfigDict(extra="forbid")

  fileName: str
  sheetName: str | None
  sheetNames: list[str]
  header: list[str]
  rows: list[list[str]]
  rowNumbers: list[int]


def readTable(fileName: str, data: bytes, sheetName: str | None = None) -> SheetTable:
  """Read a .csv or .xlsx file's bytes; for a workbook, the named sheet or else the first."""
  suffix = PurePosixPath(fileName.replace("\\", "/")).suffix.lower()
  if suffix == ".csv":
    if sheetName is not None:
      raise SpreadsheetError(f"'{fileName}' is a CSV file; it has no sheet '{sheetName}'")
    return _table(fileName, None, [], _csvRows(fileName, data))
  if suffix == ".xlsx":
    sheetNames, chosen, grid = _workbookRows(fileName, data, sheetName)
    return _table(fileName, chosen, sheetNames, grid)
  raise SpreadsheetError(
    f"'{fileName}': only .csv and .xlsx files can be read; save an .xls or .ods workbook as .xlsx first"
  )


def _csvRows(fileName: str, data: bytes) -> list[list[str]]:
  try:
    text = data.decode("utf-8-sig")
  except UnicodeDecodeError as error:
    raise SpreadsheetError(
      f"'{fileName}' is not UTF-8 text (byte {error.start}); save it as CSV UTF-8"
    ) from error
  return [list(row) for row in csv.reader(io.StringIO(text, newline=""))]


def _table(fileName: str, sheetName: str | None, sheetNames: list[str], grid: list[list[str]]) -> SheetTable:
  where = f"'{fileName}'" + (f" sheet '{sheetName}'" if sheetName is not None else "")
  numbered = [(number, row) for number, row in enumerate(grid, start=1) if any(cell.strip() for cell in row)]
  if not numbered:
    raise SpreadsheetError(f"{where} is empty")
  header = [cell.strip() for cell in numbered[0][1]]
  width = len(header)
  while width and not header[width - 1]:
    width -= 1
  rows = []
  for rowNumber, row in numbered[1:]:
    extra = [cell for cell in row[width:] if cell.strip()]
    if extra:
      raise SpreadsheetError(f"{where} row {rowNumber} has values beyond the last named column: {extra}")
    rows.append([cell.strip() for cell in row[:width]] + [""] * (width - len(row[:width])))
  header = header[:width]
  unnamed = [index + 1 for index, name in enumerate(header) if not name]
  if unnamed:
    raise SpreadsheetError(f"{where}: column(s) {unnamed} have no name in the header row")
  repeated = sorted({name for name in header if header.count(name) > 1})
  if repeated:
    raise SpreadsheetError(f"{where}: the header names these columns more than once: {repeated}")
  return SheetTable(
    fileName=fileName, sheetName=sheetName, sheetNames=sheetNames, header=header, rows=rows,
    rowNumbers=[number for number, _ in numbered[1:]],
  )


def _localName(tag: str) -> str:
  return tag.rsplit("}", 1)[-1]


def _children(element, name: str):
  return [child for child in element if _localName(child.tag) == name]


def _descendants(element, name: str):
  return [child for child in element.iter() if _localName(child.tag) == name]


def _workbookRows(fileName: str, data: bytes, sheetName: str | None) -> tuple[list[str], str, list[list[str]]]:
  try:
    archive = zipfile.ZipFile(io.BytesIO(data))
  except zipfile.BadZipFile as error:
    raise SpreadsheetError(f"'{fileName}' is not an .xlsx workbook (not a zip archive)") from error
  with archive:
    if sum(info.file_size for info in archive.infolist()) > maximumUnpackedBytes:
      raise SpreadsheetError(f"'{fileName}' unpacks to more than {maximumUnpackedBytes} bytes")

    def part(name: str):
      try:
        return ElementTree.fromstring(archive.read(name))
      except KeyError as error:
        raise SpreadsheetError(f"'{fileName}' has no part '{name}'; it is not an .xlsx workbook") from error
      except ElementTree.ParseError as error:
        raise SpreadsheetError(f"'{fileName}' part '{name}' is not well-formed XML: {error}") from error

    workbook = part("xl/workbook.xml")
    relationships = {
      element.get("Id"): element.get("Target")
      for element in _descendants(part("xl/_rels/workbook.xml.rels"), "Relationship")
    }
    sheets = []
    for sheet in _descendants(workbook, "sheet"):
      relationship = sheet.get(f"{{{_relationshipNamespace}}}id") or sheet.get(f"{{{_strictRelationshipNamespace}}}id")
      target = relationships.get(relationship)
      if target is None:
        raise SpreadsheetError(f"'{fileName}': sheet '{sheet.get('name')}' points at no part")
      path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
      sheets.append((sheet.get("name"), path))
    if not sheets:
      raise SpreadsheetError(f"'{fileName}' has no sheets")
    sheetNames = [name for name, _ in sheets]
    if sheetName is None:
      sheetName = sheetNames[0]
    if sheetName not in sheetNames:
      raise SpreadsheetError(f"'{fileName}' has no sheet '{sheetName}'; its sheets are {sheetNames}")
    sharedStrings = []
    if "xl/sharedStrings.xml" in archive.namelist():
      sharedStrings = [_richText(item) for item in _children(part("xl/sharedStrings.xml"), "si")]
    worksheet = part(dict(sheets)[sheetName])
  return sheetNames, sheetName, _sheetGrid(fileName, sheetName, worksheet, sharedStrings)


def _richText(element) -> str:
  """The text of a shared or inline string: its own t, or its runs' t, never phonetic runs."""
  pieces = []
  for child in element:
    name = _localName(child.tag)
    if name == "t":
      pieces.append(child.text or "")
    elif name == "r":
      pieces += [t.text or "" for t in _children(child, "t")]
  return "".join(pieces)


def _columnIndex(letters: str) -> int:
  index = 0
  for letter in letters:
    index = index * 26 + ord(letter) - ord("A") + 1
  return index - 1


def _numberText(text: str, where: str) -> str:
  try:
    value = float(text)
  except ValueError as error:
    raise SpreadsheetError(f"{where}: number cell holds '{text}'") from error
  if value.is_integer() and abs(value) < 1e15:
    return str(int(value))
  return repr(value)


def _sheetGrid(fileName: str, sheetName: str, worksheet, sharedStrings: list[str]) -> list[list[str]]:
  data = _descendants(worksheet, "sheetData")
  if len(data) != 1:
    raise SpreadsheetError(f"'{fileName}' sheet '{sheetName}' has no cell data")
  grid: dict[int, dict[int, str]] = {}
  nextRow = 0
  for row in _children(data[0], "row"):
    rowIndex = int(row.get("r")) - 1 if row.get("r") else nextRow
    nextRow = rowIndex + 1
    cells = grid.setdefault(rowIndex, {})
    nextColumn = 0
    for cell in _children(row, "c"):
      reference = cell.get("r")
      if reference:
        match = _cellReference.match(reference)
        if match is None:
          raise SpreadsheetError(f"'{fileName}' sheet '{sheetName}': cell reference '{reference}' is not valid")
        columnIndex = _columnIndex(match.group(1))
      else:
        columnIndex = nextColumn
        reference = f"row {rowIndex + 1} column {columnIndex + 1}"
      nextColumn = columnIndex + 1
      cells[columnIndex] = _cellText(cell, f"'{fileName}' sheet '{sheetName}' cell {reference}", sharedStrings)
  if not grid:
    return []
  width = max((max(cells) + 1 for cells in grid.values() if cells), default=0)
  return [[grid.get(rowIndex, {}).get(column, "") for column in range(width)] for rowIndex in range(max(grid) + 1)]


def _cellText(cell, where: str, sharedStrings: list[str]) -> str:
  kind = cell.get("t", "n")
  values = _children(cell, "v")
  value = values[0].text if values else None
  if kind == "inlineStr":
    inline = _children(cell, "is")
    return _richText(inline[0]) if inline else ""
  if kind == "e":
    raise SpreadsheetError(f"{where} holds the error {value}")
  if value is None:
    if _children(cell, "f"):
      raise SpreadsheetError(f"{where} holds a formula with no computed value; open and save it in Excel first")
    return ""
  if kind == "s":
    index = int(value)
    if not 0 <= index < len(sharedStrings):
      raise SpreadsheetError(f"{where} points at shared string {index}, which does not exist")
    return sharedStrings[index]
  if kind in ("str", "d"):
    return value
  if kind == "b":
    return "TRUE" if value == "1" else "FALSE"
  if kind == "n":
    return _numberText(value, where)
  raise SpreadsheetError(f"{where} has the unknown cell type '{kind}'")
