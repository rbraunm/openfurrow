# 0044 - Retention, and the files as received

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The owner's direction (2026-11-16, worklist "Policies are settings"): how long data is kept
is a setting, not a rule the project fixes, and retention is a system of its own -- each
kind of stored data in its own area, monitored, and pruned when its owners decide
(`governance-plan.md`, F6). The readiness bar asks for "the original data kept as received"
(worklist USR-6), and the brief for the resolved column mapping to be recorded; until now
an import saved the values and dropped the file and the mapping (REC-16).

The forks were where the received bytes live, how they travel with a trial without entering
its content hash, what "pruning a trial's record" may mean when the hash must never change,
and how the audit log can be pruned without erasing the trail of its own pruning.

## Decision

### The file as received

- **Every import from a file keeps the file**, in the same transaction as what it imports:
  observations (the import page, the command line, the API's CSV endpoints, a Field Book
  export), a weather log, and a layout uploaded as planted. Kept are the bytes, their
  SHA-256, the name the file was sent under, the sheet read, the column mapping as resolved
  against the file's header (the columns read and as what, the columns left unread, the
  decimal mark and the tokens read as missing; a weather file's columns with their units), who
  imported it, when, and what it produced in counts. An import that is refused keeps nothing.
  An API body sent without a name has none recorded; `?fileName=` sends one.
- **The bytes live in the database**, so a store stays one file or one database with nothing
  beside it. They are bounded by the one limit there was, the configuration's
  `service.maxUploadBytes` (16 MiB by default), which now holds on every surface: a larger
  request is refused before it is read, as before, and a larger file named on the command line
  or to the library is refused by name before it is read.
- **Outside the content hash.** The hash covers the record the values became; the file is the
  evidence of where they came from. A trial hashes the same with its files, without them, and
  after they are pruned.
- **Read back exactly.** Listing and downloading take `importValues` at the trial: those who
  may bring files in may read them back; a viewer, or someone given data entry on one trial,
  may not, since a file can hold more than was imported from it. What comes out is checked
  against the SHA-256 taken on the way in, and a file whose bytes no longer match is refused,
  not served. The web serves it as a download and never as a page.
