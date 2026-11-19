# SPDX-License-Identifier: Apache-2.0
"""Installing, removing, starting, stopping and reading OpenFurrow's two services (decision 0009).

What is the same on every platform is here: what a deployment is checked for before
anything is changed, the order the services start and stop in, and what counts as done.
What differs is behind a manager, one module per platform (`windows`, `systemd`,
`launchd`), each with the same functions: `isElevated`, `check`, `install`, `uninstall`,
`installed`, `state`, `start` and `stop` (which stops a service in any state), and
`failedStartsAgain`, whether the platform starts a failed service again even after a stop.

Everything refused is refused by name before the first change, and an install that fails
part of the way is undone. Services are named by their suffix alone: the store, the
address and the rest are read back from the installed definitions.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from openfurrow.osService.deployment import (
  Deployment, DeploymentError, Role, ServiceState, checkedSuffix, logsFolderName, readEnvironmentFile, serviceName,
)
from openfurrow.store.database import createDatabase, isDatabaseURL
from openfurrow.tasks.run import storeVariable

startSeconds = 150
stopSeconds = 90
_stoppingOrder = (Role.scheduler, Role.web)


@dataclass(frozen=True)
class Status:
  """Each service's state, and the deployment the installed ones were installed with."""

  states: dict[Role, ServiceState]
  deployment: Deployment | None


def managerFor(platform: str = sys.platform):
  if platform == "win32":
    from openfurrow.osService import windows
    return windows
  if platform == "linux":
    from openfurrow.osService import systemd
    return systemd
  if platform == "darwin":
    from openfurrow.osService import launchd
    return launchd
  raise DeploymentError(f"OpenFurrow installs as a service on Windows, on Linux under systemd and on macOS; this "
                        f"platform, '{platform}', is none of them")


def _requireElevation(manager, action: str) -> None:
  if not manager.isElevated():
    raise DeploymentError(f"to {action} services this shell must be elevated: {manager.elevationHint}")


def _hint(suffix: str | None) -> str:
  return f" --suffix {suffix}" if suffix else ""


def _names(suffix: str | None) -> str:
  return " and ".join(serviceName(role, suffix) for role in Role)


def install(location: str, host: str, port: int, suffix: str | None = None, environmentFile: str | None = None,
            logsFolder: str | None = None, manager=None) -> Deployment:
  """Install the web server and the scheduler on the store at `location`, to start with the machine."""
  manager = manager or managerFor()
  _requireElevation(manager, "install")
  suffix = checkedSuffix(suffix)
  taken = [serviceName(role, suffix) for role in Role if manager.state(serviceName(role, suffix)) is not ServiceState.notInstalled]
  if taken:
    raise DeploymentError(f"{' and '.join(taken)} already installed: uninstall first (openfurrow service uninstall"
                          f"{_hint(suffix)}), or install this deployment under a --suffix of its own")
  deployment = _deployment(location, host, port, suffix, environmentFile, logsFolder)
  manager.check(deployment)
  _requireFreeAddress(host, port)
  makesLogsFolder = not deployment.logsFolder.exists()
  if makesLogsFolder:
    deployment.logsFolder.mkdir()
  try:
    manager.install(deployment)
  except BaseException:
    manager.uninstall(deployment)
    if makesLogsFolder:
      deployment.logsFolder.rmdir()
    raise
  return deployment


def _deployment(location: str, host: str, port: int, suffix: str | None, environmentFile: str | None,
                logsFolder: str | None) -> Deployment:
  environmentPath = None if environmentFile is None else Path(environmentFile).resolve()
  variables = {} if environmentPath is None else readEnvironmentFile(environmentPath)
  if isDatabaseURL(location):
    if variables.get(storeVariable) != location:
      raise DeploymentError(f"the URL of a PostgreSQL store carries a password, so no service definition holds it: "
                            f"put {storeVariable}=<the URL> in an environment file and name the file with "
                            f"--environment-file")
    if logsFolder is None:
      raise DeploymentError("a PostgreSQL store has no folder to keep the logs beside: name one with --logs")
    storeFile = None
  else:
    storeFile = Path(location).resolve()
  createDatabase(location, create=False).dispose()
  logs = storeFile.parent / logsFolderName if logsFolder is None else Path(logsFolder).resolve()
  if not logs.parent.is_dir():
    raise DeploymentError(f"the logs folder '{logs}' has no folder to be made in")
  deployment = Deployment(storeFile=storeFile, logsFolder=logs, suffix=suffix, environmentFile=environmentPath,
                          python=Path(sys.executable), host=host, port=port)
  if storeFile is not None:
    _requireOwnFolder(deployment)
  return deployment


