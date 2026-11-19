# SPDX-License-Identifier: Apache-2.0
"""A service's process (decision 0009), as far as it goes without a service manager: the statuses and exit codes
the Windows service manager would be given and the controls it would send, around scripted work and around the
real web server and scheduler; and the process itself in the foreground, with what it writes to its log."""

import datetime
import json
import logging
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import taskKindsForTests  # noqa: F401
from openfurrow import Workspace
from openfurrow.osService.host import Phase, SchedulerWork, WebWork
from openfurrow.osService.windowsHost import (
  ControlledService, ServiceStatus, acceptShutdown, acceptStop, controlInterrogate, controlShutdown, controlStop,
  errorCallNotImplemented, errorServiceSpecificError, noError, stateRunning, stateStartPending, stateStopPending,
  stateStopped, statusOf,
)
from openfurrow.service import listen
from openfurrow.tasks.model import RunState

testsFolder = Path(__file__).parent
runner = [sys.executable, str(testsFolder / "runWithTestKinds.py")]
log = logging.getLogger("openfurrow.service")
startPending = ServiceStatus(stateStartPending, checkPoint=2, waitHint=120000)
running = ServiceStatus(stateRunning, controlsAccepted=acceptStop | acceptShutdown)
stoppedClean = ServiceStatus(stateStopped)
stoppedFailed = ServiceStatus(stateStopped, win32ExitCode=errorServiceSpecificError, serviceSpecificExitCode=1)
controlPause = 2


class ScriptedWork:
  """Work that runs until it is stopped, or fails or ends where the test says."""

  stopSeconds = 7.0

  def __init__(self, failsAtStart=False, failsRunning=False, endsUnasked=False, endsOnlyWhenHurried=False, startGate=None):
    self.failsAtStart, self.failsRunning, self.endsUnasked = failsAtStart, failsRunning, endsUnasked
    self.endsOnlyWhenHurried, self.startGate = endsOnlyWhenHurried, startGate
    self.calls = []
    self.starting = threading.Event()
    self.stopped = threading.Event()

  def start(self):
    self.calls.append("start")
    self.starting.set()
    if self.startGate is not None:
      assert self.startGate.wait(30)
    if self.failsAtStart:
      raise RuntimeError("no store at C:\\OpenFurrow")

  def run(self):
    self.calls.append("run")
    if self.failsRunning:
      raise RuntimeError("the row of Ada Lovelace was refused")
    if not self.endsUnasked:
      assert self.stopped.wait(30)

  def stop(self, hurry):
    self.calls.append(("stop", hurry))
    if hurry or not self.endsOnlyWhenHurried:
      self.stopped.set()


def serving(service):
  """Serve on a thread of its own, as the service manager's dispatcher does; the thread and where its exit code lands."""
  exitCodes = []
  thread = threading.Thread(target=lambda: exitCodes.append(service.serve()), daemon=True)
  thread.start()
  return thread, exitCodes


def until(condition, seconds=60, what="the condition"):
  deadline = time.monotonic() + seconds
  while time.monotonic() < deadline:
    value = condition()
    if value:
      return value
    time.sleep(0.05)
  raise AssertionError(f"{what} did not come about within {seconds} seconds")


def freePort():
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.bind(("127.0.0.1", 0))
    return probe.getsockname()[1]


@pytest.fixture
def location(newStore):
  location = newStore("served")
  Workspace.create(location)
  return location


# ---- phases as the Windows service manager is told them ------------------------------

def testEachPhaseIsOneStatus():
  assert statusOf(Phase.starting, 0, 0) == startPending
  assert statusOf(Phase.running, 0, 0) == running
  assert statusOf(Phase.stopping, 0, 45.5) == ServiceStatus(stateStopPending, checkPoint=1, waitHint=45500)
  assert statusOf(Phase.stopped, 0, 0) == stoppedClean
  assert statusOf(Phase.stopped, 1, 0) == stoppedFailed
  assert (stateStopped, stateStartPending, stateStopPending, stateRunning) == (1, 2, 3, 4)
  assert (stoppedFailed.win32ExitCode, startPending.controlsAccepted, running.controlsAccepted) == (1066, 0, 0x5)


def testAStopControlStopsTheWorkInItsOwnTimeAndTheServiceEndsClean():
  statuses, work = [], ScriptedWork()
  service = ControlledService(work, statuses.append, log)
  thread, exitCodes = serving(service)
  until(lambda: statuses[-1:] == [running])
  assert service.control(controlStop) == noError
  thread.join(30)
  assert exitCodes == [0]
  assert statuses == [startPending, running, ServiceStatus(stateStopPending, checkPoint=1, waitHint=7000), stoppedClean]
  assert work.calls == ["start", "run", ("stop", False)]


