# SPDX-License-Identifier: Apache-2.0
"""Portable exchange: JSON and CSV import/export for trial documents.

Data ownership means a trial is never trapped in the store. A trial document
exports to a single JSON file -- the portable, human-readable archival artifact,
re-validated on import -- and observations export to long-format CSV annotated with
block and treatment for spreadsheets, R, and pandas. The JSON round-trips to the
same content hash as the database, so an exported file is a faithful, movable copy
of the record, not a lossy dump.

A trial bundle (decision 0044) carries the files as received beside that document, in
one zip archive:

- `trial.json`: the trial document, byte for byte what the JSON export writes;
- `manifest.json`: the bundle's version, the trial's code and content hash, and one
  record per received file (kind, name, sheet, SHA-256, size, column mapping, who
  imported it, when, and what it produced);
- `received/<SHA-256>`: each file's bytes, named by their hash, so the same bytes
  received twice travel once.

The archive is written without compression, with fixed dates and attributes, so the
same trial gives the same bytes on every platform. Reading one checks everything
against everything: the document against the manifest's content hash, every file
against its size and hash, and no member that the manifest does not name.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile

from pydantic import BaseModel, ConfigDict, ValidationError

from openfurrow.received import ReceivedFileRecord, sha256Of
from openfurrow.schema.document import TrialDocument, contentHash

bundleVersion = 1
documentMember = "trial.json"
manifestMember = "manifest.json"
receivedFolder = "received/"


class ExchangeError(ValueError):
  """A file is not a trial document that can be imported."""


def documentBytes(document: TrialDocument) -> bytes:
  """A trial document as deterministic, human-readable JSON: UTF-8 with LF line endings on every platform."""
  return (json.dumps(document.canonicalDict(), sort_keys=True, indent=2) + "\n").encode("utf-8")


def exportJson(document: TrialDocument, path: str) -> None:
  """Write a trial document to a JSON file."""
  with open(path, "wb") as handle:
    handle.write(documentBytes(document))


def readDocument(data: bytes) -> TrialDocument:
  """Validate a trial document's JSON bytes.

  Validation is the schema's: a malformed package (too few treatments, a bad enum,
  an out-of-domain field), a layout that does not fit the package, or an observation
  on a plot the layout does not have is rejected here, not silently accepted.
  """
  try:
    content = json.loads(data.decode("utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as error:
    raise ExchangeError(f"not valid JSON: {error}") from error
  try:
    return TrialDocument.model_validate(content)
  except ValidationError as error:
    raise ExchangeError(f"not a valid trial document: {error}") from error


def importJson(path: str) -> TrialDocument:
  """Read and validate a trial document from a JSON file."""
  with open(path, "rb") as handle:
    return readDocument(handle.read())


class BundleManifest(BaseModel):
  model_config = ConfigDict(extra="forbid")

  bundleVersion: int
  trialCode: str
  contentHash: str
  receivedFiles: list[ReceivedFileRecord]


def _member(name: str) -> zipfile.ZipInfo:
  # Fixed, so the archive's bytes depend on the trial alone: zipfile would otherwise write the present time and the
  # system it runs on.
  info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
  info.compress_type = zipfile.ZIP_STORED
  info.create_system = 3
  info.external_attr = 0o644 << 16
  return info


def bundleBytes(document: TrialDocument, files: list[tuple[ReceivedFileRecord, bytes]]) -> bytes:
  """A trial bundle: the document, a manifest, and the received files' bytes."""
  manifest = BundleManifest(bundleVersion=bundleVersion, trialCode=document.package.trial.trialCode,
                            contentHash=contentHash(document), receivedFiles=[record for record, _ in files])
  for record, content in files:
    if len(content) != record.sizeBytes or sha256Of(content) != record.sha256:
      raise ExchangeError(f"received file '{record.fileName}' is not the bytes its record names")
  contents = {record.sha256: content for record, content in files}
  archive = io.BytesIO()
  with zipfile.ZipFile(archive, "w") as bundle:
    bundle.writestr(_member(documentMember), documentBytes(document))
    bundle.writestr(_member(manifestMember),
                    (json.dumps(manifest.model_dump(mode="json"), sort_keys=True, indent=2) + "\n").encode("utf-8"))
    for digest in sorted(contents):
      bundle.writestr(_member(receivedFolder + digest), contents[digest])
  return archive.getvalue()


