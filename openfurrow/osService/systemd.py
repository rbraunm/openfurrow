# SPDX-License-Identifier: Apache-2.0
"""OpenFurrow's services under systemd: two system units, written and enabled by the install.

Both run as one unprivileged account made for the deployment, `openfurrow` or
`openfurrow-<suffix>`, which owns the store's folder and the logs. Each unit is a notify
service: systemd counts it started when the web server listens or the scheduler has
opened the store, and starts it again five seconds after it fails. To a unit the file
system is read-only apart from the store's folder and the logs, home directories are out
of sight and /tmp is one of its own, so neither the store nor the Python that runs
OpenFurrow can live in a home directory or in /tmp. A stop reaches the main process
alone, so the scheduler's runs get the time the scheduler gives them. systemd reads the
environment file itself, as root, and the install leaves it readable by root only.

The scheduler is not ordered after the web unit: it needs the store, not the web server.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from openfurrow.osService.deployment import (
  Deployment, DeploymentError, Role, ServiceState, deploymentOf, hostModule, serviceCode, serviceName, serviceTitle, under,
)
from openfurrow.osService.posixAccount import accountComment, elevationHint, give, groupNote, isElevated, run, takeBack

__all__ = ["check", "elevationHint", "failedStartsAgain", "install", "installed", "isElevated", "start", "state",
           "stop", "uninstall"]

failedStartsAgain = False

unitFolder = Path("/etc/systemd/system")
runningMarker = Path("/run/systemd/system")
outOfSight = (Path("/home"), Path("/root"), Path("/run/user"), Path("/tmp"), Path("/var/tmp"))
_plainWord = re.compile(r"[A-Za-z0-9_@+=:,./-]+")
_states = {"active": ServiceState.running, "reloading": ServiceState.running, "inactive": ServiceState.stopped,
           "failed": ServiceState.failed, "activating": ServiceState.starting, "deactivating": ServiceState.stopping}


def account(suffix: str | None) -> str:
  return "openfurrow" + (f"-{suffix}" if suffix else "")


def unitPath(name: str) -> Path:
  return unitFolder / f"{name}.service"


def _taken(text: str) -> str:
  if any(character in '"\\$%' or ord(character) < 32 for character in text):
    raise DeploymentError(f"systemd reads a double quote, a backslash, $, % and control characters in a unit file in "
                          f"ways of its own, and '{text}' holds one; choose paths without them")
  return text


def _word(text: str) -> str:
  """A word of a unit file's command or list of paths: as it is, or in double quotes when it holds a space or the like."""
  return text if _plainWord.fullmatch(text) else f'"{_taken(text)}"'


def unitFile(deployment: Deployment, role: Role) -> str:
  user = account(deployment.suffix)
  command = [str(deployment.python), "-P", "-m", hostModule, *deployment.hostArguments(role, readsEnvironmentFile=False)]
  environment = ([] if deployment.environmentFile is None
                 else [f"EnvironmentFile={_taken(str(deployment.environmentFile))}"])
  return "\n".join([
    "[Unit]",
    f"Description={serviceTitle(role, deployment.suffix)}",
    "After=network.target",
    "",
    "[Service]",
    "Type=notify",
    f"User={user}",
    f"Group={user}",
    f"ExecStart={' '.join(_word(word) for word in command)}",
    *environment,
    "Restart=on-failure",
    "RestartSec=5",
    "KillMode=mixed",
    "TimeoutStopSec=60",
    "UMask=0027",
    "NoNewPrivileges=yes",
    "ProtectSystem=strict",
    "ProtectHome=yes",
    "PrivateTmp=yes",
    "PrivateDevices=yes",
    "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes",
    "ProtectControlGroups=yes",
    "RestrictSUIDSGID=yes",
    "LockPersonality=yes",
    f"ReadWritePaths={' '.join(_word(str(folder)) for folder in deployment.writtenFolders())}",
    "",
    "[Install]",
    "WantedBy=multi-user.target",
    "",
  ])


def deploymentOfUnit(text: str) -> tuple[Role, Deployment]:
  """The role and the deployment a unit file written by `unitFile` says."""
  settings = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
  command = shlex.split(settings.get("ExecStart", ""))
  if command[1:4] != ["-P", "-m", hostModule]:
    raise DeploymentError("the unit is not one OpenFurrow installed: it does not run OpenFurrow's service process")
  environmentFile = settings.get("EnvironmentFile")
  return deploymentOf(command[0], command[4:], None if environmentFile is None else Path(environmentFile))


