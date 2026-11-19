# SPDX-License-Identifier: Apache-2.0
"""Trusted workloads (decision 0042): the rules, the roles given to them, and platform tokens presented to the API,
signed by the stand-in issuer and, in the workflow's providers job, by GitHub Actions itself."""

import base64
import copy
import hashlib
import json
import os
import re

import pytest
from carnelian.workload import WorkloadIdentity, githubActions
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from openfurrow import TrialPackage, Workspace
from openfurrow.cli.main import main
from openfurrow.identity import ActorKind, IdentityError, Permission, RoleAssignment
from openfurrow.identity.workloads import (Verifiers, WorkloadTokenRefused, discoveryRetrySeconds, gitlab, isWorkloadToken,
                                           runOf)
from openfurrow.service import createApp
from openfurrow.store.database import AccountRow, RoleAssignmentRow, createDatabase
from openfurrow.workspace import NotPermitted

from storeHelpers import standardPath, standardStudy

password = "correct horse battery"
audience = "https://openfurrow.example.org"
githubAudience = "openfurrow-ci"
otherPath = "station/trials/other"
repositoryID = "734251980"
job = {"sub": "repo:station/weather:ref:refs/heads/main", "repository_id": repositoryID, "repository": "station/weather",
       "ref": "refs/heads/main", "run_id": "77"}
matchesNoRule = "the token is its issuer's, but its claims match no workload trusted here"
issuerNotTrusted = "the token's issuer is not one whose workloads are trusted here"


@pytest.fixture
def location(newStore, validPackageDict):
  location = newStore("w")
  operator = Workspace.create(location)
  standardStudy(operator)
  operator.addPlace("station/trials", "other", "Other")
  operator.addPackage(TrialPackage.model_validate(validPackageDict), standardPath)
  elsewhere = copy.deepcopy(validPackageDict)
  elsewhere["trial"]["trialCode"] = "ESV-2025-02"
  operator.addPackage(TrialPackage.model_validate(elsewhere), otherPath)
  operator.createAccount("admin", "Administrator", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  operator.setSetting("server", "identity.signInMode", "accounts")
  operator.setSetting("server", "identity.workloadAudience", audience)
  return location


@pytest.fixture
def client(location):
  return createApp(location).test_client()


def trust(location, standIn, name="nightly", claims=None, roles=(("analyst", f"place:{standardPath}"),), realm="ci"):
  """A rule for the stand-in's jobs, holding `roles`; the operator's workspace."""
  operator = Workspace.open(location)
  operator.addWorkloadRule(name, standIn.issuer(realm), claims or {"repository_id": repositoryID},
                           str(standIn.certificateAuthority))
  for roleCode, scope in roles:
    operator.assignRole(RoleAssignment(roleCode=roleCode, scope=scope, ruleName=name))
  return operator


def bearer(token):
  return {"Authorization": f"Bearer {token}"}


def errorOf(response):
  return response.get_json()["error"]


def trialCodes(response):
  return [trial["trialCode"] for trial in response.get_json()]


def yields(location):
  plots = Workspace.open(location).layoutFor("ESV-2025-01").plots
  lines = ["plotNumber,assessmentCode,value"] + [f"{plot.plotNumber},YIELD,{5000 + plot.plotNumber}" for plot in plots]
  return "\n".join(lines).encode("ascii")


def claimsOf(token):
  payload = token.split(".")[1]
  return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def changedAfterSigning(token):
  header, _, signature = token.split(".")
  claims = claimsOf(token)
  claims["ref"] = "refs/heads/another"
  changed = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).rstrip(b"=").decode("ascii")
  return f"{header}.{changed}.{signature}"


def without(claims, name):
  return {key: value for key, value in claims.items() if key != name}


# ---- a token accepted ---------------------------------------------------------

