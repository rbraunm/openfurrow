# SPDX-License-Identifier: Apache-2.0
"""OpenFurrow's services on Windows: real services, made and removed through the service manager's own calls.

Each service runs as its own virtual account, `NT SERVICE\\<service name>`: an identity
Windows derives from the service's name, with no password to keep, no rights beyond an
ordinary user's, and nothing shared with any other service. LocalService would be shared
with every other service that uses it, so rights given on a store's folder would reach
all of them; LocalSystem can do anything on the machine. The two accounts are given
"modify" on the folders the services write in and "read" on the environment file, which
is closed to everyone but them, administrators and the system; uninstalling takes the
rights back.

A service starts automatically, delayed until the machine has settled after boot, and is
started again when it fails: after 5 seconds, then 30, then every 60, the count forgotten
after a day without a failure. A failure is the process dying or the service stopping
with an exit code (`windowsHost`).
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from openfurrow.osService.deployment import (
  Deployment, DeploymentError, Role, ServiceState, deploymentOf, serviceCode, serviceName, serviceTitle, under,
)

elevationHint = "open the shell with 'Run as administrator'"
failedStartsAgain = True
administratorsSID = "S-1-5-32-544"
systemSID = "S-1-5-18"
failureResetSeconds = 86400
restartDelaysMilliseconds = (5000, 30000, 60000)
deletionSeconds = 10
pendingSeconds = 150

_scManagerConnect, _scManagerCreateService = 0x1, 0x2
_serviceQueryConfig, _serviceQueryStatus, _serviceStart, _serviceStop, _delete = 0x1, 0x4, 0x10, 0x20, 0x10000
_serviceAllAccess = 0xF01FF
_serviceWin32OwnProcess, _serviceAutoStart, _serviceErrorNormal = 0x10, 2, 1
_configDescription, _configFailureActions, _configDelayedAutoStart, _configFailureActionsFlag = 1, 2, 3, 4
_actionRestart = 1
_controlStop = 1
_errorInsufficientBuffer, _errorServiceAlreadyRunning, _errorServiceDoesNotExist = 122, 1056, 1060
_errorServiceCannotAcceptControl, _errorServiceNotActive, _errorServiceNeverStarted = 1061, 1062, 1077
_winBuiltinAdministratorsSid = 26


@dataclass(frozen=True)
class ServiceDefinition:
  """A service as the service manager is asked to hold it."""

  name: str
  displayName: str
  description: str
  commandLine: str
  account: str
  delayedStart: bool = True
  failureResetSeconds: int = failureResetSeconds
  restartDelaysMilliseconds: tuple[int, ...] = restartDelaysMilliseconds
  restartsOnExitCode: bool = True


def serviceSID(name: str) -> str:
  """The security identifier Windows derives from a service's name: S-1-5-80 and the SHA-1 of the name in capitals."""
  digest = hashlib.sha1(name.upper().encode("utf-16-le")).digest()
  return "S-1-5-80-" + "-".join(str(int.from_bytes(digest[index:index + 4], "little")) for index in range(0, 20, 4))


def definition(deployment: Deployment, role: Role) -> ServiceDefinition:
  name = deployment.name(role)
  entry = Path(__file__).with_name("windowsEntry.py")
  command = [str(deployment.python), "-P", str(entry), *deployment.hostArguments(role, readsEnvironmentFile=True)]
  does = ("serves the web interface and the API" if role is Role.web else "runs the scheduled tasks")
  return ServiceDefinition(name=name, displayName=serviceTitle(role, deployment.suffix),
                           description=f"OpenFurrow, agricultural trial management: {does} of one store.",
                           commandLine=subprocess.list2cmdline(command), account=f"NT SERVICE\\{name}")


def grantCommands(deployment: Deployment) -> list[list[str]]:
  identifiers = [serviceSID(deployment.name(role)) for role in Role]
  commands = [["icacls", str(folder), "/grant", *[f"*{identifier}:(OI)(CI)M" for identifier in identifiers]]
              for folder in deployment.writtenFolders()]
  if deployment.environmentFile is not None:
    commands.append(["icacls", str(deployment.environmentFile), "/inheritance:r", "/grant:r",
                     f"*{administratorsSID}:F", f"*{systemSID}:F", *[f"*{identifier}:R" for identifier in identifiers]])
  return commands


