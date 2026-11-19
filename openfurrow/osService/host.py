# SPDX-License-Identifier: Apache-2.0
"""The process an installed service runs (decision 0009): `python -m openfurrow.osService.host web|scheduler ...`.

One process does one service's work, the web server or the scheduler, under a supervisor
that tells the service manager where it stands: starting, running, stopping, stopped, and
whether it stopped because it was asked or because it failed. A process that fails exits
non-zero, so the service manager's restart rule applies. systemd is told through its
notification socket and launchd reads the exit code; the Windows service manager is
served by `windowsHost`, which runs the same supervisor.

Everything the process says goes to one log file in the deployment's logs folder, a new
file each UTC day and `logRetentionDays` of them kept. The log holds no personal data:
a request is logged by its route's pattern and its status, never by the address asked
for, its query or the client's address, and an error after start by its type and the
code it passed through, never by its message, which can quote what a person entered.
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import os
import signal
import socket
import sys
import threading
import time
import traceback
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol

from openfurrow.osService.deployment import DeploymentError, Role, hostOptions, logRetentionDays, readEnvironmentFile, serviceName
from openfurrow.tasks.run import storeVariable


class Phase(Enum):
  starting = "starting"
  running = "running"
  stopping = "stopping"
  stopped = "stopped"


Report = Callable[[Phase, int], None]


def describe(error: BaseException) -> str:
  """An error's type and the code it passed through, without its message, which can quote a person's data."""
  frames = traceback.extract_tb(error.__traceback__)
  trail = " < ".join(f"{Path(frame.filename).name}:{frame.lineno} {frame.name}" for frame in reversed(frames))
  return f"{type(error).__name__} at {trail}" if trail else type(error).__name__


class Work(Protocol):
  stopSeconds: float

  def start(self) -> None: ...
  def run(self) -> None: ...
  def stop(self, hurry: bool) -> None: ...


class _StoreWork:
  def __init__(self, store: str | None, environmentFile: Path | None) -> None:
    self.store = store
    self.environmentFile = environmentFile

  def location(self) -> str:
    if self.environmentFile is not None:
      os.environ.update(readEnvironmentFile(self.environmentFile))
    if self.store is not None:
      return self.store
    if not os.environ.get(storeVariable):
      raise DeploymentError(f"the service was given no store file, and the environment variable {storeVariable} "
                            f"is not set")
    return os.environ[storeVariable]


class WebWork(_StoreWork):
  stopSeconds = 15.0

  def __init__(self, store: str | None, environmentFile: Path | None, host: str, port: int) -> None:
    super().__init__(store, environmentFile)
    self.host = host
    self.port = port
    self.server = None

  def start(self) -> None:
    from openfurrow.config import OpenFurrowConfig
    from openfurrow.osService.quietServer import QuietRequestHandler, QuietServer, logRequestsByRoute
    from openfurrow.service import createApp, makeServer
    config = OpenFurrowConfig.model_validate({"service": {"host": self.host, "port": self.port}})
    application = createApp(self.location(), config)
    logRequestsByRoute(application)
    self.server = makeServer(application, config, QuietServer, QuietRequestHandler)

  def run(self) -> None:
    self.server.serve_forever()

  def stop(self, hurry: bool) -> None:
    self.server.shutdown()


class SchedulerWork(_StoreWork):
  def __init__(self, store: str | None, environmentFile: Path | None, runCommand: list[str] | None = None) -> None:
    super().__init__(store, environmentFile)
    self.runCommand = runCommand
    self.scheduler = None

  @property
  def stopSeconds(self) -> float:
    return self.scheduler.stopGraceSeconds + self.scheduler.killGraceSeconds + 15

  def start(self) -> None:
    from openfurrow.tasks.scheduler import Scheduler
    self.scheduler = Scheduler(self.location(), runCommand=self.runCommand)

  def run(self) -> None:
    self.scheduler.loop()

  def stop(self, hurry: bool) -> None:
    self.scheduler.stop()
    if hurry:
      self.scheduler.stop()


class Supervisor:
  """Starts the work, runs it until it is asked to stop or fails, and reports each phase as it is entered.

  `serve` does the work on the calling thread and returns the process's exit code; `requestStop` comes from
  another thread or a signal. A stop asked for while the work starts ends the service once it has started; one
  asked for again, or with `hurry`, has the work stop at once rather than in its own time.
  """

  def __init__(self, work: Work, report: Report, log: logging.Logger) -> None:
    self.work = work
    self.report = report
    self.log = log
    self._lock = threading.Lock()
    self._phase: Phase | None = None
    self._stopsRequested = 0

  def serve(self) -> int:
    self._enter(Phase.starting)
    try:
      self.work.start()
    except Exception as error:
      self.log.error("could not start: %s: %s (%s)", type(error).__name__, error, describe(error))
      return self._finish(failed=True)
    with self._lock:
      stopRequested = self._stopsRequested > 0
      if not stopRequested:
        self._setPhase(Phase.running, 0)
    if stopRequested:
      return self._finish(failed=False)
    try:
      self.work.run()
    except Exception as error:
      self.log.error("failed while running: %s", describe(error))
      return self._finish(failed=True)
    with self._lock:
      stopRequested = self._stopsRequested > 0
    if not stopRequested:
      self.log.error("the work ended without being asked to stop")
    return self._finish(failed=not stopRequested)

  def requestStop(self, hurry: bool = False) -> None:
    with self._lock:
      if self._phase is Phase.stopped:
        return
      self._stopsRequested += 1
      hurry = hurry or self._stopsRequested > 1
      if self._phase in (None, Phase.starting):
        return
      if self._phase is Phase.running:
        self._setPhase(Phase.stopping, 0)
    self.work.stop(hurry)

  def _enter(self, phase: Phase) -> None:
    with self._lock:
      self._setPhase(phase, 0)

  def _finish(self, failed: bool) -> int:
    exitCode = 1 if failed else 0
    with self._lock:
      self._setPhase(Phase.stopped, exitCode)
    return exitCode

  def _setPhase(self, phase: Phase, exitCode: int) -> None:
    self._phase = phase
    self.log.log(logging.ERROR if exitCode else logging.INFO, "%s%s", phase.value, " after a failure" if exitCode else "")
    self.report(phase, exitCode)


class _LogStream(io.TextIOBase):
  """Standard output or error as lines of the log: a service has no console to show them."""

  def __init__(self, log: logging.Logger, level: int) -> None:
    self._log = log
    self._level = level
    self._pending = ""
    self._writing = threading.local()

  def writable(self) -> bool:
    return True

  def write(self, text: str) -> int:
    # A log handler that fails reports to standard error, which is this stream.
    if getattr(self._writing, "now", False):
      return len(text)
    self._writing.now = True
    try:
      *lines, self._pending = (self._pending + text).split("\n")
      for line in lines:
        if line.strip():
          self._log.log(self._level, "%s", line.rstrip())
    finally:
      self._writing.now = False
    return len(text)


def openLog(logsFolder: Path, name: str) -> logging.Logger:
  """Send this process's logging, warnings, standard output and standard error to the service's log file."""
  handler = logging.handlers.TimedRotatingFileHandler(logsFolder / f"{name}.log", when="midnight", utc=True,
                                                      backupCount=logRetentionDays, encoding="utf-8")
  formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%SZ")
  formatter.converter = time.gmtime
  handler.setFormatter(formatter)
  root = logging.getLogger()
  root.addHandler(handler)
  root.setLevel(logging.INFO)
  logging.captureWarnings(True)
  output = logging.getLogger("openfurrow.service.output")
  sys.stdout = _LogStream(output, logging.INFO)
  sys.stderr = _LogStream(output, logging.WARNING)
  log = logging.getLogger("openfurrow.service")
  sys.excepthook = lambda kind, error, trace: log.error("unhandled: %s", describe(error))
  threading.excepthook = lambda hook: log.error("unhandled in a thread: %s", hook.exc_type.__name__ if hook.exc_value is None
                                                else describe(hook.exc_value))
  return log


def workOf(options) -> Work:
  environmentFile = None if options.environmentFile is None else Path(options.environmentFile)
  if Role(options.role) is Role.scheduler:
    return SchedulerWork(options.store, environmentFile)
  return WebWork(options.store, environmentFile, options.host, options.port)


def tellSystemd(phase: Phase, exitCode: int) -> None:
  """systemd's notification protocol: a datagram to the socket it names, when it started the process as a notify service."""
  address = os.environ.get("NOTIFY_SOCKET")
  message = {Phase.running: b"READY=1", Phase.stopping: b"STOPPING=1"}.get(phase)
  if address is None or message is None:
    return
  with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
    notifier.sendto(message, "\0" + address[1:] if address.startswith("@") else address)


def main(argv: list[str]) -> int:
  options = hostOptions(argv)
  log = openLog(Path(options.logs), serviceName(Role(options.role), options.suffix))
  supervisor = Supervisor(workOf(options), tellSystemd, log)

  def onSignal(number, frame) -> None:
    # A stop waits for the serving loop to end, and that loop runs on this, the signal's, thread.
    threading.Thread(target=supervisor.requestStop, daemon=True).start()

  for number in [signal.SIGINT, signal.SIGTERM] + ([signal.SIGBREAK] if sys.platform == "win32" else []):
    signal.signal(number, onSignal)
  return supervisor.serve()


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
