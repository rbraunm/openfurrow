# SPDX-License-Identifier: Apache-2.0
"""The file as received (decision 0044, worklist REC-16): every import keeps its file byte for byte with the mapping
that read it, outside the trial's content hash; the file is read back by those who may import, travels with the trial
in a bundle, and leaves with the trial."""

import base64
import datetime
import hashlib
import io
import json
import zipfile

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from openfurrow import TrialPackage, Workspace, defaultConfig
from openfurrow.cli.main import main
from openfurrow.exchange import ExchangeError
from openfurrow.identity import RoleAssignment
from openfurrow.service import createApp
from openfurrow.store import NotFoundError, StoreError
from openfurrow.store.database import ReceivedFileRow, createDatabase
from openfurrow.workspace import NotPermitted

from storeHelpers import standardPath, standardStudy, standardStudyAt

password = "correct horse battery"
trialCode = "ESV-2025-01"
origin = {"Origin": "http://localhost"}
naTokens = ["", "NA", "na", "N/A"]
weatherFile = b"date,rainfall [mm]\n2026-05-01,3\n2026-05-02,0\n"


class Clock:
  def __init__(self, moment):
    self.moment = moment

  def __call__(self):
    return self.moment


@pytest.fixture
def clock():
  return Clock(datetime.datetime(2026, 3, 1, 9, 30, 15, 250000, tzinfo=datetime.UTC))


@pytest.fixture
def location(newStore, validPackageDict, clock):
  location = newStore("received")
  workspace = Workspace.create(location, clock=clock)
  workspace.addPackage(TrialPackage.model_validate(validPackageDict), standardStudy(workspace))
  return location


def sha256(content):
  return hashlib.sha256(content).hexdigest()


def plotNumbers(location):
  return sorted(plot.plotNumber for plot in Workspace.open(location).layoutFor(trialCode).plots)


def yieldFile(location):
  """A long CSV as a spreadsheet saves it: a byte-order mark, CRLF line ends, and a column the import does not read."""
  rows = ["plotNumber,assessmentCode,value,notes"] + [f"{plot},YIELD,{5000 + plot}.5,ok" for plot in plotNumbers(location)]
  return b"\xef\xbb\xbf" + "\r\n".join(rows + [""]).encode("utf-8")


def severityFile(location):
  return ("plotNumber,assessmentCode,value\n" + "".join(f"{plot},SEV,low\n" for plot in plotNumbers(location))).encode()


def storedFileCount(location):
  with Session(createDatabase(location, create=False)) as session:
    return session.execute(select(func.count()).select_from(ReceivedFileRow)).scalar_one()


# ---- every import keeps its file ---------------------------------------------------------

def testACsvImportedOnTheCommandLineComesBackByteForByteWithItsMapping(location, tmp_path, newStore, capsys):
  data = yieldFile(location)
  path = tmp_path / "yield 2026.csv"
  path.write_bytes(data)
  assert main(["import", location, trialCode, str(path)]) == 0
  capsys.readouterr()
  assert main(["received", "list", location, trialCode]) == 0
  [line] = capsys.readouterr().out.splitlines()
  fileID, kind, fileName, sheet, size, digest, who, when, produced, mapping = line.split("\t")
  assert (fileID, kind, fileName, sheet, size, digest, who) == (
    "1", "observations", "yield 2026.csv", "-", str(len(data)), sha256(data), "operator")
  assert abs((datetime.datetime.now(datetime.UTC) - datetime.datetime.fromisoformat(when)).total_seconds()) < 300
  assert json.loads(produced) == {"values": 12, "missing": 0,
                                  "assessments": {"YIELD": {"values": 12, "missing": 0, "plotsWithout": 0}}}
  assert json.loads(mapping) == {
    "format": "long", "plotNumber": "plotNumber", "assessmentCode": "assessmentCode", "value": "value",
    "subsample": None, "assessmentColumns": [], "unreadColumns": ["notes"], "decimalSeparator": ".",
    "naTokens": naTokens}
  output = tmp_path / "back.csv"
  assert main(["received", "download", location, trialCode, "1", str(output)]) == 0
  assert capsys.readouterr().out.strip() == f"Wrote {output} ({len(data)} bytes, SHA-256 {sha256(data)})"
  assert output.read_bytes() == data
  assert main(["received", "download", location, trialCode, "2", str(output)]) == 1
  assert f"trial '{trialCode}' holds no received file 2" in capsys.readouterr().err


