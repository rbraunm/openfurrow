# SPDX-License-Identifier: Apache-2.0
"""What a deployment chooses when OpenFurrow runs as operating-system services (decision 0009).

Two services share one store: the web server and the scheduler (decision 0041). A
deployment names the store, the address the web server listens on, the folder its logs go
to, an environment file (provider secrets and settings; and the location of a PostgreSQL
store, whose URL carries a password and so is written nowhere else) and a suffix that
sets its services apart from another deployment's on the same machine. Each service's
definition is generated from the deployment and read back from an installed definition,
so nothing else records it.
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from openfurrow.tasks.run import storeVariable

hostModule = "openfurrow.osService.host"
logsFolderName = "logs"
logRetentionDays = 90
maximumSuffixLength = 16
_suffixPattern = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_variablePattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_plainValue = re.compile(r"[^'\"\\]*")
_singleQuotedValue = re.compile(r"'[^']*'")
_doubleQuotedValue = re.compile(r'"(?:[^"\\]|\\["\\])*"')


class DeploymentError(RuntimeError):
  """The services cannot be installed, removed, started, stopped or read as asked."""


class Role(str, Enum):
  web = "web"
  scheduler = "scheduler"


class ServiceState(str, Enum):
  notInstalled = "not installed"
  stopped = "stopped"
  starting = "starting"
  running = "running"
  stopping = "stopping"
  failed = "failed"


def checkedSuffix(suffix: str | None) -> str | None:
  if suffix is None:
    return None
  if len(suffix) > maximumSuffixLength or not _suffixPattern.fullmatch(suffix):
    raise DeploymentError(f"'{suffix}' is not a suffix for service names: lower-case letters and digits, in words "
                          f"joined by '-', at most {maximumSuffixLength} characters")
  return suffix


def serviceName(role: Role, suffix: str | None) -> str:
  return f"openfurrow-{role.value}" + (f"-{suffix}" if suffix else "")


def serviceTitle(role: Role, suffix: str | None) -> str:
  title = "OpenFurrow web server" if role is Role.web else "OpenFurrow scheduler"
  return title + (f" ({suffix})" if suffix else "")


@dataclass(frozen=True)
class Deployment:
  """One store served by a web server and a scheduler. `storeFile` is None for a PostgreSQL store, whose URL only
  the environment file holds; `host` and `port` are None when read back from the scheduler's definition alone."""

  storeFile: Path | None
  logsFolder: Path
  suffix: str | None
  environmentFile: Path | None
  python: Path
  host: str | None = None
  port: int | None = None

  def name(self, role: Role) -> str:
    return serviceName(role, self.suffix)

  def logFile(self, role: Role) -> Path:
    return self.logsFolder / f"{self.name(role)}.log"

  def storeLocation(self) -> str:
    """The store as every command takes it: the file, or the URL the environment file carries."""
    if self.storeFile is not None:
      return str(self.storeFile)
    variables = readEnvironmentFile(self.environmentFile) if self.environmentFile is not None else {}
    if storeVariable not in variables:
      raise DeploymentError(f"the services of this deployment name no store file, and their environment file does "
                            f"not set {storeVariable}")
    return variables[storeVariable]

  def storeFiles(self) -> list[Path]:
    """The store's file and the files SQLite keeps beside it while it works."""
    name = self.storeFile.name
    return [self.storeFile, *[self.storeFile.with_name(name + ending) for ending in ("-journal", "-wal", "-shm")]]

  def writtenFolders(self) -> list[Path]:
    """The folders the services write in: the store's, and the logs folder where it lies elsewhere."""
    folders = [] if self.storeFile is None else [self.storeFile.parent]
    if not any(self.logsFolder == folder or folder in self.logsFolder.parents for folder in folders):
      folders.append(self.logsFolder)
    return folders

  def hostArguments(self, role: Role, readsEnvironmentFile: bool) -> list[str]:
    """What the service's process is given after its program. Where the service manager reads the environment
    file itself, the process is not told of it."""
    arguments = [role.value]
    if self.suffix is not None:
      arguments += ["--suffix", self.suffix]
    if self.storeFile is not None:
      arguments += ["--store", str(self.storeFile)]
    arguments += ["--logs", str(self.logsFolder)]
    if role is Role.web:
      arguments += ["--host", self.host, "--port", str(self.port)]
    if readsEnvironmentFile and self.environmentFile is not None:
      arguments += ["--environment-file", str(self.environmentFile)]
    return arguments


class _HostParser(argparse.ArgumentParser):
  def error(self, message: str):
    raise DeploymentError(f"these are not the arguments of an OpenFurrow service's process: {message}")


