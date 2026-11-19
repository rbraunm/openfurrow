# SPDX-License-Identifier: Apache-2.0
"""Retention (decision 0044): what each storage area holds, the three forms of a rule, closing and holding a trial,
a preview that is exactly what pruning removes, the rights and the audit of it all, and the store's own daily task."""

import copy
import datetime
import hashlib
import json
import threading
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from openfurrow import TrialPackage, Workspace, defaultConfig
from openfurrow.cli.main import main
from openfurrow.identity import Actor, ActorKind, IdentityError, Permission, RoleAssignment, RoleDefinition
from openfurrow.identity.providers import Provider
from openfurrow.retention import (
  Period,
  PeriodUnit,
  PruneLine,
  RetentionError,
  RetentionPolicy,
  RetentionRule,
  StorageArea,
  retentionTaskName,
)
from openfurrow.service import createApp
from openfurrow.settings import SettingError
from openfurrow.store import NotFoundError
from openfurrow.store.database import AuthTokenRow, PendingSignInRow, createDatabase
from openfurrow.store.providers import claimOnce
from openfurrow.tasks.model import RunState
from openfurrow.tasks.scheduler import Scheduler
from openfurrow.workspace import NotPermitted

from storeHelpers import standardPath, standardStudy

password = "correct horse battery"
origin = {"Origin": "http://localhost"}
start = datetime.datetime(2026, 1, 10, 12, 0, tzinfo=datetime.UTC)
otherPath = "station/trials/other"
days = datetime.timedelta


class Clock:
  def __init__(self, moment):
    self.moment = moment

  def __call__(self):
    return self.moment


@pytest.fixture
def clock():
  return Clock(start)


def populated(location, validPackageDict, clock):
  """A store with TRIAL-A in the standard study and TRIAL-B in the study beside it."""
  operator = Workspace.create(location, clock=clock)
  standardStudy(operator)
  operator.addPlace("station/trials", "other", "Other study")
  for code, place in (("TRIAL-A", standardPath), ("TRIAL-B", otherPath)):
    package = copy.deepcopy(validPackageDict)
    package["trial"]["trialCode"] = code
    operator.addPackage(TrialPackage.model_validate(package), place)
  return operator


@pytest.fixture
def location(newStore):
  return newStore("retention")


@pytest.fixture
def store(location, validPackageDict, clock):
  return populated(location, validPackageDict, clock)


def fileOf(workspace, trialCode, assessment="YIELD"):
  value = "low" if assessment == "SEV" else "5000.5"
  plots = sorted(plot.plotNumber for plot in workspace.layoutFor(trialCode).plots)
  return ("plotNumber,assessmentCode,value\n" + "".join(f"{plot},{assessment},{value}\n" for plot in plots)).encode()


def imported(workspace, trialCode, assessment="YIELD"):
  """Import one assessment's file into a trial; its bytes."""
  data = fileOf(workspace, trialCode, assessment)
  workspace.importObservationFile(trialCode, f"{assessment.lower()}.csv", data, defaultConfig().importProfile)
  return data


def sha256(content):
  return hashlib.sha256(content).hexdigest()


def exportedBytes(workspace, trialCode, folder):
  """The bytes of a trial's canonical document, worked out from its JSON export alone."""
  path = Path(folder) / f"{trialCode}.json"
  workspace.exportDocument(trialCode, str(path))
  return len(json.dumps(json.loads(path.read_text(encoding="utf-8")), sort_keys=True, separators=(",", ":")).encode("utf-8"))


def eventBytes(event):
  texts = (event.actorKind, event.actorName or "", event.surface, event.action, event.scope,
           json.dumps(event.detail, sort_keys=True, default=str))
  return sum(len(text.encode("utf-8")) for text in texts)


def areas(workspace):
  return {area.area: (area.count, area.sizeBytes) for area in workspace.retentionStatus().areas}


def rules(workspace, scope):
  return {setting.key: (setting.value, setting.source) for setting in workspace.effectiveSettings(scope)
          if setting.key.startswith("retention.")}


def eventsAt(workspace, scope):
  return [event for event in workspace.auditEvents(limit=10000) if event.scope == scope]


def fileLine(trialCode, data, fileID, importedAt, rule, source, name="yield.csv", **detail):
  return PruneLine(area=StorageArea.receivedFiles, scope=f"trial:{trialCode}", count=1, sizeBytes=len(data), rule=rule,
                   source=source, detail=detail | {"files": [{
                     "fileID": fileID, "kind": "observations", "fileName": name, "sha256": sha256(data),
                     "sizeBytes": len(data), "importedAt": importedAt}]})


# ---- rules -------------------------------------------------------------------------

@pytest.mark.parametrize("text, policy, period", [
  ("keep", RetentionPolicy.keep, None),
  ("keepFor:P90D", RetentionPolicy.keepFor, Period(90, PeriodUnit.days)),
  ("keepFor:P18M", RetentionPolicy.keepFor, Period(18, PeriodUnit.months)),
  ("keepUntilClosed:P5Y", RetentionPolicy.keepUntilClosed, Period(5, PeriodUnit.years)),
])
def testARuleIsReadAndWrittenTheSame(text, policy, period):
  rule = RetentionRule.read(text)
  assert (rule.policy, rule.period, rule.text) == (policy, period, text)


@pytest.mark.parametrize("text, why", [
  ("forever", "is not a retention rule: keep, keepFor:<period> or keepUntilClosed:<period>"),
  ("keep:P1D", "keep takes no period"),
  ("keepFor", "keepFor needs its period, such as keepFor:P5Y"),
  ("keepFor:90", "'90' is not a period"),
  ("keepFor:P0D", "'P0D' is not a period"),
  ("keepFor:P2W", "'P2W' is not a period"),
  ("keepUntilClosed:P101Y", "'P101Y' is longer than a hundred years"),
])
def testWhatIsNotARuleIsRefused(text, why):
  with pytest.raises(RetentionError, match=why):
    RetentionRule.read(text)


def testAPeriodCountsBackKeepingTheDayOfTheMonth():
  assert Period.read("P90D").before(datetime.date(2026, 3, 31)) == datetime.date(2025, 12, 31)
  assert Period.read("P1M").before(datetime.date(2026, 3, 31)) == datetime.date(2026, 2, 28)
  assert Period.read("P1Y").before(datetime.date(2028, 2, 29)) == datetime.date(2027, 2, 28)
  assert Period.read("P4Y").before(datetime.date(2028, 2, 29)) == datetime.date(2024, 2, 29)
  moment = datetime.datetime(2026, 1, 15, 8, 30, tzinfo=datetime.UTC)
  assert Period.read("P18M").before(moment) == datetime.datetime(2024, 7, 15, 8, 30, tzinfo=datetime.UTC)


def testEveryAreaIsKeptUntilARuleIsSet(store):
  expected = {f"retention.{area.value}": ("keep", "default") for area in StorageArea}
  assert rules(store, "server") == rules(store, "trial:TRIAL-A") == expected