def testAShutdownControlStopsTheWorkAtOnce():
  statuses, work = [], ScriptedWork()
  service = ControlledService(work, statuses.append, log)
  thread, exitCodes = serving(service)
  until(lambda: statuses[-1:] == [running])
  assert service.control(controlShutdown) == noError
  thread.join(30)
  assert (exitCodes, work.calls[-1], statuses[-1]) == ([0], ("stop", True), stoppedClean)


def testASecondStopHurriesTheWork():
  statuses, work = [], ScriptedWork(endsOnlyWhenHurried=True)
  service = ControlledService(work, statuses.append, log)
  thread, exitCodes = serving(service)
  until(lambda: statuses[-1:] == [running])
  service.control(controlStop)
  assert (work.calls, thread.is_alive()) == (["start", "run", ("stop", False)], True)
  service.control(controlStop)
  thread.join(30)
  assert (exitCodes, work.calls[-1]) == ([0], ("stop", True))
  assert [status.currentState for status in statuses] == [stateStartPending, stateRunning, stateStopPending, stateStopped]


def testInterrogationIsAnsweredAndOtherControlsAreNotTaken():
  statuses, work = [], ScriptedWork()
  service = ControlledService(work, statuses.append, log)
  thread, exitCodes = serving(service)
  until(lambda: statuses[-1:] == [running])
  assert service.control(controlInterrogate) == noError
  assert service.control(controlPause) == errorCallNotImplemented
  assert (statuses, work.calls) == ([startPending, running], ["start", "run"])
  service.control(controlStop)
  thread.join(30)
  assert exitCodes == [0]


def testWorkThatCannotStartStopsTheServiceWithItsExitCodeAndSaysWhy(caplog):
  statuses, work = [], ScriptedWork(failsAtStart=True)
  with caplog.at_level(logging.INFO, logger="openfurrow.service"):
    assert ControlledService(work, statuses.append, log).serve() == 1
  assert statuses == [startPending, stoppedFailed]
  assert work.calls == ["start"]
  assert "could not start: RuntimeError: no store at C:\\OpenFurrow" in caplog.text


def testWorkThatFailsWhileRunningStopsTheServiceWithItsExitCodeAndLogsNoMessage(caplog):
  statuses, work = [], ScriptedWork(failsRunning=True)
  with caplog.at_level(logging.INFO, logger="openfurrow.service"):
    assert ControlledService(work, statuses.append, log).serve() == 1
  assert statuses == [startPending, running, stoppedFailed]
  assert re.search(r"failed while running: RuntimeError at testServiceHost\.py:\d+ run < host\.py:\d+ serve", caplog.text)
  assert "Ada Lovelace" not in caplog.text


def testWorkThatEndsWithoutBeingAskedIsAFailure(caplog):
  statuses = []
  with caplog.at_level(logging.INFO, logger="openfurrow.service"):
    assert ControlledService(ScriptedWork(endsUnasked=True), statuses.append, log).serve() == 1
  assert statuses == [startPending, running, stoppedFailed]
  assert "the work ended without being asked to stop" in caplog.text


def testAStopAskedWhileTheWorkStartsEndsTheServiceOnceItHasStarted():
  gate = threading.Event()
  statuses, work = [], ScriptedWork(startGate=gate)
  service = ControlledService(work, statuses.append, log)
  thread, exitCodes = serving(service)
  assert work.starting.wait(30)
  service.supervisor.requestStop()
  assert statuses == [startPending]
  gate.set()
  thread.join(30)
  assert (exitCodes, statuses, work.calls) == ([0], [startPending, stoppedClean], ["start"])


# ---- the real web server and scheduler under the same controls -----------------------

def testTheWebServerAnswersWhileRunningAndFreesItsAddressWhenStopped(location):
  port = freePort()
  statuses = []
  service = ControlledService(WebWork(location, None, "127.0.0.1", port), statuses.append, log)
  thread, exitCodes = serving(service)
  until(lambda: statuses[-1:] == [running], what="the running status")
  with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
    assert (response.status, json.loads(response.read())["status"]) == (200, "ok")
  assert service.control(controlStop) == noError
  thread.join(30)
  assert exitCodes == [0]
  assert statuses == [startPending, running, ServiceStatus(stateStopPending, checkPoint=1, waitHint=15000), stoppedClean]
  with pytest.raises(OSError):
    socket.create_connection(("127.0.0.1", port), timeout=2)


