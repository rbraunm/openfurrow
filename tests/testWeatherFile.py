# SPDX-License-Identifier: Apache-2.0
"""A trial's weather log read from a CSV file (worklist REC-13)."""

import datetime
import io

import pytest

from openfurrow import Quantity, TrialPackage, Workspace
from openfurrow.cli.main import main
from openfurrow.importers.weatherCsv import WeatherFileError, readWeatherCsv
from openfurrow.service import createApp

goodFile = (
  "date,rainfall [mm],minimumTemperature [C],maximumTemperature [C],notes\n"
  "2026-05-03,0,4.5,19.0,\n"
  "2026-05-01,12.4,,,Storm\n"
  "\n"
  "2026-05-02,,-1.5,14,Frost\n"
)


def write(tmp_path, text, name="weather.csv"):
  path = tmp_path / name
  path.write_text(text, encoding="utf-8")
  return path


def testDaysAreReadWithTheirUnitsAndPutInOrder(tmp_path):
  records = readWeatherCsv(write(tmp_path, goodFile))
  assert [record.date for record in records] == [datetime.date(2026, 5, day) for day in (1, 2, 3)]
  assert records[0].rainfall == Quantity(value=12.4, unit="mm") and records[0].notes == "Storm"
  assert records[1].minimumTemperature == Quantity(value=-1.5, unit="C") and records[1].rainfall is None
  assert records[2].maximumTemperature == Quantity(value=19.0, unit="C")


@pytest.mark.parametrize("text, message", [
  ("date,rainfall\n2026-05-01,3\n", r"column 'rainfall' needs its unit in brackets"),
  ("date,humidity [%]\n2026-05-01,80\n", r"column 'humidity \[%\]' is not one of"),
  ("rainfall [mm]\n3\n", "has no date column"),
  ("date,rainfall [mm],rainfall [in]\n2026-05-01,3,0.1\n", r"columns given twice: \['rainfall'\]"),
  ("date [day],rainfall [mm]\n2026-05-01,3\n", "takes no unit"),
  ("date,rainfall [mm]\n2026-05-01,lots\n", "row 2: rainfall 'lots' is not a number"),
  ("date,rainfall [mm]\n2026-05-01,-2\n", "row 2: .*rainfall must not be negative"),
  ("date,rainfall [mm]\n01/05/2026,2\n", "row 2: .*a date is written YYYY-MM-DD"),
  ("date,rainfall [mm]\n2026-05-01,2\n2026-05-01,3\n", r"days given more than once: \['2026-05-01'\]"),
  ("date,rainfall [mm]\n2026-05-01,nan\n", "row 2: "),
  ("date,rainfall [mm]\n2026-05-01,2,9\n", "row 2 has 3 cells, the header 2"),
  ("date,rainfall [mm]\n", "lists no days"),
  ("", "is empty"),
])
def testProblemsAreNamed(tmp_path, text, message):
  with pytest.raises(WeatherFileError, match=message):
    readWeatherCsv(write(tmp_path, text))


@pytest.fixture
def trial(tmp_path, validPackageDict):
  databasePath = str(tmp_path / "trials.db")
  workspace = Workspace.create(databasePath)
  validPackageDict["weather"] = [{"date": "2026-04-01", "rainfall": {"value": 1, "unit": "mm"}}]
  workspace.addPackage(TrialPackage.model_validate(validPackageDict))
  return databasePath, workspace


def testImportReplacesTheLogAndTheHashFollows(tmp_path, trial):
  _, workspace = trial
  before = workspace.contentHashFor("ESV-2025-01")
  assert workspace.importWeather("ESV-2025-01", str(write(tmp_path, goodFile))) == 3
  weather = workspace.loadPackage("ESV-2025-01").weather
  assert [record.date.day for record in weather] == [1, 2, 3] and weather[0].date.month == 5
  assert workspace.contentHashFor("ESV-2025-01") != before
  exported = tmp_path / "doc.json"
  workspace.exportDocument("ESV-2025-01", str(exported))
  other = Workspace.create(str(tmp_path / "other.db"))
  other.importDocument(str(exported))
  assert other.contentHashFor("ESV-2025-01") == workspace.contentHashFor("ESV-2025-01")


def testTemperaturesInTwoUnitsAreRefusedWholeTrial(tmp_path, trial):
  _, workspace = trial
  text = "date,minimumTemperature [C],maximumTemperature [F]\n2026-05-01,4,60\n"
  with pytest.raises(WeatherFileError, match="cannot be compared"):
    workspace.importWeather("ESV-2025-01", str(write(tmp_path, text)))
  assert [record.date.month for record in workspace.loadPackage("ESV-2025-01").weather] == [4]


def testCommandReplacesTheLog(tmp_path, trial, capsys):
  databasePath, workspace = trial
  assert main(["import-weather", databasePath, "ESV-2025-01", str(write(tmp_path, goodFile))]) == 0
  assert "Replaced the weather log of 'ESV-2025-01' with 3 days" in capsys.readouterr().out
  assert main(["import-weather", databasePath, "ESV-2025-01", str(write(tmp_path, "date\n", "bad.csv"))]) == 1
  assert "lists no days" in capsys.readouterr().err


def testTrialPageTakesTheFile(trial):
  databasePath, workspace = trial
  client = createApp(databasePath).test_client()
  response = client.post("/trials/ESV-2025-01/weather", data={"file": (io.BytesIO(goodFile.encode()), "w.csv")},
                         content_type="multipart/form-data")
  assert response.status_code == 200 and "The weather log now holds 3 days." in response.get_data(as_text=True)
  bad = client.post("/trials/ESV-2025-01/weather", data={"file": (io.BytesIO(b"date,rain\n"), "w.csv")},
                    content_type="multipart/form-data")
  assert bad.status_code == 400 and "is not one of" in bad.get_data(as_text=True)
  assert client.get("/trials/ESV-2025-01/verify").status_code == 200