@pytest.mark.parametrize("scope, area, text, why", [
  ("server", "trialRecords", "keepFor:P1Y", "trialRecords is not kept by keepFor; it takes keep, keepUntilClosed"),
  ("server", "taskRuns", "keepUntilClosed:P1Y", "taskRuns is not kept by keepUntilClosed; it takes keep, keepFor"),
  ("server", "sessionsAndTokens", "keepUntilClosed:P1Y", "sessionsAndTokens is not kept by keepUntilClosed"),
  ("server", "auditLog", "P1Y", "'P1Y' is not a retention rule"),
  ("trial:TRIAL-A", "taskRuns", "keepFor:P1Y", "'retention.taskRuns' is not set at the trial level"),
  ("place:station", "sessionsAndTokens", "keepFor:P1Y", "'retention.sessionsAndTokens' is not set at the place level"),
])
def testAnAreaTakesOnlyTheRulesAndScopesThatFitIt(store, scope, area, text, why):
  with pytest.raises(SettingError, match=why):
    store.setSetting(scope, f"retention.{area}", text)
  assert rules(store, "trial:TRIAL-A")[f"retention.{area}"] == ("keep", "default")


def testTheNearestRuleAppliesAndSaysWhereItWasSet(store):
  store.setSetting("server", "retention.receivedFiles", " keepFor:P1Y ")
  store.setSetting("place:station/trials", "retention.receivedFiles", "keepUntilClosed:P5Y")
  store.setSetting("trial:TRIAL-A", "retention.receivedFiles", "keep")
  assert rules(store, "server")["retention.receivedFiles"] == ("keepFor:P1Y", "server")
  assert rules(store, "trial:TRIAL-B")["retention.receivedFiles"] == ("keepUntilClosed:P5Y", "place:station/trials")
  assert rules(store, "trial:TRIAL-A")["retention.receivedFiles"] == ("keep", "trial:TRIAL-A")
  [files] = [area for area in store.retentionStatus().areas if area.area is StorageArea.receivedFiles]
  assert (files.rule, files.source) == ("keepFor:P1Y", "server")
  assert [(below.scope, below.rule) for below in files.setBelow] == [
    ("place:station/trials", "keepUntilClosed:P5Y"), ("trial:TRIAL-A", "keep")]


# ---- what each area holds ------------------------------------------------------------

def testEachAreaIsCountedAndWeighedByItsContent(location, validPackageDict, standIn, monkeypatch, tmp_path, capsys):
  operator = populated(location, validPackageDict, Clock(datetime.datetime.now(datetime.UTC)))
  assert areas(operator)[StorageArea.receivedFiles] == areas(operator)[StorageArea.sessionsAndTokens] == (0, 0)
  assert areas(operator)[StorageArea.taskRuns] == (0, 0)

  files = [imported(operator, "TRIAL-A"), imported(operator, "TRIAL-B", "SEV")]
  account = operator.createAccount("jos\u00e9", "Jos\u00e9", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="jos\u00e9"))
  acting = operator.actingAs(Actor(kind=ActorKind.account, accountID=account.accountID, userName=account.userName,
                                   surface="web"))
  acting.addPlace("station", "campo", "Campo")
  operator.signIn("jos\u00e9", password, "web")
  acting.issueAPIToken("cl\u00e9", None)
  monkeypatch.setenv("OPENFURROW_TEST_SECRET", "stand-in secret")
  operator.addProvider(Provider.of("standin", "openIDConnect", {
    "issuer": standIn.issuer("lab"), "clientID": "openfurrow", "clientSecretVariable": "OPENFURROW_TEST_SECRET",
    "returnURL": "https://openfurrow.example.org/signin/with/standin/return",
    "certificateAuthority": str(standIn.certificateAuthority)}))
  operator.beginProviderSignIn("standin", "/")
  engine = createDatabase(location, create=False)
  with Session(engine) as session:
    [pendingState] = session.execute(select(PendingSignInRow.stateJSON)).scalars().all()
  moment = datetime.datetime.now(datetime.UTC).timestamp()
  assert claimOnce(engine, "sc\u00e8ne", "used", moment + 60, moment)
  operator.runTaskNow(retentionTaskName)

  events = operator.auditEvents(limit=10000)
  assert "jos\u00e9" in {event.actorName for event in events}
  assert areas(operator) == {
    StorageArea.trialRecords: (2, sum(exportedBytes(operator, code, tmp_path) for code in ("TRIAL-A", "TRIAL-B"))),
    StorageArea.receivedFiles: (2, len(files[0]) + len(files[1])),
    StorageArea.auditLog: (len(events), sum(eventBytes(event) for event in events)),
    StorageArea.sessionsAndTokens: (4, (64 + len("session")) + (64 + len("api") + len("cl\u00e9".encode("utf-8")))
                                    + (64 + len("standin") + len(pendingState.encode("utf-8")))
                                    + (len("sc\u00e8ne".encode("utf-8")) + len("used"))),
    StorageArea.taskRuns: (1, len(retentionTaskName) + len("operator")),
  }

  assert main(["retention", "status", location]) == 0
  shown = capsys.readouterr().out.splitlines()
  assert shown[1] == f"receivedFiles\t2\t{len(files[0]) + len(files[1])} bytes\tkeep\tdefault"
  assert [line.split("\t")[0] for line in shown] == [area.value for area in StorageArea] + ["(no holds)"]
  assert [line.split("\t")[1] for line in shown[:5]] == ["2", "2", str(len(operator.auditEvents(limit=10000))), "4", "1"]


# ---- the forms of a rule, and what pruning then removes ------------------------------------------------

def testWithEveryAreaKeptNothingIsEverPruned(store, clock):
  imported(store, "TRIAL-A")
  store.closeTrial("TRIAL-A", start.date())
  clock.moment = start + days(36500)
  assert store.previewPruning().lines == []
  before = areas(store)
  assert store.prune().lines == []
  assert areas(store) == before


def testAFileKeptForAPeriodLeavesOnceItIsOlder(store, clock):
  first = imported(store, "TRIAL-A")
  clock.moment = start + days(20)
  second = imported(store, "TRIAL-A", "SEV")
  store.setSetting("server", "retention.receivedFiles", "keepFor:P30D")
  hashes = {code: store.contentHashFor(code) for code in ("TRIAL-A", "TRIAL-B")}

  clock.moment = start + days(30) - datetime.timedelta(seconds=1)
  assert store.previewPruning().lines == []
  clock.moment = start + days(30)
  preview = store.previewPruning()
  assert preview.lines == [fileLine("TRIAL-A", first, 1, "2026-01-10T12:00:00Z", "keepFor:P30D", "server")]
  assert len(store.receivedFiles("TRIAL-A")) == 2

  outcome = store.prune()
  assert outcome == preview and outcome.at == clock.moment
  [kept] = store.receivedFiles("TRIAL-A")
  assert (kept.fileName, store.receivedFile("TRIAL-A", kept.fileID)[1]) == ("sev.csv", second)
  assert {code: store.contentHashFor(code) for code in hashes} == hashes
  assert store.previewPruning().lines == []
  [pruned] = [event for event in store.auditEvents() if event.action == "retention.prune"]
  assert (pruned.scope, pruned.actorKind, pruned.at) == ("trial:TRIAL-A", "operator", "2026-02-09T12:00:00Z")
  assert pruned.detail == {"area": "receivedFiles", "count": 1, "sizeBytes": len(first), "rule": "keepFor:P30D",
                           "source": "server", "files": preview.lines[0].detail["files"]}