def _requireOwnFolder(deployment: Deployment) -> None:
  folder = deployment.storeFile.parent
  expected = {*deployment.storeFiles(), deployment.logsFolder, deployment.environmentFile}
  others = sorted(entry.name for entry in folder.iterdir() if entry not in expected)
  if others:
    raise DeploymentError(f"the services' accounts are given the store's whole folder, and {folder} holds more than "
                          f"the store ({', '.join(others[:5])}{', ...' if len(others) > 5 else ''}); keep a served "
                          f"store in a folder of its own")


def _requireFreeAddress(host: str, port: int) -> None:
  from openfurrow.service.runner import ServiceError, listen
  try:
    listen(host, port).close()
  except ServiceError as error:
    raise DeploymentError(f"the web server could not listen on {host}:{port}, which is in use or not this machine's "
                          f"({error}); choose another with --host and --port") from error


def _installed(manager, suffix: str | None) -> dict[Role, Deployment]:
  found = {role: manager.installed(role, suffix) for role in Role}
  return {role: deployment for role, deployment in found.items() if deployment is not None}


def _whole(manager, suffix: str | None, action: str) -> Deployment:
  """The deployment of the two installed services; refused unless both are there."""
  found = _installed(manager, suffix)
  missing = [serviceName(role, suffix) for role in Role if role not in found]
  if missing:
    raise DeploymentError(f"cannot {action} {' and '.join(missing)}: not installed")
  return found[Role.web]


def uninstall(suffix: str | None = None, manager=None) -> list[str]:
  """Stop and remove the services of this suffix; the names of those removed. The store, its logs and the
  environment file stay."""
  manager = manager or managerFor()
  _requireElevation(manager, "uninstall")
  suffix = checkedSuffix(suffix)
  found = _installed(manager, suffix)
  if not found:
    raise DeploymentError(f"cannot uninstall {_names(suffix)}: not installed")
  for role in _stoppingOrder:
    if role in found:
      _stop(manager, serviceName(role, suffix))
  manager.uninstall(found.get(Role.web) or found[Role.scheduler])
  return [serviceName(role, suffix) for role in Role if role in found]


def start(suffix: str | None = None, manager=None) -> Deployment:
  manager = manager or managerFor()
  _requireElevation(manager, "start")
  deployment = _whole(manager, checkedSuffix(suffix), "start")
  for role in Role:
    name = deployment.name(role)
    if manager.state(name) is not ServiceState.running:
      manager.start(name)
      _await(manager, name, ServiceState.running, startSeconds, f"see its log, {deployment.logFile(role)}")
  return deployment


def stop(suffix: str | None = None, manager=None) -> Deployment:
  manager = manager or managerFor()
  _requireElevation(manager, "stop")
  deployment = _whole(manager, checkedSuffix(suffix), "stop")
  for role in _stoppingOrder:
    _stop(manager, deployment.name(role))
  for role in _stoppingOrder:
    if manager.failedStartsAgain and manager.state(deployment.name(role)) is ServiceState.failed:
      raise DeploymentError(f"{deployment.name(role)} is not running because it failed, and this system starts a "
                            f"failed service again by itself, within a minute, whatever it is told: see its log, "
                            f"{deployment.logFile(role)}, or uninstall the services to keep it down")
  return deployment


def status(suffix: str | None = None, manager=None) -> Status:
  manager = manager or managerFor()
  suffix = checkedSuffix(suffix)
  found = _installed(manager, suffix)
  states = {role: manager.state(serviceName(role, suffix)) for role in Role}
  return Status(states=states, deployment=found.get(Role.web) or found.get(Role.scheduler))


def _stop(manager, name: str) -> None:
  """Have the service manager stop the service, whatever state it is in, and wait until it has."""
  manager.stop(name)
  _await(manager, name, ServiceState.stopped, stopSeconds, "it is still stopping")


def _await(manager, name: str, wanted: ServiceState, seconds: float, advice: str) -> None:
  deadline = time.monotonic() + seconds
  while (state := manager.state(name)) is not wanted:
    if state is ServiceState.failed:
      if wanted is ServiceState.stopped:
        return
      raise DeploymentError(f"{name} failed to start; {advice}")
    if time.monotonic() > deadline:
      raise DeploymentError(f"{name} is {state.value}, not {wanted.value}, after {seconds} seconds; {advice}")
    time.sleep(0.2)
