# SPDX-License-Identifier: Apache-2.0
"""Real services (decision 0009), behind --service-install and an elevated shell.

On a throwaway store and under a random suffix, both services are installed through this
platform's service manager, started, used, killed and found started again, stopped and
uninstalled, and then nothing of them is left: no service, no definition, no account or
profile and no right on the store's folder. Whatever an assertion leaves behind, the fixture's
finalizer uninstalls. Only services of the test's own suffix are ever touched.
"""

import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

from openfurrow import Workspace
from openfurrow.cli.main import main
from openfurrow.osService import launchd, manage, systemd, windows
from openfurrow.osService.deployment import Deployment, DeploymentError, Role, ServiceState, serviceName
from openfurrow.service import listen
from openfurrow.tasks.scheduler import processIsAlive

pytestmark = pytest.mark.xdist_group("serviceInstall")

# Where a service's account can reach a throwaway store: pytest's own folder on Windows; elsewhere not /tmp,
# which a systemd unit does not see and which is private to its user on macOS.
dataRoots = {"linux": Path("/srv"), "darwin": Path("/Users/Shared")}


@dataclass
class Throwaway:
  suffix: str
  folder: Path
  store: Path
  environmentFile: Path
  port: int

  def name(self, role):
    return serviceName(role, self.suffix)


@pytest.fixture
def throwaway(request, tmp_path):
  if not request.config.getoption("--service-install"):
    pytest.skip("installs real services: run with --service-install in an elevated shell")
  assert manage.managerFor().isElevated(), "--service-install needs an elevated shell (root on Linux and macOS)"
  suffix = "test" + secrets.token_hex(4)
  folder = (dataRoots[sys.platform] / f"openfurrow-{suffix}" if sys.platform in dataRoots else tmp_path / "deployment").resolve()
  folder.mkdir()
  store = folder / "trials.db"
  Workspace.create(str(store))
  environmentFile = folder / "openfurrow.env"
  environmentFile.write_text("# as an identity provider's secret is given\nOPENFURROW_TEST_SECRET='not a secret'\n", encoding="utf-8")
  with listen("127.0.0.1", 0) as probe:
    port = probe.getsockname()[1]
  yield Throwaway(suffix, folder, store, environmentFile, port)
  try:
    if manage.status(suffix).deployment is not None:
      manage.uninstall(suffix)
  finally:
    # pytest shows this with a failed test only: what the services themselves said.
    for log in sorted((folder / "logs").glob("*")):
      print(f"----- {log.name}\n{log.read_text(encoding='utf-8', errors='replace')[-6000:]}")
    if sys.platform in dataRoots:
      shutil.rmtree(folder)


def until(condition, seconds, what):
  deadline = time.monotonic() + seconds
  while time.monotonic() < deadline:
    value = condition()
    if value:
      return value
    time.sleep(0.25)
  raise AssertionError(f"{what} did not come about within {seconds} seconds")


def health(port):
  try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
      return (response.status, json.loads(response.read())["status"])
  except OSError:
    return None


def output(*command):
  return subprocess.run(command, capture_output=True, text=True).stdout


def kill(processID):
  if sys.platform == "win32":
    subprocess.run(["taskkill", "/F", "/PID", str(processID)], check=True, capture_output=True)
  else:
    os.kill(processID, signal.SIGKILL)


def states(suffix):
  return manage.status(suffix).states


def both(state):
  return {Role.web: state, Role.scheduler: state}