def testTheReceivedFileIsOutsideTheContentHash(location, tmp_path, newStore):
  workspace = Workspace.open(location)
  workspace.importObservationFile(trialCode, "yield.csv", yieldFile(location), defaultConfig().importProfile)
  exported = tmp_path / "trial.json"
  workspace.exportDocument(trialCode, str(exported))
  other = Workspace.create(newStore("other"))
  other.importDocument(str(exported), standardStudy(other))
  assert other.receivedFiles(trialCode) == [] and len(workspace.receivedFiles(trialCode)) == 1
  assert other.contentHashFor(trialCode) == workspace.contentHashFor(trialCode)


def testAWorkbookImportedOnTheWebComesBackByteForByteWithItsSheetAndMapping(location):
  openpyxl = pytest.importorskip("openpyxl")
  workbook = openpyxl.Workbook()
  workbook.active.title = "Readme"
  workbook.active.append(["Collected by the field team"])
  sheet = workbook.create_sheet("Harvest")
  sheet.append(["Plot", "Yield kg", "Notes"])
  for index, plot in enumerate(plotNumbers(location)):
    sheet.append([plot, "NA" if index == 0 else 4000 + 10.5 * index, "ok"])
  buffer = io.BytesIO()
  workbook.save(buffer)
  data = buffer.getvalue()
  client = createApp(location).test_client()
  response = client.post(f"/trials/{trialCode}/import", data={
    "fileName": "harvest.xlsx", "fileData": base64.b64encode(data).decode(), "previewedSheet": "Harvest",
    "sheet": "Harvest", "decimal": ".", "shape": "wide", "plot": "0", "column-1": "YIELD", "column-2": "",
    "action": "import"})
  assert response.status_code == 200 and "Imported 12 observations from harvest.xlsx." in response.get_data(as_text=True)
  workspace = Workspace.open(location)
  [kept] = workspace.receivedFiles(trialCode)
  assert (kept.kind.value, kept.fileName, kept.sheetName, kept.sizeBytes, kept.sha256) == (
    "observations", "harvest.xlsx", "Harvest", len(data), sha256(data))
  assert (kept.importedBy.kind, kept.importedBy.name) == ("everyone", None)
  assert abs((datetime.datetime.now(datetime.UTC) - kept.importedAt).total_seconds()) < 300
  assert kept.mapping == {
    "format": "wide", "plotNumber": "Plot", "assessmentCode": None, "value": None, "subsample": None,
    "assessmentColumns": [{"column": "Yield kg", "assessmentCode": "YIELD", "subsample": None}],
    "unreadColumns": ["Notes"], "decimalSeparator": ".", "naTokens": naTokens}
  assert kept.produced == {"values": 11, "missing": 1,
                           "assessments": {"YIELD": {"values": 11, "missing": 1, "plotsWithout": 0}}}
  page = client.get(f"/trials/{trialCode}").get_data(as_text=True)
  assert '<section class="received"' in page and "harvest.xlsx" in page and "11 values, 1 marked missing" in page
  assert f'href="/trials/{trialCode}/received/{kept.fileID}"' in page and sha256(data) in page
  downloaded = client.get(f"/trials/{trialCode}/received/{kept.fileID}")
  assert downloaded.status_code == 200 and downloaded.data == data
  assert downloaded.mimetype == "application/octet-stream"
  assert downloaded.headers["Content-Disposition"] == "attachment; filename=harvest.xlsx"
  assert downloaded.headers["X-Content-Type-Options"] == "nosniff"
  assert client.get(f"/trials/{trialCode}/received/{kept.fileID + 1}").status_code == 404


