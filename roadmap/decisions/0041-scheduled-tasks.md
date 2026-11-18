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
  parameters it takes (a pydantic model, checked when the task is saved), a default schedule
  and time limit, and the function a run calls, which returns a one-line summary. A task is
  a name (a lower-case letter, then letters, digits and `-`), the kind, its parameters, a
  schedule, a time limit (1 second to 24 hours) and whether it is enabled; one kind can be
  configured many times (a report for each place, say). Kinds that OpenFurrow's own features
  need are created with their feature and name it in the data: a federation provider with a
  discovery aggregate gets the task `federationRefresh-<provider>`, owned by the provider, so
  it can be changed but is not deleted while the provider uses it, and its first run is
  requested at once so the list is loaded without waiting for the schedule.
- **A schedule is a five-field cron expression** (minute, hour, day of month, month, day of
  week) read in the server's time zone, the setting `tasks.timeZone` (an IANA name, UTC by
  default), as administrators know it from cron and from Windows Task Scheduler's
  equivalents. The web form takes the expression with the common ones shown as examples
  ("every six hours" is `0 */6 * * *`). OpenFurrow reads it itself: no third-party
  scheduler library. Each task keeps its next run time, worked out again when its schedule,
  the zone or its enabled flag changes; a disabled task has none. A run missed while the
  scheduler was stopped runs once when it starts, not once per missed time.
- **The scheduler is its own process**, `openfurrow scheduler <store>`, beside the web
  server, installed as a service by the same install command once it exists (decision
  0009). Every two seconds it checks in, finds the tasks that are due and the runs requested
  by hand, and starts each run as a subprocess (`python -m openfurrow.tasks.run <run>`, the
  store's location in the environment variable `OPENFURROW_STORE` rather than on the command
  line, where any user of the machine could read a database password), so a crash, a hang
  or memory a run holds never reaches the scheduler or another run. A run past its task's
  time limit is terminated, killed if it does not end, and recorded as stopped. At most one
  run of a task at a time: a run due while the previous one is still going is recorded as
  skipped, and "run now" is refused while one is requested or running. How many runs go at
  once is the server setting `tasks.maximumConcurrentRuns` (2).
- **A run is a fresh Python process**: it reads the store and the task itself, acts through
  the facade as the scheduler for its task, and records its own outcome (succeeded with its
  summary, or failed with the error); everything it logs is its output. A process that ends
  without recording an outcome (a crash, an exit) is recorded failed by the scheduler with
  its exit code and its output.
- **Due times and runs are claimed in the database**, so two schedulers on one store (a
  mistake, or two hosts of a cluster) never act twice: a due time is taken by one
  conditional update of the task's next run time, and a run moves from requested to running
  by one conditional update; only the scheduler whose update took acts on it. A running run
  records its host and the scheduler's and its own process, so a scheduler finds a run left
  running on its host by a scheduler that died: failed when its process is gone too, stopped
  at its time limit when its process outlived the scheduler.
- **Stopping the scheduler** (Ctrl+C or SIGTERM; Ctrl+Break on Windows) ends the claiming
  of new runs and waits for the running ones for a grace period (20 seconds); those still
  going then, or at a second signal, are stopped and recorded so. Runs start in a process
  group of their own, so a console's Ctrl+C reaches the scheduler only.
- **Every run is recorded**: who or what asked for it (the schedule, or the account that
  pressed "run now", or the operator), when it was asked for, started and finished, its
  outcome (succeeded, failed, stopped, skipped), the one-line summary, and the last 64 KB of
  its output, marked when earlier output was left out. Run records are kept for 90 days by
  default, the setting `tasks.runRetentionDays`; the scheduler removes older ones.
- **Rights**: a permission, `manageTasks`, at server scope, held by the administrator role,
  lets its holder see the tasks and their runs, change a schedule or time limit, enable or
  disable a task and run it now. Each change is audited (decision 0038). A run that changes
  data acts as the scheduler (the actor kind `scheduler`, naming the task) in the audit log.
- **The web interface** has a tasks page for holders of `manageTasks`, linked from the
  masthead: each task with its schedule, its next run in the server's zone, and its last
  run's outcome and time; and how long ago the scheduler checked in, with a warning when it
  has not for over a minute or never has. Each task's page has the form to change the
  schedule and time limit (in minutes), enable or disable it, and "run now", and the task's
  run history with each run's output. The command line has the same: `openfurrow task
  list|show|set|enable|disable|run|runs`, with `--time-limit` as 90s, 15m or 2h.

## Consequences

- Store version 19: the task and run tables, the scheduler's check-in, and a federation's
  stored discovery list (decision 0040). The scheduler and the web server share the store,
  so a schedule changed on the page is the scheduler's next read.
- Without the scheduler running, nothing scheduled happens; the tasks page says when the
  scheduler last checked in, so a stopped scheduler is seen rather than silently missed.
- A run whose scheduler died on another host is not detected: only the host's own
  scheduler can see whether the process lives.
- Tasks are made by the features that need them, or through the library; there is no
  command or page to add or delete one yet.
