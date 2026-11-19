# SPDX-License-Identifier: Apache-2.0
"""What `openfurrow service install` hands each service manager (decision 0009), to the letter: the systemd units,
the launchd property lists, the Windows service definitions and access commands, and the environment file's form.
Nothing here touches a service manager, so it runs on every platform."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from openfurrow.osService import launchd, systemd, windows
from openfurrow.osService.deployment import (
  Deployment, DeploymentError, Role, ServiceState, checkedSuffix, deploymentOf, readEnvironmentFile, serviceName,
)

python = PurePosixPath("/opt/openfurrow/bin/python")
plain = Deployment(storeFile=PurePosixPath("/srv/openfurrow/trials.db"), logsFolder=PurePosixPath("/srv/openfurrow/logs"),
                   suffix=None, environmentFile=PurePosixPath("/etc/openfurrow/openfurrow.env"), python=python,
                   host="127.0.0.1", port=8420)
pilot = Deployment(storeFile=PurePosixPath("/srv/field trials/pilot.db"), logsFolder=PurePosixPath("/var/log/openfurrow pilot"),
                   suffix="pilot", environmentFile=None, python=python, host="0.0.0.0", port=9000)
onPostgres = Deployment(storeFile=None, logsFolder=PurePosixPath("/var/log/openfurrow"), suffix=None,
                        environmentFile=PurePosixPath("/etc/openfurrow/openfurrow.env"), python=python,
                        host="127.0.0.1", port=8420)
onWindows = Deployment(storeFile=PureWindowsPath(r"C:\OpenFurrow\trials.db"), logsFolder=PureWindowsPath(r"C:\OpenFurrow\logs"),
                       suffix="pilot", environmentFile=PureWindowsPath(r"C:\OpenFurrow\openfurrow.env"),
                       python=PureWindowsPath(r"C:\Program Files\Python313\python.exe"), host="127.0.0.1", port=8420)
webSID = "S-1-5-80-643074407-271743801-3675086135-1487001027-987694823"
schedulerSID = "S-1-5-80-382682366-2972029526-515272350-603376662-830711483"

hardening = """Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=60
UMask=0027
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
"""


def posixPaths(deployment):
  """The deployment with its paths as POSIX paths, however this platform read them back."""
  def posix(path):
    return None if path is None else PurePosixPath(path.as_posix())
  return replace(deployment, storeFile=posix(deployment.storeFile), logsFolder=posix(deployment.logsFolder),
                 environmentFile=posix(deployment.environmentFile), python=posix(deployment.python))


# ---- names ------------------------------------------------------------------------

def testServicesAreNamedByRoleAndSuffix():
  assert [serviceName(role, None) for role in Role] == ["openfurrow-web", "openfurrow-scheduler"]
  assert [serviceName(role, "pilot-2") for role in Role] == ["openfurrow-web-pilot-2", "openfurrow-scheduler-pilot-2"]
  assert (systemd.account(None), systemd.account("pilot")) == ("openfurrow", "openfurrow-pilot")
  assert (launchd.account(None), launchd.account("pilot")) == ("_openfurrow", "_openfurrow-pilot")


@pytest.mark.parametrize("suffix", ["Pilot", "-pilot", "pilot-", "two words", "a_b", "", "x" * 17, "caf\u00e9"])
def testASuffixThatIsNotLowerCaseWordsIsRefused(suffix):
  with pytest.raises(DeploymentError, match="is not a suffix for service names"):
    checkedSuffix(suffix)


def testASuffixOfLowerCaseWordsIsKept():
  assert [checkedSuffix(suffix) for suffix in (None, "pilot", "site-2", "x" * 16)] == [None, "pilot", "site-2", "x" * 16]


# ---- systemd ----------------------------------------------------------------------

def testTheWebUnitOfAFileStore():
  assert systemd.unitFile(plain, Role.web) == f"""[Unit]
Description=OpenFurrow web server
After=network.target

