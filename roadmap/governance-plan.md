# Identity, settings and data governance

**Status: accepted, being built.** A reassessment prompted by the owner's answers of
2026-11-16 (worklist, Owner decisions, "Policies are settings" and "The governance
foundation"). Each piece gets its decision record as it is built.

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

Roles and settings attach to places, so the places must exist. The hierarchy is modular:
organization, project, study and trial by default, and an administrator adds levels (a
program, a season) or removes them to make the permission groups finer or simpler. The
trial is always the last level and belongs to one place at the level above it. Sensible
defaults for a person or a small group, customization at scale for an enterprise
(decision 0004 proposed the hierarchy; it becomes the first step).

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
  - missing plots: refuse, estimate, or least squares (built behind the setting,
    decision 0043);
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
- the missing-plot methods behind their setting (USR-3; built, decision 0043);
- field collection by link (USR-9);
- the server deployment the pilot runs on (decision 0011).

## Our own sign-in library

The project writes its own sign-in library, so that no third-party licence limits where
OpenFurrow can be used (owner, 2026-11-16). It is its own project,
[Carnelian](https://github.com/rbraunm/carnelian), under MIT (decision 0039), and uses only
the Python standard library:

- **SAML 2.0** service provider: the request, the response, and the XML signature checked
  with exclusive canonicalization and the provider's certificate, refusing anything outside
  the signed element (the signature-wrapping attacks).
- **OpenID Connect** relying party: discovery, the authorization-code flow with PKCE, and
  the ID token's signature and claims checked.
- **LDAP** client for Active Directory and other directories: bind and search over TLS,
  its BER encoding written here.
- **SCIM 2.0** service provider: users, groups, filters, PATCH, and deactivation.
- **Signature verification only.** RSA (PKCS #1 v1.5 and PSS) and ECDSA verification are
  arithmetic on public keys; the library never signs or decrypts with a secret key, so it
  keeps out of the riskiest code in cryptography. TLS is the standard library's. Encrypted
  SAML assertions are refused for now; providers are configured to sign, over TLS.
- **Passwords** for local accounts are hashed with the standard library's scrypt.

Each part is checked against the specifications' own test vectors and against real
providers.

## Store

The store stays one schema on SQLAlchemy and runs on SQLite and on PostgreSQL alike;
which one a deployment uses is its choice. Both are tested with the same data.

## Test fixtures

Every sign-in method and every database has fixtures in two forms (owner, 2026-11-16):

- **For development:** semi-permanent, reprovisionable from scripts in the repository,
  running on lab machines rather than the development machine.
- **For the validation workflow:** created for one run and thrown away, from the same
  scripts.

The providers: Keycloak (SAML and OpenID Connect), a Samba Active Directory (LDAP), a SCIM
client that behaves as Entra ID's provisioning service is documented to, local accounts,
the open mode, SQLite and PostgreSQL. One test dataset is loaded into all of them: people
and groups chosen to break things (names in every script the locales cover, a disabled
account, nested and many groups, a person in two organizations, an account removed by
provisioning), so every provider is held to the same expectations.

## Order of building

1. Hierarchy (F1) and settings (F2), on SQLite and PostgreSQL, with the PostgreSQL fixture.
2. Identity core (F3: open mode, local accounts, sessions, tokens, preferences), roles
   (F4) and audit (F5), every route behind the permission boundary.
3. The sign-in library and its fixtures: OpenID Connect, SAML, LDAP, SCIM.
4. Retention (F6), with the files as received (REC-16).
5. The features on top.