def testAnAcceptedTokenActsWithItsRulesRolesAtTheirScopesAndNowhereElse(location, standIn, client):
  operator = trust(location, standIn)
  token = standIn.workloadToken("ci", audience, job)
  listed = client.get("/api/trials", headers=bearer(token))
  assert listed.status_code == 200 and trialCodes(listed) == ["ESV-2025-01"]
  imported = client.post("/api/trials/ESV-2025-01/observations", data=yields(location), headers=bearer(token))
  assert imported.status_code == 201 and imported.get_json()["imported"] == 12
  refused = client.delete("/api/trials/ESV-2025-01", headers=bearer(token))
  assert refused.status_code == 403 and errorOf(refused) == "nightly may not manageTrials at trial:ESV-2025-01"
  hidden = client.get("/api/trials/ESV-2025-02", headers=bearer(token))
  assert hidden.status_code == 404 and errorOf(hidden) == "trial 'ESV-2025-02' not found"
  workload = operator.actingAs(operator.actorForWorkloadToken(token, "api"))
  assert workload.permissionsAt("trial:ESV-2025-01") == frozenset({Permission.view, Permission.enterValues,
                                                                   Permission.importValues})
  assert workload.permissionsAt(f"place:{otherPath}") == frozenset() and workload.permissionsAt("server") == frozenset()
  assert [place.path for place in workload.places()] == ["station", "station/trials", standardPath]
  with pytest.raises(NotPermitted, match="^nightly may not manageAccess at server$"):
    workload.addWorkloadRule("another", standIn.issuer("ci"), {"repository_id": "605918342"})


def testAnIssuerNamedWithASlashAtItsEndIsThatExactIssuer(location, standIn, client):
  operator = trust(location, standIn, realm="slashed")
  assert operator.workloadRule("nightly")[0].issuer == standIn.issuer("slashed") and standIn.issuer("slashed").endswith("/slashed/")
  token = standIn.workloadToken("slashed", audience, job)
  assert claimsOf(token)["iss"] == standIn.issuer("slashed")
  listed = client.get("/api/trials", headers=bearer(token))
  assert listed.status_code == 200 and trialCodes(listed) == ["ESV-2025-01"]
  assert standIn.fetched[0] == "/slashed/.well-known/openid-configuration"
  elsewhere = client.get("/api/trials", headers=bearer(standIn.workloadToken("ci", audience, job)))
  assert elsewhere.status_code == 401 and errorOf(elsewhere) == issuerNotTrusted


def testAWorkloadHasNoAccountNoAPITokenAndNoWebSignIn(location, standIn, client):
  operator = trust(location, standIn, roles=(("administrator", "server"),))
  token = standIn.workloadToken("ci", audience, job)
  workload = operator.actingAs(operator.actorForWorkloadToken(token, "api"))
  assert workload.actor.kind is ActorKind.workload and workload.actor.label == "nightly" and workload.account() is None
  with pytest.raises(IdentityError, match="an API token belongs to an account"):
    workload.issueAPIToken("script", 1)
  with pytest.raises(IdentityError, match="^the token is not valid$"):
    operator.actorForSession(token, "web")
  page = client.get("/trials/ESV-2025-01", headers=bearer(token))
  assert page.status_code == 302 and page.headers["Location"] == "/signin?next=/trials/ESV-2025-01"
  client.set_cookie("openfurrowSession", token)
  assert client.get("/trials/ESV-2025-01").status_code == 302


def testAnAPITokenStillWorksBesideAWorkloadRule(location, standIn, client):
  operator = trust(location, standIn)
  operator.createAccount("viewer", "Viewer", None, password)
  operator.assignRole(RoleAssignment(roleCode="viewer", scope="server", userName="viewer"))
  _, session = operator.signIn("viewer", password, "test")
  apiToken = operator.actingAs(operator.actorForSession(session, "test")).issueAPIToken("script", 1)
  assert not isWorkloadToken(apiToken)
  with pytest.raises(WorkloadTokenRefused, match="^a workload token is a JSON Web Token: three base64url parts$"):
    operator.actorForWorkloadToken(apiToken, "api")
  assert trialCodes(client.get("/api/trials", headers=bearer(apiToken))) == ["ESV-2025-01", "ESV-2025-02"]
  assert trialCodes(client.get("/api/trials", headers=bearer(standIn.workloadToken("ci", audience, job)))) == ["ESV-2025-01"]
  for neither in ("nonsense", "caf\xe9", "two.parts"):
    unknown = client.get("/api/trials", headers=bearer(neither))
    assert unknown.status_code == 401 and errorOf(unknown) == "the token is not valid"


