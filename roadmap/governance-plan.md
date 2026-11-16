# Identity, settings and data governance

**Status: proposed, awaiting the owner's go.** A reassessment prompted by the owner's
answers of 2026-11-16 (worklist, Owner decisions, "Policies are settings"). Once agreed,
this becomes a lane of `platform-plan.md` and its pieces become decision records.

## What changed

Four open questions -- missing plots, keeping imported files, editing a trial after it is
made, and who changed a value -- got one answer between them:

- **Policies are settings, not rules the project fixes.** How missing plots are handled,
  what may be edited and when, and how long data is kept are chosen by whoever runs the
  tool, per server and per study or finer, not written into the code.
- **Data retention is a system of its own.** Each kind of stored data lives in its own
  area that can be watched and pruned when its owners decide it is no longer needed.
- **Sign-in with roles is needed for the university pilot**: role-based access, and the
  university's own identity provider -- Active Directory, SAML, SCIM provisioning. A
  configuration with no sign-in, where everyone can do everything, stays supported: easy,
  and insecure by choice.
- **Identity reaches everything**, down to a person's saved display language.

## Why now

- **The pilot is the route to a first user** (USR-9), and it needs sign-in through the
  university, roles, and field collection by a link someone is sent. That link is itself an
  identity feature: an invitation that grants a role on one trial.
- **Every next feature needs it.** The record forms (USR-14) need to know who may edit
  what; field collection needs invitations; the server (decision 0011) needs accounts; the
  audit of changes (USR-8) needs a "who". Building those first and fitting permissions in
  afterwards means touching every route twice.
- **The engine is in good shape to pause on.** Designs, analyses, import, charts and
  subsamples are built and validated; what remains of the trial record is forms over a
  schema that exists.

## The foundation, in dependency order

### F1. Hierarchy

Roles and settings attach to places, so the places must exist: an organization, its
projects, their studies, their trials (decision 0004 proposed this; it becomes the first
step). A trial belongs to exactly one study. Program and season stay open questions.

### F2. Settings

One registry of setting definitions -- name, type, allowed values, the levels it may be set
at, and the permission needed to change it. A value is set at the server, organization,
project, study or trial; the nearest one applies, and every page that uses a setting can
show where its value came from.

- **Unknown settings and values are refused**, and so is a value set at a level the
  setting does not allow.
- **What an analysis used is recorded with it.** The significance level, the comparison
  test and the missing-plot policy are written into the report's reproducibility block, so
  a result never depends on a setting that has changed since.
- **The configuration file moves in.** Today's project file (significance level,
  comparison test, import profile) becomes server-level values of the same registry.
- **First policy settings:**
  - missing plots: refuse, estimate, or least squares (the methods are built behind the
    setting);
  - editing, per area of the record;
  - retention, per storage area.

### F3. Identity

Who someone is, however they sign in.

- **Sign-in modes:**
  - open: no sign-in, everyone an administrator;
  - local accounts, with passwords hashed by the standard library's scrypt;
  - SAML 2.0, for university federations and Entra ID;
  - OpenID Connect, for Entra ID, Google and others;
  - Active Directory over LDAP.

  More than one can be on at once.
- **SCIM 2.0 provisioning**: the identity provider creates, updates, deactivates and groups
  accounts here, as Entra ID and others do.
- **Sessions**, form protection against cross-site requests, API tokens for scripts, and
  **invitation links** that grant a role on one trial (the field-collection link of USR-9).
- **Preferences per person**: display language, decimal mark.

### F4. Roles and permissions

Fine-grained permissions:
- view;
- enter values;
- import;
- edit the record;
- edit the design;
- change settings;
- manage members;
- manage retention.

Roles are named sets of permissions. Built-in roles are viewer, data collector, analyst,
trial manager and administrator; an organization can define its own. A role is given to a
person or a group at a level and holds below it. Groups from the identity provider map to
roles. Every request is checked at one boundary, the service layer; anything unchecked is
refused. In open mode everyone holds every permission everywhere.

### F5. Audit

An append-only log of every change: who, when, from which surface (page, file, API,
provisioning), and the value before and after. It answers "who changed this value"
(USR-8, decision 0023). Kept beside the trial record, not in its content hash.

### F6. Retention

Storage areas, each with its size and count on a monitoring page:
- trial records;
- files as received (REC-16), with the column mapping used;
- the audit log;
- reports and exports;
- sessions and tokens.

- **Each area has a retention setting**: keep, keep for a period, or keep until a trial
  is closed plus a period.
- **Pruning** is previewed, needs its permission, can run on a schedule, and is itself
  logged. A hold stops pruning for a trial.
- **Pruning never changes a trial's content hash.** The hash covers the trial record;
  received files, logs and reports are outside it.

## Then the features, on top

With F1 to F6 in place:
- the record forms (USR-14), under the edit permissions and settings;
- the missing-plot methods behind their setting (USR-3);
- field collection by link (USR-9);
- the server deployment the pilot runs on (decision 0011).

## Store

The store stays one schema on SQLAlchemy. A single person or a small group can stay on
SQLite; a server with many users moves to PostgreSQL, as decisions 0001 and 0005 already
foresee. Whether SQLite is allowed for a multi-user server is an open question below.

## Testing sign-in for real

Each sign-in mode is tested against a real provider, not a stand-in:
- Keycloak (Apache-2.0) for SAML, OpenID Connect and SCIM-style provisioning;
- a Samba or Windows Active Directory for LDAP;
- Entra ID if a tenant is available.

The providers run on lab machines, not on the development machine.

## Open questions for the owner

1. Build the foundation now, before the remaining record forms?
2. Which levels the hierarchy has: organization, project, study, trial, or also program
   and season.
3. How Active Directory is reached:
   - directly over LDAP, with the LGPL-licensed ldap3 library;
   - or only through the directory's own SAML or OpenID Connect front (ADFS or Entra ID),
     with no LDAP library at all.
4. Whether an Entra ID tenant is available for testing.
5. Whether a multi-user server may run on SQLite or must use PostgreSQL.