def testAWebServerWhoseAddressIsTakenFailsToStart(location, caplog):
  with listen("127.0.0.1", 0) as taken:
    port = taken.getsockname()[1]
    statuses = []
    with caplog.at_level(logging.INFO, logger="openfurrow.service"):
      assert ControlledService(WebWork(location, None, "127.0.0.1", port), statuses.append, log).serve() == 1
  assert statuses == [startPending, stoppedFailed]
  assert f"could not start: ServiceError: cannot listen on 127.0.0.1:{port}" in caplog.text


def testAServiceOnAStoreThatDoesNotExistFailsToStart(tmp_path, caplog):
  statuses = []
  with caplog.at_level(logging.INFO, logger="openfurrow.service"):
    assert ControlledService(SchedulerWork(str(tmp_path / "absent.db"), None), statuses.append, log).serve() == 1
  assert statuses == [startPending, stoppedFailed]
  assert "could not start: StoreError: database " in caplog.text and "absent.db' does not exist" in caplog.text
  assert not (tmp_path / "absent.db").exists()


def schedulerServing(location, seconds):
  operator = Workspace.open(location)
  operator.createTask("nap", "testSleep", {"seconds": seconds})
  operator.runTaskNow("nap")
  statuses = []
  work = SchedulerWork(location, None, runCommand=runner)
  service = ControlledService(work, statuses.append, log)
  thread, exitCodes = serving(service)
  until(lambda: statuses[-1:] == [running], what="the running status")
  until(lambda: work.scheduler.children, what="the run's process")
  return operator, service, statuses, thread, exitCodes


def testAStoppedSchedulerLetsItsRunFinish(location):
  operator, service, statuses, thread, exitCodes = schedulerServing(location, 1)
  assert service.control(controlStop) == noError
  thread.join(60)
  assert exitCodes == [0]
  assert statuses == [startPending, running, ServiceStatus(stateStopPending, checkPoint=1, waitHint=45000), stoppedClean]
  assert [(run.state, run.summary) for run in operator.taskRuns("nap")] == [(RunState.succeeded, "slept 1.0 seconds")]
  assert operator.schedulerHeartbeat().host == socket.gethostname()


def testASchedulerShutDownWithTheMachineStopsItsRunAndRecordsItStopped(location):
  operator, service, statuses, thread, exitCodes = schedulerServing(location, 600)
  assert service.control(controlShutdown) == noError
  thread.join(60)
  assert exitCodes == [0]
  assert [status.currentState for status in statuses] == [stateStartPending, stateRunning, stateStopPending, stateStopped]
  assert [(run.state, run.summary) for run in operator.taskRuns("nap")] == [(RunState.stopped, "stopped: the scheduler was stopping")]


# ---- the process in the foreground, and its log ---------------------------------------

@pytest.fixture
def started():
  processes = []

  def start(*arguments):
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {}
    process = subprocess.Popen([sys.executable, "-P", "-m", "openfurrow.osService.host", *arguments], **group)
    processes.append(process)
    return process

  yield start
  for process in processes:
    if process.poll() is None:
      process.kill()
      process.wait(30)


def interrupt(process):
  process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)


def get(url):
  try:
    with urllib.request.urlopen(url, timeout=10) as response:
      return response.status
  except urllib.error.HTTPError as error:
    return error.code


def healthy(process, port):
  def answered():
    assert process.poll() is None, f"the process ended with exit code {process.returncode} before it answered"
    try:
      return get(f"http://127.0.0.1:{port}/health") == 200
    except OSError:
      return False
  return answered


