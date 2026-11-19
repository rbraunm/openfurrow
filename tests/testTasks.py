# SPDX-License-Identifier: Apache-2.0
"""Scheduled tasks (decision 0041): configuration, the scheduler's claims and runs as real subprocesses, time limits,
crashes, a scheduler that dies or is stopped, rights and audit, the command line and the tasks page."""

import datetime
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import taskKindsForTests  # noqa: F401
from openfurrow import Workspace
from openfurrow.cli.main import main
from openfurrow.identity import RoleAssignment
from openfurrow.retention import retentionTaskName
from openfurrow.service import createApp
from openfurrow.store.database import TaskRunRow, createDatabase
from openfurrow.tasks.model import RunState, TaskError, outputLimitBytes
from openfurrow.tasks.scheduler import Scheduler, processIsAlive
from openfurrow.workspace import NotPermitted

testsFolder = Path(__file__).parent
runner = [sys.executable, str(testsFolder / "runWithTestKinds.py")]
password = "correct horse battery"


class Clock:
  def __init__(self, moment=None):
    self.moment, self.ahead = moment, datetime.timedelta()

  def __call__(self):
    return self.moment if self.moment is not None else datetime.datetime.now(datetime.UTC) + self.ahead

  def runOnFrom(self, moment):
    self.ahead, self.moment = moment - datetime.datetime.now(datetime.UTC), None


@pytest.fixture
def location(newStore):
  """A store whose own daily task (retention, decision 0044) is disabled, so only what a test schedules can run."""
  location = newStore("tasks")
  Workspace.create(location).setTaskEnabled(retentionTaskName, False)
  return location


@pytest.fixture
def schedulers(location):
  made = []

  def make(clock=None, **options):
    scheduler = Scheduler(location, pollSeconds=0.1, clock=clock or Clock(), runCommand=runner,
                          stopGraceSeconds=options.pop("stopGraceSeconds", 0), killGraceSeconds=1, **options)
    made.append(scheduler)
    return scheduler

  yield make
  for scheduler in made:
    scheduler.windDown()


def untilSettled(scheduler, operator, name, seconds=60):
  deadline = time.monotonic() + seconds
  while time.monotonic() < deadline:
    scheduler.tick()
    runs = operator.taskRuns(name)
    if runs and all(run.state not in (RunState.requested, RunState.running) for run in runs) and not scheduler.children:
      return runs
    time.sleep(0.1)
  raise AssertionError(f"the runs of {name} did not settle: {operator.taskRuns(name)}")


def untilRunning(location, operator, name, seconds=30):
  deadline = time.monotonic() + seconds
  while time.monotonic() < deadline:
    runs = operator.taskRuns(name)
    if runs and runs[0].state is RunState.running and processOf(location, runs[0].runID) is not None:
      return runs[0]
    time.sleep(0.1)
  raise AssertionError(f"no run of {name} started: {operator.taskRuns(name)}")


def processOf(location, runID):
  with Session(createDatabase(location, create=False)) as session:
    return session.get(TaskRunRow, runID).processID


# ---- configuration ----------------------------------------------------------------

def testATaskTakesItsKindsDefaultsAndIsCheckedWhenSaved(location):
  operator = Workspace.open(location)
  task = operator.createTask("echo", "testEcho", {"message": "hello"})
  assert (task.schedule, task.timeLimitSeconds, task.enabled, task.timeZone) == ("*/10 * * * *", 60, True, "UTC")
  assert task.nextRunAt.minute % 10 == 0 and task.nextRunAt.second == 0
  assert 0 < (task.nextRunAt - datetime.datetime.now(datetime.UTC)).total_seconds() <= 600
  with pytest.raises(TaskError, match="does not take"):
    operator.createTask("echo2", "testEcho", {"words": "hello"})
  with pytest.raises(TaskError, match="no task kind 'nothing'"):
    operator.createTask("nothing", "nothing", {})
  with pytest.raises(TaskError, match="is not a task name"):
    operator.createTask("Echo Task", "testEcho", {"message": "x"})
  with pytest.raises(TaskError, match="already exists"):
    operator.createTask("echo", "testEcho", {"message": "again"})
  with pytest.raises(TaskError, match="a schedule has five fields"):
    operator.setTask("echo", schedule="every hour")
  with pytest.raises(TaskError, match="not 0 seconds"):
    operator.setTask("echo", timeLimitSeconds=0)
  assert operator.task("echo").schedule == "*/10 * * * *"