def testAFileKeptUntilItsTrialIsClosedLeavesAPeriodAfterTheClosedDate(store, clock):
  ofA, ofB = imported(store, "TRIAL-A"), imported(store, "TRIAL-B")
  store.setSetting("trial:TRIAL-A", "retention.receivedFiles", "keepUntilClosed:P1Y")
  clock.moment = start + days(3650)
  assert store.previewPruning().lines == []

  clock.moment = datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC)
  store.closeTrial("TRIAL-A", datetime.date(2026, 6, 30))
  clock.moment = datetime.datetime(2027, 6, 29, 13, 0, tzinfo=datetime.UTC)
  assert store.previewPruning().lines == []
  expected = [fileLine("TRIAL-A", ofA, 1, "2026-01-10T12:00:00Z", "keepUntilClosed:P1Y", "trial:TRIAL-A")]
  store.setSetting("server", "tasks.timeZone", "Pacific/Auckland")
  assert store.previewPruning().lines == expected
  store.setSetting("server", "tasks.timeZone", "UTC")
  assert store.previewPruning().lines == []
  clock.moment = datetime.datetime(2027, 6, 30, 0, 0, tzinfo=datetime.UTC)
  assert store.prune().lines == expected
  assert store.receivedFiles("TRIAL-A") == []
  assert [store.receivedFile("TRIAL-B", file.fileID)[1] for file in store.receivedFiles("TRIAL-B")] == [ofB]


def testATrialsRecordLeavesWholeAPeriodAfterItIsClosedAndItsFilesWithIt(store, clock, tmp_path):
  ofA, ofB = imported(store, "TRIAL-A"), imported(store, "TRIAL-B")
  store.setSetting(f"place:{standardPath}", "retention.trialRecords", "keepUntilClosed:P5Y")
  for code in ("TRIAL-A", "TRIAL-B"):
    store.closeTrial(code, datetime.date(2026, 1, 10))
  hashOfA, hashOfB = store.contentHashFor("TRIAL-A"), store.contentHashFor("TRIAL-B")
  size = exportedBytes(store, "TRIAL-A", tmp_path)

  clock.moment = datetime.datetime(2031, 1, 9, 23, 59, tzinfo=datetime.UTC)
  assert store.previewPruning().lines == []
  clock.moment = datetime.datetime(2031, 1, 10, 0, 0, tzinfo=datetime.UTC)
  preview = store.previewPruning()
  rule, source = "keepUntilClosed:P5Y", f"place:{standardPath}"
  assert preview.lines == [
    PruneLine(area=StorageArea.trialRecords, scope="trial:TRIAL-A", count=1, sizeBytes=size, rule=rule, source=source,
              detail={"title": "Fungicide efficacy on winter wheat", "contentHash": hashOfA, "closedOn": "2026-01-10",
                      "place": standardPath}),
    fileLine("TRIAL-A", ofA, 1, "2026-01-10T12:00:00Z", rule, source, withTheTrialRecord=True),
  ]
  assert store.prune() == preview

  assert store.listTrials() == [("TRIAL-B", "Fungicide efficacy on winter wheat")]
  assert store.contentHashFor("TRIAL-B") == hashOfB
  assert [store.receivedFile("TRIAL-B", file.fileID)[1] for file in store.receivedFiles("TRIAL-B")] == [ofB]
  assert areas(store)[StorageArea.receivedFiles] == (1, len(ofB))
  assert [(event.action, event.detail.get("area")) for event in eventsAt(store, "trial:TRIAL-A")] == [
    ("retention.prune", "receivedFiles"), ("retention.prune", "trialRecords"), ("trial.close", None),
    ("values.import", None), ("trial.add", None)]
  assert eventsAt(store, "trial:TRIAL-A")[1].detail["contentHash"] == hashOfA


def testAReopenedTrialIsNotPruned(store, clock):
  store.setSetting("server", "retention.trialRecords", "keepUntilClosed:P1M")
  store.closeTrial("TRIAL-A", start.date())
  store.reopenTrial("TRIAL-A")
  clock.moment = start + days(400)
  assert store.previewPruning().lines == []


def testEventsKeptForAPeriodLeaveByAgeWhateverTheyRecord(store, clock):
  clock.moment = start + days(10)
  store.setSetting("server", "analysis.significanceLevel", 0.1)
  store.setSetting("server", "retention.auditLog", "keepFor:P30D")
  clock.moment = start + days(30)
  old = [event for event in store.auditEvents(limit=10000) if event.at == "2026-01-10T12:00:00Z"]
  scopes = ["place:station", "place:station/trials", f"place:{otherPath}", f"place:{standardPath}", "trial:TRIAL-A",
            "trial:TRIAL-B"]
  assert sorted(event.scope for event in old) == scopes

  preview = store.previewPruning()
  assert [(line.area, line.scope, line.count, line.rule, line.source) for line in preview.lines] == [
    (StorageArea.auditLog, scope, 1, "keepFor:P30D", "server") for scope in scopes]
  byScope = {event.scope: event for event in old}
  assert [(line.sizeBytes, line.detail) for line in preview.lines] == [
    (eventBytes(byScope[scope]), {"oldest": "2026-01-10T12:00:00Z", "newest": "2026-01-10T12:00:00Z",
                                  "firstEventID": byScope[scope].eventID, "lastEventID": byScope[scope].eventID})
    for scope in scopes]

  assert store.prune() == preview
  left = store.auditEvents(limit=10000)
  assert [(event.action, event.scope) for event in left] == [
    ("retention.prune", "server"), ("setting.set", "server"), ("setting.set", "server")]
  assert left[0].detail == {
    "area": "auditLog", "count": 6, "sizeBytes": sum(line.sizeBytes for line in preview.lines),
    "scopes": [{"scope": line.scope, "count": 1, "sizeBytes": line.sizeBytes, "rule": "keepFor:P30D",
                "source": "server"} | line.detail for line in preview.lines]}

  clock.moment = start + days(40)
  assert [(line.scope, line.count) for line in store.prune().lines] == [("server", 2)]
  assert [(event.action, event.at) for event in store.auditEvents(limit=10000)] == [
    ("retention.prune", "2026-02-19T12:00:00Z"), ("retention.prune", "2026-02-09T12:00:00Z")]


