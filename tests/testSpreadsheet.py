# SPDX-License-Identifier: Apache-2.0
"""Reading a CSV or an .xlsx workbook into one table (decision 0031).

Workbooks written by openpyxl are read back and compared with what openpyxl itself reads;
hand-built parts cover what other writers (Excel among them) put in a workbook: rich
shared strings with phonetic runs, inline strings, cells without references, booleans,
error cells and absolute part paths.
"""

import io
import zipfile

import pytest

from openfurrow.importers import SpreadsheetError, readTable

openpyxl = pytest.importorskip("openpyxl")


def workbookBytes(sheets):
  workbook = openpyxl.Workbook()
  workbook.remove(workbook.active)
  for name, rows in sheets.items():
    sheet = workbook.create_sheet(name)
    for row in rows:
      sheet.append(row)
  buffer = io.BytesIO()
  workbook.save(buffer)
  return buffer.getvalue()


def openpyxlText(value):
  if value is None:
    return ""
  if isinstance(value, float):
    return str(int(value)) if value.is_integer() else repr(value)
  return str(value)


def testWorkbookReadsAsOpenpyxlReadsIt():
  rows = [
    ["Plot", "Yield kg", "Note", "Severity"],
    [101, 4812.5, "lodged", 0.1],
    [102, 1 / 3, None, 1e-7],
    [103, 123456789.125, "edge", 12],
    [104, -0.0, "", 3.0],
  ]
  data = workbookBytes({"Field data": rows, "Notes": [["Remark"], ["second sheet"]]})
  table = readTable("trial.xlsx", data)
  reference = openpyxl.load_workbook(io.BytesIO(data))["Field data"]
  expected = [[openpyxlText(cell.value) for cell in row] for row in reference.iter_rows()]
  assert [table.header] + table.rows == expected
  assert table.sheetNames == ["Field data", "Notes"] and table.sheetName == "Field data"
  assert table.rowNumbers == [2, 3, 4, 5]
  assert float(table.rows[1][1]) == 1 / 3
  other = readTable("trial.xlsx", data, "Notes")
  assert (other.header, other.rows) == (["Remark"], [["second sheet"]])


def testUnknownSheetIsNamed():
  data = workbookBytes({"A": [["x"]]})
  with pytest.raises(SpreadsheetError, match=r"has no sheet 'B'; its sheets are \['A'\]"):
    readTable("t.xlsx", data, "B")


def testFormulaWithoutComputedValueIsRefused():
  data = workbookBytes({"S": [["Plot", "Y"], [101, "=1+1"]]})
  with pytest.raises(SpreadsheetError, match="cell B2 holds a formula with no computed value"):
    readTable("t.xlsx", data)


_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_relationships = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def handBuilt(sheetData, sharedStrings=None, target="worksheets/sheet1.xml"):
  buffer = io.BytesIO()
  with zipfile.ZipFile(buffer, "w") as archive:
    archive.writestr("[Content_Types].xml", "<Types/>")
    archive.writestr("xl/workbook.xml", (
      f'<workbook xmlns="{_main}" xmlns:r="{_relationships}"><sheets>'
      f'<sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'))
    archive.writestr("xl/_rels/workbook.xml.rels", (
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      f'<Relationship Id="rId1" Type="worksheet" Target="{target}"/></Relationships>'))
    if sharedStrings is not None:
      archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{_main}">{sharedStrings}</sst>')
    archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{_main}"><sheetData>{sheetData}</sheetData></worksheet>')
  return buffer.getvalue()


def testWhatOtherWritersPutInAWorkbook():
  shared = (
    "<si><t>Plot</t></si>"
    "<si><r><t>Yield </t></r><r><rPr><b/></rPr><t>kg</t></r><rPh sb='0' eb='1'><t>IGNORED</t></rPh></si>"
  )
  data = handBuilt(
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="inlineStr"><is><t>Seen</t></is></c></row>'
    '<row r="3"><c><v>101</v></c><c><v>4.25E3</v></c><c t="b"><v>1</v></c></row>',
    shared, target="/xl/worksheets/sheet1.xml",
  )
  table = readTable("excel.xlsx", data)
  assert (table.header, table.rows, table.rowNumbers) == (["Plot", "Yield kg", "Seen"], [["101", "4250", "TRUE"]], [3])


def testAColumnWithValuesButNoHeaderIsRefused():
  data = handBuilt(
    '<row r="1"><c r="A1" t="inlineStr"><is><t>Plot</t></is></c><c r="C1" t="inlineStr"><is><t>Seen</t></is></c></row>'
    '<row r="2"><c r="A2"><v>101</v></c><c r="B2"><v>5</v></c><c r="C2" t="b"><v>0</v></c></row>'
  )
  with pytest.raises(SpreadsheetError, match=r"column\(s\) \[2\] have no name in the header row"):
    readTable("t.xlsx", data)


def testErrorCellIsRefusedByItsReference():
  data = handBuilt('<row r="1"><c r="A1" t="inlineStr"><is><t>Y</t></is></c></row><row r="2"><c r="A2" t="e"><v>#DIV/0!</v></c></row>')
  with pytest.raises(SpreadsheetError, match="sheet 'Data' cell A2 holds the error #DIV/0!"):
    readTable("t.xlsx", data)


def testCsvByteOrderMarkAndBlankRows():
  data = "﻿Plot,Y,,\r\n101,4.5,,\r\n,,,\r\n102,,,\r\n".encode("utf-8")
  table = readTable("t.csv", data)
  assert (table.header, table.rows, table.rowNumbers) == (["Plot", "Y"], [["101", "4.5"], ["102", ""]], [2, 4])


@pytest.mark.parametrize("fileName, data, message", [
  ("t.csv", "Plot,Y\n101,é\n".encode("latin-1"), r"'t.csv' is not UTF-8 text \(byte 11\); save it as CSV UTF-8"),
  ("t.csv", b"Plot,Y,Plot\n1,2,3\n", r"the header names these columns more than once: \['Plot'\]"),
  ("t.csv", b"Plot,Y\n101,4,9\n", r"'t.csv' row 2 has values beyond the last named column: \['9'\]"),
  ("t.csv", b"\n,\n", "'t.csv' is empty"),
  ("t.xls", b"\xd0\xcf\x11\xe0", r"only \.csv and \.xlsx files can be read; save an \.xls or \.ods workbook as \.xlsx first"),
  ("t.xlsx", b"Plot,Y\n", r"'t.xlsx' is not an \.xlsx workbook \(not a zip archive\)"),
])
def testWhatCannotBeReadExactlyIsRefused(fileName, data, message):
  with pytest.raises(SpreadsheetError, match=message):
    readTable(fileName, data)