def revokeCommands(deployment: Deployment) -> list[list[str]]:
  identifiers = [f"*{serviceSID(deployment.name(role))}" for role in Role]
  paths = [*deployment.writtenFolders(), *([] if deployment.environmentFile is None else [deployment.environmentFile])]
  return [["icacls", str(path), "/remove", *identifiers] for path in paths]


# ---- the service manager's calls ------------------------------------------------------

class SERVICE_STATUS(ctypes.Structure):
  _fields_ = [("dwServiceType", wintypes.DWORD), ("dwCurrentState", wintypes.DWORD),
              ("dwControlsAccepted", wintypes.DWORD), ("dwWin32ExitCode", wintypes.DWORD),
              ("dwServiceSpecificExitCode", wintypes.DWORD), ("dwCheckPoint", wintypes.DWORD),
              ("dwWaitHint", wintypes.DWORD)]


class QUERY_SERVICE_CONFIGW(ctypes.Structure):
  _fields_ = [("dwServiceType", wintypes.DWORD), ("dwStartType", wintypes.DWORD), ("dwErrorControl", wintypes.DWORD),
              ("lpBinaryPathName", wintypes.LPWSTR), ("lpLoadOrderGroup", wintypes.LPWSTR), ("dwTagId", wintypes.DWORD),
              ("lpDependencies", wintypes.LPWSTR), ("lpServiceStartName", wintypes.LPWSTR),
              ("lpDisplayName", wintypes.LPWSTR)]


class SERVICE_DESCRIPTIONW(ctypes.Structure):
  _fields_ = [("lpDescription", wintypes.LPWSTR)]


class SERVICE_DELAYED_AUTO_START_INFO(ctypes.Structure):
  _fields_ = [("fDelayedAutostart", wintypes.BOOL)]


class SC_ACTION(ctypes.Structure):
  _fields_ = [("Type", ctypes.c_int), ("Delay", wintypes.DWORD)]


class SERVICE_FAILURE_ACTIONSW(ctypes.Structure):
  _fields_ = [("dwResetPeriod", wintypes.DWORD), ("lpRebootMsg", wintypes.LPWSTR), ("lpCommand", wintypes.LPWSTR),
              ("cActions", wintypes.DWORD), ("lpsaActions", ctypes.POINTER(SC_ACTION))]


class SERVICE_FAILURE_ACTIONS_FLAG(ctypes.Structure):
  _fields_ = [("fFailureActionsOnNonCrashFailures", wintypes.BOOL)]


def _advapi32():
  library = ctypes.WinDLL("advapi32", use_last_error=True)
  handle, text, number = wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD
  for name, result, arguments in (
    ("OpenSCManagerW", handle, (text, text, number)),
    ("OpenServiceW", handle, (handle, text, number)),
    ("CreateServiceW", handle, (handle, text, text, number, number, number, number, text, text,
                                ctypes.POINTER(number), text, text, text)),
    ("ChangeServiceConfig2W", wintypes.BOOL, (handle, number, wintypes.LPVOID)),
    ("DeleteService", wintypes.BOOL, (handle,)),
    ("StartServiceW", wintypes.BOOL, (handle, number, ctypes.POINTER(text))),
    ("ControlService", wintypes.BOOL, (handle, number, ctypes.POINTER(SERVICE_STATUS))),
    ("QueryServiceStatus", wintypes.BOOL, (handle, ctypes.POINTER(SERVICE_STATUS))),
    ("QueryServiceConfigW", wintypes.BOOL, (handle, wintypes.LPVOID, number, ctypes.POINTER(number))),
    ("CloseServiceHandle", wintypes.BOOL, (handle,)),
    ("CreateWellKnownSid", wintypes.BOOL, (ctypes.c_int, wintypes.LPVOID, wintypes.LPVOID, ctypes.POINTER(number))),
    ("CheckTokenMembership", wintypes.BOOL, (handle, wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL))),
  ):
    function = getattr(library, name)
    function.restype, function.argtypes = result, arguments
  return library


def _failure(what: str) -> DeploymentError:
  code = ctypes.get_last_error()
  return DeploymentError(f"{what}: {ctypes.FormatError(code).strip()} (Windows error {code})")