def testSchedulesAreReadInTheServersTimeZone(location):
  operator = Workspace.open(location)
  operator.createTask("echo", "testEcho", {"message": "hello"})
  operator.setTask("echo", schedule="0 6 * * *")
  assert operator.task("echo").nextRunAt.astimezone(datetime.UTC).time() == datetime.time(6, 0)
  operator.setSetting("server", "tasks.timeZone", "Asia/Kolkata")
  task = operator.task("echo")
  assert task.timeZone == "Asia/Kolkata"
  assert task.nextRunAt.astimezone(datetime.UTC).time() == datetime.time(0, 30)
  with pytest.raises(Exception, match="is not an IANA time zone name"):
    operator.setSetting("server", "tasks.timeZone", "Moon/Tranquility")


def testADisabledTaskHasNoNextRunUntilEnabled(location):
  operator = Workspace.open(location)
  operator.createTask("echo", "testEcho", {"message": "hello"})
  assert operator.setTaskEnabled("echo", False).nextRunAt is None
  assert operator.setTaskEnabled("echo", True).nextRunAt is not None


# ---- the scheduler ------------------------------------------------------------------

def testADueTaskRunsOnceAndTimesMissedWhileStoppedRunOnce(location, schedulers):
  operator = Workspace.open(location)
  due = operator.createTask("echo", "testEcho", {"message": "hello"}).nextRunAt
  later = due + datetime.timedelta(hours=3, minutes=4)
  scheduler = schedulers(Clock(later))
  runs = untilSettled(scheduler, operator, "echo")
  assert [(run.state, run.requestedBy, run.summary) for run in runs] == [(RunState.succeeded, "schedule", "said hello")]
  assert "echo says hello" in runs[0].output
  assert operator.task("echo").nextRunAt == later + datetime.timedelta(minutes=10 - later.minute % 10)
  scheduler.tick()
  assert len(operator.taskRuns("echo")) == 1


def testATimeDueWhileThePreviousRunGoesIsRecordedSkipped(location, schedulers):
  operator = Workspace.open(location)
  due = operator.createTask("sleeper", "testSleep", {"seconds": 30}).nextRunAt
  clock = Clock(due + datetime.timedelta(seconds=5))
  scheduler = schedulers(clock)
  scheduler.tick()
  untilRunning(location, operator, "sleeper")
  clock.moment = due + datetime.timedelta(minutes=10, seconds=5)
  scheduler.tick()
  runs = operator.taskRuns("sleeper")
  assert [(run.state, run.requestedBy) for run in runs] == [(RunState.skipped, "schedule"), (RunState.running, "schedule")]
  assert runs[0].summary == "skipped: the task's previous run was still going"


def testOfTwoSchedulersOnlyOneClaimsARun(location, schedulers):
  operator = Workspace.open(location)
  operator.createTask("echo", "testEcho", {"message": "hello"})
  runID = operator.runTaskNow("echo")
  first, second = schedulers(), schedulers()
  barrier, claims = threading.Barrier(2), []

  def claim(scheduler):
    barrier.wait()
    claims.append(scheduler.claim(runID))

  threads = [threading.Thread(target=claim, args=(scheduler,)) for scheduler in (first, second)]
  for thread in threads:
    thread.start()
  for thread in threads:
    thread.join()
  assert sorted(claims) == [False, True]

  operator.createTask("other", "testEcho", {"message": "once"})
  operator.runTaskNow("other")
  barrier = threading.Barrier(2)

  def tick(scheduler):
    barrier.wait()
    scheduler.tick()

  threads = [threading.Thread(target=tick, args=(scheduler,)) for scheduler in (first, second)]
  for thread in threads:
    thread.start()
  for thread in threads:
    thread.join()
  started = [runID for scheduler in (first, second) for runID in scheduler.children]
  assert len(started) == 1


def testNoMoreRunsGoAtOnceThanTheServerAllows(location, schedulers):
  operator = Workspace.open(location)
  operator.setSetting("server", "tasks.maximumConcurrentRuns", 1)
  for name in ("one", "two"):
    operator.createTask(name, "testSleep", {"seconds": 30})
    operator.runTaskNow(name)
  scheduler = schedulers()
  scheduler.tick()
  assert {name: operator.taskRuns(name)[0].state for name in ("one", "two")} == {
    "one": RunState.running, "two": RunState.requested}


def testARunNowIsRefusedWhileOneIsWaiting(location):
  operator = Workspace.open(location)
  operator.createTask("echo", "testEcho", {"message": "hello"})
  operator.runTaskNow("echo")
  with pytest.raises(TaskError, match="has a run requested or running already"):
    operator.runTaskNow("echo")


