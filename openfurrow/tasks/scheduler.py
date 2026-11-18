# SPDX-License-Identifier: Apache-2.0
"""The scheduler (decision 0041): its own process, `openfurrow scheduler <store>`, beside the web server.

Every poll it checks in, finds the tasks that are due and requests one run of each (a
time missed while no scheduler ran is run once, not once per missed time; a time due
while the task's previous run still goes is recorded skipped), claims requested runs up
to the server's limit on runs at once, and starts each as a subprocess with its output
captured. A run past its task's time limit is stopped and recorded so; a run whose
process ends without recording an outcome is recorded failed with its output.

Several schedulers may share a store by mistake, or as hosts of a cluster: a due time is
taken by one conditional update of the task's next run time, and a run by one conditional
update from requested to running, so only the scheduler whose update took acts on it. A
run left running by a scheduler on this host that has died, and whose process is gone,
is recorded failed; one whose process outlived it is stopped at its time limit.

Stopping (Ctrl+C, SIGTERM, or Ctrl+Break on Windows) ends the claiming of new runs and
waits for the running ones up to `stopGraceSeconds`; those still going then, or at a
second signal, are stopped and recorded so. Runs are started in a process group of their
own, so the console's Ctrl+C reaches the scheduler and not them.
"""

from __future__ import annotations

import datetime
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openfurrow.store.database import ScheduledTaskRow, SchedulerHeartbeatRow, TaskRunRow, createDatabase
from openfurrow.store.tasks import hasActiveRun, readSchedule, serverSetting, stored
from openfurrow.tasks.model import RunState, outputLimitBytes
from openfurrow.tasks.run import storeVariable

Clock = Callable[[], datetime.datetime]


def utcNow() -> datetime.datetime:
  return datetime.datetime.now(datetime.UTC)


