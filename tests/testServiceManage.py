# SPDX-License-Identifier: Apache-2.0
"""`openfurrow service` up to the service manager (decision 0009): what is refused before anything is changed, the
deployment an install hands on, and the order services start and stop in. A service manager held in memory stands
in for the platform's; the real ones are exercised by testServiceInstall.py."""

import sys
from pathlib import Path

import pytest

from openfurrow import StoreError, Workspace
from openfurrow.cli.main import main
from openfurrow.osService import launchd, manage, systemd, windows
from openfurrow.osService.deployment import Deployment, DeploymentError, Role, ServiceState
from openfurrow.service import listen


class MemoryManager:
  """A service manager that keeps its services in a dictionary and records what it is asked to do."""

  elevationHint = "ask the test for elevation"

  def __init__(self, elevated=True, failsToInstall=False, startsAs=ServiceState.running, failedStartsAgain=False):
    self.elevated, self.failsToInstall, self.startsAs = elevated, failsToInstall, startsAs
    self.failedStartsAgain = failedStartsAgain
    self.deployments: dict[str, Deployment] = {}
    self.states: dict[str, ServiceState] = {}
    self.asked: list[tuple] = []

  def isElevated(self):
    return self.elevated

  def check(self, deployment):
    self.asked.append(("check", deployment))

  def state(self, name):
    return self.states.get(name, ServiceState.notInstalled)

  def installed(self, role, suffix):
    return self.deployments.get(manage.serviceName(role, suffix))

  def install(self, deployment):
    self.asked.append(("install", deployment))
    self.deployments[deployment.name(Role.web)] = deployment
    self.states[deployment.name(Role.web)] = ServiceState.stopped
    if self.failsToInstall:
      raise DeploymentError("the scheduler's service cannot be created")
    self.deployments[deployment.name(Role.scheduler)] = deployment
    self.states[deployment.name(Role.scheduler)] = ServiceState.stopped

  def uninstall(self, deployment):
    self.asked.append(("uninstall", deployment))
    for role in Role:
      self.deployments.pop(deployment.name(role), None)
      self.states.pop(deployment.name(role), None)

  def start(self, name):
    self.asked.append(("start", name))
    self.states[name] = self.startsAs

  def stop(self, name):
    self.asked.append(("stop", name))
    if self.states[name] is not ServiceState.failed:
      self.states[name] = ServiceState.stopped

  def changes(self):
    return [request for request in self.asked if request[0] != "check"]


def freePort():
  with listen("127.0.0.1", 0) as probe:
    return probe.getsockname()[1]


@pytest.fixture
def store(tmp_path):
  """A store in a folder of its own, as a served store is kept."""
  folder = tmp_path / "deployment"
  folder.mkdir()
  path = folder / "trials.db"
  Workspace.create(str(path))
  return path


def installedOn(store, manager, **options):
  return manage.install(str(store), "127.0.0.1", freePort(), manager=manager, **options)


# ---- the platform -------------------------------------------------------------------

def testEachSupportedPlatformHasItsServiceManager():
  assert (manage.managerFor("win32"), manage.managerFor("linux"), manage.managerFor("darwin")) == (windows, systemd, launchd)


@pytest.mark.parametrize("platform", ["freebsd14", "sunos5", "emscripten"])
def testAnUnsupportedPlatformIsRefusedByName(platform):
  with pytest.raises(DeploymentError, match=f"this platform, '{platform}', is none of them"):
    manage.managerFor(platform)


# ---- install --------------------------------------------------------------------------

def testAnInstallHandsOnTheDeploymentAndMakesTheLogsFolder(store):
  manager = MemoryManager()
  port = freePort()
  deployment = manage.install(str(store), "127.0.0.1", port, manager=manager)
  assert deployment == Deployment(storeFile=store.resolve(), logsFolder=store.resolve().parent / "logs", suffix=None,
                                  environmentFile=None, python=Path(sys.executable), host="127.0.0.1", port=port)
  assert manager.asked == [("check", deployment), ("install", deployment)]
  assert deployment.logsFolder.is_dir()
  assert deployment.storeLocation() == str(store.resolve())


