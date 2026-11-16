# SPDX-License-Identifier: Apache-2.0
"""The places trials live in (decision 0034)."""

import pytest
from pydantic import ValidationError

from openfurrow import TrialPackage, Workspace
from openfurrow.schema.hierarchy import HierarchyLevel
from openfurrow.service import createApp
from openfurrow.store import StoreError

from storeHelpers import standardPath, standardStudy


def package(validPackageDict, code="H-1"):
  validPackageDict["trial"]["trialCode"] = code
  return TrialPackage.model_validate(validPackageDict)


def testTheDefaultHierarchyHoldsTrialsInStudies(newStore, validPackageDict):
  workspace = Workspace.create(newStore("h"))
  assert [level.levelCode for level in workspace.hierarchyLevels()] == ["organization", "project", "study"]
  path = standardStudy(workspace)
  workspace.addPackage(package(validPackageDict), path)
  assert workspace.placeOf("H-1") == "station/trials/study"
  assert [(place.path, place.levelCode) for place in workspace.places()] == [
    ("station", "organization"), ("station/trials", "project"), ("station/trials/study", "study"),
  ]
  assert workspace.trialsIn("station") == [("H-1", validPackageDict["trial"]["title"])]


@pytest.mark.parametrize("place, message", [
  (None, "a trial goes in a place of the last level, a study; name its path"),
  ("station/trials", "'station/trials' is a project; a trial goes in a study"),
  ("station/other/study", "no place 'station/other'"),
])
def testATrialGoesInAPlaceOfTheLastLevel(newStore, validPackageDict, place, message):
  workspace = Workspace.create(newStore("h"))
  standardStudy(workspace)
  with pytest.raises(StoreError, match=message):
    workspace.addPackage(package(validPackageDict), place)
  assert workspace.listTrials() == []


def testPlacesFollowTheLevels(newStore):
  workspace = Workspace.create(newStore("h"))
  standardStudy(workspace)
  with pytest.raises(StoreError, match="'station/trials/study' is a study, the last level; it holds trials"):
    workspace.addPlace("station/trials/study", "deeper", "Deeper")
  with pytest.raises(StoreError, match="place 'station/trials' already exists"):
    workspace.addPlace("station", "trials", "Again")
  with pytest.raises(ValueError, match="'two words' is not a code"):
    workspace.addPlace(None, "two words", "Name")


def testAnEnterpriseAddsLevelsAndASmallTeamRemovesThem(newStore, validPackageDict):
  enterprise = Workspace.create(newStore("enterprise"))
  enterprise.setHierarchyLevels([
    HierarchyLevel(levelCode="organization"), HierarchyLevel(levelCode="program", name="Program"),
    HierarchyLevel(levelCode="project"), HierarchyLevel(levelCode="season", name="Season"),
    HierarchyLevel(levelCode="study"),
  ])
  parent = None
  for code in ("acme", "crops", "fungicides", "2026", "wheat"):
    parent = enterprise.addPlace(parent, code, code.title()).path
  enterprise.addPackage(package(validPackageDict), parent)
  assert enterprise.placeOf("H-1") == "acme/crops/fungicides/2026/wheat"
  assert [place.levelCode for place in enterprise.places()] == ["organization", "program", "project", "season", "study"]

  small = Workspace.create(newStore("small"))
  small.setHierarchyLevels([])
  small.addPackage(package(validPackageDict), None)
  assert small.placeOf("H-1") is None
  with pytest.raises(StoreError, match="no hierarchy levels, so it has no places"):
    small.addPlace(None, "station", "Station")


def testLevelsChangeOnlyWhileTheStoreIsEmpty(newStore, validPackageDict):
  workspace = Workspace.create(newStore("h"))
  standardStudy(workspace)
  with pytest.raises(StoreError, match="only while the store holds no places and no trials; it holds 3 places and 0 trials"):
    workspace.setHierarchyLevels([HierarchyLevel(levelCode="study")])
  with pytest.raises(ValidationError, match="level 'program' is not built in, so it needs a name"):
    HierarchyLevel(levelCode="program")


def testMovingATrialLeavesItUnchanged(newStore, validPackageDict):
  workspace = Workspace.create(newStore("h"))
  standardStudy(workspace)
  workspace.addPlace("station/trials", "other", "Other study")
  workspace.addPackage(package(validPackageDict), standardPath)
  before = workspace.contentHashFor("H-1")
  workspace.moveTrial("H-1", "station/trials/other")
  assert workspace.placeOf("H-1") == "station/trials/other"
  assert workspace.contentHashFor("H-1") == before


def testOnlyAnEmptyPlaceIsDeleted(newStore, validPackageDict):
  workspace = Workspace.create(newStore("h"))
  standardStudy(workspace)
  workspace.addPackage(package(validPackageDict), standardPath)
  with pytest.raises(StoreError, match="holds 0 places and 1 trials"):
    workspace.deletePlace(standardPath)
  with pytest.raises(StoreError, match="holds 1 places and 0 trials"):
    workspace.deletePlace("station/trials")
  workspace.deleteTrial("H-1")
  workspace.deletePlace(standardPath)
  assert [place.path for place in workspace.places()] == ["station", "station/trials"]


def testThePlacesPageAddsAPlaceAndTheFormOffersIt(newStore):
  location = newStore("h")
  Workspace.create(location)
  client = createApp(location).test_client()
  for parent, code, name in (("", "station", "Station"), ("station", "trials", "Trials"), ("station/trials", "wheat", "Wheat")):
    assert client.post("/places", data={"parent": parent, "code": code, "name": name}).status_code == 302
  page = client.get("/places").get_data(as_text=True)
  assert "station/trials/wheat" in page and "Study" in page
  form = client.get("/trials/form").get_data(as_text=True)
  assert '<option value="station/trials/wheat" >Wheat (station/trials/wheat)</option>' in form
  refused = client.post("/places", data={"parent": "station/trials/wheat", "code": "x", "name": "X"})
  assert refused.status_code == 400 and "the last level; it holds trials" in refused.get_data(as_text=True)