def testARunPastItsTimeLimitIsStoppedAndRecordedSo(location, schedulers, tmp_path):
  operator = Workspace.open(location)
  sleeping = tmp_path / "sleeping"
  operator.createTask("sleeper", "testSleepOnceStarted", {"seconds": 120, "startedFile": str(sleeping)})
  operator.setTask("sleeper", timeLimitSeconds=10)
  operator.runTaskNow("sleeper")
  # The scheduler's clock stands still while the run's process starts, however long a busy machine takes over it.
  begun = datetime.datetime.now(datetime.UTC)
  clock = Clock(begun)
  scheduler = schedulers(clock)
  deadline = time.monotonic() + 180
  while not sleeping.exists():
    assert time.monotonic() < deadline, f"the run did not start: {operator.taskRuns('sleeper')}"
    scheduler.tick()
    time.sleep(0.1)
  scheduler.tick()
  assert operator.taskRuns("sleeper")[0].state is RunState.running
  clock.moment = begun + datetime.timedelta(seconds=10)
  scheduler.tick()
  assert operator.taskRuns("sleeper")[0].state is RunState.running
  clock.runOnFrom(begun + datetime.timedelta(seconds=11))
  runs = untilSettled(scheduler, operator, "sleeper", 60)
  assert runs[0].state is RunState.stopped and runs[0].summary == "stopped at its time limit of 10 seconds"
  assert "sleeping 120.0 seconds" in runs[0].output
  assert 11 <= (runs[0].finishedAt - runs[0].startedAt).total_seconds() < 60


def testARunThatRaisesIsRecordedFailedWithItsTraceback(location, schedulers):
  operator = Workspace.open(location)
  operator.createTask("failing", "testFail", {})
  operator.runTaskNow("failing")
  runs = untilSettled(schedulers(), operator, "failing")
  assert runs[0].state is RunState.failed
  assert runs[0].summary == "RuntimeError: the test kind fails on purpose"
  assert "about to fail" in runs[0].output and "Traceback" in runs[0].output


def testACrashedRunIsRecordedFailedWithItsOutput(location, schedulers):
  operator = Workspace.open(location)
  operator.createTask("crashing", "testCrash", {})
  operator.runTaskNow("crashing")
  runs = untilSettled(schedulers(), operator, "crashing")
  assert runs[0].state is RunState.failed
  assert runs[0].summary == "failed: the run's process ended with exit code 3 without recording an outcome"
  assert "about to crash" in runs[0].output


def testOutputIsKeptToItsLast64KB(location, schedulers):
  operator = Workspace.open(location)
  operator.createTask("loud", "testLoud", {})
  operator.runTaskNow("loud")
  run = untilSettled(schedulers(), operator, "loud")[0]
  assert run.state is RunState.succeeded
  assert len(run.output.encode("utf-8")) == outputLimitBytes
  assert run.output.startswith("[") and "earlier bytes of output left out]\n" in run.output
  assert "line 03999 " in run.output and "line 00000 " not in run.output


@pytest.fixture
def started():
  """Scheduler processes for one test, each started in a process group of its own, and none left behind by it."""
  processes = []

  def start(command):
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **group)
    processes.append(process)
    return process

  yield start
  for process in processes:
    if process.poll() is None:
      if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
      else:
        process.kill()
      process.wait(30)


def startedSchedulerProcess(started, location, stopGraceSeconds):
  process = started([sys.executable, str(testsFolder / "schedulerWithTestKinds.py"), location, str(stopGraceSeconds)])
  assert process.stdout.readline().strip() == b"scheduling"
  return process


def interrupt(process):
  process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)


def testARunLeftByASchedulerThatDiedIsRecordedFailed(location, schedulers, started):
  operator = Workspace.open(location)
  operator.createTask("sleeper", "testSleep", {"seconds": 120})
  operator.runTaskNow("sleeper")
  process = startedSchedulerProcess(started, location, 20)
  run = untilRunning(location, operator, "sleeper")
  runProcess = processOf(location, run.runID)
  process.kill()
  process.wait(30)
  assert processIsAlive(runProcess)
  os.kill(runProcess, signal.SIGTERM)
  deadline = time.monotonic() + 30
  while processIsAlive(runProcess) and time.monotonic() < deadline:
    time.sleep(0.1)
  assert operator.taskRuns("sleeper")[0].state is RunState.running
  schedulers().tick()
  run = operator.taskRuns("sleeper")[0]
  assert run.state is RunState.failed
  assert run.summary == "failed: the scheduler that started it stopped, and its process is gone"


