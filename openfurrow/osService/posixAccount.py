# SPDX-License-Identifier: Apache-2.0
"""What systemd and launchd installs share: the files a service account is given, and commands run as root."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from openfurrow.osService.deployment import Deployment, DeploymentError

elevationHint = "run the command with sudo"
accountComment = "OpenFurrow service account made by openfurrow service install"
groupNote = " with its group"


def isElevated() -> bool:
  return os.geteuid() == 0


def run(command: list[str]) -> str:
  completed = subprocess.run(command, capture_output=True, text=True)
  if completed.returncode != 0:
    raise DeploymentError(f"{' '.join(command)} failed with exit code {completed.returncode}: "
                          f"{(completed.stderr or completed.stdout).strip()}")
  return completed.stdout


def ownedPaths(deployment: Deployment) -> list[Path]:
  """What the service account owns: the store's folder, the store with the files SQLite keeps beside it, and the
  logs folder with its files."""
  paths = [] if deployment.storeFile is None else [deployment.storeFile.parent, *deployment.storeFiles()]
  if deployment.logsFolder.is_dir():
    paths += [deployment.logsFolder, *sorted(deployment.logsFolder.iterdir())]
  return [path for path in paths if path.exists()]


def give(deployment: Deployment, userID: int, groupID: int) -> None:
  for path in ownedPaths(deployment):
    os.chown(path, userID, groupID)


def takeBack(deployment: Deployment, userID: int) -> None:
  """Hand what the account owned to root, so no later account that is given its number inherits the files."""
  for path in ownedPaths(deployment):
    if path.stat().st_uid == userID:
      os.chown(path, 0, 0)