def testAnInstallTakesASuffixAnEnvironmentFileAndALogsFolder(store, tmp_path):
  environmentFile = store.parent / "openfurrow.env"
  environmentFile.write_text("OIDC_CLIENT_SECRET=s3cr3t\n", encoding="utf-8")
  logs = tmp_path / "elsewhere"
  deployment = installedOn(store, MemoryManager(), suffix="pilot", environmentFile=str(environmentFile), logsFolder=str(logs))
  assert (deployment.suffix, deployment.environmentFile, deployment.logsFolder) == ("pilot", environmentFile.resolve(), logs.resolve())
  assert [deployment.name(role) for role in Role] == ["openfurrow-web-pilot", "openfurrow-scheduler-pilot"]
  assert logs.is_dir()


@pytest.mark.parametrize("action", ["install", "uninstall", "start", "stop"])
def testAShellThatIsNotElevatedIsRefusedByName(store, action):
  manager = MemoryManager(elevated=False)
  with pytest.raises(DeploymentError, match=f"to {action} services this shell must be elevated: ask the test for elevation"):
    if action == "install":
      installedOn(store, manager)
    else:
      getattr(manage, action)(manager=manager)
  assert manager.asked == []
  assert not (store.parent / "logs").exists()


def testAStoreThatDoesNotExistIsRefusedByName(tmp_path):
  manager = MemoryManager()
  with pytest.raises(StoreError, match=r"absent\.db' does not exist; create it first"):
    manage.install(str(tmp_path / "absent.db"), "127.0.0.1", freePort(), manager=manager)
  assert manager.asked == []
  assert not (tmp_path / "absent.db").exists()


def testAFileThatHoldsNoStoreIsRefusedByName(tmp_path):
  (tmp_path / "notes.db").write_bytes(b"")
  with pytest.raises(StoreError, match="holds no OpenFurrow store"):
    manage.install(str(tmp_path / "notes.db"), "127.0.0.1", freePort(), manager=MemoryManager())


def testAPortInUseIsRefusedByNameBeforeAnythingIsInstalled(store):
  manager = MemoryManager()
  with listen("127.0.0.1", 0) as taken:
    port = taken.getsockname()[1]
    with pytest.raises(DeploymentError, match=f"could not listen on 127.0.0.1:{port}, which is in use"):
      manage.install(str(store), "127.0.0.1", port, manager=manager)
  assert manager.changes() == []
  assert not (store.parent / "logs").exists()


def testAStoreAmongOtherFilesIsRefusedBecauseItsFolderIsGivenToTheServices(store):
  (store.parent / "thesis.docx").write_bytes(b"not the services' business")
  manager = MemoryManager()
  with pytest.raises(DeploymentError, match=r"holds more than the store \(thesis\.docx\); keep a served store in a folder of its own"):
    installedOn(store, manager)
  assert manager.asked == []


def testAStoresOwnCompanionsAreNotOtherFiles(store):
  for name in ("trials.db-journal", "trials.db-wal", "trials.db-shm", "openfurrow.env"):
    (store.parent / name).write_bytes(b"")
  (store.parent / "logs").mkdir()
  deployment = installedOn(store, MemoryManager(), environmentFile=str(store.parent / "openfurrow.env"))
  assert deployment.storeFile == store.resolve()


def testServicesAlreadyInstalledAreRefusedByName(store):
  manager = MemoryManager()
  installedOn(store, manager, suffix="pilot")
  with pytest.raises(DeploymentError, match="openfurrow-web-pilot and openfurrow-scheduler-pilot already installed: "
                                            "uninstall first \\(openfurrow service uninstall --suffix pilot\\)"):
    installedOn(store, manager, suffix="pilot")
  assert [request[0] for request in manager.changes()] == ["install"]


def testASecondDeploymentInstallsBesideTheFirstUnderItsOwnSuffix(store, tmp_path):
  manager = MemoryManager()
  installedOn(store, manager)
  other = tmp_path / "second"
  other.mkdir()
  Workspace.create(str(other / "trials.db"))
  installedOn(other / "trials.db", manager, suffix="second")
  assert sorted(manager.states) == ["openfurrow-scheduler", "openfurrow-scheduler-second", "openfurrow-web", "openfurrow-web-second"]


