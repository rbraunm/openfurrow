# SPDX-License-Identifier: Apache-2.0
"""Task kinds that exist only for the tests, registered when this module is imported: one that logs and succeeds, one
that sleeps, one that raises, one whose process dies without a word to the store, and one that writes a lot."""

import os
import sys
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from openfurrow.tasks.kinds import register
from openfurrow.tasks.model import TaskKind


class Message(BaseModel):
  model_config = ConfigDict(extra="forbid")

  message: str


class Seconds(BaseModel):
  model_config = ConfigDict(extra="forbid")

  seconds: float
  startedFile: str | None = None


class Nothing(BaseModel):
  model_config = ConfigDict(extra="forbid")


def echo(context, parameters):
  context.logger.info("echo says %s", parameters.message)
  return f"said {parameters.message}"


def sleep(context, parameters):
  context.logger.info("sleeping %s seconds", parameters.seconds)
  if parameters.startedFile is not None:
    Path(parameters.startedFile).write_text("sleeping", encoding="ascii")
  time.sleep(parameters.seconds)
  return f"slept {parameters.seconds} seconds"


def fail(context, parameters):
  context.logger.info("about to fail")
  raise RuntimeError("the test kind fails on purpose")


def crash(context, parameters):
  context.logger.info("about to crash")
  sys.stdout.flush()
  os._exit(3)


def loud(context, parameters):
  for line in range(4000):
    print(f"line {line:05d} " + "x" * 40)
  return "wrote 4000 lines"


for kind in (TaskKind("testEcho", Message, "*/10 * * * *", 60, echo),
             TaskKind("testSleep", Seconds, "*/10 * * * *", 3600, sleep),
             TaskKind("testFail", Nothing, "0 0 * * *", 60, fail),
             TaskKind("testCrash", Nothing, "0 0 * * *", 60, crash),
             TaskKind("testLoud", Nothing, "0 0 * * *", 60, loud)):
  register(kind)