def testATrialsEventsLeaveWithItsClosingButTheRecordsOfRetentionStayTheirOwnPeriod(store, clock):
  trial = "trial:TRIAL-A"
  store.setSetting(trial, "retention.auditLog", "keepUntilClosed:P1Y")
  clock.moment = datetime.datetime(2026, 2, 1, 12, 0, tzinfo=datetime.UTC)
  imported(store, "TRIAL-A")
  store.setSetting(trial, "analysis.significanceLevel", 0.1)
  clock.moment = datetime.datetime(2026, 3, 1, 12, 0, tzinfo=datetime.UTC)
  store.closeTrial("TRIAL-A", datetime.date(2026, 2, 28))
  clock.moment = datetime.datetime(2026, 12, 1, 12, 0, tzinfo=datetime.UTC)
  store.holdTrial("TRIAL-A", "Audit by the sponsor")
  store.releaseHold("TRIAL-A", "Audit closed")
  everyEvent = [event.action for event in eventsAt(store, trial)]
  assert everyEvent == ["retention.release", "retention.hold", "trial.close", "setting.set", "values.import",
                        "setting.set", "trial.add"]
  ofB = eventsAt(store, "trial:TRIAL-B")

  clock.moment = datetime.datetime(2027, 2, 27, 23, 0, tzinfo=datetime.UTC)
  assert store.previewPruning().lines == []
  clock.moment = datetime.datetime(2027, 2, 28, 0, 0, tzinfo=datetime.UTC)
  [line] = store.prune().lines
  assert (line.area, line.scope, line.count, line.rule, line.source) == (
    StorageArea.auditLog, trial, 4, "keepUntilClosed:P1Y", trial)
  assert (line.detail["oldest"], line.detail["newest"]) == ("2026-01-10T12:00:00Z", "2026-02-01T12:00:00Z")
  assert [event.action for event in eventsAt(store, trial)] == ["retention.release", "retention.hold", "trial.close"]
  assert eventsAt(store, "trial:TRIAL-B") == ofB
  [recorded] = [event for event in store.auditEvents() if event.action == "retention.prune"]
  assert (recorded.scope, recorded.detail["count"], [entry["scope"] for entry in recorded.detail["scopes"]]) == (
    "server", 4, [trial])

  clock.moment = datetime.datetime(2027, 3, 1, 12, 0, tzinfo=datetime.UTC)
  assert [(line.scope, line.count) for line in store.prune().lines] == [(trial, 1)]
  assert [event.action for event in eventsAt(store, trial)] == ["retention.release", "retention.hold"]
  clock.moment = datetime.datetime(2027, 12, 1, 12, 0, tzinfo=datetime.UTC)
  assert [(line.scope, line.count) for line in store.prune().lines] == [(trial, 2)]
  assert eventsAt(store, trial) == []


def testEventsOutsideAnyTrialCountTheirPeriodFromThemselves(store, clock):
  store.setSetting("server", "retention.auditLog", "keepUntilClosed:P1Y")
  clock.moment = start + days(1)
  store.deleteTrial("TRIAL-B")
  clock.moment = datetime.datetime(2027, 1, 10, 12, 0, tzinfo=datetime.UTC)
  assert [(line.scope, line.count, line.source) for line in store.previewPruning().lines] == [
    ("place:station", 1, "server"), ("place:station/trials", 1, "server"), (f"place:{otherPath}", 1, "server"),
    (f"place:{standardPath}", 1, "server"), ("server", 1, "server"), ("trial:TRIAL-B", 1, "server")]
  store.prune()
  assert [event.action for event in eventsAt(store, "trial:TRIAL-B")] == ["trial.delete"]
  assert [event.action for event in eventsAt(store, "trial:TRIAL-A")] == ["trial.add"]


def testExpiredSessionsTokensSignInsAndClaimsLeaveAPeriodAfterTheyExpire(location, standIn, monkeypatch):
  now = datetime.datetime.now(datetime.UTC)
  clock = Clock(now)
  operator = Workspace.create(location, clock=clock)
  operator.createAccount("ana", "Ana", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="ana"))
  _, session = operator.signIn("ana", password, "web")
  _, stale = operator.signIn("ana", password, "web")
  ana = operator.actingAs(operator.actorForSession(session, "web"))
  forever, week = ana.issueAPIToken("forever", None), ana.issueAPIToken("week", 7)
  monkeypatch.setenv("OPENFURROW_TEST_SECRET", "stand-in secret")
  operator.addProvider(Provider.of("standin", "openIDConnect", {
    "issuer": standIn.issuer("lab"), "clientID": "openfurrow", "clientSecretVariable": "OPENFURROW_TEST_SECRET",
    "returnURL": "https://openfurrow.example.org/signin/with/standin/return",
    "certificateAuthority": str(standIn.certificateAuthority)}))
  operator.beginProviderSignIn("standin", "/")
  engine = createDatabase(location, create=False)
  with Session(engine) as database:
    [pendingState] = database.execute(select(PendingSignInRow.stateJSON)).scalars().all()
    database.execute(update(AuthTokenRow).where(AuthTokenRow.tokenHash == hashlib.sha256(stale.encode()).hexdigest())
                     .values(expiresAt=(now - datetime.timedelta(hours=2)).replace(tzinfo=None)))
    database.commit()
  assert claimOnce(engine, "scope", "used", (now + datetime.timedelta(hours=1)).timestamp(), now.timestamp())
  operator.setSetting("server", "retention.sessionsAndTokens", "keepFor:P30D")
  with pytest.raises(IdentityError, match="the token has expired"):
    operator.actorForSession(stale, "web")
  assert areas(operator)[StorageArea.sessionsAndTokens][0] == 6

  clock.moment = now + days(29)
  assert operator.previewPruning().lines == []
  clock.moment = now + days(30)
  [line] = operator.prune().lines
  assert (line.count, line.sizeBytes, line.detail) == (1, 64 + len("session"), {
    "expiredSessions": 1, "expiredTokens": 0, "pendingSignIns": 0, "messageClaims": 0})
  assert operator.actorForSession(session, "web").userName == "ana"
  clock.moment = now + days(30) + datetime.timedelta(hours=13)
  preview = operator.previewPruning()
  size = (64 + len("session")) + (64 + len("standin") + len(pendingState)) + len("scope") + len("used")
  assert preview.lines == [PruneLine(
    area=StorageArea.sessionsAndTokens, scope="server", count=3, sizeBytes=size, rule="keepFor:P30D", source="server",
    detail={"expiredSessions": 1, "expiredTokens": 0, "pendingSignIns": 1, "messageClaims": 1})]
  assert operator.prune() == preview
  assert areas(operator)[StorageArea.sessionsAndTokens] == (2, 2 * (64 + len("api")) + len("forever") + len("week"))

  clock.moment = now + days(38)
  [line] = operator.prune().lines
  assert (line.count, line.detail) == (1, {"expiredSessions": 0, "expiredTokens": 1, "pendingSignIns": 0,
                                         "messageClaims": 0})
  clock.moment = now + days(36500)
  assert operator.prune().lines == []
  assert operator.actorForAPIToken(forever, "api").userName == "ana"
  with pytest.raises(IdentityError, match="the token is not valid"):
    operator.actorForAPIToken(week, "api")