[Service]
Type=notify
User=openfurrow
Group=openfurrow
ExecStart=/opt/openfurrow/bin/python -P -m openfurrow.osService.host web --store /srv/openfurrow/trials.db --logs /srv/openfurrow/logs --host 127.0.0.1 --port 8420
EnvironmentFile=/etc/openfurrow/openfurrow.env
{hardening}ReadWritePaths=/srv/openfurrow

[Install]
WantedBy=multi-user.target
"""


def testTheSchedulerUnitQuotesPathsWithSpacesAndIsNotOrderedAfterTheWebUnit():
  unit = systemd.unitFile(pilot, Role.scheduler)
  assert unit == f"""[Unit]
Description=OpenFurrow scheduler (pilot)
After=network.target

[Service]
Type=notify
User=openfurrow-pilot
Group=openfurrow-pilot
ExecStart=/opt/openfurrow/bin/python -P -m openfurrow.osService.host scheduler --suffix pilot --store "/srv/field trials/pilot.db" --logs "/var/log/openfurrow pilot"
{hardening}ReadWritePaths="/srv/field trials" "/var/log/openfurrow pilot"

[Install]
WantedBy=multi-user.target
"""
  assert "openfurrow-web" not in unit


def testAPostgresStoreIsNamedOnlyByTheEnvironmentFile():
  unit = systemd.unitFile(onPostgres, Role.scheduler)
  assert "ExecStart=/opt/openfurrow/bin/python -P -m openfurrow.osService.host scheduler --logs /var/log/openfurrow\n" in unit
  assert "EnvironmentFile=/etc/openfurrow/openfurrow.env\n" in unit
  assert "ReadWritePaths=/var/log/openfurrow\n" in unit
  assert "--store" not in unit and "postgresql" not in unit


@pytest.mark.parametrize("deployment", [plain, pilot, onPostgres])
def testAUnitReadsBackAsTheDeploymentItWasWrittenFrom(deployment):
  role, readBack = systemd.deploymentOfUnit(systemd.unitFile(deployment, Role.web))
  assert (role, posixPaths(readBack)) == (Role.web, deployment)
  role, readBack = systemd.deploymentOfUnit(systemd.unitFile(deployment, Role.scheduler))
  assert (role, posixPaths(readBack)) == (Role.scheduler, replace(deployment, host=None, port=None))


@pytest.mark.parametrize("character", ['"', "\\", "$", "%", "\n"])
def testAPathSystemdWouldReadInItsOwnWayIsRefused(character):
  odd = replace(plain, storeFile=PurePosixPath(f"/srv/open{character}furrow/trials.db"))
  with pytest.raises(DeploymentError, match="choose paths without them"):
    systemd.unitFile(odd, Role.web)
  with pytest.raises(DeploymentError, match="choose paths without them"):
    systemd.unitFile(replace(plain, environmentFile=PurePosixPath(f"/etc/open{character}furrow.env")), Role.web)


def testAUnitThatDoesNotRunOpenFurrowIsNotReadAsOne():
  with pytest.raises(DeploymentError, match="not one OpenFurrow installed"):
    systemd.deploymentOfUnit("[Service]\nExecStart=/usr/sbin/sshd -D\n")


def testTheLinuxAccountIsASystemAccountThatCannotLogInWithAGroupOfItsName():
  assert systemd.accountCommand("openfurrow-pilot", hasGroup=False) == [
    "useradd", "--system", "--home-dir", "/nonexistent", "--no-create-home", "--shell", "/usr/sbin/nologin",
    "--user-group", "--comment", "OpenFurrow service account made by openfurrow service install with its group",
    "openfurrow-pilot"]
  assert systemd.accountCommand("openfurrow", hasGroup=True) == [
    "useradd", "--system", "--home-dir", "/nonexistent", "--no-create-home", "--shell", "/usr/sbin/nologin",
    "--gid", "openfurrow", "--comment", "OpenFurrow service account made by openfurrow service install", "openfurrow"]


def testSystemdsWordForAUnitsStateIsRead():
  words = ("active", "reloading", "inactive", "activating", "deactivating", "failed")
  assert [systemd.stateNamed(word) for word in words] == [
    ServiceState.running, ServiceState.running, ServiceState.stopped, ServiceState.starting, ServiceState.stopping,
    ServiceState.failed]
  with pytest.raises(DeploymentError, match="answered 'maintenance', which is no state of a unit"):
    systemd.stateNamed("maintenance")


# ---- launchd ----------------------------------------------------------------------

directoryUsers = """_amavisd                 83
_appleevents             55
_openfurrow-old          499
daemon                   1
nobody                   -2
root                     0
runner                   501
"""
daemonListing = """system/openfurrow-web = {
	active count = 1
	path = /Library/LaunchDaemons/openfurrow-web.plist
	type = LaunchDaemon
	state = running

	program = /opt/openfurrow/bin/python
	arguments = {
		/opt/openfurrow/bin/python
		-P
	}

	default environment = {
		PATH => /usr/bin:/bin:/usr/sbin:/sbin
	}

	pid = 4242
	immediate reason = speculative
	last exit code = (never exited)
}
"""


def testTheMacAccountTakesTheHighestFreeNumberIsHiddenAndCannotLogIn():
  users = launchd.numbersIn(directoryUsers)
  assert users == {"_amavisd": 83, "_appleevents": 55, "_openfurrow-old": 499, "daemon": 1, "nobody": -2, "root": 0, "runner": 501}
  commands, userID, groupID = launchd.accountCommands("_openfurrow", users, {"wheel": 0, "staff": 20, "_lodger": 498})
  assert (userID, groupID) == (497, 497)
  assert commands == [["dscl", ".", "-create", *record] for record in (
    ["/Groups/_openfurrow"], ["/Groups/_openfurrow", "PrimaryGroupID", "497"], ["/Groups/_openfurrow", "Password", "*"],
    ["/Users/_openfurrow"], ["/Users/_openfurrow", "UniqueID", "497"], ["/Users/_openfurrow", "PrimaryGroupID", "497"],
    ["/Users/_openfurrow", "UserShell", "/usr/bin/false"], ["/Users/_openfurrow", "NFSHomeDirectory", "/var/empty"],
    ["/Users/_openfurrow", "Password", "*"], ["/Users/_openfurrow", "IsHidden", "1"],
    ["/Users/_openfurrow", "RealName", "OpenFurrow service account made by openfurrow service install with its group"])]


def testAMacAccountJoinsAGroupOfItsNameThatIsAlreadyThere():
  commands, userID, groupID = launchd.accountCommands("_openfurrow", {"root": 0}, {"_openfurrow": 250})
  assert (userID, groupID) == (499, 250)
  assert [command[3:] for command in commands if "/Groups/" in command[3]] == []
  assert ["/Users/_openfurrow", "PrimaryGroupID", "250"] in [command[3:] for command in commands]
  assert commands[-1][3:] == ["/Users/_openfurrow", "RealName", "OpenFurrow service account made by openfurrow service install"]


def testNoFreeAccountNumberIsRefusedByName():
  with pytest.raises(DeploymentError, match="no account number between 300 and 499 is free for the service account _openfurrow"):
    launchd.accountCommands("_openfurrow", {f"user{number}": number for number in range(300, 500)}, {})


def testLaunchdsListingOfADaemonIsReadForItsState():
  assert launchd.stateIn(daemonListing) is ServiceState.running
  assert launchd.stateIn(daemonListing.replace("state = running", "state = not running")) is ServiceState.stopped
  assert launchd.stateIn(daemonListing.replace("state = running", "state = spawn scheduled")) is ServiceState.stopped


def testTheWebDaemonsPropertyList():
  assert launchd.propertyList(plain, Role.web).decode("utf-8") == """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>ExitTimeOut</key>
	<integer>60</integer>
	<key>GroupName</key>
	<string>_openfurrow</string>
	<key>KeepAlive</key>
	<dict>
		<key>SuccessfulExit</key>
		<false/>
	</dict>
	<key>Label</key>
	<string>openfurrow-web</string>
	<key>ProgramArguments</key>
	<array>
		<string>/opt/openfurrow/bin/python</string>
		<string>-P</string>
		<string>-m</string>
		<string>openfurrow.osService.host</string>
		<string>web</string>
		<string>--store</string>
		<string>/srv/openfurrow/trials.db</string>
		<string>--logs</string>
		<string>/srv/openfurrow/logs</string>
		<string>--host</string>
		<string>127.0.0.1</string>
		<string>--port</string>
		<string>8420</string>
		<string>--environment-file</string>
		<string>/etc/openfurrow/openfurrow.env</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardErrorPath</key>
	<string>/srv/openfurrow/logs/openfurrow-web.launchd.log</string>
	<key>StandardOutPath</key>
	<string>/srv/openfurrow/logs/openfurrow-web.launchd.log</string>
	<key>UserName</key>
	<string>_openfurrow</string>