def logLines(path):
  """The log's lines without their time, each checked to carry one in UTC."""
  lines = path.read_text(encoding="utf-8").splitlines()
  assert all(re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z ", line) for line in lines), lines
  return [line[21:] for line in lines]


def testTheWebProcessLogsRequestsByRouteWithoutAddressesAndStopsOnASignal(location, tmp_path, started):
  logs = tmp_path / "logs"
  logs.mkdir()
  port = freePort()
  process = started("web", "--suffix", "pilot", "--store", location, "--logs", str(logs), "--host", "127.0.0.1",
                    "--port", str(port))
  until(healthy(process, port), what="the web server's answer")
  assert get(f"http://127.0.0.1:{port}/trials/LOVELACE-1?token=sesame") == 404
  assert get(f"http://127.0.0.1:{port}/nowhere/a.lovelace?name=Lovelace") == 404
  interrupt(process)
  assert process.wait(60) == 0
  lines = logLines(logs / "openfurrow-web-pilot.log")
  assert lines[:2] == ["INFO openfurrow.service starting", "INFO openfurrow.service running"]
  assert lines[-2:] == ["INFO openfurrow.service stopping", "INFO openfurrow.service stopped"]
  requests = [line for line in lines if " openfurrow.service.request " in line]
  assert set(requests[:-2]) == {"INFO openfurrow.service.request GET /health 200"}
  assert requests[-2:] == ["INFO openfurrow.service.request GET /trials/<trialCode> 404",
                           "INFO openfurrow.service.request GET (no route) 404"]
  text = "\n".join(lines)
  assert not any(word in text.lower() for word in ("127.0.0.1", "lovelace", "sesame", "nowhere"))


def testTheSchedulerProcessTakesItsStoreFromTheEnvironmentFileAndStopsOnASignal(location, tmp_path, started):
  logs = tmp_path / "logs"
  logs.mkdir()
  environmentFile = tmp_path / "openfurrow.env"
  environmentFile.write_text(f"# the store, as a PostgreSQL deployment names it\nOPENFURROW_STORE='{location}'\n", encoding="utf-8")
  before = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=5)
  process = started("scheduler", "--logs", str(logs), "--environment-file", str(environmentFile))
  operator = Workspace.open(location)

  def checkedIn():
    assert process.poll() is None, f"the process ended with exit code {process.returncode} before it checked in"
    return operator.schedulerHeartbeat()

  heartbeat = until(checkedIn, what="the scheduler's check-in")
  assert heartbeat.lastSeenAt > before
  interrupt(process)
  assert process.wait(60) == 0
  assert logLines(logs / "openfurrow-scheduler.log") == [
    "INFO openfurrow.service starting", "INFO openfurrow.service running",
    "INFO openfurrow.service stopping", "INFO openfurrow.service stopped",
  ]


def testAProcessThatCannotStartExitsNonZeroAndLogsWhy(tmp_path, started):
  logs = tmp_path / "logs"
  logs.mkdir()
  process = started("scheduler", "--store", str(tmp_path / "absent.db"), "--logs", str(logs))
  assert process.wait(120) == 1
  lines = logLines(logs / "openfurrow-scheduler.log")
  assert lines[0] == "INFO openfurrow.service starting"
  assert lines[1].startswith("ERROR openfurrow.service could not start: StoreError: database ")
  assert "absent.db' does not exist; create it first" in lines[1]
  assert lines[2:] == ["ERROR openfurrow.service stopped after a failure"]
  assert not (tmp_path / "absent.db").exists()


logCheck = """
import logging, sys, time
from pathlib import Path
from openfurrow.osService.host import openLog
folder = Path(sys.argv[1])
log = openLog(folder, "openfurrow-web")
handler = logging.getLogger().handlers[0]
log.info("first day")
print("printed, not logged by hand")
print("to standard error", file=sys.stderr)
handler.rolloverAt = int(time.time())
log.info("next day")
names = sorted(path.name for path in folder.iterdir())
Path(sys.argv[2]).write_text(repr((type(handler).__name__, handler.when, handler.utc, handler.backupCount, len(names),
                                   names[0])), encoding="utf-8")
"""


def testTheLogStartsAFileEachUTCDayKeepsNinetyAndTakesStandardOutputAndError(tmp_path):
  logs = tmp_path / "logs"
  logs.mkdir()
  subprocess.run([sys.executable, "-P", "-c", logCheck, str(logs), str(tmp_path / "seen.txt")], check=True, timeout=120)
  assert (tmp_path / "seen.txt").read_text(encoding="utf-8") == repr(
    ("TimedRotatingFileHandler", "MIDNIGHT", True, 90, 2, "openfurrow-web.log"))
  rotated = [path for path in logs.iterdir() if path.name != "openfurrow-web.log"]
  assert re.fullmatch(r"openfurrow-web\.log\.\d{4}-\d{2}-\d{2}", rotated[0].name)
  assert logLines(rotated[0]) == ["INFO openfurrow.service first day",
                                  "INFO openfurrow.service.output printed, not logged by hand",
                                  "WARNING openfurrow.service.output to standard error"]
  assert logLines(logs / "openfurrow-web.log") == ["INFO openfurrow.service next day"]