# ---- the store's own task ----------------------------------------------------------------

def settledRun(location, operator, seconds=120):
  """Request a run of the store's pruning task and let a scheduler carry it out; the run."""
  operator.runTaskNow(retentionTaskName)
  scheduler = Scheduler(location, pollSeconds=0.1, stopGraceSeconds=0, killGraceSeconds=1)
  try:
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
    while datetime.datetime.now() < deadline:
      scheduler.tick()
      run = operator.taskRuns(retentionTaskName)[0]
      if run.state not in (RunState.requested, RunState.running) and not scheduler.children:
        return run
      threading.Event().wait(0.1)
  finally:
    scheduler.windDown()
  raise AssertionError(f"the run did not finish: {operator.taskRuns(retentionTaskName)}")


def testTheStoresOwnTaskPrunesEveryDayAndItsSummarySaysWhatWent(location, validPackageDict):
  now = datetime.datetime.now(datetime.UTC)
  data = imported(populated(location, validPackageDict, Clock(now - days(40))), "TRIAL-A")
  operator = Workspace.open(location)
  task = operator.task(retentionTaskName)
  assert (task.name, task.kind, task.parameters, task.schedule, task.enabled, task.timeLimitSeconds, task.ownerFeature,
          task.ownerProvider) == ("retentionPrune", "retentionPrune", {}, "15 3 * * *", True, 1800, "retention", None)
  assert (task.nextRunAt.hour, task.nextRunAt.minute) == (3, 15) and task.nextRunAt - now <= days(1)

  kept = settledRun(location, operator)
  assert (kept.state, kept.summary) == (RunState.succeeded, "nothing pruned: no retention rule lets anything go")
  assert len(operator.receivedFiles("TRIAL-A")) == 1

  operator.setSetting("server", "retention.receivedFiles", "keepFor:P30D")
  pruned = settledRun(location, operator)
  assert (pruned.state, pruned.summary) == (RunState.succeeded, f"pruned 1 received file ({len(data)} bytes)")
  assert f"pruned 1 of receivedFiles at trial:TRIAL-A ({len(data)} bytes) under keepFor:P30D, set at server" in pruned.output
  assert operator.receivedFiles("TRIAL-A") == []
  [event] = [event for event in operator.auditEvents() if event.action == "retention.prune"]
  assert (event.actorKind, event.actorName, event.surface, event.scope) == (
    "scheduler", retentionTaskName, "scheduler", "trial:TRIAL-A")

  operator.setSetting("server", "retention.taskRuns", "keepFor:P30D")
  operator.runTaskNow(retentionTaskName)
  later = Workspace.open(location, clock=Clock(now + days(29)))
  assert later.previewPruning().lines == []
  later = Workspace.open(location, clock=Clock(datetime.datetime.now(datetime.UTC) + days(31)))
  finished = [run for run in operator.taskRuns(retentionTaskName) if run.finishedAt is not None]
  [line] = later.prune().lines
  assert (line.area, line.scope, line.count, line.detail["byTask"]) == (
    StorageArea.taskRuns, "server", 2, {retentionTaskName: 2})
  assert line.sizeBytes == sum(len(text.encode("utf-8")) for run in finished
                               for text in (run.taskName, run.requestedBy, run.summary, run.output))
  assert [run.state for run in operator.taskRuns(retentionTaskName)] == [RunState.requested]


# ---- a preview is what pruning removes ----------------------------------------------------------------

def testWhatAPreviewListsIsExactlyWhatPruningRemoves(location, validPackageDict):
  now = datetime.datetime.now(datetime.UTC)
  clock = Clock(now)
  operator = populated(location, validPackageDict, clock)
  ofA, ofB = imported(operator, "TRIAL-A"), imported(operator, "TRIAL-B")
  operator.createAccount("ana", "Ana", None, password)
  operator.signIn("ana", password, "web")
  for area in ("receivedFiles", "auditLog", "sessionsAndTokens", "taskRuns"):
    operator.setSetting("server", f"retention.{area}", "keepFor:P30D")
  operator.setSetting(f"place:{standardPath}", "retention.trialRecords", "keepUntilClosed:P1M")
  operator.closeTrial("TRIAL-A", now.date())
  operator.holdTrial("TRIAL-B", "Under review")
  hashOfB, eventsOfB = operator.contentHashFor("TRIAL-B"), eventsAt(operator, "trial:TRIAL-B")

  clock.moment = now + days(40)
  before, preview = areas(operator), operator.previewPruning()
  assert areas(operator) == before
  totals = preview.totals()
  assert {area: count for area, (count, _) in totals.items()} == {
    StorageArea.trialRecords: 1, StorageArea.receivedFiles: 1, StorageArea.sessionsAndTokens: 1,
    StorageArea.auditLog: before[StorageArea.auditLog][0] - len(eventsOfB)}
  assert "trial:TRIAL-B" not in {line.scope for line in preview.lines}

  outcome = operator.prune()
  assert outcome == preview
  after = areas(operator)
  written = [event for event in operator.auditEvents(limit=10000) if event.action == "retention.prune"]
  assert [(event.scope, event.detail["area"]) for event in written] == [
    ("server", "auditLog"), ("server", "sessionsAndTokens"), ("trial:TRIAL-A", "receivedFiles"),
    ("trial:TRIAL-A", "trialRecords")]
  for area in (StorageArea.trialRecords, StorageArea.receivedFiles, StorageArea.sessionsAndTokens):
    assert after[area] == (before[area][0] - totals[area][0], before[area][1] - totals[area][1])
  assert after[StorageArea.auditLog] == (
    before[StorageArea.auditLog][0] - totals[StorageArea.auditLog][0] + len(written),
    before[StorageArea.auditLog][1] - totals[StorageArea.auditLog][1] + sum(eventBytes(event) for event in written))
  assert after[StorageArea.taskRuns] == before[StorageArea.taskRuns] == (0, 0)
  assert operator.previewPruning().lines == []

  assert operator.listTrials() == [("TRIAL-B", "Fungicide efficacy on winter wheat")]
  assert operator.contentHashFor("TRIAL-B") == hashOfB
  assert [operator.receivedFile("TRIAL-B", file.fileID)[1] for file in operator.receivedFiles("TRIAL-B")] == [ofB]
  assert eventsAt(operator, "trial:TRIAL-B") == eventsOfB
  assert len(ofA) == totals[StorageArea.receivedFiles][1]


# ---- holds ---------------------------------------------------------------------------

