# SPDX-License-Identifier: Apache-2.0
"""An OpenFurrow service under the Windows service manager: what it reports and how it answers controls.

`windowsEntry` holds the connection to the service manager and loads this module once the
connection stands. Here the supervisor's phases become the statuses the service manager
is given: start pending, running (taking stop and shutdown), stop pending, and stopped,
with a service-specific exit code when the work failed, so the recovery actions set at
install apply. A stop lets the work end in its own time; a system shutdown, which gives
a service only seconds, has it end at once: the scheduler then stops its running runs and
records them stopped, as it does at a second Ctrl+C.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openfurrow.osService.deployment import Role, hostOptions, serviceName
from openfurrow.osService.host import Phase, Supervisor, Work, openLog, workOf

stateStopped, stateStartPending, stateStopPending, stateRunning = 1, 2, 3, 4
acceptStop, acceptShutdown = 0x1, 0x4
controlStop, controlInterrogate, controlShutdown = 1, 4, 5
noError, errorCallNotImplemented, errorServiceSpecificError = 0, 120, 1066
startSeconds = 120


@dataclass(frozen=True)
class ServiceStatus:
  """The fields of a SERVICE_STATUS that a service sets; the wait hint is in milliseconds."""

  currentState: int
  controlsAccepted: int = 0
  win32ExitCode: int = noError
  serviceSpecificExitCode: int = 0
  checkPoint: int = 0
  waitHint: int = 0


def statusOf(phase: Phase, exitCode: int, stopSeconds: float) -> ServiceStatus:
  if phase is Phase.starting:
    return ServiceStatus(stateStartPending, checkPoint=2, waitHint=startSeconds * 1000)
  if phase is Phase.running:
    return ServiceStatus(stateRunning, controlsAccepted=acceptStop | acceptShutdown)
  if phase is Phase.stopping:
    return ServiceStatus(stateStopPending, checkPoint=1, waitHint=int(stopSeconds * 1000))
  if exitCode:
    return ServiceStatus(stateStopped, win32ExitCode=errorServiceSpecificError, serviceSpecificExitCode=exitCode)
  return ServiceStatus(stateStopped)


class ControlledService:
  """A supervisor whose phases reach the service manager through `setStatus`, and the answers to its controls."""

  def __init__(self, work: Work, setStatus: Callable[[ServiceStatus], None], log) -> None:
    self.work = work
    self.setStatus = setStatus
    self.supervisor = Supervisor(work, self._report, log)

  def _report(self, phase: Phase, exitCode: int) -> None:
    stopSeconds = self.work.stopSeconds if phase is Phase.stopping else 0
    self.setStatus(statusOf(phase, exitCode, stopSeconds))

  def serve(self) -> int:
    return self.supervisor.serve()

  def control(self, control: int) -> int:
    if control == controlStop:
      self.supervisor.requestStop()
    elif control == controlShutdown:
      self.supervisor.requestStop(hurry=True)
    elif control != controlInterrogate:
      return errorCallNotImplemented
    return noError


def serve(arguments: list[str], setStatus: Callable[[ServiceStatus], None],
          takeControls: Callable[[Callable[[int], int]], None]) -> int:
  """Run the service these arguments define; `takeControls` is handed the function that answers a control."""
  options = hostOptions(arguments)
  log = openLog(Path(options.logs), serviceName(Role(options.role), options.suffix))
  service = ControlledService(workOf(options), setStatus, log)
  takeControls(service.control)
  return service.serve()
