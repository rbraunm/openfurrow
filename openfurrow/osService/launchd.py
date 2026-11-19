# SPDX-License-Identifier: Apache-2.0
"""OpenFurrow's services under launchd: two system daemons, their property lists in /Library/LaunchDaemons.

Both run as one unprivileged account made for the deployment, `_openfurrow` or
`_openfurrow-<suffix>`, hidden from the login window, which owns the store's folder and
the logs. launchd starts a daemon when the machine starts and again after it ends with
a failure. It has no word for "ready": a daemon counts as running once its process
exists. It reads no environment file either, so the process reads the file itself, and
the install leaves the file readable by root and the account's group only. What Python
says before OpenFurrow's log is open goes to `<name>.launchd.log` in the logs folder.

Installing writes the property lists. Starting loads a daemon into launchd; stopping
unloads it, until it is started again or the machine restarts.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
from pathlib import Path

from openfurrow.osService.deployment import (
  Deployment, DeploymentError, Role, ServiceState, deploymentOf, hostModule, serviceCode, serviceName,
)
from openfurrow.osService.posixAccount import accountComment, elevationHint, give, groupNote, isElevated, run, takeBack

__all__ = ["check", "elevationHint", "failedStartsAgain", "install", "installed", "isElevated", "start", "state",
           "stop", "uninstall"]

failedStartsAgain = False

daemonFolder = Path("/Library/LaunchDaemons")
exitSeconds = 60
firstAccountNumber, lastAccountNumber = 300, 499
bootoutInProgress = 36


def account(suffix: str | None) -> str:
  return "_openfurrow" + (f"-{suffix}" if suffix else "")


def daemonPath(name: str) -> Path:
  return daemonFolder / f"{name}.plist"


def propertyList(deployment: Deployment, role: Role) -> bytes:
  name = deployment.name(role)
  user = account(deployment.suffix)
  earlyOutput = str(deployment.logsFolder / f"{name}.launchd.log")
  return plistlib.dumps({
    "Label": name,
    "ProgramArguments": [str(deployment.python), "-P", "-m", hostModule,
                         *deployment.hostArguments(role, readsEnvironmentFile=True)],
    "UserName": user,
    "GroupName": user,
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ExitTimeOut": exitSeconds,
    "StandardOutPath": earlyOutput,
    "StandardErrorPath": earlyOutput,
  })


def deploymentOfPropertyList(data: bytes) -> tuple[Role, Deployment]:
  """The role and the deployment a property list written by `propertyList` says."""
  command = plistlib.loads(data).get("ProgramArguments", [])
  if command[1:4] != ["-P", "-m", hostModule]:
    raise DeploymentError("the daemon is not one OpenFurrow installed: it does not run OpenFurrow's service process")
  return deploymentOf(command[0], command[4:])


def check(deployment: Deployment) -> None:
  serviceCode(deployment.python)


def _listed(name: str) -> subprocess.CompletedProcess:
  return subprocess.run(["launchctl", "print", f"system/{name}"], capture_output=True, text=True)


def state(name: str) -> ServiceState:
  if not daemonPath(name).exists():
    return ServiceState.notInstalled
  listing = _listed(name)
  if listing.returncode == 0 and re.search(r"^\s*state = running$", listing.stdout, re.MULTILINE):
    return ServiceState.running
  return ServiceState.stopped


def installed(role: Role, suffix: str | None) -> Deployment | None:
  path = daemonPath(serviceName(role, suffix))
  return deploymentOfPropertyList(path.read_bytes())[1] if path.exists() else None


def install(deployment: Deployment) -> None:
  userID, groupID = _makeAccount(account(deployment.suffix))
  serviceCode(deployment.python, user=userID, group=groupID, extra_groups=[])
  give(deployment, userID, groupID)
  if deployment.environmentFile is not None:
    os.chown(deployment.environmentFile, 0, groupID)
    os.chmod(deployment.environmentFile, 0o640)
  for role in Role:
    path = daemonPath(deployment.name(role))
    path.write_bytes(propertyList(deployment, role))
    os.chown(path, 0, 0)
    path.chmod(0o644)


def uninstall(deployment: Deployment) -> None:
  """Remove the property lists of the daemons, which are stopped, and the account the install made; whatever is
  already gone is passed over."""
  for role in Role:
    daemonPath(deployment.name(role)).unlink(missing_ok=True)
  _removeAccount(deployment)


def start(name: str) -> None:
  if _listed(name).returncode == 0:
    run(["launchctl", "kickstart", f"system/{name}"])
  else:
    run(["launchctl", "bootstrap", "system", str(daemonPath(name))])


def stop(name: str) -> None:
  if _listed(name).returncode != 0:
    return
  # While the daemon is still ending launchctl answers "operation now in progress"; the daemon is unloaded
  # once launchd no longer lists it, which the caller waits for.
  unloading = subprocess.run(["launchctl", "bootout", f"system/{name}"], capture_output=True, text=True)
  if unloading.returncode not in (0, bootoutInProgress):
    raise DeploymentError(f"launchctl bootout system/{name} failed with exit code {unloading.returncode}: "
                          f"{unloading.stderr.strip()}")


def _numbers(kind: str, key: str) -> dict[str, int]:
  listing = run(["dscl", ".", "-list", f"/{kind}", key])
  return {name: int(number) for name, number in (line.rsplit(None, 1) for line in listing.splitlines() if line.strip())}


def accountExists(suffix: str | None) -> bool:
  return account(suffix) in _numbers("Users", "UniqueID")


def _makeAccount(user: str) -> tuple[int, int]:
  """The account's user and group numbers; the account is made when it does not exist."""
  users = _numbers("Users", "UniqueID")
  if user in users:
    return users[user], int(run(["dscl", ".", "-read", f"/Users/{user}", "PrimaryGroupID"]).split()[1])
  groups = _numbers("Groups", "PrimaryGroupID")
  taken = {*users.values(), *groups.values()}
  free = [number for number in range(lastAccountNumber, firstAccountNumber - 1, -1) if number not in taken]
  if not free:
    raise DeploymentError(f"no account number between {firstAccountNumber} and {lastAccountNumber} is free for the "
                          f"service account {user}")
  makesGroup = user not in groups
  if makesGroup:
    run(["dscl", ".", "-create", f"/Groups/{user}"])
    for key, value in (("PrimaryGroupID", str(free[0])), ("Password", "*")):
      run(["dscl", ".", "-create", f"/Groups/{user}", key, value])
  groupID = free[0] if makesGroup else groups[user]
  run(["dscl", ".", "-create", f"/Users/{user}"])
  for key, value in (("UniqueID", str(free[0])), ("PrimaryGroupID", str(groupID)),
                     ("UserShell", "/usr/bin/false"), ("NFSHomeDirectory", "/var/empty"), ("Password", "*"),
                     ("IsHidden", "1"), ("RealName", accountComment + (groupNote if makesGroup else ""))):
    run(["dscl", ".", "-create", f"/Users/{user}", key, value])
  return free[0], groupID


def _removeAccount(deployment: Deployment) -> None:
  """Remove the account when the install made it, which its name in full says; one made by anyone else stays."""
  user = account(deployment.suffix)
  users = _numbers("Users", "UniqueID")
  if user not in users:
    return
  comment = " ".join(run(["dscl", ".", "-read", f"/Users/{user}", "RealName"]).split()[1:])
  if not comment.startswith(accountComment):
    return
  takeBack(deployment, users[user])
  run(["dscl", ".", "-delete", f"/Users/{user}"])
  if comment.endswith(groupNote) and user in _numbers("Groups", "PrimaryGroupID"):
    run(["dscl", ".", "-delete", f"/Groups/{user}"])