def testAHoldStopsEveryPruningThatConcernsItsTrial(store, clock):
  ofA = imported(store, "TRIAL-A")
  imported(store, "TRIAL-B")
  store.setSetting("server", "retention.receivedFiles", "keepFor:P30D")
  store.setSetting("server", "retention.auditLog", "keepFor:P30D")
  store.setSetting("server", "retention.trialRecords", "keepUntilClosed:P1M")
  for code in ("TRIAL-A", "TRIAL-B"):
    store.closeTrial(code, start.date())
  store.holdTrial("TRIAL-A", "Dispute over plot 7")
  hashOfA, eventsOfA = store.contentHashFor("TRIAL-A"), eventsAt(store, "trial:TRIAL-A")
  assert [event.action for event in eventsOfA] == ["retention.hold", "trial.close", "values.import", "trial.add"]

  clock.moment = start + days(60)
  preview = store.previewPruning()
  assert {line.scope for line in preview.lines if line.scope.startswith("trial:")} == {"trial:TRIAL-B"}
  assert [(line.area, line.count) for line in preview.lines if line.scope == "trial:TRIAL-B"] == [
    (StorageArea.trialRecords, 1), (StorageArea.receivedFiles, 1), (StorageArea.auditLog, 3)]
  assert store.prune() == preview
  assert store.listTrials() == [("TRIAL-A", "Fungicide efficacy on winter wheat")]
  assert store.contentHashFor("TRIAL-A") == hashOfA
  assert [store.receivedFile("TRIAL-A", file.fileID)[1] for file in store.receivedFiles("TRIAL-A")] == [ofA]
  assert eventsAt(store, "trial:TRIAL-A") == eventsOfA

  store.releaseHold("TRIAL-A", "Settled")
  released = store.prune()
  assert [(line.area, line.scope, line.count) for line in released.lines] == [
    (StorageArea.trialRecords, "trial:TRIAL-A", 1), (StorageArea.receivedFiles, "trial:TRIAL-A", 1),
    (StorageArea.auditLog, "trial:TRIAL-A", 4)]
  assert store.listTrials() == []


def testAHoldHasAReasonStandsOncePerTrialAndRefusesDeletion(store, clock):
  with pytest.raises(RetentionError, match="a hold needs its reason"):
    store.holdTrial("TRIAL-A", "   ")
  with pytest.raises(NotFoundError, match="trial 'NOPE' not found"):
    store.holdTrial("NOPE", "Dispute")
  hold = store.holdTrial("TRIAL-A", " Dispute over plot 7 ")
  assert (hold.trialCode, hold.reason, hold.heldByKind, hold.heldByName, hold.heldAt) == (
    "TRIAL-A", "Dispute over plot 7", "operator", None, start)
  assert store.holdOn("TRIAL-A") == hold and store.holdOn("TRIAL-B") is None
  assert store.retentionStatus().holds == [hold]
  with pytest.raises(RetentionError, match="trial 'TRIAL-A' is under a hold already: Dispute over plot 7"):
    store.holdTrial("TRIAL-A", "Another matter")
  with pytest.raises(RetentionError, match="trial 'TRIAL-A' is under a hold and is not deleted: Dispute over plot 7"):
    store.deleteTrial("TRIAL-A")
  assert [code for code, _ in store.listTrials()] == ["TRIAL-A", "TRIAL-B"]
  with pytest.raises(RetentionError, match="releasing a hold needs its reason"):
    store.releaseHold("TRIAL-A", "")
  with pytest.raises(RetentionError, match="trial 'TRIAL-B' is under no hold"):
    store.releaseHold("TRIAL-B", "Settled")
  clock.moment = start + days(5)
  store.releaseHold("TRIAL-A", "Settled")
  assert store.holdOn("TRIAL-A") is None and store.retentionStatus().holds == []
  assert [(event.action, event.at, event.detail) for event in eventsAt(store, "trial:TRIAL-A")][:2] == [
    ("retention.release", "2026-01-15T12:00:00Z", {"reason": "Settled", "hold": {
      "reason": "Dispute over plot 7", "heldByKind": "operator", "heldByName": None,
      "heldAt": "2026-01-10T12:00:00Z"}}),
    ("retention.hold", "2026-01-10T12:00:00Z", {"reason": "Dispute over plot 7"}),
  ]
  store.deleteTrial("TRIAL-A")
  assert [code for code, _ in store.listTrials()] == ["TRIAL-B"]


# ---- closing ---------------------------------------------------------------------------

def testClosingIsADaySetAndClearedAndChangesNothingElse(store, clock):
  before = store.contentHashFor("TRIAL-A")
  assert store.closedOn("TRIAL-A") is None
  with pytest.raises(RetentionError, match="trial 'TRIAL-A' cannot be closed on 2026-01-11, a day that has not come; "
                                           "it is 2026-01-10 at the server"):
    store.closeTrial("TRIAL-A", datetime.date(2026, 1, 11))
  with pytest.raises(NotFoundError, match="trial 'NOPE' not found"):
    store.closeTrial("NOPE", datetime.date(2026, 1, 1))
  store.closeTrial("TRIAL-A", datetime.date(2025, 12, 31))
  assert (store.closedOn("TRIAL-A"), store.closedOn("TRIAL-B")) == (datetime.date(2025, 12, 31), None)
  assert store.contentHashFor("TRIAL-A") == before
  imported(store, "TRIAL-A")
  assert len(store.loadObservations("TRIAL-A")) == 12
  store.closeTrial("TRIAL-A", datetime.date(2026, 1, 10))
  store.reopenTrial("TRIAL-A")
  assert store.closedOn("TRIAL-A") is None
  with pytest.raises(RetentionError, match="trial 'TRIAL-A' is not closed"):
    store.reopenTrial("TRIAL-A")
  assert [(event.action, event.detail) for event in eventsAt(store, "trial:TRIAL-A")
          if event.action.startswith("trial.") and event.action != "trial.add"] == [
    ("trial.reopen", {"before": "2026-01-10"}),
    ("trial.close", {"before": "2025-12-31", "after": "2026-01-10"}),
    ("trial.close", {"before": None, "after": "2025-12-31"}),
  ]


# ---- rights ---------------------------------------------------------------------------

@pytest.fixture
def people(store):
  store.defineRole(RoleDefinition(roleCode="retentionOfficer", name="Retention officer",
                                  permissions=frozenset({Permission.view, Permission.manageRetention})))
  for userName, roleCode, scope in (("tia", "trialManager", "place:station"), ("vic", "viewer", "server"),
                                    ("rex", "retentionOfficer", f"place:{standardPath}"),
                                    ("ada", "administrator", "server")):
    store.createAccount(userName, userName.title(), None, password)
    store.assignRole(RoleAssignment(roleCode=roleCode, scope=scope, userName=userName))
  store.setSetting("server", "identity.signInMode", "accounts")
  return store


def actingAs(operator, userName):
  _, token = operator.signIn(userName, password, "web")
  return operator.actingAs(operator.actorForSession(token, "web"))