@contextmanager
def _serviceManager(access: int):
  advapi32 = _advapi32()
  manager = advapi32.OpenSCManagerW(None, None, access)
  if not manager:
    raise _failure("the service manager cannot be opened")
  try:
    yield advapi32, manager
  finally:
    advapi32.CloseServiceHandle(manager)


@contextmanager
def _service(name: str, access: int):
  """The service's handle, or None when no such service is installed."""
  with _serviceManager(_scManagerConnect) as (advapi32, manager):
    service = advapi32.OpenServiceW(manager, name, access)
    if not service:
      if ctypes.get_last_error() != _errorServiceDoesNotExist:
        raise _failure(f"the service {name} cannot be opened")
      yield advapi32, None
      return
    try:
      yield advapi32, service
    finally:
      advapi32.CloseServiceHandle(service)


def _status(name: str) -> SERVICE_STATUS | None:
  with _service(name, _serviceQueryStatus) as (advapi32, service):
    if service is None:
      return None
    status = SERVICE_STATUS()
    if not advapi32.QueryServiceStatus(service, ctypes.byref(status)):
      raise _failure(f"the state of the service {name} cannot be read")
    return status


def _run(command: list[str]) -> None:
  completed = subprocess.run(command, capture_output=True, text=True)
  if completed.returncode != 0:
    raise DeploymentError(f"{' '.join(command)} failed with exit code {completed.returncode}: "
                          f"{(completed.stderr or completed.stdout).strip()}")


# ---- what the installer asks of a platform ----------------------------------------------

def isElevated() -> bool:
  advapi32 = _advapi32()
  size = wintypes.DWORD(68)
  administrators = ctypes.create_string_buffer(size.value)
  member = wintypes.BOOL()
  if not advapi32.CreateWellKnownSid(_winBuiltinAdministratorsSid, None, administrators, ctypes.byref(size)) \
     or not advapi32.CheckTokenMembership(None, administrators, ctypes.byref(member)):
    raise _failure("whether this shell is elevated cannot be read")
  return bool(member.value)


def check(deployment: Deployment) -> None:
  profile = Path(os.environ["USERPROFILE"]).resolve()
  hidden = sorted({str(path) for path in serviceCode(deployment.python) if under(path, (profile,))})
  if hidden:
    raise DeploymentError(f"a service runs as an account of its own, which cannot read your profile folder {profile}, "
                          f"and Python or OpenFurrow is installed there ({hidden[0]}"
                          f"{f' and {len(hidden) - 1} more files' if len(hidden) > 1 else ''}). Install Python for "
                          f"all users and OpenFurrow outside the profile, then install the services from there")


def state(name: str) -> ServiceState:
  status = _status(name)
  if status is None:
    return ServiceState.notInstalled
  if status.dwCurrentState == 1:
    ended = status.dwWin32ExitCode not in (0, _errorServiceNeverStarted)
    return ServiceState.failed if ended else ServiceState.stopped
  states = {2: ServiceState.starting, 3: ServiceState.stopping, 4: ServiceState.running}
  if status.dwCurrentState not in states:
    raise DeploymentError(f"the service {name} is in state {status.dwCurrentState}, which an OpenFurrow service "
                          f"never enters")
  return states[status.dwCurrentState]


def installed(role: Role, suffix: str | None) -> Deployment | None:
  name = serviceName(role, suffix)
  with _service(name, _serviceQueryConfig) as (advapi32, service):
    if service is None:
      return None
    needed = wintypes.DWORD()
    advapi32.QueryServiceConfigW(service, None, 0, ctypes.byref(needed))
    if ctypes.get_last_error() != _errorInsufficientBuffer:
      raise _failure(f"the definition of the service {name} cannot be read")
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.QueryServiceConfigW(service, buffer, needed, ctypes.byref(needed)):
      raise _failure(f"the definition of the service {name} cannot be read")
    commandLine = ctypes.cast(buffer, ctypes.POINTER(QUERY_SERVICE_CONFIGW)).contents.lpBinaryPathName
  return deploymentOfCommandLine(name, commandLine)[1]