def readBundle(data: bytes, maximumMemberBytes: int) -> tuple[TrialDocument, list[tuple[ReceivedFileRecord, bytes]]]:
  """The document and received files of a trial bundle, each checked against the manifest."""
  try:
    archive = zipfile.ZipFile(io.BytesIO(data))
  except zipfile.BadZipFile as error:
    raise ExchangeError("not a trial bundle: not a zip archive") from error
  with archive:
    def read(name: str) -> bytes:
      try:
        return archive.read(name)
      except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ExchangeError(f"bundle member '{name}' cannot be read: {error}") from error

    sizes: dict[str, int] = {}
    for info in archive.infolist():
      if info.filename in sizes:
        raise ExchangeError(f"not a trial bundle: member '{info.filename}' is there twice")
      if info.file_size > maximumMemberBytes:
        raise ExchangeError(f"bundle member '{info.filename}' is {info.file_size} bytes; the limit for a file is "
                            f"{maximumMemberBytes}")
      sizes[info.filename] = info.file_size
    lacking = [name for name in (documentMember, manifestMember) if name not in sizes]
    if lacking:
      raise ExchangeError(f"not a trial bundle: it has no {' and no '.join(lacking)}")
    try:
      manifest = BundleManifest.model_validate(json.loads(read(manifestMember).decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
      raise ExchangeError(f"the bundle's {manifestMember} is not a manifest: {error}") from error
    if manifest.bundleVersion != bundleVersion:
      raise ExchangeError(f"the bundle is of version {manifest.bundleVersion}, and this build reads version {bundleVersion}")
    document = readDocument(read(documentMember))
    if (document.package.trial.trialCode, contentHash(document)) != (manifest.trialCode, manifest.contentHash):
      raise ExchangeError(
        f"the bundle's {documentMember} is trial '{document.package.trial.trialCode}' with content hash "
        f"{contentHash(document)}; its manifest names '{manifest.trialCode}' with {manifest.contentHash}"
      )
    named = {receivedFolder + record.sha256 for record in manifest.receivedFiles}
    stray = sorted(set(sizes) - named - {documentMember, manifestMember})
    if stray:
      raise ExchangeError(f"the bundle holds members its manifest does not name: {stray}")
    files = []
    for record in manifest.receivedFiles:
      member = receivedFolder + record.sha256
      if member not in sizes:
        raise ExchangeError(f"the bundle lacks '{member}', the bytes of received file '{record.fileName}'")
      content = read(member)
      if len(content) != record.sizeBytes or sha256Of(content) != record.sha256:
        raise ExchangeError(f"bundle member '{member}' is not the {record.sizeBytes} bytes with that SHA-256 the "
                            f"manifest names for received file '{record.fileName}'")
      files.append((record, content))
  return document, files


def exportObservationsCsv(document: TrialDocument, path: str) -> None:
  """Write observations as long-format CSV, annotated with block and treatment.

  Block and treatment come from the document's layout, giving a file that is
  directly analyzable in a spreadsheet or R. An untreated check beside the plots has
  no treatment and names the plots it is the check for. A missing value, and the
  subsample of a value that is not one, are written as empty cells.
  """
  plotInfo = {plot.plotNumber: (plot.block, plot.treatmentCode, "") for plot in document.layout}
  plotInfo |= {
    check.plotNumber: (check.block, "", " ".join(str(number) for number in check.pairedPlots))
    for check in document.checkPlots
  }
  orderedObservations = sorted(
    document.observations, key=lambda row: (row.plotNumber, row.assessmentCode, row.subsample or 0),
  )

  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "block", "treatment", "checkFor", "assessmentCode", "subsample", "value"])
    for observation in orderedObservations:
      block, treatment, checkFor = plotInfo[observation.plotNumber]
      value = "" if observation.value is None else observation.value
      subsample = "" if observation.subsample is None else observation.subsample
      writer.writerow([observation.plotNumber, block, treatment, checkFor, observation.assessmentCode, subsample, value])