def processIsAlive(processID: int) -> bool:
  if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, processID)
    if not handle:
      return ctypes.get_last_error() == 5
    try:
      code = wintypes.DWORD()
      if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
        raise OSError(ctypes.get_last_error(), f"the state of process {processID} cannot be read")
      return code.value == 259
    finally:
      kernel.CloseHandle(handle)
  try:
    os.kill(processID, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    return True
  return True


class _Output:
  """A run's output as it arrives, keeping the last outputLimitBytes and counting what was left out before them."""

  def __init__(self) -> None:
    self._kept = bytearray()
    self._leftOut = 0

  def add(self, chunk: bytes) -> None:
    self._kept += chunk
    excess = len(self._kept) - outputLimitBytes
    if excess > 0:
      del self._kept[:excess]
      self._leftOut += excess

  def text(self) -> str:
    if not self._leftOut:
      return self._kept.decode("utf-8", errors="replace")
    notice = f"[{self._leftOut} earlier bytes of output left out]\n".encode("ascii")
    kept = bytes(self._kept[len(notice):])
    return (notice + kept).decode("utf-8", errors="replace")


@dataclass
class _Child:
  runID: int
  process: subprocess.Popen
  startedAt: datetime.datetime
  timeLimitSeconds: int
  output: _Output = field(default_factory=_Output)
  reader: threading.Thread | None = None
  killAt: float | None = None


class Scheduler:
  def __init__(self, location: str, pollSeconds: float = 2.0, clock: Clock = utcNow,
               runCommand: list[str] | None = None, stopGraceSeconds: float = 20.0, killGraceSeconds: float = 10.0) -> None:
    if pollSeconds <= 0:
      raise ValueError("the scheduler polls every so many seconds, more than none")
    self.location = location
    self.engine = createDatabase(location, create=False)
    self.pollSeconds = pollSeconds
    self.clock = clock
    self.runCommand = runCommand or [sys.executable, "-m", "openfurrow.tasks.run"]
    self.stopGraceSeconds = stopGraceSeconds
    self.killGraceSeconds = killGraceSeconds
    self.host = socket.gethostname()
    self.processID = os.getpid()
    self.children: dict[int, _Child] = {}
    self._stopRequested = threading.Event()
    self._hurry = threading.Event()

  # ---- one poll -------------------------------------------------------------

  def tick(self) -> None:
    self._checkIn()
    self._recordAbandoned()
    self._collectFinished()
    self._enforceTimeLimits()
    if not self._stopRequested.is_set():
      self._requestDue()
      self._claimRequested()
    self._removeOldRuns()

  def _checkIn(self) -> None:
    values = {"host": self.host, "processID": self.processID, "lastSeenAt": stored(self.clock())}
    with Session(self.engine) as session:
      if session.execute(update(SchedulerHeartbeatRow).where(SchedulerHeartbeatRow.heartbeatID == 1)
                         .values(**values)).rowcount == 1:
        session.commit()
        return
      session.add(SchedulerHeartbeatRow(heartbeatID=1, **values))
      try:
        session.commit()
      except IntegrityError:
        session.rollback()
        session.execute(update(SchedulerHeartbeatRow).where(SchedulerHeartbeatRow.heartbeatID == 1).values(**values))
        session.commit()

  def _requestDue(self) -> None:
    now = self.clock()
    with Session(self.engine) as session:
      zone = serverSetting(session, "tasks.timeZone")
      due = session.execute(select(ScheduledTaskRow).where(ScheduledTaskRow.enabled.is_(True),
                                                           ScheduledTaskRow.nextRunAt <= stored(now))).scalars().all()
      plans = [(row.name, row.nextRunAt, stored(readSchedule(row.schedule, zone).nextAfter(now))) for row in due]
    for name, dueAt, following in plans:
      with Session(self.engine) as session:
        taken = session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.name == name,
                                                               ScheduledTaskRow.nextRunAt == dueAt)
                                .values(nextRunAt=following)).rowcount
        if taken != 1:
          session.rollback()
          continue
        if hasActiveRun(session, name):
          session.add(TaskRunRow(taskName=name, requestedBy="schedule", requestedAt=stored(now),
                                 finishedAt=stored(now), state=RunState.skipped.value, output="",
                                 summary="skipped: the task's previous run was still going"))
        else:
          session.add(TaskRunRow(taskName=name, requestedBy="schedule", requestedAt=stored(now),
                                 state=RunState.requested.value, output=""))
        session.commit()

  def claim(self, runID: int) -> bool:
    """Move a requested run to running for this scheduler; True only for the one scheduler whose update took."""
    with Session(self.engine) as session:
      taken = session.execute(update(TaskRunRow).where(TaskRunRow.runID == runID,
                                                       TaskRunRow.state == RunState.requested.value)
                              .values(state=RunState.running.value, startedAt=stored(self.clock()), host=self.host,
                                      schedulerProcessID=self.processID)).rowcount
      session.commit()
    return taken == 1

  def _claimRequested(self) -> None:
    with Session(self.engine) as session:
      limit = serverSetting(session, "tasks.maximumConcurrentRuns")
      running = session.execute(select(func.count()).select_from(TaskRunRow)
                                .where(TaskRunRow.state == RunState.running.value)).scalar_one()
      requested = session.execute(select(TaskRunRow.runID, TaskRunRow.taskName, ScheduledTaskRow.timeLimitSeconds)
                                  .join(ScheduledTaskRow, ScheduledTaskRow.name == TaskRunRow.taskName)
                                  .where(TaskRunRow.state == RunState.requested.value)
                                  .order_by(TaskRunRow.requestedAt, TaskRunRow.runID)).all()
    for runID, taskName, timeLimitSeconds in requested:
      if running >= limit:
        return
      if self._taskIsRunning(taskName):
        self._finish(runID, RunState.skipped, "skipped: a run of the task was already going",
                     fromState=RunState.requested)
        continue
      if not self.claim(runID):
        continue
      running += 1
      self._start(runID, timeLimitSeconds)

  def _taskIsRunning(self, taskName: str) -> bool:
    with Session(self.engine) as session:
      return session.execute(select(TaskRunRow.runID).where(TaskRunRow.taskName == taskName,
                                                            TaskRunRow.state == RunState.running.value)
                             .limit(1)).first() is not None

  def _start(self, runID: int, timeLimitSeconds: int) -> None:
    environment = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    environment[storeVariable] = self.location
    separate = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
                else {"start_new_session": True})
    try:
      process = subprocess.Popen([*self.runCommand, str(runID)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=environment, **separate)
    except OSError as error:
      self._finish(runID, RunState.failed, f"the run's process could not be started: {error}")
      return
    child = _Child(runID=runID, process=process, startedAt=self.clock(), timeLimitSeconds=timeLimitSeconds)
    child.reader = threading.Thread(target=self._read, args=(child,), daemon=True)
    child.reader.start()
    self.children[runID] = child
    with Session(self.engine) as session:
      session.execute(update(TaskRunRow).where(TaskRunRow.runID == runID).values(processID=process.pid))
      session.commit()

  @staticmethod
  def _read(child: _Child) -> None:
    while chunk := child.process.stdout.read1(65536):
      child.output.add(chunk)

  def _finish(self, runID: int, state: RunState, summary: str, fromState: RunState = RunState.running) -> bool:
    """Record a run's outcome, only while it is still in `fromState`; True when this recorded it."""
    with Session(self.engine) as session:
      taken = session.execute(update(TaskRunRow).where(TaskRunRow.runID == runID, TaskRunRow.state == fromState.value)
                              .values(state=state.value, summary=summary, finishedAt=stored(self.clock()),
                                      processID=None, schedulerProcessID=None)).rowcount
      session.commit()
    return taken == 1

  def _collectFinished(self) -> None:
    for runID, child in list(self.children.items()):
      code = child.process.poll()
      if code is None:
        continue
      child.reader.join()
      child.process.stdout.close()
      self._finish(runID, RunState.failed, f"failed: the run's process ended with exit code {code} without recording "
                                           f"an outcome")
      with Session(self.engine) as session:
        session.execute(update(TaskRunRow).where(TaskRunRow.runID == runID).values(output=child.output.text()))
        session.commit()
      del self.children[runID]

  def _stopChild(self, child: _Child, summary: str) -> None:
    if child.killAt is not None:
      return
    if self._finish(child.runID, RunState.stopped, summary):
      child.process.terminate()
      child.killAt = time.monotonic() + self.killGraceSeconds

  def _enforceTimeLimits(self) -> None:
    now = self.clock()
    for child in list(self.children.values()):
      if child.killAt is None and (now - child.startedAt).total_seconds() > child.timeLimitSeconds:
        self._stopChild(child, f"stopped at its time limit of {child.timeLimitSeconds} seconds")
      elif child.killAt is not None and time.monotonic() >= child.killAt and child.process.poll() is None:
        child.process.kill()

  def _recordAbandoned(self) -> None:
    """Runs this host's schedulers started that no living scheduler watches: failed when their process is gone too,
    stopped once past their time limit when it is not."""
    with Session(self.engine) as session:
      rows = session.execute(select(TaskRunRow.runID, TaskRunRow.schedulerProcessID, TaskRunRow.processID,
                                    TaskRunRow.startedAt, ScheduledTaskRow.timeLimitSeconds)
                             .join(ScheduledTaskRow, ScheduledTaskRow.name == TaskRunRow.taskName)
                             .where(TaskRunRow.state == RunState.running.value, TaskRunRow.host == self.host)).all()
    for runID, schedulerProcessID, processID, startedAt, timeLimitSeconds in rows:
      if runID in self.children or schedulerProcessID == self.processID:
        continue
      if schedulerProcessID is not None and processIsAlive(schedulerProcessID):
        continue
      if processID is None or not processIsAlive(processID):
        self._finish(runID, RunState.failed, "failed: the scheduler that started it stopped, and its process is gone")
      elif (stored(self.clock()) - startedAt).total_seconds() > timeLimitSeconds:
        if self._finish(runID, RunState.stopped, f"stopped at its time limit of {timeLimitSeconds} seconds, after "
                                                 f"the scheduler that started it stopped"):
          os.kill(processID, signal.SIGTERM)

  def _removeOldRuns(self) -> None:
    with Session(self.engine) as session:
      days = serverSetting(session, "tasks.runRetentionDays")
      session.execute(delete(TaskRunRow).where(TaskRunRow.finishedAt < stored(self.clock() - datetime.timedelta(days=days))))
      session.commit()

  # ---- the loop -------------------------------------------------------------

  def stop(self) -> None:
    """Ask the loop to stop; asked again, stop the running runs at once."""
    if self._stopRequested.is_set():
      self._hurry.set()
    self._stopRequested.set()

  def _onSignal(self, number, frame) -> None:
    self.stop()

  def run(self) -> None:
    """Poll until stopped, then wind down the running runs."""
    signals = [signal.SIGINT, signal.SIGTERM] + ([signal.SIGBREAK] if sys.platform == "win32" else [])
    previous = {number: signal.signal(number, self._onSignal) for number in signals}
    try:
      while not self._stopRequested.is_set():
        self.tick()
        self._stopRequested.wait(self.pollSeconds)
      self.windDown()
    finally:
      for number, handler in previous.items():
        signal.signal(number, handler)

  def windDown(self) -> None:
    """Claim nothing more; wait up to stopGraceSeconds for the running runs, then stop and record those still going."""
    self._stopRequested.set()
    deadline = time.monotonic() + self.stopGraceSeconds
    while self.children and time.monotonic() < deadline and not self._hurry.is_set():
      self.tick()
      self._hurry.wait(min(self.pollSeconds, 0.5))
    for child in list(self.children.values()):
      self._stopChild(child, "stopped: the scheduler was stopping")
    while self.children:
      self._checkIn()
      self._collectFinished()
      for child in self.children.values():
        if child.killAt is not None and time.monotonic() >= child.killAt and child.process.poll() is None:
          child.process.kill()
      time.sleep(0.1)
