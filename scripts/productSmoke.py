# SPDX-License-Identifier: Apache-2.0
"""Build the distributions, install the wheel into a clean environment, and run the worked example and the service from there."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

repositoryRoot = Path(__file__).resolve().parent.parent
exampleDirectory = repositoryRoot / "examples" / "yatesOats"
localeDirectory = repositoryRoot / "openfurrow" / "i18n" / "locales"
executableSuffix = ".exe" if os.name == "nt" else ""
# Every pip this script starts, the build's isolated environments included, installs the
# pinned versions.
pinnedEnvironment = {**os.environ, "PIP_CONSTRAINT": str(repositoryRoot / "constraints.txt")}
commandTimeoutSeconds = 900
serviceStartTimeoutSeconds = 30
serviceStopTimeoutSeconds = 15
contentHashPrefix = "Content hash: "


def step(message):
  print(f"==> {message}", flush=True)


def require(condition, message):
  if not condition:
    raise RuntimeError(message)


studyPath = "rothamsted/oats/varieties"


def addPlaces(openfurrow, database, workDirectory):
  """The example's place in the default hierarchy: organization, project, study."""
  for path, name in (("rothamsted", "Rothamsted"), ("rothamsted/oats", "Oats"), (studyPath, "Varieties and nitrogen")):
    run([openfurrow, "place", "add", database, path, name], workDirectory)

def run(arguments, workDirectory):
  command = [str(argument) for argument in arguments]
  completed = subprocess.run(
    command, cwd=workDirectory, env=pinnedEnvironment, stdout=subprocess.PIPE, text=True,
    timeout=commandTimeoutSeconds,
  )
  if completed.returncode != 0:
    print(completed.stdout, flush=True)
    raise RuntimeError(f"{command} exited with code {completed.returncode}")
  return completed.stdout


def contentHashFrom(infoOutput):
  hashes = [line[len(contentHashPrefix):] for line in infoOutput.splitlines() if line.startswith(contentHashPrefix)]
  require(len(hashes) == 1, f"expected one content hash line in the info output, found {len(hashes)}")
  return hashes[0]


def freePort():
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.bind(("127.0.0.1", 0))
    return probe.getsockname()[1]


def fetch(url):
  with urllib.request.urlopen(url, timeout=10) as response:
    return response.read().decode("utf-8")


def waitForService(service, baseURL):
  deadline = time.monotonic() + serviceStartTimeoutSeconds
  while time.monotonic() < deadline:
    require(service.poll() is None, f"the service exited with code {service.returncode} before answering")
    try:
      return json.loads(fetch(f"{baseURL}/health"))
    except (urllib.error.URLError, ConnectionError):
      time.sleep(0.2)
  raise RuntimeError(f"the service did not answer on {baseURL} within {serviceStartTimeoutSeconds} seconds")


def waitForPortClosed(port):
  deadline = time.monotonic() + serviceStopTimeoutSeconds
  while time.monotonic() < deadline:
    try:
      socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
      return
    time.sleep(0.2)
  raise RuntimeError(f"port {port} still accepts connections after the service was stopped")


def main():
  trialCode = json.loads((exampleDirectory / "trial.json").read_text(encoding="utf-8"))["trial"]["trialCode"]
  locales = sorted(path.stem for path in localeDirectory.glob("*.json"))

  with tempfile.TemporaryDirectory() as temporary:
    workDirectory = Path(temporary).resolve()

    # The wheel is built from the source distribution, not from the tree: a build/
    # directory left by an earlier in-tree build would otherwise supply files the
    # project no longer packages, and the smoke would pass on a broken package.
    step("building the source distribution and, from it, the wheel")
    wheelDirectory = workDirectory / "distributions"
    run([sys.executable, "-m", "build", "--outdir", wheelDirectory, repositoryRoot], workDirectory)
    wheels = list(wheelDirectory.glob("openfurrow-*.whl"))
    require(len(wheels) == 1, f"expected one openfurrow wheel, found {[wheel.name for wheel in wheels]}")

    step("installing it, with the service extra, into a clean environment")
    environmentDirectory = workDirectory / "environment"
    run([sys.executable, "-m", "venv", environmentDirectory], workDirectory)
    binDirectory = environmentDirectory / ("Scripts" if os.name == "nt" else "bin")
    python = binDirectory / f"python{executableSuffix}"
    openfurrow = binDirectory / f"openfurrow{executableSuffix}"
    run([python, "-m", "pip", "install", "--quiet", f"{wheels[0]}[service]"], workDirectory)

    modulePath = Path(run([python, "-c", "import openfurrow; print(openfurrow.__file__)"], workDirectory).strip()).resolve()
    require(
      environmentDirectory in modulePath.parents,
      f"openfurrow was imported from {modulePath}, not from the installed wheel",
    )

    step(f"running the worked example ({trialCode}) through the installed command")
    database = workDirectory / "trials.db"
    run([openfurrow, "init", database], workDirectory)
    addPlaces(openfurrow, database, workDirectory)
    run([openfurrow, "add", database, exampleDirectory / "trial.json", "--place", studyPath], workDirectory)
    run([openfurrow, "import", database, trialCode, exampleDirectory / "observations.csv"], workDirectory)
    wheelVersion = wheels[0].name.split("-")[1]
    for locale in locales:
      reportPath = workDirectory / f"report-{locale}.md"
      run([openfurrow, "report", database, trialCode, "--locale", locale, "--output", reportPath], workDirectory)
      require(
        f"OpenFurrow {wheelVersion}" in reportPath.read_text(encoding="utf-8"),
        f"the {locale} report does not name the installed version {wheelVersion}",
      )
    run([openfurrow, "verify", database, trialCode], workDirectory)

    documentPath = workDirectory / "trial.json"
    copyDatabase = workDirectory / "copy.db"
    run([openfurrow, "export", database, trialCode, "--json", documentPath, "--csv", workDirectory / "observations.csv"], workDirectory)
    run([openfurrow, "init", copyDatabase], workDirectory)
    addPlaces(openfurrow, copyDatabase, workDirectory)
    run([openfurrow, "import-json", copyDatabase, documentPath, "--place", studyPath], workDirectory)
    originalHash = contentHashFrom(run([openfurrow, "info", database, trialCode], workDirectory))
    copyHash = contentHashFrom(run([openfurrow, "info", copyDatabase, trialCode], workDirectory))
    require(originalHash == copyHash, f"the re-imported trial hashes to {copyHash}, the original to {originalHash}")

    step("serving it and reading the pages")
    port = freePort()
    baseURL = f"http://127.0.0.1:{port}"
    service = subprocess.Popen([str(openfurrow), "serve", str(database), "--port", str(port)], cwd=workDirectory)
    try:
      health = waitForService(service, baseURL)
      require(health["locales"] == locales, f"the service offers locales {health['locales']}, the source tree has {locales}")
      require(trialCode in fetch(f"{baseURL}/"), f"the trial list does not show {trialCode}")
      fetch(f"{baseURL}/static/openfurrow.css")
      require(originalHash in fetch(f"{baseURL}/trials/{trialCode}/report"), "the report page does not show the content hash")
    finally:
      service.terminate()
      service.wait(timeout=serviceStopTimeoutSeconds)
    waitForPortClosed(port)

  print(f"product smoke passed: {wheels[0].name}, {len(locales)} locales, content hash {originalHash}")


if __name__ == "__main__":
  main()