def testTheNameIsKeptAsSentAndAnAPIBodyHasNone(location):
  client = createApp(location).test_client()
  first, second = yieldFile(location), severityFile(location)
  named = client.post(f"/api/trials/{trialCode}/observations?fileName=r%C3%A9colte%20%C3%A9t%C3%A9.csv", data=first)
  unnamed = client.post(f"/api/trials/{trialCode}/observations", data=second)
  assert (named.status_code, unnamed.status_code) == (201, 201)
  listed = client.get(f"/api/trials/{trialCode}/received").get_json()
  assert [(file["fileName"], file["sha256"], file["sizeBytes"]) for file in listed] == [
    ("r\u00e9colte \u00e9t\u00e9.csv", sha256(first), len(first)), (None, sha256(second), len(second))]
  assert listed == [file.model_dump(mode="json") for file in Workspace.open(location).receivedFiles(trialCode)]
  assert [client.get(f"/api/trials/{trialCode}/received/{file['fileID']}").data for file in listed] == [first, second]
  page = client.get(f"/trials/{trialCode}").get_data(as_text=True)
  assert "r\u00e9colte \u00e9t\u00e9.csv" in page and "(sent without a name)" in page
  dispositions = [client.get(f"/trials/{trialCode}/received/{file['fileID']}").headers["Content-Disposition"]
                  for file in listed]
  assert "filename*=UTF-8''r%C3%A9colte%20%C3%A9t%C3%A9.csv" in dispositions[0]
  assert dispositions[1] == f"attachment; filename=received-{listed[1]['fileID']}.csv"
  events = [event.detail for event in Workspace.open(location).auditEvents() if event.action == "values.import"]
  assert [(event["file"], event["receivedFile"], event["sha256"]) for event in events] == [
    (None, listed[1]["fileID"], sha256(second)), ("r\u00e9colte \u00e9t\u00e9.csv", listed[0]["fileID"], sha256(first))]


@pytest.mark.parametrize("fileName", ["two%0Alines.csv", "n" * 252 + ".csv"])
def testAFileNameThatCannotBeShownIsRefusedWithItsImport(location, fileName):
  client = createApp(location).test_client()
  refused = client.post(f"/api/trials/{trialCode}/observations?fileName={fileName}", data=yieldFile(location))
  assert refused.status_code == 400 and "is not a file name to keep" in refused.get_json()["error"]
  workspace = Workspace.open(location)
  assert workspace.loadObservations(trialCode) == [] and workspace.receivedFiles(trialCode) == []


def testAnImportThatIsRefusedKeepsNoFile(location):
  workspace = Workspace.open(location)
  profile = defaultConfig().importProfile
  workspace.importObservationFile(trialCode, "yield.csv", yieldFile(location), profile)
  with pytest.raises(Exception, match="already holds 12 of these values"):
    workspace.importObservationFile(trialCode, "again.csv", yieldFile(location), profile)
  with pytest.raises(Exception, match="plot 9999 is not in the trial layout"):
    workspace.importObservationFile(trialCode, "stray.csv", b"plotNumber,assessmentCode,value\n9999,SEV,low\n", profile)
  assert [file.fileName for file in workspace.receivedFiles(trialCode)] == ["yield.csv"]


# ---- what comes out is what went in ---------------------------------------------------------

def testAFileDamagedInTheStoreIsRefusedOnTheWayOut(location):
  workspace = Workspace.open(location)
  workspace.importObservationFile(trialCode, "yield.csv", yieldFile(location), defaultConfig().importProfile)
  [kept] = workspace.receivedFiles(trialCode)
  with Session(createDatabase(location, create=False)) as session:
    session.execute(update(ReceivedFileRow).values(content=yieldFile(location).replace(b",ok", b",no")))
    session.commit()
  with pytest.raises(StoreError, match=rf"received file {kept.fileID} of trial '{trialCode}' is damaged in the store"):
    workspace.receivedFile(trialCode, kept.fileID)
  with pytest.raises(StoreError, match="is damaged in the store"):
    workspace.bundleFor(trialCode)
  client = createApp(location).test_client()
  assert client.get(f"/trials/{trialCode}/received/{kept.fileID}").status_code == 400
  assert client.get(f"/api/trials/{trialCode}/bundle").status_code == 400