def check(deployment: Deployment) -> None:
  if not runningMarker.is_dir():
    raise DeploymentError("this Linux does not run systemd, which OpenFurrow's services are installed under")
  for path in serviceCode(deployment.python):
    folder = under(path, outOfSight)
    if folder is not None:
      raise DeploymentError(f"a systemd service cannot see {folder}, and Python or OpenFurrow is installed there "
                            f"({path}); install OpenFurrow elsewhere, for example in a virtual environment under /opt")
  for path in deployment.writtenFolders():
    folder = under(path, outOfSight)
    if folder is not None:
      raise DeploymentError(f"a systemd service cannot see {folder}, so the store and its logs cannot be kept in "
                            f"{path}; keep them elsewhere, for example under /srv or /var/lib")


def stateNamed(word: str) -> ServiceState:
  """The state systemctl is-active names: a unit waiting to be started again after a failure is "activating"."""
  if word not in _states:
    raise DeploymentError(f"systemctl is-active answered '{word}', which is no state of a unit")
  return _states[word]


def state(name: str) -> ServiceState:
  if not unitPath(name).exists():
    return ServiceState.notInstalled
  answer = subprocess.run(["systemctl", "is-active", f"{name}.service"], capture_output=True, text=True)
  return stateNamed(answer.stdout.strip())


def installed(role: Role, suffix: str | None) -> Deployment | None:
  path = unitPath(serviceName(role, suffix))
  return deploymentOfUnit(path.read_text(encoding="utf-8"))[1] if path.exists() else None


def install(deployment: Deployment) -> None:
  userID, groupID = _makeAccount(account(deployment.suffix))
  serviceCode(deployment.python, user=userID, group=groupID, extra_groups=[])
  give(deployment, userID, groupID)
  if deployment.environmentFile is not None:
    os.chown(deployment.environmentFile, 0, 0)
    os.chmod(deployment.environmentFile, 0o600)
  for role in Role:
    path = unitPath(deployment.name(role))
    path.write_text(unitFile(deployment, role), encoding="utf-8")
    path.chmod(0o644)
  run(["systemctl", "daemon-reload"])
  run(["systemctl", "enable", *[f"{deployment.name(role)}.service" for role in Role]])


def uninstall(deployment: Deployment) -> None:
  """Remove the units, which are stopped, and the account the install made; whatever is already gone is passed over."""
  for name in [deployment.name(role) for role in Role]:
    if not unitPath(name).exists():
      continue
    run(["systemctl", "disable", f"{name}.service"])
    if state(name) is ServiceState.failed:
      run(["systemctl", "reset-failed", f"{name}.service"])
    unitPath(name).unlink()
  run(["systemctl", "daemon-reload"])
  _removeAccount(deployment)


def start(name: str) -> None:
  run(["systemctl", "start", f"{name}.service"])


def stop(name: str) -> None:
  run(["systemctl", "stop", f"{name}.service"])


def userEntry(name: str):
  import pwd
  try:
    return pwd.getpwnam(name)
  except KeyError:
    return None


def groupExists(name: str) -> bool:
  import grp
  try:
    grp.getgrnam(name)
  except KeyError:
    return False
  return True


def accountCommand(user: str, hasGroup: bool) -> list[str]:
  """The command that makes the account: a system account that cannot log in, in the group of its name, which is
  made with it unless there is one."""
  group = ["--gid", user, "--comment", accountComment] if hasGroup else ["--user-group", "--comment", accountComment + groupNote]
  return ["useradd", "--system", "--home-dir", "/nonexistent", "--no-create-home", "--shell", "/usr/sbin/nologin", *group, user]


def accountExists(suffix: str | None) -> bool:
  return userEntry(account(suffix)) is not None


def _makeAccount(user: str) -> tuple[int, int]:
  """The account's user and group numbers; the account is made when it does not exist."""
  if userEntry(user) is None:
    run(accountCommand(user, groupExists(user)))
  entry = userEntry(user)
  return entry.pw_uid, entry.pw_gid


def _removeAccount(deployment: Deployment) -> None:
  """Remove the account when the install made it, which its comment says; one made by anyone else stays."""
  user = account(deployment.suffix)
  entry = userEntry(user)
  if entry is None or not entry.pw_gecos.startswith(accountComment):
    return
  takeBack(deployment, entry.pw_uid)
  run(["userdel", user])
  if entry.pw_gecos.endswith(groupNote) and groupExists(user):
    run(["groupdel", user])
