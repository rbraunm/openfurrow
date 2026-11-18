# 0041 - Scheduled tasks

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Some work has to happen on a schedule rather than at a request: refreshing a research
federation's aggregate (eduGAIN's is 95 MB and asks to be refetched every few hours,
decision 0040), and in time maintenance (retention, GOV-5), reports and audit summaries for
administrators. The owner (2026-11-18) asked for one scheduled-task system for all of it,
whose schedules an administrator sees and changes in the web interface, with any task run
at once on request; it runs in a separate scheduler process, and each run is its own
subprocess so runs never collide with each other or with the scheduler.

## Decision

- **A task kind is code; a task is configuration.** OpenFurrow defines the kinds (the first:
  `federationRefresh`, which refreshes one federation provider's aggregate), each with the
  parameters it takes, checked when the task is saved. An administrator configures tasks
  of those kinds: a name, the kind, its parameters, a schedule, a time limit and whether it
  is enabled. One kind can be configured many times (a report for each place, say). Kinds
  that OpenFurrow's own features need are created with their feature and can be changed but
  not deleted while the feature uses them.
- **A schedule is a five-field cron expression** (minute, hour, day of month, month, day of
  week) read in the server's time zone setting, as administrators know it from cron and
  from Windows Task Scheduler's equivalents; the web form offers the common ones ("every N
  hours", "daily at", "weekly on") and writes the expression. OpenFurrow reads it itself:
  no third-party scheduler library. A run missed while the scheduler was stopped runs once
  when it starts, not once per missed time.
- **The scheduler is its own process**, `openfurrow scheduler`, installed as a service
  beside the web server by the same install command (decision 0009). It wakes every few
  seconds, finds the tasks that are due and the runs requested by hand, and starts each run
  as a subprocess (`python -m openfurrow.tasks.run <run>`), so a crash, a hang or memory a
  run holds never reaches the scheduler or another run. A run past its task's time limit is
  stopped and recorded as such. At most one run of a task at a time; a run due while the
  previous one is still going is recorded as skipped. How many runs go at once is a server
  setting.
- **Runs are claimed in the database**, so two schedulers on one store (a mistake, or two
  hosts of a cluster) never start the same run twice: a run moves from requested to
  running by one conditional update, and only the scheduler whose update took starts it.
- **Every run is recorded**: who or what asked for it (the schedule, or the account that
  pressed "run now"), when it was asked for, started and finished, its outcome (succeeded,
  failed, stopped at its time limit, skipped), a one-line summary the task writes, and the
  run's output up to 64 KB. Run records are kept for 90 days by default, a retention
  setting.
- **Rights**: a new permission, `manageTasks`, at server scope, lets an administrator see
  the tasks and their runs, change a schedule, enable or disable a task and run it now.
  Each of those is audited (decision 0038). A run that changes data acts as the scheduler
  (a new actor kind, `scheduler`, naming the task) in the audit log.
- **The web interface** has a tasks page for holders of `manageTasks`: each task with its
  schedule in words, its next and last run and outcome, a form to change the schedule and
  limit, enable and disable, and "run now"; and each task's run history with the output.
  The command line has the same (`openfurrow task list|show|set|enable|disable|run`).

## Consequences

- Store: the task and run tables; the scheduler and the web server share the store, so a
  schedule changed on the page is the scheduler's next read.
- Without the scheduler running, nothing scheduled happens; the tasks page says when the
  scheduler last checked in, so a stopped scheduler is seen rather than silently missed.
- A run is a fresh Python process: it reads the store and settings itself and needs no
  state from the scheduler.