def testAnInstallThatFailsPartWayIsUndone(store):
  manager = MemoryManager(failsToInstall=True)
  with pytest.raises(DeploymentError, match="the scheduler's service cannot be created"):
    installedOn(store, manager)
  assert [request[0] for request in manager.changes()] == ["install", "uninstall"]
  assert (manager.states, manager.deployments) == ({}, {})
  assert not (store.parent / "logs").exists()


def testAPostgresStoreMustBeNamedByTheEnvironmentFileAndGivenALogsFolder(tmp_path):
  url = "postgresql+pg8000://openfurrow:hunter2hunter2@db.example:5432/openfurrow"
  manager = MemoryManager()
  with pytest.raises(DeploymentError, match="put OPENFURROW_STORE=<the URL> in an environment file") as refusal:
    manage.install(url, "127.0.0.1", freePort(), manager=manager)
  assert "hunter2" not in str(refusal.value)
  environmentFile = tmp_path / "openfurrow.env"
  environmentFile.write_text("OPENFURROW_STORE=postgresql+pg8000://openfurrow:other@db.example:5432/openfurrow\n", encoding="utf-8")
  with pytest.raises(DeploymentError, match="put OPENFURROW_STORE=<the URL> in an environment file"):
    manage.install(url, "127.0.0.1", freePort(), environmentFile=str(environmentFile), manager=manager)
  environmentFile.write_text(f"OPENFURROW_STORE={url}\n", encoding="utf-8")
  with pytest.raises(DeploymentError, match="has no folder to keep the logs beside: name one with --logs"):
    manage.install(url, "127.0.0.1", freePort(), environmentFile=str(environmentFile), manager=manager)
  assert manager.asked == []


def testADeploymentWithoutAStoreFileReadsItsStoreFromItsEnvironmentFile(tmp_path):
  environmentFile = tmp_path / "openfurrow.env"
  environmentFile.write_text("OPENFURROW_STORE=postgresql+pg8000://openfurrow:pw@db.example:5432/openfurrow\n", encoding="utf-8")
  deployment = Deployment(storeFile=None, logsFolder=tmp_path / "logs", suffix=None, environmentFile=environmentFile,
                          python=Path(sys.executable))
  assert deployment.storeLocation() == "postgresql+pg8000://openfurrow:pw@db.example:5432/openfurrow"
  environmentFile.write_text("OTHER=1\n", encoding="utf-8")
  with pytest.raises(DeploymentError, match="their environment file does not set OPENFURROW_STORE"):
    deployment.storeLocation()


def testAnEnvironmentFileInAFormNotTakenIsRefusedAtInstall(store, tmp_path):
  environmentFile = tmp_path / "openfurrow.env"
  environmentFile.write_text("export SECRET=1\n", encoding="utf-8")
  manager = MemoryManager()
  with pytest.raises(DeploymentError, match="line 1 .* is not NAME=value"):
    installedOn(store, manager, environmentFile=str(environmentFile))
  assert manager.asked == []


# ---- uninstall, start, stop, status ---------------------------------------------------

def testUninstallingWhatIsNotInstalledIsRefusedByName():
  manager = MemoryManager()
  with pytest.raises(DeploymentError, match="cannot uninstall openfurrow-web-pilot and openfurrow-scheduler-pilot: not installed"):
    manage.uninstall("pilot", manager=manager)
  assert manager.asked == []


def testUninstallStopsTheSchedulerThenTheWebServerAndRemovesBoth(store):
  manager = MemoryManager()
  deployment = installedOn(store, manager)
  manage.start(manager=manager)
  del manager.asked[:]
  assert manage.uninstall(manager=manager) == ["openfurrow-web", "openfurrow-scheduler"]
  assert manager.asked == [("stop", "openfurrow-scheduler"), ("stop", "openfurrow-web"), ("uninstall", deployment)]
  assert manage.status(manager=manager) == manage.Status(
    states={Role.web: ServiceState.notInstalled, Role.scheduler: ServiceState.notInstalled}, deployment=None)


