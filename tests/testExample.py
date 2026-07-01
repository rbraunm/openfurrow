# SPDX-License-Identifier: Apache-2.0
"""The worked example must keep working.

Runs the Yates oats example under examples/ through the CLI loop and checks it
reproduces the published analysis of variance, the known stable input hash, and a
passing round-trip. This guards the example against drift in the data, the schema,
or the analysis.
"""

from pathlib import Path

from openfurrow.cli.main import main

exampleDirectory = Path(__file__).parent.parent / "examples" / "yatesOats"
trialPath = str(exampleDirectory / "trial.json")
observationsPath = str(exampleDirectory / "observations.csv")
knownInputHash = "b47f48c8cc2b9ba02152ca57f7494748d47b52b20a8bd244b793ce26dbbe50d6"


def loadExample(database):
  assert main(["init", database]) == 0
  assert main(["add", database, trialPath]) == 0
  assert main(["import", database, "yatesOats1935", observationsPath]) == 0


def testExampleReproducesPublishedYatesTable(tmp_path, capsys):
  database = str(tmp_path / "oats.db")
  loadExample(database)
  capsys.readouterr()
  assert main(["report", database, "yatesOats1935"]) == 0
  report = capsys.readouterr().out
  assert "| Block | 5 | 3968.8194 | 793.7639 | 5.28 | 0.0124 |" in report
  assert "| Treatment | 2 | 446.5903 | 223.2951 | 1.49 | 0.2724 |" in report
  assert "| Error | 10 | 1503.3264 | 150.3326 | - | - |" in report
  assert "- Coefficient of variation: 11.79%" in report
  assert "Treatment effect not significant" in report
  assert knownInputHash in report


def testExampleVerifyPasses(tmp_path, capsys):
  database = str(tmp_path / "oats.db")
  loadExample(database)
  capsys.readouterr()
  assert main(["verify", database, "yatesOats1935"]) == 0
  output = capsys.readouterr().out
  assert "PASS" in output
  assert knownInputHash in output