@pytest.mark.parametrize("seconds, grace, state, summary", [
  (1, 30, RunState.succeeded, "slept 1.0 seconds"),
  (120, 1, RunState.stopped, "stopped: the scheduler was stopping"),
])
def testAStoppedSchedulerLetsRunsFinishOrRecordsThemStopped(location, started, seconds, grace, state, summary):
  operator = Workspace.open(location)
  operator.createTask("sleeper", "testSleep", {"seconds": seconds})
  operator.runTaskNow("sleeper")
  process = startedSchedulerProcess(started, location, grace)
  untilRunning(location, operator, "sleeper")
  interrupt(process)
  output, _ = process.communicate(timeout=60)
  assert process.returncode == 0 and output.strip().endswith(b"stopped")
  run = operator.taskRuns("sleeper")[0]
  assert (run.state, run.summary) == (state, summary)


def testTheSchedulerCommandChecksInAndStopsOnASignal(location, started):
  process = started([sys.executable, "-m", "openfurrow.cli.main", "scheduler", location, "--poll-seconds", "0.2"])
  announced = process.stdout.readline().decode("utf-8")
  assert announced.startswith(f"Scheduler running on {socket.gethostname()} (process ")
  operator = Workspace.open(location)
  deadline = time.monotonic() + 30
  while operator.schedulerHeartbeat() is None and time.monotonic() < deadline:
    time.sleep(0.1)
  heartbeat = operator.schedulerHeartbeat()
  assert heartbeat.host == socket.gethostname() and f"(process {heartbeat.processID})" in announced
  assert (datetime.datetime.now(datetime.UTC) - heartbeat.lastSeenAt).total_seconds() < 30
  interrupt(process)
  output, _ = process.communicate(timeout=60)
  assert process.returncode == 0 and output.strip().endswith(b"Scheduler stopped")


# ---- rights, audit and surfaces -----------------------------------------------------------