@pytest.mark.parametrize("token, isOne", [
  ("eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJ4In0.c2lnbmF0dXJl", True),
  ("a-_.b.c", True),
  ("a.b", False),
  ("a.b.c.d", False),
  ("a.b.", False),
  ("a.b.c=", False),
  ("a.b.c\n", False),
  ("3q2-7wABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhs", False),
])
def testOnlyThreeBase64urlPartsAreAWorkloadToken(token, isOne):
  assert isWorkloadToken(token) is isOne


def testARulesVerifierIsKeptSoItsIssuerIsAskedOnce(location, standIn, client):
  trust(location, standIn)
  for _ in range(3):
    assert client.get("/api/trials", headers=bearer(standIn.workloadToken("ci", audience, job))).status_code == 200
  another = createApp(location).test_client()
  assert another.get("/api/trials", headers=bearer(standIn.workloadToken("ci", audience, job))).status_code == 200
  assert standIn.fetched == ["/ci/.well-known/openid-configuration", "/ci/jwks"]


# ---- a token refused ----------------------------------------------------------

@pytest.mark.parametrize("presented, why", [
  (lambda standIn: standIn.workloadToken("ci", "https://elsewhere.example.org", job),
   re.escape(f"the token is not for audience '{audience}'")),
  (lambda standIn: standIn.workloadToken("ci", audience, without(job, "repository_id")), re.escape(matchesNoRule)),
  (lambda standIn: standIn.workloadToken("ci", audience, job | {"repository_id": "605918342"}), re.escape(matchesNoRule)),
  (lambda standIn: standIn.workloadToken("ci", audience, job, age=900), "the token has expired"),
  (lambda standIn: standIn.workloadToken("ci", audience, job, validIn=600), re.escape("the token is not valid yet ('nbf')")),
  (lambda standIn: standIn.workloadToken("ci", audience, job, age=-600), "the token is issued in the future"),
  (lambda standIn: standIn.workloadToken("elsewhere", audience, job), re.escape(issuerNotTrusted)),
  (lambda standIn: changedAfterSigning(standIn.workloadToken("ci", audience, job)),
   "the token is refused: the JWS signature does not verify.*"),
  (lambda standIn: standIn.workloadToken("ci", audience, without(job, "sub")), "the token names no subject"),
  (lambda standIn: "bm90IEpTT04.bm90IEpTT04.c2lnbmF0dXJl", "the token is refused: the token's claims is not JSON.*"),
], ids=["wrongAudience", "missingClaim", "differentClaim", "expired", "notYetValid", "issuedInTheFuture", "unknownIssuer",
        "changedAfterSigning", "noSubject", "notAToken"])
def testATokenNoRuleAcceptsIsRefusedWithWhatIsWrongWithItAndNothingOfTheRules(location, standIn, client, presented, why):
  operator = trust(location, standIn, roles=(("administrator", "server"),))
  refused = client.delete("/api/trials/ESV-2025-01", headers=bearer(presented(standIn)))
  assert refused.status_code == 401 and refused.headers["WWW-Authenticate"] == "Bearer"
  assert re.fullmatch(why, errorOf(refused), re.DOTALL), errorOf(refused)
  assert repositoryID not in errorOf(refused) and "nightly" not in errorOf(refused)
  assert [code for code, _ in operator.listTrials()] == ["ESV-2025-01", "ESV-2025-02"]
  assert "workload" not in {event.actorKind for event in operator.auditEvents()}


def testATokenTwoRulesAcceptIsRefusedAsAmbiguous(location, standIn, client):
  trust(location, standIn, "nightly")
  trust(location, standIn, "weather", {"repository_id": repositoryID, "ref": "refs/heads/main"})
  refused = client.get("/api/trials", headers=bearer(standIn.workloadToken("ci", audience, job)))
  assert refused.status_code == 401
  assert errorOf(refused) == ("the token is ambiguous: the workload rules 'nightly', 'weather' all accept it, and a "
                              "token must match exactly one")
  branch = standIn.workloadToken("ci", audience, job | {"ref": "refs/heads/trial"})
  assert client.get("/api/trials", headers=bearer(branch)).status_code == 200


