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
- **A trusted workload is a rule** in the store: a name (formed like a provider's), the
  issuer, and the claims a token must carry, each with the exact value required.
  - The issuer is `githubActions`, `gitlab` (GitLab.com), or the https address of any
    OpenID Connect issuer exactly as its tokens name it (a slash at its end, as Entra ID's
    and Auth0's have, is part of the name). An issuer with a
    certificate authority of its own names that authority's file, as a provider does.
  - A rule requires at least one claim. A claim's required value is text, compared exactly
    with what the token carries. The issuer, the audience and the times are checked for
    every token and are not claims of a rule.
  - A rule names the claim that stays with the job's owner: for GitHub Actions
    `repository_id`, for GitLab.com `project_id`. A rule that names only `repository` or
    `project_path` is refused, since a name given up can be registered again by someone
    else; `repository_owner_id` beside `repository_id` is recommended.
  - What a rule trusts does not change. A rule that should trust something else is removed
    and made again, so the audit log's word on what it trusted when it acted stays true.
- **The audience every token must name** is the server's own: the server setting
  `identity.workloadAudience`, with no default, so a token minted for another service is
  never accepted here. While it is unset, no rule is added and every workload token is
  refused, by name.
- **Roles are given to the rule directly**, at a scope, like to an account or a group
  (decision 0037): a role assignment names exactly one of an account, a group or a rule,
  which the store itself enforces. The rule is not an account: it has no password, no
  sessions, no API tokens and no web sign-in. A removed rule takes its roles with it; a
  disabled rule keeps them and holds nothing until it is enabled again. Either takes effect
  at the next permission check, also for a request already under way.
- **A request proves the workload** by sending the platform's token as its bearer token to
  the API; the web pages never take one. In the open mode every request is everyone, as
  before, and no token is read.
  - A bearer token in the form of a JSON Web Token (three base64url parts) is a workload
    token; any other is an API token.
  - The issuer the token names is read before any check, only to choose the enabled rules
    of that issuer. Each of them checks the token with Carnelian (decision 0039): the
    issuer's signature and keys, the times, the audience and every required claim.
  - Exactly one rule must accept, and the request acts with the roles of that rule and
    nothing else. A token two rules accept is refused as ambiguous, naming them.
  - A token no rule accepts is answered 401 with what is wrong with the token itself: its
    signature, its times, its audience, an issuer no enabled rule names, or claims that
    match no rule. The answer never says what a rule requires or what rules exist.
  - A token may be used for as many requests as its job makes while it is valid. It is
    never stored, and a refused one is not recorded, as a refused API token is not.
- **The audit log names the rule** (a new actor kind, `workload`) and carries, in every
  event the workload writes, the run its token came from as the platform tells it
  (`workloadRun` in the event's detail): the issuer and the subject for any issuer; for
  GitHub Actions also the repository, ref, workflow ref, run ID, run attempt and commit;
  for GitLab.com the project path, ref, pipeline ID, job ID and commit. A change is traced
  to the job that made it.
- **Rules are managed** with `manageAccess`: `openfurrow workload add`, `list`, `show`,
  `enable`, `disable` and `remove`, and `openfurrow role assign` and `unassign` with
  `--workload`, on the command line now and on the access pages when they come (worklist
  GOV-6). Adding, enabling, disabling and removing a rule, and giving and taking back its
  roles, are audited.

## Consequences

- Store version 20: the workload rules; role assignments gain the rule as a third kind of
  holder, exactly one holder each.
- Permission checks and the audit log handle a third kind of actor besides accounts and
  the operator.
- Carnelian's verifier for each rule is kept for the life of the process, with the issuer's
  keys it fetches and caches. An issuer that cannot be reached refuses its workloads'
  requests, by name, and its discovery document is asked for again after a minute.
- The stand-in issuer of the tests signs the tokens of every case; a token from GitHub
  Actions itself is checked in the validation workflow's `providers` job. GitLab.com's
  claims are taken from its documentation and have not met a token of its own.