def testAFileLargerThanTheLimitIsRefusedAndNothingIsKept(location, tmp_path, capsys):
  data = yieldFile(location)
  path = tmp_path / "yield.csv"
  path.write_bytes(data)
  profile = defaultConfig().importProfile
  small = Workspace.open(location, maximumFileBytes=len(data) - 1)
  refusal = rf"'yield.csv' is {len(data)} bytes; an import takes, and keeps, a file of at most {len(data) - 1} bytes"
  with pytest.raises(StoreError, match=refusal):
    small.importObservations(trialCode, str(path), profile)
  with pytest.raises(StoreError, match=refusal):
    small.importObservationFile(trialCode, "yield.csv", data, profile)
  with pytest.raises(StoreError, match="'weather.csv' is 45 bytes; an import takes, and keeps, a file of at most 44"):
    Workspace.open(location, maximumFileBytes=len(weatherFile) - 1).importWeatherFile(trialCode, "weather.csv", weatherFile)
  config = tmp_path / "openfurrow.yaml"
  config.write_text(f"service:\n  maxUploadBytes: {len(data) - 1}\n", encoding="utf-8")
  assert main(["import", location, trialCode, str(path), "--config", str(config)]) == 1
  assert "an import takes, and keeps, a file of at most" in capsys.readouterr().err
  assert small.loadObservations(trialCode) == [] and small.receivedFiles(trialCode) == []
  Workspace.open(location, maximumFileBytes=len(data)).importObservations(trialCode, str(path), profile)
  assert [file.sizeBytes for file in small.receivedFiles(trialCode)] == [len(data)]


# ---- who may read them, and what becomes of them ---------------------------------------------------------