def testRetentionRulesHoldsAndPruningTakeManageRetention(people):
  tia, vic, rex, ada = (actingAs(people, userName) for userName in ("tia", "vic", "rex", "ada"))
  trial = "trial:TRIAL-A"

  tia.setSetting(trial, "analysis.significanceLevel", 0.1)
  for attempt in (lambda: tia.setSetting(trial, "retention.auditLog", "keepFor:P1D"),
                  lambda: tia.clearSetting(trial, "retention.auditLog"), lambda: tia.holdTrial("TRIAL-A", "Mine")):
    with pytest.raises(NotPermitted, match="tia may not manageRetention at trial:TRIAL-A"):
      attempt()
  for someone in (tia, vic, rex):
    for attempt in (someone.retentionStatus, someone.previewPruning, someone.prune):
      with pytest.raises(NotPermitted, match="may not manageRetention at server"):
        attempt()

  rex.setSetting(f"place:{standardPath}", "retention.receivedFiles", "keepFor:P1Y")
  assert rex.holdTrial("TRIAL-A", "Review").heldByName == "rex"
  rex.releaseHold("TRIAL-A", "Reviewed")
  with pytest.raises(NotPermitted, match="rex may not changeSettings at trial:TRIAL-A"):
    rex.setSetting(trial, "analysis.significanceLevel", 0.01)
  with pytest.raises(NotPermitted, match="rex may not manageRetention at server"):
    rex.setSetting("server", "retention.receivedFiles", "keepFor:P1Y")
  with pytest.raises(NotFoundError, match="trial 'TRIAL-B' not found"):
    rex.holdTrial("TRIAL-B", "Review")

  for someone, name in ((vic, "vic"), (rex, "rex")):
    with pytest.raises(NotPermitted, match=f"{name} may not manageTrials at trial:TRIAL-A"):
      someone.closeTrial("TRIAL-A", datetime.date(2026, 1, 1))
  tia.closeTrial("TRIAL-A", datetime.date(2026, 1, 1))
  assert vic.closedOn("TRIAL-A") == datetime.date(2026, 1, 1) and vic.holdOn("TRIAL-A") is None
  with pytest.raises(NotPermitted, match="vic may not manageTrials at trial:TRIAL-A"):
    vic.reopenTrial("TRIAL-A")

  ada.setSetting("server", "retention.sessionsAndTokens", "keepFor:P30D")
  assert [area.area for area in ada.retentionStatus().areas] == list(StorageArea)
  assert ada.prune().lines == [] and ada.previewPruning().lines == []


# ---- the command line -------------------------------------------------------------------

def testTheCommandLineShowsHoldsPreviewsAndPrunes(location, validPackageDict, capsys):
  data = imported(populated(location, validPackageDict, Clock(datetime.datetime.now(datetime.UTC) - days(40))), "TRIAL-A")

  def said(command, *arguments, code=0):
    assert main([*command.split(), location, *arguments]) == code
    captured = capsys.readouterr()
    return (captured.out if code == 0 else captured.err).strip()

  assert said("retention preview") == "(nothing to prune)"
  assert "trialRecords is not kept by keepFor" in said("setting set", "server", "retention.trialRecords", "keepFor:P30D", code=1)
  said("setting set", "place:station", "retention.receivedFiles", "keepFor:P30D")
  status = said("retention status").splitlines()
  assert status[1:3] == [f"receivedFiles\t1\t{len(data)} bytes\tkeep\tdefault",
                         "receivedFiles\tset at place:station\tkeepFor:P30D"]
  assert status[-1] == "(no holds)"

  assert said("retention hold", "TRIAL-A", "Dispute over plot 7") == "Trial 'TRIAL-A' is under a hold: Dispute over plot 7"
  held = said("retention status").splitlines()[-1].split("\t")
  assert (held[0], held[1], held[2], held[4]) == ("hold", "TRIAL-A", "operator", "Dispute over plot 7")
  assert said("retention preview") == "(nothing to prune)"
  assert "is under a hold and is not deleted" in said("delete", "TRIAL-A", code=1)
  assert "releasing a hold needs its reason" in said("retention release", "TRIAL-A", "", code=1)
  assert said("retention release", "TRIAL-A", "Settled") == "Released the hold on trial 'TRIAL-A'"

  lines = [f"receivedFiles\ttrial:TRIAL-A\t1\t{len(data)} bytes\tkeepFor:P30D\tplace:station",
           f"  file 1\tyield.csv\t{len(data)} bytes\t{sha256(data)}"]
  assert said("retention preview").splitlines() == lines
  assert len(Workspace.open(location).receivedFiles("TRIAL-A")) == 1
  assert said("retention prune").splitlines() == lines + [f"pruned 1 received file ({len(data)} bytes)"]
  assert said("received list", "TRIAL-A") == "(no received files)"
  assert said("retention prune") == "nothing pruned: no retention rule lets anything go"

  assert "'2026-13-40' is not a day; write it YYYY-MM-DD" in said("close", "TRIAL-A", "2026-13-40", code=1)
  assert "a day that has not come" in said("close", "TRIAL-A", "2999-01-01", code=1)
  assert said("close", "TRIAL-A", "2026-01-05") == "Trial 'TRIAL-A' is closed on 2026-01-05"
  assert Workspace.open(location).closedOn("TRIAL-A") == datetime.date(2026, 1, 5)
  assert said("reopen", "TRIAL-A") == "Trial 'TRIAL-A' is open again"
  assert "trial 'TRIAL-A' is not closed" in said("reopen", "TRIAL-A", code=1)


# ---- the web ---------------------------------------------------------------------------

@pytest.fixture
def aged(location, validPackageDict):
  """A store, open to everyone, with a file forty days old in TRIAL-A."""
  data = imported(populated(location, validPackageDict, Clock(datetime.datetime.now(datetime.UTC) - days(40))), "TRIAL-A")
  return Workspace.open(location), data


