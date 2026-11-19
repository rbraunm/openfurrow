# SPDX-License-Identifier: Apache-2.0
"""The file as received (decision 0044, worklist REC-16).

Every import from a file keeps the file beside the trial: its bytes, their SHA-256, the
name it was sent under, the sheet that was read, the columns as they were mapped, who
imported it, when, and what the import made of it. The file is not part of the trial
document and not in its content hash: the hash covers the record the values became, and
the file is the evidence of where they came from. It leaves with the trial, or earlier
when its retention rule lets it go.
"""

from __future__ import annotations

import datetime
import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReceivedFileKind(str, Enum):
  observations = "observations"
  weather = "weather"
  layout = "layout"


class Importer(BaseModel):
  """Who imported a file, as the audit log names actors: the kind, and the name of an account, task or workload rule."""

  model_config = ConfigDict(extra="forbid")

  kind: str
  name: str | None = None


class ReceivedFileRecord(BaseModel):
  """What is kept about a received file beside its bytes; the form it travels in, in a bundle's manifest."""

  model_config = ConfigDict(extra="forbid")

  kind: ReceivedFileKind
  fileName: str | None = Field(description="The name the file was sent under; none for a request body sent without one.")
  sheetName: str | None = Field(description="The sheet of a workbook that was read.")
  sha256: str
  sizeBytes: int
  mapping: dict[str, Any] = Field(description="The columns as they were read.")
  produced: dict[str, Any] = Field(description="What the import made of the file, in counts.")
  importedBy: Importer
  importedAt: datetime.datetime


class ReceivedFile(ReceivedFileRecord):
  """A received file as a store holds it."""

  fileID: int
  trialCode: str

  def record(self) -> ReceivedFileRecord:
    return ReceivedFileRecord(**self.model_dump(exclude={"fileID", "trialCode"}))


def sha256Of(content: bytes) -> str:
  return hashlib.sha256(content).hexdigest()