def testADisabledRuleAcceptsNoTokenAndHoldsNothing(location, standIn, client):
  operator = trust(location, standIn)
  token = standIn.workloadToken("ci", audience, job)
  workload = operator.actingAs(operator.actorForWorkloadToken(token, "api"))
  assert [code for code, _ in workload.listTrials()] == ["ESV-2025-01"]
  operator.setWorkloadRuleEnabled("nightly", False)
  refused = client.get("/api/trials", headers=bearer(token))
  assert refused.status_code == 401 and errorOf(refused) == issuerNotTrusted
  assert workload.permissionsAt("trial:ESV-2025-01") == frozenset()
  assert workload.listTrials() == [] and workload.places() == []
  operator.setWorkloadRuleEnabled("nightly", True)
  assert trialCodes(client.get("/api/trials", headers=bearer(token))) == ["ESV-2025-01"]


def testRemovingARuleTakesItsRolesWithIt(location, standIn, client):
  operator = trust(location, standIn, roles=(("analyst", f"place:{standardPath}"), ("viewer", "server")))
  token = standIn.workloadToken("ci", audience, job)
  workload = operator.actingAs(operator.actorForWorkloadToken(token, "api"))
  operator.removeWorkloadRule("nightly")
  assert operator.workloadRules() == []
  assert operator.assignments() == [RoleAssignment(roleCode="administrator", scope="server", userName="admin")]
  assert operator.auditEvents()[0].detail == {"rule": "nightly", "roles": [
    {"roleCode": "analyst", "scope": f"place:{standardPath}"}, {"roleCode": "viewer", "scope": "server"}]}
  refused = client.get("/api/trials", headers=bearer(token))
  assert refused.status_code == 401 and errorOf(refused) == issuerNotTrusted
  assert workload.permissionsAt("server") == frozenset()
  with pytest.raises(IdentityError, match="^no workload rule 'nightly'$"):
    operator.removeWorkloadRule("nightly")
  trust(location, standIn, roles=())
  again = client.get("/api/trials", headers=bearer(token))
  assert again.status_code == 200 and again.get_json() == []


def testWithoutTheAudienceSettingNoRuleIsAddedAndNoTokenAccepted(location, standIn, client):
  operator = trust(location, standIn)
  operator.clearSetting("server", "identity.workloadAudience")
  with pytest.raises(IdentityError, match="set the server setting identity.workloadAudience before adding a workload rule"):
    operator.addWorkloadRule("another", standIn.issuer("ci"), {"repository_id": "605918342"})
  assert [rule.name for rule in operator.workloadRules()] == ["nightly"]
  refused = client.get("/api/trials", headers=bearer(standIn.workloadToken("ci", audience, job)))
  assert refused.status_code == 401
  assert errorOf(refused) == "workload tokens are not accepted here: the server setting identity.workloadAudience is not set"
  assert standIn.fetched == []


def testAnIssuerThatCannotBeUsedRefusesItsWorkloadsByName(location, standIn, client, tmp_path):
  trust(location, standIn, realm="misnamed")
  refused = client.get("/api/trials", headers=bearer(standIn.workloadToken("misnamed", audience, job)))
  assert refused.status_code == 401
  assert errorOf(refused) == (f"the issuer {standIn.issuer('misnamed')} cannot be used: the discovery document names "
                              f"issuer '{standIn.issuer('another')}', not '{standIn.issuer('misnamed')}'")
  Workspace.open(location).addWorkloadRule("private", standIn.issuer("ci"), {"repository_id": repositoryID},
                                           str(tmp_path / "absent.pem"))
  unread = client.get("/api/trials", headers=bearer(standIn.workloadToken("ci", audience, job)))
  assert unread.status_code == 401
  assert errorOf(unread) == (f"the issuer {standIn.issuer('ci')} cannot be used: the certificate authority file of its "
                             "workload rule cannot be read (FileNotFoundError)")


