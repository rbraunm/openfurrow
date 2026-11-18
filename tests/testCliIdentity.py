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


def testAnOperatorConfiguresProviders(newStore, capsys, monkeypatch, tmp_path):
  database = newStore("cli")
  run(capsys, monkeypatch, ["init", database])
  settings = tmp_path / "entra.json"
  settings.write_text('{"baseURL": "https://openfurrow.example.org/scim/entra/v2", "groups": "mirror"}', encoding="utf-8")
  assert run(capsys, monkeypatch, ["provider", "add", database, "entra", "scim", str(settings)])[0] == 0
  bad = tmp_path / "bad.json"
  bad.write_text('{"issuer": "http://idp.example.org"}', encoding="utf-8")
  code, _, error = run(capsys, monkeypatch, ["provider", "add", database, "idp", "openIDConnect", str(bad)])
  assert code == 1 and "must be an https address" in error
  code, token, _ = run(capsys, monkeypatch, ["provider", "token", database, "entra"])
  assert code == 0 and len(token.strip()) == 43
  assert run(capsys, monkeypatch, ["provider", "disable", database, "entra"])[0] == 0
  assert run(capsys, monkeypatch, ["provider", "list", database])[1] == "entra\tscim\tdisabled\n"
  run(capsys, monkeypatch, ["account", "add", database, "ana", "Ana", "--no-password"])
  code, _, error = run(capsys, monkeypatch, ["provider", "link", database, "entra", "subject-1", "nobody"])
  assert code == 1 and "no account 'nobody'" in error
  assert run(capsys, monkeypatch, ["provider", "link", database, "entra", "subject-1", "ana"])[0] == 0
