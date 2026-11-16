# SPDX-License-Identifier: Apache-2.0
"""A place for test trials in the default hierarchy (decision 0034)."""

from openfurrow import Workspace

standardPath = "station/trials/study"


def standardStudy(workspace: Workspace) -> str:
  """The study 'station/trials/study', made on first use, for a test's trials."""
  existing = {place.path for place in workspace.places()}
  parent = None
  for code, name in (("station", "Research station"), ("trials", "Trials"), ("study", "Study")):
    path = code if parent is None else f"{parent}/{code}"
    if path not in existing:
      workspace.addPlace(parent, code, name)
    parent = path
  return standardPath


def standardStudyAt(location: str) -> str:
  """The same study in the store at `location`, the store made if it is not there yet."""
  return standardStudy(Workspace.create(location))