def deploymentOfCommandLine(name: str, commandLine: str) -> tuple[Role, Deployment]:
  shell32 = ctypes.WinDLL("shell32", use_last_error=True)
  shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
  shell32.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
  kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
  kernel32.LocalFree.argtypes = (wintypes.LPVOID,)
  count = ctypes.c_int()
  words = shell32.CommandLineToArgvW(commandLine, ctypes.byref(count))
  if not words:
    raise _failure(f"the command line of the service {name} cannot be read")
  try:
    command = [words[index] for index in range(count.value)]
  finally:
    kernel32.LocalFree(words)
  if len(command) < 4 or command[1] != "-P" or Path(command[2]).name != "windowsEntry.py":
    raise DeploymentError(f"the service {name} is not one OpenFurrow installed: it runs {commandLine}")
  return deploymentOf(command[0], command[3:])


def install(deployment: Deployment) -> None:
  with _serviceManager(_scManagerConnect | _scManagerCreateService) as (advapi32, manager):
    for role in Role:
      _create(advapi32, manager, definition(deployment, role))
  for command in grantCommands(deployment):
    _run(command)


def _create(advapi32, manager, wanted: ServiceDefinition) -> None:
  service = advapi32.CreateServiceW(manager, wanted.name, wanted.displayName, _serviceAllAccess, _serviceWin32OwnProcess,
                                    _serviceAutoStart, _serviceErrorNormal, wanted.commandLine, None, None, None,
                                    wanted.account, None)
  if not service:
    raise _failure(f"the service {wanted.name} cannot be created")
  try:
    actions = (SC_ACTION * len(wanted.restartDelaysMilliseconds))(
      *[SC_ACTION(_actionRestart, delay) for delay in wanted.restartDelaysMilliseconds])
    for level, information in (
      (_configDescription, SERVICE_DESCRIPTIONW(wanted.description)),
      (_configDelayedAutoStart, SERVICE_DELAYED_AUTO_START_INFO(wanted.delayedStart)),
      (_configFailureActions, SERVICE_FAILURE_ACTIONSW(wanted.failureResetSeconds, None, None, len(actions), actions)),
      (_configFailureActionsFlag, SERVICE_FAILURE_ACTIONS_FLAG(wanted.restartsOnExitCode)),
    ):
      if not advapi32.ChangeServiceConfig2W(service, level, ctypes.byref(information)):
        raise _failure(f"the service {wanted.name} cannot be configured (setting {level})")
  finally:
    advapi32.CloseServiceHandle(service)


def uninstall(deployment: Deployment) -> None:
  """Take back the rights and delete the services, which are stopped; whatever is already gone is passed over."""
  for command in revokeCommands(deployment):
    if Path(command[1]).exists():
      _run(command)
  names = [deployment.name(role) for role in Role]
  for name in names:
    with _service(name, _delete) as (advapi32, service):
      if service is not None and not advapi32.DeleteService(service):
        raise _failure(f"the service {name} cannot be deleted")
  for name in names:
    deadline = time.monotonic() + deletionSeconds
    while state(name) is not ServiceState.notInstalled:
      if time.monotonic() > deadline:
        raise DeploymentError(f"the service {name} is marked for deletion and goes once nothing holds it open: "
                              f"close the Services console and any other tool showing it")
      time.sleep(0.2)


def start(name: str) -> None:
  with _service(name, _serviceStart) as (advapi32, service):
    if service is None:
      raise DeploymentError(f"the service {name} is not installed")
    if not advapi32.StartServiceW(service, 0, None) and ctypes.get_last_error() != _errorServiceAlreadyRunning:
      raise _failure(f"the service {name} cannot be started")


def stop(name: str) -> None:
  """Ask the service to stop. One that is starting or already stopping takes no control, so it is asked again
  until it does or has stopped; one that is not running needs no asking."""
  deadline = time.monotonic() + pendingSeconds
  with _service(name, _serviceStop) as (advapi32, service):
    if service is None:
      raise DeploymentError(f"the service {name} is not installed")
    status = SERVICE_STATUS()
    while not advapi32.ControlService(service, _controlStop, ctypes.byref(status)):
      if ctypes.get_last_error() == _errorServiceNotActive:
        return
      if ctypes.get_last_error() != _errorServiceCannotAcceptControl or time.monotonic() > deadline:
        raise _failure(f"the service {name} cannot be stopped")
      time.sleep(0.2)