class Clock:
  def __init__(self):
    self.now = 1000.0

  def __call__(self):
    return self.now


def testAnIssuerThatCannotBeUsedIsAskedAgainOnlyAfterAWhile(standIn):
  clock = Clock()
  verifiers = Verifiers(clock)
  discovery = "/misnamed/.well-known/openid-configuration"

  def refusal():
    with pytest.raises(WorkloadTokenRefused) as refused:
      verifiers.get(standIn.issuer("misnamed"), str(standIn.certificateAuthority), audience, {"repository_id": repositoryID})
    return str(refused.value)

  first = refusal()
  assert first.endswith(f"not '{standIn.issuer('misnamed')}'") and standIn.fetched == [discovery]
  clock.now += discoveryRetrySeconds - 1
  assert refusal() == f"{first}; it is asked again in 1 seconds" and standIn.fetched == [discovery]
  clock.now += 1
  assert refusal() == first and standIn.fetched == [discovery, discovery]


def testAVerifierIsMadeOnceForEachRuleAndAudience(standIn):
  verifiers = Verifiers()
  issuer, authority = standIn.issuer("ci"), str(standIn.certificateAuthority)
  first = verifiers.get(issuer, authority, audience, {"repository_id": repositoryID, "ref": "refs/heads/main"})
  assert verifiers.get(issuer, authority, audience, {"ref": "refs/heads/main", "repository_id": repositoryID}) is first
  assert verifiers.get(issuer, authority, audience, {"repository_id": repositoryID}) is not first
  assert verifiers.get(issuer, authority, "another-audience", first.requiredClaims) is not first
  assert (first.audience, first.requiredClaims) == (audience, {"repository_id": repositoryID, "ref": "refs/heads/main"})
  assert standIn.fetched == ["/ci/.well-known/openid-configuration"]


# ---- rules and their roles ------------------------------------------------------

@pytest.mark.parametrize("name, issuer, claims, why", [
  ("nightly", "http://ci.example.org", {"repository_id": "7"}, "'http://ci.example.org' is not an issuer"),
  ("nightly", "https://ci.example.org/#top", {"repository_id": "7"}, "is not an issuer"),
  ("nightly", "https://ci.example.org?realm=x", {"repository_id": "7"}, "is not an issuer"),
  ("Nightly", "https://ci.example.org", {"repository_id": "7"}, "'Nightly' is not a workload rule name"),
  ("nightly", "https://ci.example.org", {}, "a rule requires at least one claim"),
  ("nightly", "https://ci.example.org", {"repository_id": 7}, "the claim 'repository_id' cannot require 7"),
  ("nightly", "https://ci.example.org", {"environment": ""}, "the claim 'environment' cannot require ''"),
  ("nightly", "https://ci.example.org", {"aud": "elsewhere"}, "'aud' is checked for every token"),
  ("nightly", "githubActions", {"repository": "station/weather"},
   "requires the claim repository_id, the number that stays with its owner: repository is a name, and a name given up "
   "can be registered again by someone else"),
  ("nightly", githubActions, {"repository_owner_id": "7", "ref": "refs/heads/main"}, "requires the claim repository_id"),
  ("nightly", "gitlab", {"project_path": "station/weather"}, "requires the claim project_id"),
])
def testARuleIsCheckedWhenItIsMade(location, name, issuer, claims, why):
  operator = Workspace.open(location)
  with pytest.raises(ValidationError, match=re.escape(why)):
    operator.addWorkloadRule(name, issuer, claims)
  assert operator.workloadRules() == []


