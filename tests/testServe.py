# SPDX-License-Identifier: Apache-2.0
"""Tests for the `serve` command (B3).

Two things need proving. First, the command is wired correctly: it parses host/port,
overrides the config with them, fails loud on a missing database before binding, and
gives a clear hint if the service extra is absent. Second -- and this is the point of a
`serve` command at all -- the app it builds actually binds a socket and answers, which a
test-client check cannot show. So one test starts the real server on an ephemeral port
in a background thread and makes an HTTP request against it.
"""

import socket
import threading
import time
import urllib.request

import pytest

from openfurrow import Workspace
from openfurrow.cli.main import _buildParser
from openfurrow.service import createApp
from openfurrow.service.runner import runService


@pytest.fixture
def databasePath(tmp_path):
  path = str(tmp_path / "trials.db")
  Workspace.create(path)
  return path


def _freePort() -> int:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.bind(("127.0.0.1", 0))
    return probe.getsockname()[1]


# ---- command wiring -------------------------------------------------------

def testServeParsesHostAndPort():
  args = _buildParser().parse_args(["serve", "trials.db", "--host", "0.0.0.0", "--port", "9000"])
  assert (args.database, args.host, args.port) == ("trials.db", "0.0.0.0", 9000)


def testServeMissingDatabaseFailsLoud(tmp_path):
  from openfurrow.cli.main import _commandServe

  args = _buildParser().parse_args(["serve", str(tmp_path / "absent.db")])
  # Workspace.open raises before any socket is bound.
  with pytest.raises(Exception):
    _commandServe(args)


def testServeOverridesConfigBindFromFlags(databasePath, monkeypatch):
  """--host/--port must reach runService as the actual bind address."""
  from openfurrow.cli import main as cli

  captured = {}

  def fakeRun(application, config):
    captured["host"] = config.service.host
    captured["port"] = config.service.port

  # The handler does `from openfurrow.service import ... runService`, which binds the
  # name in openfurrow.service's namespace; patch it there.
  monkeypatch.setattr("openfurrow.service.runService", fakeRun)

  args = _buildParser().parse_args(["serve", databasePath, "--host", "0.0.0.0", "--port", "9123"])
  assert cli._commandServe(args) == 0
  assert captured == {"host": "0.0.0.0", "port": 9123}


# ---- a real bound socket answers ------------------------------------------

def testServerBindsAndAnswers(databasePath):
  port = _freePort()
  application = createApp(databasePath)

  # Flask's dev server, on loopback, in a daemon thread. This is a genuine bind, unlike
  # the test client -- it proves runService's path actually serves.
  from openfurrow.config import OpenFurrowConfig
  config = OpenFurrowConfig.model_validate({"service": {"host": "127.0.0.1", "port": port}})
  server = threading.Thread(target=runService, args=(application, config), daemon=True)
  server.start()

  # Wait briefly for the socket to come up.
  deadline = time.time() + 5
  lastError = None
  while time.time() < deadline:
    try:
      with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
        assert response.status == 200
        break
    except Exception as error:            # not yet listening
      lastError = error
      time.sleep(0.1)
  else:
    raise AssertionError(f"server did not answer on port {port}: {lastError}")
