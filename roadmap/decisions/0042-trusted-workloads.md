# 0042 - Trusted workloads

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Automated jobs reach the API too: a station's nightly job pushing weather or sensor
readings into trials, a university's pipeline copying results into its warehouse, a
scheduled report built elsewhere. An API token (decision 0036) works, but it is a long-lived
secret that has to be stored in the job's settings, rotated and kept from leaking. CI and
cloud platforms (GitHub Actions, GitLab CI, the cloud providers) now give a running job a
short-lived OpenID Connect token that says which repository, branch and workflow it is,
signed by the platform; PyPI's trusted publishing is built on it. The owner (2026-11-18):
keep tokens for whoever finds them easier, and also let a job prove what it is, with roles
given directly to that trust, as PyPI does.

## Decision

- **API tokens stay** as decision 0036 has them: an account's token, used by a script.
- **A trusted workload is a rule** in the store: a name, the issuer (GitHub Actions and
  GitLab.com named; any https OpenID Connect issuer by its address), and the claims a
  token must carry, each with the exact value required. A rule names at least one claim
  that identifies the job's owner; for GitHub Actions that is `repository_id` (the number,
  which survives a rename and cannot be taken over by a new repository of the same name),
  and `repository_owner_id` beside it is recommended. The audience every token must name is
  the server's own, a server setting with no default, so a token minted for another
  service is never accepted here.
- **Roles are given to the rule directly**, at a scope, like to an account or a group
  (decision 0037): a role assignment names exactly one of an account, a group or a rule.
  The rule is not an account: it has no password, no sessions, no API tokens and no web
  sign-in.
- **A request proves the workload** by sending the platform's token as its bearer token.
  OpenFurrow tells it from an API token by its form (a JSON Web Token), checks it with
  Carnelian (decision 0039: the issuer's signature and keys, the times, the audience and
  every required claim), and acts with the roles of the one rule it matches. A token that
  matches no enabled rule, or more than one, is refused by name. A token may be used for as
  many requests as its job makes while it is valid; it is never stored.
- **The audit log names the rule** (a new actor kind, `workload`) and, in each event's
  detail, the run the token came from as the platform tells it (for GitHub Actions the
  repository, ref, workflow and run ID), so a change is traced to the job that made it.
- **Rules are managed** with `manageAccess`, on the command line now and on the access
  pages when they come (worklist GOV-6); adding, changing, disabling and removing a rule are
  audited.

## Consequences

- Store: the workload rules; role assignments gain the rule as a third kind of holder.
- Permission checks and the audit log handle a third kind of actor besides accounts and
  the operator.
- Each issuer's keys are fetched and cached by Carnelian's verifier for the life of the
  process; an issuer that cannot be reached refuses its workloads' requests, by name.