@pytest.fixture
def people(location):
  operator = Workspace.open(location)
  operator.importObservationFile(trialCode, "yield.csv", yieldFile(location), defaultConfig().importProfile)
  for userName, roleCode in (("vera", "viewer"), ("ana", "analyst"), ("nora", None)):
    operator.createAccount(userName, userName.title(), None, password)
    if roleCode is not None:
      operator.assignRole(RoleAssignment(roleCode=roleCode, scope=f"trial:{trialCode}", userName=userName))
  operator.createAccount("admin", "Admin", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  operator.setSetting("server", "identity.signInMode", "accounts")
  return operator


def actingAs(operator, userName):
  _, token = operator.signIn(userName, password, "web")
  return operator.actingAs(operator.actorForSession(token, "web"))


def signedInClient(location, userName):
  client = createApp(location).test_client()
  assert client.post("/signin", data={"userName": userName, "password": password}, headers=origin).status_code == 302
  return client


def testReadingReceivedFilesTakesThePermissionThatBringsThemIn(people, location):
  [kept] = people.receivedFiles(trialCode)
  vera, ana, nora = (actingAs(people, userName) for userName in ("vera", "ana", "nora"))
  for attempt in (lambda: vera.receivedFiles(trialCode), lambda: vera.receivedFile(trialCode, kept.fileID),
                  lambda: vera.bundleFor(trialCode)):
    with pytest.raises(NotPermitted, match=f"vera may not importValues at trial:{trialCode}"):
      attempt()
  with pytest.raises(NotFoundError, match=f"trial '{trialCode}' not found"):
    nora.receivedFiles(trialCode)
  assert ana.receivedFiles(trialCode) == [kept]
  assert ana.receivedFile(trialCode, kept.fileID) == (kept, yieldFile(location))
  assert (kept.importedBy.kind, kept.importedBy.name) == ("operator", None)

  viewing, analysing = signedInClient(location, "vera"), signedInClient(location, "ana")
  assert '<section class="received"' not in viewing.get(f"/trials/{trialCode}").get_data(as_text=True)
  assert viewing.get(f"/trials/{trialCode}/received/{kept.fileID}").status_code == 403
  assert viewing.get(f"/trials/{trialCode}/bundle").status_code == 403
  assert '<section class="received"' in analysing.get(f"/trials/{trialCode}").get_data(as_text=True)
  assert analysing.get(f"/trials/{trialCode}/received/{kept.fileID}").data == yieldFile(location)


def testAnAccountsImportNamesTheAccount(people, location):
  actingAs(people, "ana").importObservationFile(trialCode, "severity.csv", severityFile(location),
                                                defaultConfig().importProfile)
  assert [(file.fileName, file.importedBy.kind, file.importedBy.name) for file in people.receivedFiles(trialCode)] == [
    ("yield.csv", "operator", None), ("severity.csv", "account", "ana")]


def testTheFilesLeaveWithTheTrial(location):
  workspace = Workspace.open(location)
  workspace.importObservationFile(trialCode, "yield.csv", yieldFile(location), defaultConfig().importProfile)
  workspace.importWeatherFile(trialCode, "weather.csv", weatherFile)
  assert storedFileCount(location) == 2
  workspace.deleteTrial(trialCode)
  assert storedFileCount(location) == 0
  [deleted] = [event for event in workspace.auditEvents() if event.action == "trial.delete"]
  assert deleted.detail == {"place": standardPath, "receivedFiles": 2}


# ---- the bundle ---------------------------------------------------------

@pytest.fixture
def bundled(location, clock):
  """A trial with three received files, two of them the same bytes, and its bundle."""
  source = Workspace.open(location, clock=clock)
  source.importObservationFile(trialCode, "yield.csv", yieldFile(location), defaultConfig().importProfile)
  clock.moment += datetime.timedelta(days=1, microseconds=1)
  source.importWeatherFile(trialCode, "weather.csv", weatherFile)
  source.importWeatherFile(trialCode, "weather again.csv", weatherFile)
  return source, source.bundleFor(trialCode)


def testTheBundleIsTheDocumentAManifestAndTheFiles(bundled, location, tmp_path, capsys):
  source, _ = bundled
  observations = yieldFile(location)
  bundlePath, jsonPath = tmp_path / "trial.zip", tmp_path / "trial.json"
  assert main(["export", location, trialCode, "--bundle", str(bundlePath), "--json", str(jsonPath)]) == 0
  with zipfile.ZipFile(bundlePath) as bundle:
    assert bundle.namelist() == ["trial.json", "manifest.json"] + sorted(
      f"received/{digest}" for digest in (sha256(observations), sha256(weatherFile)))
    assert bundle.read("trial.json") == jsonPath.read_bytes()
    assert bundle.read(f"received/{sha256(observations)}") == observations
    assert bundle.read(f"received/{sha256(weatherFile)}") == weatherFile
    manifest = json.loads(bundle.read("manifest.json"))
  assert (manifest["bundleVersion"], manifest["trialCode"], manifest["contentHash"]) == (
    1, trialCode, source.contentHashFor(trialCode))
  assert [(file["kind"], file["fileName"], file["sha256"], file["sizeBytes"], file["importedAt"], file["importedBy"])
          for file in manifest["receivedFiles"]] == [
    ("observations", "yield.csv", sha256(observations), len(observations), "2026-03-01T09:30:15.250000Z",
     {"kind": "operator", "name": None}),
    ("weather", "weather.csv", sha256(weatherFile), len(weatherFile), "2026-03-02T09:30:15.250001Z",
     {"kind": "operator", "name": None}),
    ("weather", "weather again.csv", sha256(weatherFile), len(weatherFile), "2026-03-02T09:30:15.250001Z",
     {"kind": "operator", "name": None}),
  ]
  assert manifest["receivedFiles"][0]["mapping"]["unreadColumns"] == ["notes"]
  assert manifest["receivedFiles"][1]["produced"] == {"days": 2}
  assert bundlePath.read_bytes() == source.bundleFor(trialCode)


def testATrialSurvivesExportThenImportWithItsFilesAndItsHash(bundled, location, newStore, tmp_path, capsys):
  source, bundle = bundled
  bundlePath = tmp_path / "trial.zip"
  bundlePath.write_bytes(bundle)
  target = newStore("target")
  standardStudyAt(target)
  assert main(["import-bundle", target, str(bundlePath), "--place", standardPath]) == 0
  assert capsys.readouterr().out.strip() == f"Imported trial '{trialCode}' with 12 observations and 3 received files"
  copy = Workspace.open(target)
  assert copy.contentHashFor(trialCode) == source.contentHashFor(trialCode)
  assert [file.record() for file in copy.receivedFiles(trialCode)] == [file.record() for file in source.receivedFiles(trialCode)]
  assert [copy.receivedFile(trialCode, file.fileID)[1] for file in copy.receivedFiles(trialCode)] == [
    yieldFile(location), weatherFile, weatherFile]
  assert copy.bundleFor(trialCode) == bundle
  [added] = [event for event in copy.auditEvents() if event.action == "trial.add"]
  assert added.detail == {"place": standardPath, "values": 12, "receivedFiles": 3}
  assert main(["import-bundle", target, str(bundlePath), "--place", standardPath]) == 1
  assert f"trial '{trialCode}' already exists" in capsys.readouterr().err


def testTheAPIGivesAndTakesTheSameBundle(bundled, location, newStore):
  source, bundle = bundled
  assert createApp(location).test_client().get(f"/api/trials/{trialCode}/bundle").data == bundle
  assert createApp(location).test_client().get(f"/trials/{trialCode}/bundle").data == bundle
  target = newStore("target")
  standardStudyAt(target)
  taken = createApp(target).test_client().post(f"/api/bundles?place={standardPath}", data=bundle)
  assert taken.status_code == 201 and taken.get_json() == {
    "trialCode": trialCode, "contentHash": source.contentHashFor(trialCode), "receivedFiles": 3}
  assert Workspace.open(target).bundleFor(trialCode) == bundle


def rebuilt(bundle, change):
  with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
    members = {name: archive.read(name) for name in archive.namelist()}
  change(members)
  out = io.BytesIO()
  with zipfile.ZipFile(out, "w") as archive:
    for name, content in members.items():
      archive.writestr(name, content)
  return out.getvalue()


def changedManifest(members, **changes):
  members["manifest.json"] = json.dumps(json.loads(members["manifest.json"]) | changes).encode()


def changedDocument(members):
  document = json.loads(members["trial.json"])
  document["package"]["trial"]["title"] = "Another title"
  members["trial.json"] = json.dumps(document).encode()


def changedRecord(members, **changes):
  manifest = json.loads(members["manifest.json"])
  manifest["receivedFiles"][0] |= changes
  members["manifest.json"] = json.dumps(manifest).encode()


def changedFile(members):
  members[f"received/{sha256(weatherFile)}"] = weatherFile.replace(b"3", b"4")


@pytest.mark.parametrize("change, refusal", [
  (changedFile, "is not the 45 bytes with that SHA-256 the manifest names for received file 'weather.csv'"),
  (lambda members: members.pop(f"received/{sha256(weatherFile)}"), "the bundle lacks 'received/"),
  (lambda members: members.update({"received/extra": b"x"}), r"members its manifest does not name: \['received/extra'\]"),
  (changedDocument, "its manifest names 'ESV-2025-01' with"),
  (lambda members: changedManifest(members, bundleVersion=2), "is of version 2, and this build reads version 1"),
  (lambda members: changedManifest(members, receivedFiles="none"), "manifest.json is not a manifest"),
  (lambda members: changedRecord(members, produced={"values": "many"}), "a received file of kind observations says how many values it produced"),
  (lambda members: changedRecord(members, importedBy={"kind": "robot"}), "manifest.json is not a manifest"),
  (lambda members: changedRecord(members, importedBy={"kind": "account"}), "an importer of kind account needs its name"),
  (lambda members: changedRecord(members, importedAt="2026-03-01T09:30:15"), "manifest.json is not a manifest"),
  (lambda members: changedRecord(members, fileName="yield\n.csv"), "is not a file name to keep"),
  (lambda members: members.pop("manifest.json"), "not a trial bundle: it has no manifest.json"),
  (lambda members: members.pop("trial.json"), "not a trial bundle: it has no trial.json"),
])
def testABundleThatDoesNotAgreeWithItsManifestIsRefusedWhole(bundled, newStore, change, refusal):
  _, bundle = bundled
  target = Workspace.create(newStore("target"))
  with pytest.raises(ExchangeError, match=refusal):
    target.addBundle(rebuilt(bundle, change), standardStudy(target))
  assert target.listTrials() == []


def testWhatIsNotABundleOrTooLargeIsRefused(bundled, location, newStore):
  _, bundle = bundled
  target = Workspace.create(newStore("target"))
  place = standardStudy(target)
  with pytest.raises(ExchangeError, match="not a trial bundle: not a zip archive"):
    target.addBundle(b"plotNumber,value\n1,2\n", place)
  limit = len(yieldFile(location)) - 1
  small = Workspace.open(newStore("target"), maximumFileBytes=limit)
  refusal = rf"bundle member '(trial.json|received/[0-9a-f]+)' is \d+ bytes; the limit for a file is {limit}"
  with pytest.raises(ExchangeError, match=refusal):
    small.addBundle(bundle, place)
  assert target.listTrials() == [] and storedFileCount(newStore("target")) == 0