def testTheRetentionPageShowsAreasHoldsAPreviewAndPrunesOnlyOnConfirmation(aged, location):
  operator, data = aged
  operator.setSetting("server", "retention.receivedFiles", "keepFor:P30D")
  operator.setSetting("trial:TRIAL-B", "retention.receivedFiles", "keepUntilClosed:P5Y")
  operator.holdTrial("TRIAL-B", "Dispute over plot 7")
  client = createApp(location).test_client()
  assert 'href="/retention"' in client.get("/").get_data(as_text=True)

  page = client.get("/retention").get_data(as_text=True)
  for expected in ("Storage areas", "Trial records", "Files as received", "Audit log", "Sessions and tokens", "Task runs",
                   f"{len(data)} bytes", "Keep for 30 days (set for the server)", "retention.receivedFiles = keepFor:P30D",
                   "Keep until the trial is closed, then for 5 years", "trial:TRIAL-B", "Keep (default)",
                   "Dispute over plot 7", 'href="/trials/TRIAL-B#retention"', 'href="/tasks/retentionPrune"'):
    assert expected in page, expected
  assert "Pruning now would remove exactly this:" not in page

  preview = client.get("/retention?preview=yes").get_data(as_text=True)
  assert "Pruning now would remove exactly this:" in preview and "yield.csv" in preview and sha256(data) in preview
  confirm = client.get("/retention/prune").get_data(as_text=True)
  assert "Prune now?" in confirm and "It cannot be undone." in confirm and sha256(data) in confirm
  assert len(operator.receivedFiles("TRIAL-A")) == 1

  done = client.post("/retention/prune")
  body = done.get_data(as_text=True)
  assert done.status_code == 200 and "This was removed, and recorded in the audit log:" in body and sha256(data) in body
  assert operator.receivedFiles("TRIAL-A") == []
  assert "Nothing would be pruned now" in client.get("/retention?preview=yes").get_data(as_text=True)
  assert "Nothing was pruned" in client.post("/retention/prune").get_data(as_text=True)
  assert "Nothing would be pruned now" in client.get("/retention/prune").get_data(as_text=True)


def testTheTrialPageClosesReopensHoldsAndReleases(aged, location):
  operator, _ = aged
  client = createApp(location).test_client()
  page = client.get("/trials/TRIAL-A").get_data(as_text=True)
  assert "This trial is open." in page and "This trial is under no hold." in page and "Keep (default)" in page

  def post(**fields):
    return client.post("/trials/TRIAL-A/retention", data=fields)

  bad = post(action="close", closedOn="yesterday")
  assert bad.status_code == 400 and "Not done: write the day as YYYY-MM-DD" in bad.get_data(as_text=True)
  future = post(action="close", closedOn="2999-01-01")
  assert future.status_code == 400 and "a day that has not come" in future.get_data(as_text=True)
  closed = post(action="close", closedOn="2026-01-05")
  assert closed.status_code == 302 and closed.headers["Location"].endswith("/trials/TRIAL-A?done=close")
  page = client.get(closed.headers["Location"]).get_data(as_text=True)
  assert "The closed date is recorded." in page and "This trial was closed on 01/05/2026." in page
  assert operator.closedOn("TRIAL-A") == datetime.date(2026, 1, 5)

  unreasoned = post(action="hold", reason=" ")
  assert unreasoned.status_code == 400 and "Not done: a hold needs its reason" in unreasoned.get_data(as_text=True)
  assert post(action="hold", reason="Dispute over plot 7").status_code == 302
  page = client.get("/trials/TRIAL-A").get_data(as_text=True)
  assert "This trial is under a hold" in page and "Dispute over plot 7" in page and "everyone (no sign-in)" in page
  assert client.post("/trials/TRIAL-A/delete").status_code == 400
  assert [code for code, _ in operator.listTrials()] == ["TRIAL-A", "TRIAL-B"]
  assert post(action="release", reason="Settled").status_code == 302 and operator.holdOn("TRIAL-A") is None
  assert post(action="reopen").status_code == 302 and operator.closedOn("TRIAL-A") is None
  assert post(action="reopen").status_code == 400
  assert post(action="shred").status_code == 400


@pytest.mark.parametrize("locale", ["en-US", "en-GB", "es", "fr", "ar"])
def testEveryRetentionPageRendersInEveryLocale(aged, location, locale):
  operator, _ = aged
  operator.importWeatherFile("TRIAL-A", "weather.csv", b"date,rainfall [mm]\n2026-05-01,3\n")
  operator.setSetting("server", "retention.receivedFiles", "keepFor:P1D")
  operator.setSetting("server", "retention.trialRecords", "keepUntilClosed:P18M")
  operator.setSetting("server", "retention.auditLog", "keepUntilClosed:P1Y")
  operator.closeTrial("TRIAL-A", datetime.date(2020, 1, 1))
  operator.holdTrial("TRIAL-B", "Dispute")
  client = createApp(location).test_client()
  for address in ("/retention", "/retention?preview=yes", "/retention/prune", "/trials/TRIAL-A", "/trials/TRIAL-B",
                  f"/tasks/{retentionTaskName}"):
    separator = "&" if "?" in address else "?"
    answered = client.get(f"{address}{separator}locale={locale}")
    assert answered.status_code == 200, (address, answered.get_data(as_text=True)[:400])
    assert ('dir="rtl"' in answered.get_data(as_text=True)) == (locale == "ar")
  assert client.post(f"/retention/prune?locale={locale}").status_code == 200
  assert operator.listTrials() == [("TRIAL-B", "Fungicide efficacy on winter wheat")]


def testTheArabicRetentionPageIsWrittenRightToLeft(aged, location):
  page = createApp(location).test_client().get("/retention?locale=ar").get_data(as_text=True)
  assert '<html lang="ar" dir="rtl">' in page
  assert "\u0645\u0646\u0627\u0637\u0642 \u0627\u0644\u062a\u062e\u0632\u064a\u0646" in page
  assert '<span class="code" dir="ltr">retention.receivedFiles = keep</span>' in page


def testRetentionOnTheWebTakesItsPermissions(people, location):
  def signedIn(userName):
    client = createApp(location).test_client()
    assert client.post("/signin", data={"userName": userName, "password": password}, headers=origin).status_code == 302
    return client

  viewer, manager, administrator = signedIn("vic"), signedIn("tia"), signedIn("ada")
  assert 'href="/retention"' not in viewer.get("/").get_data(as_text=True)
  assert viewer.get("/retention").status_code == 403 and viewer.get("/retention/prune").status_code == 403
  assert viewer.post("/retention/prune", headers=origin).status_code == 403
  assert viewer.post("/trials/TRIAL-A/retention", data={"action": "close", "closedOn": "2026-01-05"},
                     headers=origin).status_code == 403
  page = viewer.get("/trials/TRIAL-A").get_data(as_text=True)
  assert "This trial is open." in page and 'name="closedOn"' not in page and 'name="reason"' not in page

  page = manager.get("/trials/TRIAL-A").get_data(as_text=True)
  assert 'name="closedOn"' in page and 'name="reason"' not in page
  assert manager.post("/trials/TRIAL-A/retention", data={"action": "hold", "reason": "Mine"},
                      headers=origin).status_code == 403
  assert manager.post("/trials/TRIAL-A/retention", data={"action": "close", "closedOn": "2026-01-05"},
                      headers=origin).status_code == 302
  assert manager.get("/retention").status_code == 403

  assert 'href="/retention"' in administrator.get("/").get_data(as_text=True)
  page = administrator.get("/trials/TRIAL-A").get_data(as_text=True)
  assert 'name="closedOn"' in page and 'name="reason"' in page
  assert administrator.get("/retention").status_code == 200
  assert administrator.post("/retention/prune", headers=origin).status_code == 200
  assert administrator.post("/retention/prune").status_code == 403