</dict>
</plist>
"""


def testTheSchedulerDaemonsPropertyList():
  assert launchd.propertyList(pilot, Role.scheduler).decode("utf-8") == """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>ExitTimeOut</key>
	<integer>60</integer>
	<key>GroupName</key>
	<string>_openfurrow-pilot</string>
	<key>KeepAlive</key>
	<dict>
		<key>SuccessfulExit</key>
		<false/>
	</dict>
	<key>Label</key>
	<string>openfurrow-scheduler-pilot</string>
	<key>ProgramArguments</key>
	<array>
		<string>/opt/openfurrow/bin/python</string>
		<string>-P</string>
		<string>-m</string>
		<string>openfurrow.osService.host</string>
		<string>scheduler</string>
		<string>--suffix</string>
		<string>pilot</string>
		<string>--store</string>
		<string>/srv/field trials/pilot.db</string>
		<string>--logs</string>
		<string>/var/log/openfurrow pilot</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardErrorPath</key>
	<string>/var/log/openfurrow pilot/openfurrow-scheduler-pilot.launchd.log</string>
	<key>StandardOutPath</key>
	<string>/var/log/openfurrow pilot/openfurrow-scheduler-pilot.launchd.log</string>
	<key>UserName</key>
	<string>_openfurrow-pilot</string>
