# SPDX-License-Identifier: Apache-2.0
"""Settings by scope, resolved down the hierarchy (decision 0035)."""

import pytest

from openfurrow import TrialPackage, Workspace
from openfurrow.analysis import MeanComparison
from openfurrow.settings import SettingError

from storeHelpers import standardPath, standardStudy


@pytest.fixture
def workspace(newStore, validPackageDict):
  workspace = Workspace.create(newStore("s"))
  standardStudy(workspace)
  workspace.addPlace("station/trials", "other", "Other")
  workspace.addPackage(TrialPackage.model_validate(validPackageDict), standardPath)
  return workspace


def effective(workspace, scope):
  return {setting.key: (setting.value, setting.source) for setting in workspace.effectiveSettings(scope)}


def testTheNearestValueWinsAndSaysWhereItWasSet(workspace):
  trial = "trial:ESV-2025-01"
  assert effective(workspace, trial)["analysis.significanceLevel"] == (0.05, "default")
  workspace.setSetting("server", "analysis.significanceLevel", 0.1)
  workspace.setSetting("place:station", "analysis.significanceLevel", 0.01)
  assert effective(workspace, trial)["analysis.significanceLevel"] == (0.01, "place:station")
  workspace.setSetting("place:station/trials/study", "analysis.meanComparison", "tukeyHSD")
  workspace.setSetting(trial, "analysis.significanceLevel", 0.02)
  values = effective(workspace, trial)
  assert values["analysis.significanceLevel"] == (0.02, trial)
  assert values["analysis.meanComparison"] == (MeanComparison.tukeyHSD, "place:station/trials/study")
  assert effective(workspace, "place:station/trials/other")["analysis.meanComparison"] == (MeanComparison.protectedLSD, "default")
  assert effective(workspace, "place:station/trials/other")["analysis.significanceLevel"] == (0.01, "place:station")
  workspace.clearSetting(trial, "analysis.significanceLevel")
  assert effective(workspace, trial)["analysis.significanceLevel"] == (0.01, "place:station")


def testTheAnalysisFollowsTheTrialsSettings(workspace):
  observations = workspace.layoutFor("ESV-2025-01")
  from openfurrow.schema.observation import Observation
  values = {"T1": [5000, 5100, 4900, 5050], "T2": [5600, 5500, 5700, 5650], "T3": [5300, 5250, 5400, 5350]}
  workspace.recordValues("ESV-2025-01", "YIELD", [
    Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD", value=float(values[plot.treatmentCode][plot.block - 1]))
    for plot in observations.plots
  ])
  loose = workspace.separateMeans("ESV-2025-01", "YIELD")
  workspace.setSetting("place:station/trials/study", "analysis.significanceLevel", 0.001)
  strict = workspace.separateMeans("ESV-2025-01", "YIELD")
  assert (loose.significanceLevel, strict.significanceLevel) == (0.05, 0.001)
  assert strict.criticalDifference > loose.criticalDifference
  report = workspace.buildReport("ESV-2025-01")
  assert "analysis.significanceLevel = 0.001 (set for station/trials/study)" in report
  assert "analysis.missingPlots = refuse (default)" in report


@pytest.mark.parametrize("scope, key, value, message", [
  ("server", "analysis.colour", 1, "no setting 'analysis.colour'"),
  ("server", "analysis.significanceLevel", 1.0, "does not take 1.0"),
  ("server", "analysis.meanComparison", "duncan", "does not take 'duncan'"),
  ("galaxy", "analysis.significanceLevel", 0.1, "'galaxy' is not a scope"),
  ("place:station/nowhere", "analysis.significanceLevel", 0.1, "no place 'station/nowhere'"),
  ("trial:NOPE", "analysis.significanceLevel", 0.1, "trial 'NOPE' not found"),
])
def testWhatASettingDoesNotTakeIsRefused(workspace, scope, key, value, message):
  with pytest.raises(Exception, match=message):
    workspace.setSetting(scope, key, value)
  assert effective(workspace, "server")["analysis.significanceLevel"] == (0.05, "default")


def testATrialsValuesGoWithIt(workspace, validPackageDict):
  workspace.setSetting("trial:ESV-2025-01", "analysis.significanceLevel", 0.2)
  workspace.deleteTrial("ESV-2025-01")
  workspace.addPackage(TrialPackage.model_validate(validPackageDict), standardPath)
  assert effective(workspace, "trial:ESV-2025-01")["analysis.significanceLevel"] == (0.05, "default")
  with pytest.raises(SettingError, match="has no value at trial:ESV-2025-01"):
    workspace.clearSetting("trial:ESV-2025-01", "analysis.significanceLevel")