def assertNothingIsLeft(throwaway):
  names = [throwaway.name(role) for role in Role]
  assert manage.status(throwaway.suffix) == manage.Status(states=both(ServiceState.notInstalled), deployment=None)
  if sys.platform == "win32":
    assert [subprocess.run(["sc.exe", "query", name], capture_output=True).returncode for name in names] == [1060, 1060]
    for path in (throwaway.folder, throwaway.environmentFile):
      rights = output("icacls", str(path))
      assert str(path) in rights and "NT SERVICE" not in rights and "S-1-5-80-" not in rights
    assert [(Path(os.environ["SystemRoot"]) / "ServiceProfiles" / name).exists() for name in names] == [False, False]
  elif sys.platform == "linux":
    assert [systemd.unitPath(name).exists() for name in names] == [False, False]
    assert output("systemctl", "list-units", "--all", "--plain", "--no-legend", f"openfurrow-*-{throwaway.suffix}.service") == ""
    assert (systemd.accountExists(throwaway.suffix), systemd.groupExists(systemd.account(throwaway.suffix))) == (False, False)
    assert throwaway.store.stat().st_uid == 0
  else:
    assert [launchd.daemonPath(name).exists() for name in names] == [False, False]
    assert [subprocess.run(["launchctl", "print", f"system/{name}"], capture_output=True).returncode == 0 for name in names] == [False, False]
    assert launchd.accountExists(throwaway.suffix) is False
    assert throwaway.store.stat().st_uid == 0


def assertInstalledAsThisPlatformShould(throwaway):
  web = throwaway.name(Role.web)
  if sys.platform == "win32":
    definition = output("sc.exe", "qc", web)
    assert re.search(r"START_TYPE\s+: 2\s+AUTO_START\s+\(DELAYED\)", definition)
    assert re.search(r"SERVICE_START_NAME : NT AUTHORITY\\LocalService\s", definition)
    assert re.search(r"SERVICE_SID_TYPE:\s+UNRESTRICTED", output("sc.exe", "qsidtype", web))
    assert re.search(r"FAILURE_ACTIONS_ON_NONCRASH_FAILURES:\s+TRUE", output("sc.exe", "qfailureflag", web))
    recovery = output("sc.exe", "qfailure", web)
    assert re.findall(r"RESTART -- Delay = (\d+) milliseconds", recovery) == ["5000", "30000", "60000"]
    rights = output("icacls", str(throwaway.environmentFile)).replace(str(throwaway.environmentFile), "")
    assert f"NT SERVICE\\{web}:(R)" in rights and "Users" not in rights and "Everyone" not in rights
  elif sys.platform == "linux":
    account = systemd.userEntry(systemd.account(throwaway.suffix))
    assert account.pw_uid < 1000 and account.pw_shell == "/usr/sbin/nologin"
    assert (throwaway.store.stat().st_uid, throwaway.folder.stat().st_uid) == (account.pw_uid, account.pw_uid)
    environment = throwaway.environmentFile.stat()
    assert (environment.st_uid, environment.st_mode & 0o777) == (0, 0o600)
    assert output("systemctl", "is-enabled", f"{web}.service").strip() == "enabled"
  else:
    assert launchd.accountExists(throwaway.suffix)
    environment = throwaway.environmentFile.stat()
    assert (environment.st_uid, environment.st_mode & 0o777) == (0, 0o640)
    assert throwaway.store.stat().st_uid == throwaway.folder.stat().st_uid != 0