def testARuleNamesItsIssuerByNameOrAddress(location):
  operator = Workspace.open(location)
  made = operator.addWorkloadRule("nightly", "githubActions", {"repository_id": "1296269", "ref": "refs/heads/main"})
  assert (made.issuer, made.enabled, made.certificateAuthority) == (githubActions, True, None)
  assert operator.addWorkloadRule("pipeline", "gitlab", {"project_id": "20"}).issuer == gitlab
  station = operator.addWorkloadRule("station", "https://ci.example.org/realms/station", {"job": "weather"})
  assert (station.issuer, station.claims) == ("https://ci.example.org/realms/station", {"job": "weather"})
  with pytest.raises(IdentityError, match="^workload rule 'nightly' already exists$"):
    operator.addWorkloadRule("nightly", "githubActions", {"repository_id": "1296269"})
  assert operator.workloadRules() == [made, operator.workloadRule("pipeline")[0], station]
  added = [event.detail for event in operator.auditEvents() if event.action == "workload.add"]
  assert added[-1] == {"rule": "nightly", "issuer": githubActions, "certificateAuthority": None,
                       "claims": {"repository_id": "1296269", "ref": "refs/heads/main"}}


def testARoleIsGivenToExactlyOneOfAnAccountAGroupOrARule(location, standIn):
  operator = trust(location, standIn, roles=())
  operator.createGroup("Field team")
  for holders in ({"userName": "admin", "ruleName": "nightly"}, {"groupName": "Field team", "ruleName": "nightly"},
                  {"userName": "admin", "groupName": "Field team", "ruleName": "nightly"}, {}):
    with pytest.raises(IdentityError, match="^a role is given to exactly one of an account, a group or a workload rule$"):
      operator.assignRole(RoleAssignment(roleCode="viewer", scope="server", **holders))
  with pytest.raises(IdentityError, match="^no workload rule 'absent'$"):
    operator.assignRole(RoleAssignment(roleCode="viewer", scope="server", ruleName="absent"))
  assert operator.workloadRule("nightly")[1] == []
  given = RoleAssignment(roleCode="viewer", scope=f"place:{standardPath}", ruleName="nightly")
  operator.assignRole(given)
  operator.assignRole(given)
  assert operator.workloadRule("nightly")[1] == [given]
  operator.unassignRole(given)
  assert operator.workloadRule("nightly")[1] == []


def testTheStoreItselfRefusesARoleAssignmentWithTwoHoldersOrNone(location, standIn):
  trust(location, standIn, roles=())
  engine = createDatabase(location, create=False)
  with Session(engine) as session:
    accountID = session.execute(select(AccountRow.accountID)).scalar_one()
  for holders in ({"accountID": accountID, "ruleName": "nightly"}, {}):
    with Session(engine) as session:
      session.add(RoleAssignmentRow(roleCode="viewer", scope="server", **holders))
      # pg8000 reports a failed check as a ProgrammingError, SQLite as an IntegrityError.
      with pytest.raises(DBAPIError, match="roleAssignmentHasOneHolder"):
        session.flush()
  engine.dispose()


# ---- the audit log --------------------------------------------------------------

def testEveryChangeAWorkloadMakesNamesItsRuleAndItsRun(location, standIn, client):
  operator = trust(location, standIn, roles=(("trialManager", f"place:{standardPath}"),))
  token = standIn.workloadToken("ci", audience, job)
  sent = yields(location)
  assert client.post("/api/trials/ESV-2025-01/observations", data=sent, headers=bearer(token)).status_code == 201
  assert client.delete("/api/trials/ESV-2025-01", headers=bearer(token)).status_code == 200
  deleted, imported = operator.auditEvents("trial:ESV-2025-01")[:2]
  assert [(event.action, event.actorKind, event.actorName, event.surface) for event in (deleted, imported)] == [
    ("trial.delete", "workload", "nightly", "api"), ("values.import", "workload", "nightly", "api")]
  run = {"iss": standIn.issuer("ci"), "sub": job["sub"]}
  assert deleted.detail == {"place": standardPath, "receivedFiles": 1, "workloadRun": run}
  assert imported.detail == {"file": None, "sheet": None, "values": 12, "assessments": ["YIELD"], "receivedFile": 1,
                             "sha256": hashlib.sha256(sent).hexdigest(), "workloadRun": run}
  assert all("workloadRun" not in event.detail for event in operator.auditEvents() if event.actorKind != "workload")