</dict>
</plist>
"""


@pytest.mark.parametrize("deployment", [plain, pilot, onPostgres])
def testAPropertyListReadsBackAsTheDeploymentItWasWrittenFrom(deployment):
  role, readBack = launchd.deploymentOfPropertyList(launchd.propertyList(deployment, Role.web))
  assert (role, posixPaths(readBack)) == (Role.web, deployment)
  role, readBack = launchd.deploymentOfPropertyList(launchd.propertyList(deployment, Role.scheduler))
  assert (role, posixPaths(readBack)) == (Role.scheduler, replace(deployment, host=None, port=None))


def testAPropertyListThatDoesNotRunOpenFurrowIsNotReadAsOne():
  with pytest.raises(DeploymentError, match="not one OpenFurrow installed"):
    launchd.deploymentOfPropertyList(b'<plist version="1.0"><dict><key>Label</key><string>other</string></dict></plist>')


# ---- Windows ----------------------------------------------------------------------

def testAServicesSecurityIdentifierIsTheOneWindowsDerivesFromItsName():
  assert windows.serviceSID("TrustedInstaller") == "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
  assert windows.serviceSID("trustedinstaller") == windows.serviceSID("TrustedInstaller")
  assert (windows.serviceSID("openfurrow-web-pilot"), windows.serviceSID("openfurrow-scheduler-pilot")) == (webSID, schedulerSID)


def testTheWindowsServiceDefinitions():
  entry = Path(windows.__file__).with_name("windowsEntry.py")
  assert entry.is_file()
  program = f'"C:\\Program Files\\Python313\\python.exe" -P {subprocess.list2cmdline([str(entry)])}'
  assert windows.definition(onWindows, Role.web) == windows.ServiceDefinition(
    name="openfurrow-web-pilot", displayName="OpenFurrow web server (pilot)",
    description="OpenFurrow, agricultural trial management: serves the web interface and the API of one store.",
    commandLine=f"{program} web --suffix pilot --store C:\\OpenFurrow\\trials.db --logs C:\\OpenFurrow\\logs "
                f"--host 127.0.0.1 --port 8420 --environment-file C:\\OpenFurrow\\openfurrow.env",
    account="NT AUTHORITY\\LocalService", hasOwnSID=True, delayedStart=True, failureResetSeconds=86400,
    restartDelaysMilliseconds=(5000, 30000, 60000), restartsOnExitCode=True)
  assert windows.definition(onWindows, Role.scheduler) == windows.ServiceDefinition(
    name="openfurrow-scheduler-pilot", displayName="OpenFurrow scheduler (pilot)",
    description="OpenFurrow, agricultural trial management: runs the scheduled tasks of one store.",
    commandLine=f"{program} scheduler --suffix pilot --store C:\\OpenFurrow\\trials.db --logs C:\\OpenFurrow\\logs "
                f"--environment-file C:\\OpenFurrow\\openfurrow.env",
    account="NT AUTHORITY\\LocalService", hasOwnSID=True, delayedStart=True, failureResetSeconds=86400,
    restartDelaysMilliseconds=(5000, 30000, 60000), restartsOnExitCode=True)


def testTheServicesOwnIdentifiersAreGivenTheStoresFolderAndTheEnvironmentFileToReadAndNothingElse():
  assert windows.grantCommands(onWindows) == [
    ["icacls", "C:\\OpenFurrow", "/grant", f"*{webSID}:(OI)(CI)M", f"*{schedulerSID}:(OI)(CI)M"],
    ["icacls", "C:\\OpenFurrow\\openfurrow.env", "/inheritance:r", "/grant:r", "*S-1-5-32-544:F", "*S-1-5-18:F",
     f"*{webSID}:R", f"*{schedulerSID}:R"],
  ]
  assert windows.revokeCommands(onWindows) == [
    ["icacls", "C:\\OpenFurrow", "/remove", f"*{webSID}", f"*{schedulerSID}"],
    ["icacls", "C:\\OpenFurrow\\openfurrow.env", "/remove", f"*{webSID}", f"*{schedulerSID}"],
  ]


def testLogsKeptOutsideTheStoresFolderAreGivenToo():
  apart = replace(onWindows, logsFolder=PureWindowsPath(r"D:\Logs\OpenFurrow"), environmentFile=None)
  assert windows.grantCommands(apart) == [
    ["icacls", "C:\\OpenFurrow", "/grant", f"*{webSID}:(OI)(CI)M", f"*{schedulerSID}:(OI)(CI)M"],
    ["icacls", "D:\\Logs\\OpenFurrow", "/grant", f"*{webSID}:(OI)(CI)M", f"*{schedulerSID}:(OI)(CI)M"],
  ]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own reading of a command line")
def testAWindowsCommandLineReadsBackAsTheDeploymentItWasWrittenFrom():
  spaced = replace(onWindows, storeFile=PureWindowsPath(r"C:\Field Trials\trials.db"), logsFolder=PureWindowsPath(r"C:\Field Trials\logs"))
  for deployment in (onWindows, spaced):
    name = deployment.name(Role.web)
    role, readBack = windows.deploymentOfCommandLine(name, windows.definition(deployment, Role.web).commandLine)
    assert (role, readBack) == (Role.web, deployment)
  with pytest.raises(DeploymentError, match="is not one OpenFurrow installed"):
    windows.deploymentOfCommandLine("Spooler", r"C:\WINDOWS\System32\spoolsv.exe")


# ---- what a service's process is told ------------------------------------------------

def testTheProcessIsToldOfTheEnvironmentFileOnlyWhereItReadsItItself():
  assert plain.hostArguments(Role.web, readsEnvironmentFile=True)[-2:] == ["--environment-file", "/etc/openfurrow/openfurrow.env"]
  assert "--environment-file" not in plain.hostArguments(Role.web, readsEnvironmentFile=False)


def testArgumentsThatAreNotAServicesAreRefusedByName():
  with pytest.raises(DeploymentError, match="not the arguments of an OpenFurrow service's process: the web service needs --host and --port"):
    deploymentOf("python", ["web", "--logs", "/var/log/openfurrow"])
  with pytest.raises(DeploymentError, match="not the arguments of an OpenFurrow service's process: .*--logs"):
    deploymentOf("python", ["scheduler"])
  with pytest.raises(DeploymentError, match="not the arguments of an OpenFurrow service's process: .*invalid choice: 'mail'"):
    deploymentOf("python", ["mail", "--logs", "/var/log/openfurrow"])


# ---- the environment file -----------------------------------------------------------

def testAnEnvironmentFileIsNameValueLinesInThreeForms(tmp_path):
  path = tmp_path / "openfurrow.env"
  path.write_text("# identity providers\n\nOIDC_SECRET=s3cr3t+/=\nEMPTY=\n  INDENTED= value # kept\n"
                  "PATH_VALUE='C:\\certs\\key.pem'\nQUOTED=\"two words, a \\\" and a \\\\\"\n"
                  "TRAILING=value   \nOPENFURROW_STORE=postgresql+pg8000://openfurrow:pw@db.example:5432/openfurrow\r\n",
                  encoding="utf-8", newline="")
  assert readEnvironmentFile(path) == {
    "OIDC_SECRET": "s3cr3t+/=", "EMPTY": "", "INDENTED": "value # kept", "PATH_VALUE": "C:\\certs\\key.pem",
    "QUOTED": 'two words, a " and a \\',
    "TRAILING": "value", "OPENFURROW_STORE": "postgresql+pg8000://openfurrow:pw@db.example:5432/openfurrow",
  }


@pytest.mark.parametrize("line, problem", [
  ("export SECRET=hunter2hunter2", "line 2 .* is not NAME=value"),
  ("SECRET hunter2hunter2", "line 2 .* is not NAME=value"),
  ("SEC RET=hunter2hunter2", "line 2 .* is not NAME=value"),
  ("; SECRET=hunter2hunter2", "line 2 .* is not NAME=value"),
  ("SECRET=hunter2\\hunter2", "line 2 .* does not hold a value in a form this file takes"),
  ("SECRET=hunter2'hunter2", "line 2 .* does not hold a value in a form this file takes"),
  ("SECRET=\"hunter2hunter2", "line 2 .* does not hold a value in a form this file takes"),
  ("SECRET=\"hunter2\\nhunter2\"", "line 2 .* does not hold a value in a form this file takes"),
  ("SECRET='hunter2' hunter2", "line 2 .* does not hold a value in a form this file takes"),
  ("FIRST=hunter2hunter2", "line 2 .* sets FIRST a second time"),
])
def testALineInAnotherFormIsRefusedByItsNumberWithoutItsValue(tmp_path, line, problem):
  path = tmp_path / "openfurrow.env"
  path.write_text(f"FIRST=1\n{line}\n", encoding="utf-8")
  with pytest.raises(DeploymentError, match=problem) as refusal:
    readEnvironmentFile(path)
  assert "hunter2" not in str(refusal.value)


def testAnEnvironmentFileThatIsMissingOrStartsWithAByteOrderMarkIsRefusedByName(tmp_path):
  with pytest.raises(DeploymentError, match="cannot be read"):
    readEnvironmentFile(tmp_path / "absent.env")
  marked = tmp_path / "marked.env"
  marked.write_text("NAME=value\n", encoding="utf-8-sig")
  with pytest.raises(DeploymentError, match="starts with a byte-order mark"):
    readEnvironmentFile(marked)