def testBothServicesInstallRunComeBackAfterAFailureAndLeaveNothing(throwaway, capsys):
  suffix, port = throwaway.suffix, throwaway.port
  web, scheduler = throwaway.name(Role.web), throwaway.name(Role.scheduler)
  logs = throwaway.folder / "logs"

  assert main(["service", "install", str(throwaway.store), "--port", str(port), "--suffix", suffix,
               "--environment-file", str(throwaway.environmentFile)]) == 0
  assert manage.status(suffix) == manage.Status(states=both(ServiceState.stopped), deployment=Deployment(
    storeFile=throwaway.store, logsFolder=logs, suffix=suffix, environmentFile=throwaway.environmentFile,
    python=Path(sys.executable), host="127.0.0.1", port=port))
  assertInstalledAsThisPlatformShould(throwaway)
  with pytest.raises(DeploymentError, match=f"{web} and {scheduler} already installed"):
    manage.install(str(throwaway.store), "127.0.0.1", port, suffix)

  assert main(["service", "start", "--suffix", suffix]) == 0
  assert states(suffix) == both(ServiceState.running)
  assert until(lambda: health(port), 30, "the web service's answer") == (200, "ok")
  operator = Workspace.open(str(throwaway.store))
  first = until(operator.schedulerHeartbeat, 60, "the scheduler's check-in")
  assert first.host == socket.gethostname() and processIsAlive(first.processID)

  capsys.readouterr()
  assert main(["service", "status", "--suffix", suffix]) == 0
  report = capsys.readouterr().out.splitlines()
  assert report[:2] == [f"{web}\tinstalled\trunning\thttp://127.0.0.1:{port}", f"{scheduler}\tinstalled\trunning"]
  assert re.fullmatch(rf"Scheduler: last checked in \S+ from {re.escape(first.host)} \(process {first.processID}\)", report[2])

  kill(first.processID)
  again = until(lambda: [beat for beat in [operator.schedulerHeartbeat()] if beat.processID != first.processID], 120,
                "the scheduler's check-in after it was killed")[0]
  assert processIsAlive(again.processID)
  until(lambda: states(suffix)[Role.scheduler] is ServiceState.running, 60, "the restarted scheduler's running state")

  assert main(["service", "stop", "--suffix", suffix]) == 0
  assert states(suffix) == both(ServiceState.stopped)
  assert health(port) is None
  until(lambda: not processIsAlive(again.processID), 30, "the end of the scheduler's process")
  webLog = (logs / f"{web}.log").read_text(encoding="utf-8")
  assert "openfurrow.service.request GET /health 200" in webLog and "127.0.0.1" not in webLog
  assert [line.split(" ", 1)[1] for line in webLog.splitlines()][-2:] == ["INFO openfurrow.service stopping",
                                                                          "INFO openfurrow.service stopped"]
  assert "INFO openfurrow.service stopped" in (logs / f"{scheduler}.log").read_text(encoding="utf-8")

  if sys.platform == "win32":
    with listen("127.0.0.1", port):
      with pytest.raises(DeploymentError, match=f"{web} failed to start; see its log"):
        manage.start(suffix)
      stopped = output("sc.exe", "query", web)
      assert re.search(r"WIN32_EXIT_CODE\s+: 1066\s", stopped) and re.search(r"SERVICE_EXIT_CODE\s+: 1\s", stopped)
    assert until(lambda: health(port), 90, "the web service's answer once the service manager started it again") == (200, "ok")

  assert main(["service", "uninstall", "--suffix", suffix]) == 0
  assertNothingIsLeft(throwaway)
  assert throwaway.store.is_file() and throwaway.environmentFile.is_file() and (logs / f"{web}.log").is_file()
  with pytest.raises(DeploymentError, match=f"cannot uninstall {web} and {scheduler}: not installed"):
    manage.uninstall(suffix)


def testTheWindowsEntryReportsWhatItCannotLoadToTheEventLog(throwaway):
  if sys.platform != "win32":
    pytest.skip("the Windows service manager's entry")
  name = throwaway.name(Role.web)
  entry = Path(windows.__file__).with_name("windowsEntry.py")
  command = subprocess.list2cmdline([sys.executable, "-P", str(entry), "web", "--logs", str(throwaway.folder)])
  assert subprocess.run(["sc.exe", "create", name, "binPath=", command, "start=", "demand",
                         "obj=", "NT AUTHORITY\\LocalService"], capture_output=True).returncode == 0
  try:
    subprocess.run(["sc.exe", "start", name], capture_output=True)
    stopped = until(lambda: [text for text in [output("sc.exe", "query", name)] if re.search(r"STATE\s+: 1\s", text)],
                    120, "the service's stopped state")[0]
    assert re.search(r"WIN32_EXIT_CODE\s+: 1066\s", stopped) and re.search(r"SERVICE_EXIT_CODE\s+: 2\s", stopped)
    events = output("powershell", "-NoProfile", "-Command",
                    f"Get-EventLog -LogName Application -Newest 200 | Where-Object {{ $_.Source -eq '{name}' }} | "
                    f"ForEach-Object {{ $_.EntryType; $_.ReplacementStrings[0] }}")
    assert events.startswith("Error") and "DeploymentError" in events and "the web service needs --host and --port" in events
  finally:
    assert subprocess.run(["sc.exe", "delete", name], capture_output=True).returncode == 0