def testTheRunIsToldAsItsPlatformTellsIt():
  told = {"iss": githubActions, "sub": "repo:station/weather:ref:refs/heads/main", "repository": "station/weather",
          "ref": "refs/heads/main", "workflow_ref": "station/weather/.github/workflows/nightly.yml@refs/heads/main",
          "run_id": "30433642", "run_attempt": "2", "sha": "example-sha"}
  others = {"aud": audience, "repository_id": "1296269", "actor": "someone", "jti": "example-id", "exp": 1700000300}
  assert runOf(WorkloadIdentity(githubActions, told["sub"], told | others)) == told
  early = without(without(told, "workflow_ref"), "sha")
  assert runOf(WorkloadIdentity(githubActions, told["sub"], early | others)) == early
  pipeline = {"iss": gitlab, "sub": "project_path:station/weather:ref_type:branch:ref:main", "project_path": "station/weather",
              "ref": "main", "pipeline_id": "574", "job_id": "302", "sha": "example-sha"}
  assert runOf(WorkloadIdentity(gitlab, pipeline["sub"], pipeline | {"project_id": "20", "user_login": "someone"})) == pipeline
  elsewhere = {"iss": "https://ci.example.org", "sub": "job:weather"}
  assert runOf(WorkloadIdentity(elsewhere["iss"], elsewhere["sub"], elsewhere | {"repository": "station/weather"})) == elsewhere


# ---- the command line -------------------------------------------------------------

def run(capsys, arguments):
  code = main(arguments)
  captured = capsys.readouterr()
  return code, captured.out, captured.err


def testAnOperatorManagesWorkloadRulesAndTheirRolesFromTheCommandLine(newStore, capsys):
  database = newStore("cli")
  assert run(capsys, ["init", database])[0] == 0
  code, _, error = run(capsys, ["workload", "add", database, "nightly", "githubActions", "repository_id=1296269"])
  assert code == 1 and "set the server setting identity.workloadAudience before adding a workload rule" in error
  assert run(capsys, ["setting", "set", database, "server", "identity.workloadAudience", audience])[0] == 0
  code, _, error = run(capsys, ["workload", "add", database, "nightly", "githubActions", "repository=station/weather"])
  assert code == 1 and "requires the claim repository_id" in error
  code, _, error = run(capsys, ["workload", "add", database, "nightly", "githubActions", "repository_id"])
  assert code == 1 and "'repository_id' is not a required claim: write each claim once, as CLAIM=VALUE" in error
  assert run(capsys, ["workload", "list", database])[1] == "(no workload rules)\n"
  added = run(capsys, ["workload", "add", database, "nightly", "githubActions", "repository_id=1296269", "ref=refs/heads/main"])
  assert added[0] == 0 and added[1].startswith(f"Added workload rule 'nightly' for {githubActions}")
  listed = f"nightly\tenabled\t{githubActions}\tref=refs/heads/main repository_id=1296269\n"
  assert run(capsys, ["workload", "list", database])[1] == listed
  assert run(capsys, ["role", "assign", database, "dataCollector", "server", "--workload", "nightly"])[0] == 0
  assert run(capsys, ["role", "assignments", database])[1] == "dataCollector\tserver\tworkload nightly\n"
  shown = run(capsys, ["workload", "show", database, "nightly"])[1].splitlines()
  assert shown[:4] == ["Workload rule: nightly, enabled", f"Issuer: {githubActions}", "Requires: ref=refs/heads/main",
                       "Requires: repository_id=1296269"]
  assert re.fullmatch(r"Added: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", shown[4]) and shown[5:] == ["Role: dataCollector at server"]
  assert run(capsys, ["workload", "disable", database, "nightly"])[0] == 0
  assert run(capsys, ["workload", "list", database])[1] == listed.replace("enabled", "disabled")
  assert run(capsys, ["workload", "enable", database, "nightly"])[0] == 0
  assert run(capsys, ["role", "unassign", database, "dataCollector", "server", "--workload", "nightly"])[0] == 0
  assert run(capsys, ["workload", "show", database, "nightly"])[1].splitlines()[5:] == ["Roles: none"]
  assert run(capsys, ["role", "assign", database, "viewer", "server", "--workload", "nightly"])[0] == 0
  assert run(capsys, ["workload", "remove", database, "nightly"])[0] == 0
  assert run(capsys, ["workload", "list", database])[1] == "(no workload rules)\n"
  assert run(capsys, ["role", "assignments", database])[1] == ""
  code, _, error = run(capsys, ["workload", "show", database, "nightly"])
  assert code == 1 and "no workload rule 'nightly'" in error
  audit = [line.split("\t") for line in run(capsys, ["audit", database])[1].splitlines()]
  assert [(line[1], line[2], line[3]) for line in audit] == [("operator", "cli", action) for action in (
    "workload.remove", "role.assign", "role.unassign", "workload.enable", "workload.enable", "role.assign",
    "workload.add", "setting.set")]
  assert json.loads(audit[0][5]) == {"rule": "nightly", "roles": [{"roleCode": "viewer", "scope": "server"}]}