- **A trial bundle carries them.** The JSON exchange stays what it is. A bundle is one zip
  archive holding `trial.json` (byte for byte the JSON export), `manifest.json` (the bundle's
  version, the trial's code and content hash, and each file's record) and `received/<SHA-256>`
  for each file's bytes, so the same bytes received twice travel once. It is written without
  compression and with fixed dates, so a trial gives the same archive on every platform.
  Importing one checks the document against the manifest's hash and every file against its
  size and hash, refuses a member the manifest does not name and a record no import could
  have written (a name with control characters, an importer of no known kind, counts that are
  not its kind's), and restores each file as it was recorded, the importer and the time
  included. `export --bundle`, `import-bundle`, the API's
  `/api/trials/<code>/bundle` and `/api/bundles`, and a download on the trial's page.
- **Removed with the trial**, or earlier by their own retention rule.

### Storage areas

- **Five areas**, each with its count and size on the retention page and in
  `openfurrow retention status`: trial records; files as received; the audit log; sessions and
  tokens (sessions, API tokens, sign-ins waiting for a provider, and message identifiers used
  once); task runs.
- **No area for reports and exports**: nothing of that kind is stored. A report is built when
  it is asked for and an export is written to the asker; an area is added when one is kept.
- **A size is the bytes of the content held** -- a trial's canonical document, a file's bytes,
  the text of an event, a session or a run -- not the space the database engine uses for it,
  which differs between SQLite and PostgreSQL.

### Rules

- **One setting per area**, `retention.<area>`, in the registry of decision 0035:
  - `keep`: nothing leaves until someone decides;
  - `keepFor:<period>`: a record leaves once older than the period;
  - `keepUntilClosed:<period>`: a trial's records stay while the trial is open and for the
    period after its closed date.

  A period is `P90D`, `P18M` or `P5Y`: days, months or years. A record is older than a period
  when its time is at or before now less the period.
- **What an owner would miss is kept by default; what has only expired is not.** Trial
  records, files as received and the audit log default to `keep`. Expired sessions and tokens
  default to `keepFor:P30D` and finished task runs to `keepFor:P90D`, the ninety days the
  scheduler kept runs before this decision, so a store nobody has configured does not grow
  without bound with every sign-in and every run of a task. An owner who wants those kept as
  well sets `keep`.
- **Each area takes the rules and scopes that fit it.** Sessions and tokens and task runs are
  the server's: `keep` or `keepFor`, set at the server. Received files and the audit log take
  all three, down to the trial. A trial's record takes `keep` or `keepUntilClosed` only, down
  to the trial: while a trial is open there is no date its record's age could run from.
- **What a period runs from**: a received file's import; an event's own time; a session's,
  token's, pending sign-in's or message claim's expiry (one that has not expired, or never
  does, is not retention's to remove); a run's finish (one requested or running stays).
- **The audit log's rule is the one that holds at each event's scope**, the trial's, the
  place's or the server's. When the place or trial is gone, its own settings went with it and
  the server's rule holds. Under `keepUntilClosed`, an event outside any trial in the store has
  no closing, so its period runs from the event itself.
- **Changing a setting takes the permission the setting names** (the registry carries it, as
  `governance-plan.md` F2 set out): `manageRetention` for the retention rules,
  `changeSettings` for the rest. A trial manager can therefore not shorten the life of a
  trial's audit trail.

### Closing a trial

- **A closed date**, set and cleared with `manageTrials` at the trial, today or earlier by the
  server's time zone (`tasks.timeZone`), audited, shown on the trial's page; `openfurrow close`
  and `reopen`. Like a trial's place it is a fact of the store, outside the content hash and
  not carried by a document or a bundle.
- **It has no other effect.** Retention counts from it; a closed trial still takes imports and
  edits. What a closed trial refuses is the editing policy, a later setting
  (`governance-plan.md`, F2).

### Pruning

- **A preview lists exactly what would go** and changes nothing: for each area and scope, the
  count, the bytes, the rule and where it was set; each trial by code, title and content hash;
  each file by name, size and SHA-256. Pruning works out the same selection in its own
  transaction and hands back the same lines.
- **A trial's record leaves only whole.** Pruning never removes part of what a content hash
  covers, so every trial in the store hashes the same before and after. When a record's rule
  lets it go the whole trial is removed, with its received files, as deleting it would.
- **Pruning takes `manageRetention` at the server**, and is audited.
- **A hold stops every pruning that concerns a trial**: its record, its files and the events
  at its scope. It is set and released with `manageRetention` at the trial, each with a reason,
  each audited; one hold per trial. A trial under a hold is not deleted either, by anyone: a
  hold that deleting could walk around would hold nothing.
- **What the audit trail keeps about what was pruned**: one event for each area and scope
  something left, with the count, the bytes, the rule and where it was set, and
  - for a trial's record: its title, content hash, closed date and place, so a bundle exported
    earlier can be matched to the record that was destroyed;
  - for received files: each file's name, kind, size, SHA-256 and import time -- not its
    bytes or its mapping;
  - for sessions and tokens: how many of each kind; for task runs: how many per task and the
    span of their times;
  - for the audit log itself: one event at the server naming each scope's count, bytes, rule,
    the span of the removed events' times and of their numbers -- not what they said.
- **The audit log does not erase its own trail early.** Under `keepFor` nothing younger than
  the period leaves. Under `keepUntilClosed`, when a trial's events leave with its closing, the
  records of prunings, holds and their releases, closings and reopenings, and changed retention
  settings stay until they are themselves older than the period. What left the audit log is
  recorded at the server, not at the trial, so that record does not stand among the events it
  describes and outlive them one period at a time.

### One system

- **A scheduled task, `retentionPrune`** (kind of the same name, decision 0041), is made with
  every store and owned by it, enabled, daily at 03:15 in the server's zone. Under the default
  rules it removes sessions and tokens thirty days after they expired and runs ninety days
  after they finished, and nothing else; its run's summary says what it pruned, by area. It is
  the store's own: it is disabled or given another schedule like any task, and not deleted, as
  a task an identity provider keeps is not.
- **Task runs come under it.** The setting `tasks.runRetentionDays` and the scheduler's own
  removal of old runs are gone; `retention.taskRuns` takes their place.
- **So do expired sessions and tokens.** An expired token presented again was deleted on
  sight; it now stays until `retention.sessionsAndTokens` lets it go.
- **Protocol state is not a record, and does not wait for a rule.** A sign-in waiting for its
  provider is one row for each request to `/signin/with/<provider>`, which anyone can make
  without signing in, and it lives ten minutes. Starting a sign-in sweeps those that expired
  unanswered, as it did before this decision and whatever the rule says: growth by requests
  nobody authenticated is not a retention choice. A message identifier used once is cleared
  when it is presented again after its message expired, as it always was. Both are counted in
  the sessions-and-tokens area, and a pruning removes the expired ones its rule lets go,
  which is how the identifiers never presented again leave.

### Surfaces

- **Command line**: `openfurrow retention status|preview|prune|hold|release`, `received
  list|download`, `close`, `reopen`, `export --bundle`, `import-bundle`; rules are set with
  `setting set`.
- **Web**: Retention is a section of the administration area (worklist GOV-6), for holders of
  `manageRetention` at the server: the areas with counts, sizes, each rule and where it comes
  from, the scopes below the server that set their own, the holds, a preview, and pruning
  behind a confirmation page that shows what would go. A pruning answers with the section's
  page again, and what went is in the audit log, one link away. A person without the
  permission gets the area's refusal page, which names it.
- **The rules are changed on the area's settings page**, like any setting, at the server, a
  place or a trial. That page offers each setting's form to whoever holds, at the chosen
  scope, the permission the setting names, and tells the others which permission it takes: a
  trial manager sees the retention rules there and cannot change them, and someone who only
  manages retention changes those and nothing else.
- **The trial's page** lists its received files with their downloads, and has the closed
  date, the hold and the rules that apply to the trial, with a link to change them for whoever
  may. Every page works without JavaScript.

## Consequences

- Store version 21: the received files and holds, a trial's closed date, a task's owning
  feature.
- A store left at its defaults stays bounded in what only expires, while its scheduler runs:
  sessions and tokens leave thirty days after they expire and finished runs after ninety. An
  owner who sets `keep` there has chosen that growth; sign-ins never answered do not grow with
  it.
- A trial's size is found by assembling its document, so the Retention page reads every trial
  of the store each time it is shown, and a preview finds the rules trial by trial. Both grow
  in step with the number of trials; the measured cost and when to revisit it are with
  worklist GOV-5.
- A bundle larger than the API's request limit is imported from the command line.
- Not built: retention through the API; several holds on one trial; edit locks on a closed
  trial.