def testWhatIsLeftOfABrokenInstallCanBeUninstalled(store):
  manager = MemoryManager()
  deployment = installedOn(store, manager)
  del manager.deployments["openfurrow-web"], manager.states["openfurrow-web"]
  assert manage.uninstall(manager=manager) == ["openfurrow-scheduler"]
  assert manager.asked[-1] == ("uninstall", deployment)


def testStartStartsTheWebServerThenTheSchedulerAndStopStopsThemInReverse(store):
  manager = MemoryManager()
  deployment = installedOn(store, manager)
  del manager.asked[:]
  assert manage.start(manager=manager) == deployment
  assert manager.asked == [("start", "openfurrow-web"), ("start", "openfurrow-scheduler")]
  assert manage.status(manager=manager) == manage.Status(
    states={Role.web: ServiceState.running, Role.scheduler: ServiceState.running}, deployment=deployment)
  del manager.asked[:]
  manage.start(manager=manager)
  assert manager.asked == []
  assert manage.stop(manager=manager) == deployment
  assert manager.asked == [("stop", "openfurrow-scheduler"), ("stop", "openfurrow-web")]
  manage.stop(manager=manager)
  assert manage.status(manager=manager).states == {Role.web: ServiceState.stopped, Role.scheduler: ServiceState.stopped}


def testAServiceThatFailsToStartIsReportedWithItsLog(store):
  manager = MemoryManager(startsAs=ServiceState.failed)
  deployment = installedOn(store, manager)
  with pytest.raises(DeploymentError) as refusal:
    manage.start(manager=manager)
  assert str(refusal.value) == f"openfurrow-web failed to start; see its log, {deployment.logsFolder / 'openfurrow-web.log'}"
  assert ("start", "openfurrow-scheduler") not in manager.asked


def testStoppingAFailedServiceSaysSoWhereTheSystemStartsItAgainByItself(store):
  manager = MemoryManager(startsAs=ServiceState.failed, failedStartsAgain=True)
  deployment = installedOn(store, manager)
  with pytest.raises(DeploymentError, match="openfurrow-web failed to start"):
    manage.start(manager=manager)
  with pytest.raises(DeploymentError) as refusal:
    manage.stop(manager=manager)
  assert str(refusal.value) == (
    f"openfurrow-web is not running because it failed, and this system starts a failed service again by itself, "
    f"within a minute, whatever it is told: see its log, {deployment.logsFolder / 'openfurrow-web.log'}, or "
    f"uninstall the services to keep it down")
  assert manage.uninstall(manager=manager) == ["openfurrow-web", "openfurrow-scheduler"]
  assert manager.states == {}


def testAFailedServiceIsStoppedWhereTheSystemLeavesItSo(store):
  manager = MemoryManager(startsAs=ServiceState.failed)
  deployment = installedOn(store, manager)
  with pytest.raises(DeploymentError, match="openfurrow-web failed to start"):
    manage.start(manager=manager)
  assert manage.stop(manager=manager) == deployment


@pytest.mark.parametrize("action", ["start", "stop"])
def testStartingOrStoppingWhatIsNotInstalledIsRefusedByName(action):
  with pytest.raises(DeploymentError, match=f"cannot {action} openfurrow-web and openfurrow-scheduler: not installed"):
    getattr(manage, action)(manager=MemoryManager())


def testAnOddSuffixIsRefusedBeforeAnyServiceIsLookedFor(store):
  manager = MemoryManager()
  for action in (manage.uninstall, manage.start, manage.stop, manage.status):
    with pytest.raises(DeploymentError, match="is not a suffix for service names"):
      action("Pilot One", manager=manager)
  assert manager.asked == []


# ---- the command line -----------------------------------------------------------------

def testTheStatusCommandNamesBothServicesOfASuffixNobodyInstalled(capsys):
  assert main(["service", "status", "--suffix", "nobody-has-this"]) == 0
  assert capsys.readouterr().out.splitlines() == ["openfurrow-web-nobody-has-this\tnot installed",
                                                  "openfurrow-scheduler-nobody-has-this\tnot installed"]


def testAServiceCommandThatIsRefusedExitsNonZeroWithTheReason(capsys):
  assert main(["service", "status", "--suffix", "Not A Suffix"]) == 1
  assert capsys.readouterr().err.startswith("error: 'Not A Suffix' is not a suffix for service names")