def hostOptions(arguments: list[str]) -> argparse.Namespace:
  """The arguments of a service's process, as `hostArguments` writes them."""
  parser = _HostParser(prog=f"python -m {hostModule}", description="The process an installed OpenFurrow service runs.")
  parser.add_argument("role", choices=[role.value for role in Role])
  parser.add_argument("--suffix")
  parser.add_argument("--store", help=f"the store's file; without it the store is the URL in {storeVariable}")
  parser.add_argument("--logs", required=True, help="the folder the service's log file is kept in")
  parser.add_argument("--host")
  parser.add_argument("--port", type=int)
  parser.add_argument("--environment-file", dest="environmentFile")
  options = parser.parse_args(arguments)
  if options.role == Role.web.value and (options.host is None or options.port is None):
    parser.error("the web service needs --host and --port")
  return options


def deploymentOf(python: str, arguments: list[str], environmentFile: Path | None = None) -> tuple[Role, Deployment]:
  """The role and the deployment a service's process arguments say."""
  options = hostOptions(arguments)
  if options.environmentFile is not None:
    environmentFile = Path(options.environmentFile)
  deployment = Deployment(storeFile=None if options.store is None else Path(options.store), logsFolder=Path(options.logs),
                          suffix=options.suffix, environmentFile=environmentFile, python=Path(python),
                          host=options.host, port=options.port)
  return Role(options.role), deployment


def readEnvironmentFile(path: Path) -> dict[str, str]:
  """The variables an environment file sets, one NAME=value a line; blank lines and lines starting with # are left out.

  A value is plain text without quotes or backslashes, or text in single quotes taken as written, or text in
  double quotes with a backslash before each double quote and backslash in it: the forms systemd's
  EnvironmentFile and this reader take alike, so a file means the same on every platform. Anything else is
  refused by its line, and no message shows a value.
  """
  try:
    text = path.read_text(encoding="utf-8")
  except OSError as error:
    raise DeploymentError(f"the environment file '{path}' cannot be read: {error.strerror}") from error
  except UnicodeDecodeError as error:
    raise DeploymentError(f"the environment file '{path}' is not UTF-8 text") from error
  if text.startswith(codecs.BOM_UTF8.decode("utf-8")):
    raise DeploymentError(f"the environment file '{path}' starts with a byte-order mark; save it as UTF-8 without one")
  variables: dict[str, str] = {}
  for number, line in enumerate(text.splitlines(), start=1):
    line = line.strip()
    if not line or line.startswith("#"):
      continue
    name, separator, value = line.partition("=")
    if not separator or not _variablePattern.fullmatch(name):
      raise DeploymentError(f"line {number} of the environment file '{path}' is not NAME=value")
    if name in variables:
      raise DeploymentError(f"line {number} of the environment file '{path}' sets {name} a second time")
    variables[name] = _environmentValue(value.lstrip(), f"line {number} of the environment file '{path}'")
  return variables


def _environmentValue(text: str, where: str) -> str:
  if _plainValue.fullmatch(text):
    return text
  if _singleQuotedValue.fullmatch(text):
    return text[1:-1]
  if _doubleQuotedValue.fullmatch(text):
    return re.sub(r'\\(["\\])', r"\1", text[1:-1])
  raise DeploymentError(f"{where} does not hold a value in a form this file takes: plain text without quotes or "
                        f"backslashes, text in single quotes, or text in double quotes with a backslash before "
                        f"each double quote and backslash in it")


_codeProbe = ("import json, sys, openfurrow.osService.host, openfurrow.service\n"
              "files = [module.__file__ for module in list(sys.modules.values()) if getattr(module, '__file__', None)]\n"
              "print(json.dumps([sys.executable, sys.base_prefix, *files]))")


def serviceCode(python: Path, **account) -> list[Path]:
  """The interpreter and every file a service's process loads code from, asked of that interpreter started as a
  service manager starts it: without this shell's folder or Python settings. `account` runs it as another user."""
  environment = {name: value for name, value in os.environ.items() if not name.upper().startswith("PYTHON")}
  probe = subprocess.run([str(python), "-P", "-c", _codeProbe], capture_output=True, text=True, env=environment, **account)
  if probe.returncode != 0:
    reason = (probe.stderr.strip().splitlines() or [f"exit code {probe.returncode}"])[-1]
    raise DeploymentError(f"{python} cannot load OpenFurrow's services ({reason}); OpenFurrow must be installed "
                          f"for that Python with its service extra: pip install 'openfurrow[service]'")
  return [Path(entry) for entry in json.loads(probe.stdout.splitlines()[-1])]


def under(path: Path, folders: tuple[Path, ...]) -> Path | None:
  """The first of `folders` that `path` is in, as it is written or once its links are followed."""
  for folder in folders:
    for place in (path.absolute(), path.resolve()):
      if place == folder or folder in place.parents:
        return folder
  return None
