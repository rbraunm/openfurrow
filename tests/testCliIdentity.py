# SPDX-License-Identifier: Apache-2.0
"""Accounts, roles and the audit log from the command line (decisions 0036 to 0038)."""

import io

from openfurrow.cli.main import main


def run(capsys, monkeypatch, arguments, standardInput=""):
  monkeypatch.setattr("sys.stdin", io.StringIO(standardInput))
  code = main(arguments)
  captured = capsys.readouterr()
  return code, captured.out, captured.err


def testAnOperatorSetsUpAccountsRolesAndSignInAndTheAuditSaysSo(newStore, capsys, monkeypatch):
  database = newStore("cli")
  assert run(capsys, monkeypatch, ["init", database])[0] == 0
  assert run(capsys, monkeypatch, ["account", "add", database, "Ana", "Ana A."], "correct horse battery\n")[0] == 0
  code, _, error = run(capsys, monkeypatch, ["setting", "set", database, "server", "identity.signInMode", "accounts"])
  assert code == 1 and "needs an active account that is administrator at the server first" in error
  assert run(capsys, monkeypatch, ["role", "assign", database, "administrator", "server", "--user", "ana"])[0] == 0
  assert run(capsys, monkeypatch, ["setting", "set", database, "server", "identity.signInMode", "accounts"])[0] == 0
  assert run(capsys, monkeypatch, ["role", "assignments", database])[1] == "administrator\tserver\tuser ana\n"
  code, _, error = run(capsys, monkeypatch, ["account", "add", database, "ben", "Ben"], "short\n")
  assert code == 1 and "a password is 12 to 256 characters, got 5" in error
  code, output, _ = run(capsys, monkeypatch, ["audit", database, "--limit", "3"])
  lines = [line.split("\t") for line in output.splitlines()]
  assert [(line[1], line[2], line[3]) for line in lines] == [
    ("operator", "cli", "setting.set"), ("operator", "cli", "role.assign"), ("operator", "cli", "account.create"),
  ]
  assert '"after": {"source": "server", "value": "accounts"}' in lines[0][5]