# ---- a rule of its own, and another's: the stand-in, then GitHub Actions itself ---------

def presentedThroughTheAPI(location, token, tokenAudience, issuer, certificateAuthority, own, anothers):
  """Presents a token where a rule requiring `own` holds trialManager at the study: it acts there and nowhere else,
  and its change is audited under the rule; then where only a rule requiring `anothers` exists, which refuses it.
  Returns the run its audit event carries."""
  operator = Workspace.open(location)
  operator.setSetting("server", "identity.workloadAudience", tokenAudience)
  operator.addWorkloadRule("this-repository", issuer, own, certificateAuthority)
  operator.assignRole(RoleAssignment(roleCode="trialManager", scope=f"place:{standardPath}", ruleName="this-repository"))
  client = createApp(location).test_client()
  listed = client.get("/api/trials", headers=bearer(token))
  assert listed.status_code == 200, listed.get_data(as_text=True)
  assert trialCodes(listed) == ["ESV-2025-01"]
  assert client.get("/api/trials/ESV-2025-02", headers=bearer(token)).status_code == 404
  assert client.delete("/api/trials/ESV-2025-01", headers=bearer(token)).status_code == 200
  event = operator.auditEvents()[0]
  assert (event.action, event.actorKind, event.actorName) == ("trial.delete", "workload", "this-repository")
  operator.removeWorkloadRule("this-repository")
  operator.addWorkloadRule("another-repository", issuer, anothers, certificateAuthority)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", ruleName="another-repository"))
  refused = client.get("/api/trials", headers=bearer(token))
  assert refused.status_code == 401 and errorOf(refused) == matchesNoRule
  return event.detail["workloadRun"]


def testATokenActsWithTheRoleOfItsOwnRuleAndIsRefusedByAnothers(location, standIn):
  told = presentedThroughTheAPI(location, standIn.workloadToken("ci", githubAudience, job), githubAudience,
                                standIn.issuer("ci"), str(standIn.certificateAuthority), {"repository_id": repositoryID},
                                {"repository_id": str(int(repositoryID) + 1)})
  assert told == {"iss": standIn.issuer("ci"), "sub": job["sub"]}


def testARealGitHubActionsTokenActsWithTheRoleOfItsOwnRuleAndIsRefusedByAnothers(location):
  token = os.environ.get("OPENFURROW_GITHUB_TOKEN")
  if not token:
    pytest.skip("needs a GitHub Actions run that asked for an OIDC token (the workflow's providers job does)")
  thisRepositoryID = os.environ["GITHUB_REPOSITORY_ID"]
  told = presentedThroughTheAPI(location, token, githubAudience, "githubActions", None, {"repository_id": thisRepositoryID},
                                {"repository_id": str(int(thisRepositoryID) + 1)})
  claims = claimsOf(token)
  assert told == {name: claims[name] for name in ("iss", "sub", "repository", "ref", "workflow_ref", "run_id",
                                                  "run_attempt", "sha") if name in claims}
  assert (told["iss"], told["repository"], told["run_id"], told["run_attempt"]) == (
    githubActions, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"])
  assert told["sub"].startswith("repo:") and "ref" in told
