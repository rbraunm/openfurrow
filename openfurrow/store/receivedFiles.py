# SPDX-License-Identifier: Apache-2.0
"""Files as received, in the store (decision 0044).

The bytes live in the database, in a column read only when a file is asked for, so a
store stays one file or one database with nothing beside it. What comes out is checked
against the SHA-256 taken when it went in.
"""

from __future__ import annotations

import datetime
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.identity.model import Actor
from openfurrow.received import Importer, ReceivedFile, ReceivedFileKind, ReceivedFileRecord, sha256Of
from openfurrow.store.database import NotFoundError, ReceivedFileRow, StoreError, TrialRow
from openfurrow.store.tasks import aware, stored


def _file(row: ReceivedFileRow) -> ReceivedFile:
  return ReceivedFile(
    fileID=row.fileID, trialCode=row.trialCode, kind=ReceivedFileKind(row.kind), fileName=row.fileName,
    sheetName=row.sheetName, sha256=row.sha256, sizeBytes=row.sizeBytes, mapping=json.loads(row.mappingJSON),
    produced=json.loads(row.producedJSON), importedBy=Importer(kind=row.importedByKind, name=row.importedByName),
    importedAt=aware(row.importedAt),
  )


def _add(session: Session, trialCode: str, record: ReceivedFileRecord, content: bytes) -> ReceivedFileRow:
  if session.get(TrialRow, trialCode) is None:
    raise NotFoundError(f"trial '{trialCode}' not found")
  if len(content) != record.sizeBytes or sha256Of(content) != record.sha256:
    raise StoreError(f"the bytes given for received file '{record.fileName}' are not the {record.sizeBytes} bytes "
                     f"with SHA-256 {record.sha256} its record names")
  row = ReceivedFileRow(
    trialCode=trialCode, kind=record.kind.value, fileName=record.fileName, sheetName=record.sheetName,
    sha256=record.sha256, sizeBytes=record.sizeBytes, content=content,
    mappingJSON=json.dumps(record.mapping, sort_keys=True), producedJSON=json.dumps(record.produced, sort_keys=True),
    importedByKind=record.importedBy.kind, importedByName=record.importedBy.name, importedAt=stored(record.importedAt),
  )
  session.add(row)
  session.flush()
  return row


def keepFile(session: Session, trialCode: str, kind: ReceivedFileKind, fileName: str | None, sheetName: str | None,
             content: bytes, mapping: dict, produced: dict, actor: Actor, at: datetime.datetime) -> ReceivedFile:
  """Keep a file an import just read, in the import's own transaction."""
  record = ReceivedFileRecord(
    kind=kind, fileName=fileName, sheetName=sheetName, sha256=sha256Of(content), sizeBytes=len(content),
    mapping=mapping, produced=produced, importedBy=Importer(kind=actor.kind.value, name=actor.name), importedAt=at,
  )
  return _file(_add(session, trialCode, record, content))


def restoreFile(session: Session, trialCode: str, record: ReceivedFileRecord, content: bytes) -> None:
  """Keep a file that came with its record in a bundle: who imported it and when stay as they were."""
  _add(session, trialCode, record, content)


def listFiles(session: Session, trialCode: str) -> list[ReceivedFile]:
  """A trial's received files in the order they came, without their bytes."""
  if session.get(TrialRow, trialCode) is None:
    raise NotFoundError(f"trial '{trialCode}' not found")
  rows = session.execute(
    select(ReceivedFileRow).where(ReceivedFileRow.trialCode == trialCode).order_by(ReceivedFileRow.fileID)
  ).scalars().all()
  return [_file(row) for row in rows]


def fileContent(session: Session, trialCode: str, fileID: int) -> tuple[ReceivedFile, bytes]:
  """A received file and its bytes, refused when they are no longer the bytes that were received."""
  row = session.get(ReceivedFileRow, fileID)
  if row is None or row.trialCode != trialCode:
    raise NotFoundError(f"trial '{trialCode}' holds no received file {fileID}")
  content = bytes(row.content)
  if len(content) != row.sizeBytes or sha256Of(content) != row.sha256:
    raise StoreError(
      f"received file {fileID} of trial '{trialCode}' is damaged in the store: its bytes hash to {sha256Of(content)}, "
      f"not the {row.sha256} recorded when it was received"
    )
  return _file(row), content
