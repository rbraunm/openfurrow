# SPDX-License-Identifier: Apache-2.0
"""The import page: preview a CSV or workbook, map its columns, import, reconcile (decision 0031)."""

import base64
import io
import re
from io import BytesIO

import pytest

from openfurrow import TrialPackage, Workspace
from openfurrow.importers import ImportResult, countByAssessment
from openfurrow.schema.observation import Observation
from openfurrow.service import createApp

from testWebReport import _packageDict

openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture
def setup(tmp_path, newStore):
  path = newStore("trials")
  workspace = Workspace.create(path)
  workspace.addPackage(TrialPackage.model_validate(_packageDict))
  return workspace, createApp(path).test_client()


def fieldBook(workspace, dropLast=True):
  plots = sorted(plot.plotNumber for plot in workspace.layoutFor("D2-1").plots)
  if dropLast:
    plots = plots[:-1]
  workbook = openpyxl.Workbook()
  workbook.active.title = "Readme"
  workbook.active.append(["Collected by the field team"])
  sheet = workbook.create_sheet("Harvest")
  sheet.append(["Plot", "Yield kg", "Notes"])
  for index, plot in enumerate(plots):
    sheet.append([plot, "NA" if index == 0 else 4000 + 10.5 * index, "ok"])
  buffer = io.BytesIO()
  workbook.save(buffer)
  return plots, buffer.getvalue()


def selected(body, name):
  select = re.search(rf'<select[^>]*name="{name}"[^>]*>(.*?)</select>', body, re.S).group(1)
  return re.search(r'<option value="([^"]*)" selected', select).group(1) if " selected" in select else ""


def mappingForm(data, **fields):
  return {"fileName": "harvest.xlsx", "fileData": base64.b64encode(data).decode(), "previewedSheet": "Harvest",
          "sheet": "Harvest", "decimal": ".", **fields}


def testPreviewShowsTheSheetAndSuggestsAMapping(setup):
  workspace, client = setup
  _, data = fieldBook(workspace)
  first = client.post("/trials/D2-1/import", data={"file": (BytesIO(data), "harvest.xlsx")},
                      content_type="multipart/form-data").get_data(as_text=True)
  assert "harvest.xlsx: 0 rows" in first and "Collected by the field team" in first
  body = client.post("/trials/D2-1/import", data=mappingForm(data, previewedSheet="Readme", action="preview")).get_data(as_text=True)
  assert "harvest.xlsx: 11 rows; the first ten are shown." in body
  assert selected(body, "plot") == "0" and selected(body, "longPlot") == "0"
  assert selected(body, "column-1") == "" and selected(body, "longValue") == ""
  assert 'value="wide" checked' in body
  assert "YIELD - Grain yield (kg/ha)" in body
  assert workspace.loadObservations("D2-1") == []


def testImportSavesTheMappedColumnAndReconciles(setup):
  workspace, client = setup
  plots, data = fieldBook(workspace)
  response = client.post("/trials/D2-1/import", data=mappingForm(
    data, shape="wide", plot="0", **{"column-1": "YIELD", "column-2": ""}, action="import"))
  body = response.get_data(as_text=True)
  assert response.status_code == 200
  assert "Imported 11 observations from harvest.xlsx." in body
  missing = sorted(p.plotNumber for p in workspace.layoutFor("D2-1").plots)[-1]
  assert re.search(rf'<td class="code">YIELD</td>\s*<td class="code">10</td>\s*<td class="code">1</td>\s*<td class="code">{missing}</td>', body)
  stored = {o.plotNumber: o.value for o in workspace.loadObservations("D2-1")}
  assert stored == {plot: (None if index == 0 else 4000 + 10.5 * index) for index, plot in enumerate(plots)}


def testAnImportNeverReplacesStoredValues(setup):
  workspace, client = setup
  _, data = fieldBook(workspace)
  form = mappingForm(data, shape="wide", plot="0", **{"column-1": "YIELD"}, action="import")
  client.post("/trials/D2-1/import", data=form)
  again = client.post("/trials/D2-1/import", data=form)
  assert again.status_code == 400
  assert "already holds 11 of these values" in again.get_data(as_text=True)
  assert len(workspace.loadObservations("D2-1")) == 11


@pytest.mark.parametrize("fields, message", [
  ({"shape": "wide", "plot": "0"}, "Choose the assessment at least one column holds."),
  ({"shape": "wide", "plot": "", "column-1": "YIELD"}, "Choose the column that holds the plot numbers."),
  ({"shape": "wide", "plot": "0", "column-1": "YIELD", "column-2": "YIELD"},
   "Two columns are set to the same assessment; each assessment can come from one column only."),
  ({"shape": "long", "longPlot": "0", "longAssessment": "2", "longValue": ""},
   "Choose the columns that hold the plot numbers, the assessment codes and the values."),
  ({"shape": "long", "longPlot": "0", "longAssessment": "1", "longValue": "1"},
   "The plot, the assessment and the value must come from three different columns."),
  ({"shape": "wide", "plot": "0", "column-1": "YIELD", "decimal": ""}, "Choose the decimal mark the file uses."),
  ({"shape": "wide", "plot": "0", "column-0": "YIELD"}, "wide-format plot column &#39;Plot&#39; is also an assessment column"),
])
def testEveryMappingChoiceMustBeMade(setup, fields, message):
  workspace, client = setup
  _, data = fieldBook(workspace)
  response = client.post("/trials/D2-1/import", data=mappingForm(data, action="import", **fields))
  assert response.status_code == 400
  assert message in response.get_data(as_text=True)
  assert workspace.loadObservations("D2-1") == []


def testCommaDecimalsFromACsv(setup):
  workspace, client = setup
  plot = sorted(p.plotNumber for p in workspace.layoutFor("D2-1").plots)[0]
  data = f"Plot;Yield\n{plot};\"4812,5\"\n".replace(";", ",").encode()
  client.post("/trials/D2-1/import", data={
    "fileName": "y.csv", "fileData": base64.b64encode(data).decode(), "previewedSheet": "",
    "shape": "wide", "plot": "0", "column-1": "YIELD", "decimal": ",", "action": "import"})
  assert [(o.plotNumber, o.value) for o in workspace.loadObservations("D2-1")] == [(plot, 4812.5)]


def testCountsAgainstEveryPlotAndCheckPlot(setup):
  workspace, _ = setup
  layout = workspace.layoutFor("D2-1")
  numbers = sorted(p.plotNumber for p in layout.plots)
  result = ImportResult(observations=[
    Observation(plotNumber=numbers[0], assessmentCode="YIELD", value=1.0),
    Observation(plotNumber=numbers[1], assessmentCode="YIELD", value=None),
  ], warnings=[])
  [count] = countByAssessment(result, layout)
  assert (count.assessmentCode, count.values, count.missing, count.plotsWithout) == ("YIELD", 1, 1, numbers[2:])
