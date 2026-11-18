# SPDX-License-Identifier: Apache-2.0
"""One run of a scheduled task, in a process of its own (decision 0041): `python -m openfurrow.tasks.run <runID>`.

The scheduler starts it once it has claimed the run, with the store's location in the
environment variable OPENFURROW_STORE rather than on the command line, where any user of
the machine could read a database password. The run reads the store and the task itself,
calls the task's kind with a Workspace acting as the scheduler for the task, and records
its own outcome; everything it logs goes to standard output, which the scheduler keeps
as the run's output. A run that ends without recording an outcome is recorded failed by
the scheduler.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
import time

from sqlalchemy import update
from sqlalchemy.orm import Session

from openfurrow.identity.model import Actor
from openfurrow.store.database import ScheduledTaskRow, TaskRunRow, createDatabase
from openfurrow.store.tasks import stored
from openfurrow.tasks.kinds import kindNamed
from openfurrow.tasks.model import RunContext, RunState
from openfurrow.workspace import Workspace

storeVariable = "OPENFURROW_STORE"


def _outcome(engine, runID: int, state: RunState, summary: str) -> None:
  with Session(engine) as session:
    session.execute(update(TaskRunRow).where(TaskRunRow.runID == runID, TaskRunRow.state == RunState.running.value)
                    .values(state=state.value, summary=" ".join(summary.split()),
                            finishedAt=stored(datetime.datetime.now(datetime.UTC)), processID=None,
                            schedulerProcessID=None))
    session.commit()


def _logger() -> logging.Logger:
  handler = logging.StreamHandler(sys.stdout)
  formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%SZ")
  formatter.converter = time.gmtime
  handler.setFormatter(formatter)
  logger = logging.getLogger("openfurrow.task")
  logger.addHandler(handler)
  logger.setLevel(logging.INFO)
  logger.propagate = False
  return logger


def main(argv: list[str]) -> int:
  if len(argv) != 1 or not argv[0].isdigit():
    print("usage: python -m openfurrow.tasks.run <runID>, with the store's location in OPENFURROW_STORE", file=sys.stderr)
    return 2
  location = os.environ.get(storeVariable)
  if not location:
    print(f"the environment variable {storeVariable} names no store", file=sys.stderr)
    return 2
  runID = int(argv[0])
  engine = createDatabase(location, create=False)
  with Session(engine) as session:
    run = session.get(TaskRunRow, runID)
    if run is None or run.state != RunState.running.value:
      print(f"run {runID} is not a running run of this store", file=sys.stderr)
      return 2
    task = session.get(ScheduledTaskRow, run.taskName)
    kindName, taskName, parametersJSON = task.kind, task.name, task.parametersJSON
  logger = _logger()
  try:
    kind = kindNamed(kindName)
    parameters = kind.parameters.model_validate_json(parametersJSON)
    workspace = Workspace(engine, Actor.scheduler(taskName))
    summary = kind.run(RunContext(runID=runID, taskName=taskName, workspace=workspace, logger=logger), parameters)
  except Exception as error:
    logger.exception("run %s of %s failed", runID, taskName)
    _outcome(engine, runID, RunState.failed, f"{type(error).__name__}: {error}")
    return 1
  logger.info("run %s of %s succeeded: %s", runID, taskName, summary)
  _outcome(engine, runID, RunState.succeeded, summary)
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