@pytest.fixture
def accounts(location):
  operator = Workspace.open(location)
  for userName in ("admin", "viewer"):
    operator.createAccount(userName, userName.title(), None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  operator.assignRole(RoleAssignment(roleCode="viewer", scope="server", userName="viewer"))
  operator.setSetting("server", "identity.signInMode", "accounts")
  operator.createTask("echo", "testEcho", {"message": "hello"})
  return operator


def actingAs(operator, userName):
  _, token = operator.signIn(userName, password, "web")
  return operator.actingAs(operator.actorForSession(token, "web"))


def testOnlyHoldersOfManageTasksSeeOrChangeTasks(accounts):
  viewer = actingAs(accounts, "viewer")
  for attempt in (viewer.tasks, lambda: viewer.task("echo"), lambda: viewer.setTask("echo", schedule="0 * * * *"),
                  lambda: viewer.setTaskEnabled("echo", False), lambda: viewer.runTaskNow("echo"),
                  lambda: viewer.taskRuns("echo"), viewer.schedulerHeartbeat):
    with pytest.raises(NotPermitted, match="viewer may not manageTasks at server"):
      attempt()
  admin = actingAs(accounts, "admin")
  assert [task.name for task in admin.tasks()] == ["echo", retentionTaskName]


def testEveryChangeToATaskIsAudited(accounts):
  admin = actingAs(accounts, "admin")
  admin.setTask("echo", schedule="15 3 * * *", timeLimitSeconds=120)
  admin.setTaskEnabled("echo", False)
  runID = admin.runTaskNow("echo")
  assert admin.taskRuns("echo")[0].requestedBy == "admin"
  events = [(event.actorName, event.action, event.detail) for event in accounts.auditEvents()
            if event.action.startswith("task.") and event.detail["task"] == "echo"]
  assert events == [
    ("admin", "task.run", {"task": "echo", "runID": runID}),
    ("admin", "task.enable", {"task": "echo", "enabled": False}),
    ("admin", "task.set", {"task": "echo", "before": {"schedule": "*/10 * * * *", "timeLimitSeconds": 60},
                           "after": {"schedule": "15 3 * * *", "timeLimitSeconds": 120}}),
    (None, "task.create", {"task": "echo", "kind": "testEcho", "parameters": {"message": "hello"}}),
  ]


def testTheCommandLineShowsChangesAndRunsTasks(location, schedulers, capsys):
  Workspace.open(location).createTask("echo", "testEcho", {"message": "hello"})
  assert main(["task", "set", location, "echo", "--schedule", "0 */2 * * *", "--time-limit", "5m"]) == 0
  assert main(["task", "set", location, "echo", "--time-limit", "5"]) == 1
  assert "'5' is not a duration" in capsys.readouterr().err
  assert main(["task", "disable", location, "echo"]) == 0
  assert main(["task", "list", location]) == 0
  echo, retention = capsys.readouterr().out.splitlines()[-2:]
  assert echo.split("\t") == ["echo", "testEcho", "0 */2 * * *", "disabled", "next -", "last -"]
  assert retention.split("\t") == [retentionTaskName, "retentionPrune", "15 3 * * *", "disabled", "next -", "last -"]
  assert main(["task", "run", location, "echo"]) == 0
  assert capsys.readouterr().out.strip() == "Requested run 1 of 'echo'"
  untilSettled(schedulers(), Workspace.open(location), "echo")
  assert main(["task", "runs", location, "echo", "--output"]) == 0
  shown = capsys.readouterr().out
  assert shown.split("\t")[:3] == ["1", "succeeded", "operator"] and "echo says hello" in shown
  assert main(["task", "show", location, "echo"]) == 0
  shown = capsys.readouterr().out
  assert "Schedule: 0 */2 * * * (UTC), disabled" in shown and "Time limit: 300 seconds" in shown
  assert "Last run: 1 succeeded" in shown and "Scheduler: last checked in" in shown
  assert main(["task", "show", location, "missing"]) == 1
  assert "task 'missing' not found" in capsys.readouterr().err


def signedInClient(location, userName):
  client = createApp(location).test_client()
  answer = client.post("/signin", data={"userName": userName, "password": password}, headers={"Origin": "http://localhost"})
  assert answer.status_code == 302
  return client


def testTheTasksPageShowsTasksAndTheScheduler(accounts, location, schedulers):
  client = signedInClient(location, "admin")
  page = client.get("/tasks").get_data(as_text=True)
  assert 'href="/tasks"' in page and 'href="/tasks/echo"' in page and "*/10 * * * *" in page
  assert "No scheduler has checked in" in page and "not run yet" in page
  schedulers().tick()
  page = client.get("/tasks").get_data(as_text=True)
  assert "No scheduler has checked in" not in page and "The scheduler checked in" in page
  arabic = client.get("/tasks?locale=ar").get_data(as_text=True)
  assert 'dir="rtl"' in arabic and "\u0627\u0644\u0645\u0647\u0627\u0645 \u0627\u0644\u0645\u062c\u062f\u0648\u0644\u0629" in arabic


def testTheTasksPageIsNotOfferedWithoutManageTasks(accounts, location):
  client = signedInClient(location, "viewer")
  assert 'href="/tasks"' not in client.get("/").get_data(as_text=True)
  assert client.get("/tasks").status_code == 403
  assert client.post("/tasks/echo", data={"action": "run"}, headers={"Origin": "http://localhost"}).status_code == 403
  assert accounts.taskRuns("echo") == []


def testTheTaskPageChangesTheTaskAndRunsItNow(accounts, location, schedulers):
  client = signedInClient(location, "admin")
  origin = {"Origin": "http://localhost"}
  saved = client.post("/tasks/echo", data={"action": "save", "schedule": "30 4 * * mon", "timeLimitMinutes": "3"},
                      headers=origin)
  assert saved.status_code == 302 and "Saved." in client.get(saved.headers["Location"]).get_data(as_text=True)
  task = accounts.task("echo")
  assert (task.schedule, task.timeLimitSeconds) == ("30 4 * * mon", 180)
  refused = client.post("/tasks/echo", data={"action": "save", "schedule": "30 4 * *", "timeLimitMinutes": "3"},
                        headers=origin)
  assert refused.status_code == 400 and "Not done: a schedule has five fields" in refused.get_data(as_text=True)
  assert client.post("/tasks/echo", data={"action": "disable"}, headers=origin).status_code == 302
  assert accounts.task("echo").enabled is False
  ran = client.post("/tasks/echo", data={"action": "run"}, headers=origin)
  assert ran.status_code == 302
  assert "Run requested" in client.get(ran.headers["Location"]).get_data(as_text=True)
  assert accounts.taskRuns("echo")[0].requestedBy == "admin"
  untilSettled(schedulers(), accounts, "echo")
  page = client.get("/tasks/echo").get_data(as_text=True)
  assert "succeeded" in page and "said hello" in page and "echo says hello" in page and "admin" in page
  assert client.get("/tasks/missing").status_code == 404
