#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Bootstrap a development environment for OpenFurrow.
#
# Two jobs, both of which a session otherwise rediscovers by hand every time:
#
# 1. Make apt usable. A sandbox often ships a third-party repo (nodesource, docker, ...)
#    that its egress proxy cannot reach or whose key will not verify. One such repo makes
#    *every* apt-get update fail, so any apt install anywhere fails with it. This disables
#    exactly the repos apt itself reports as failing, and nothing else.
#
# 2. Get the project onto Python 3.13. The project targets 3.13 (pyproject:
#    requires-python = ">=3.13") but a fresh sandbox ships 3.12, which refuses
#    `pip install -e .` outright. Do not work around that by hand-installing a guessed set
#    of packages against 3.12 -- that silently runs the suite on an interpreter the project
#    does not target.
#
# Idempotent: safe to re-run. Already-satisfied steps are skipped, and every step is
# re-checked on each run rather than assumed from a previous one.
#
#   bash scripts/bootstrap.sh
#   source .venv/bin/activate
#
# Afterwards `python`, `pytest`, and `openfurrow` are the 3.13 venv's.

set -euo pipefail

pythonVersion="3.13"
repoRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venvPath="${repoRoot}/.venv"

# The deadsnakes PPA signing key. add-apt-repository cannot be used here: it resolves
# the PPA through the launchpad.net API, which a restricted sandbox does not reach.
# The archive itself (ppa.launchpadcontent.net) and the keyserver's HTTPS interface
# are reachable, so the source is added by hand.
deadsnakesFingerprint="F23C5A6CF475977595C89F51BA6932366A755776"
deadsnakesKeyring="/etc/apt/keyrings/deadsnakes.gpg"

log() { echo "==> $*"; }

requireRoot() {
  if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
    echo "error: need root (or sudo) to install system packages" >&2
    exit 1
  fi
}

asRoot() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

sanitizeAptSources() {
  # A single unreachable or unverifiable repo makes *every* apt-get update fail, which
  # takes down any apt install later in this script (and any the operator runs by hand).
  # Sandboxes ship such repos: an egress proxy that only forwards allowlisted hosts turns
  # a preinstalled third-party source (nodesource, docker, ...) into a hard 403, and its
  # signing key may not verify either.
  #
  # So: probe apt, and if it fails, disable *only* the repos apt itself names as failing --
  # parsed out of its output, not hardcoded to any one vendor. Anything still broken after
  # that is a real problem and fails loud rather than being papered over.
  if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
    log "not root and no sudo; skipping apt source check"
    return
  fi
  export DEBIAN_FRONTEND=noninteractive

  local output
  if output=$(asRoot apt-get update 2>&1); then
    return                                  # apt is healthy, nothing to do
  fi

  log "apt-get update failed; finding the repos responsible"

  # Hosts apt named in its error/warning lines (Failed to fetch, not signed, NO_PUBKEY).
  local failingHosts
  failingHosts=$(printf '%s\n' "${output}" \
    | grep -E '^(E|W):' \
    | grep -oE 'https?://[^ /]+' \
    | sed -E 's#^https?://##' \
    | sort -u)

  if [ -z "${failingHosts}" ]; then
    echo "error: apt-get update failed but named no repo; not guessing." >&2
    printf '%s\n' "${output}" >&2
    exit 1
  fi

  local disabledAny=0
  local host source
  for host in ${failingHosts}; do
    for source in /etc/apt/sources.list.d/*; do
      [ -f "${source}" ] || continue
      case "${source}" in
        *.disabled) continue ;;
      esac
      # Never disable the distro's own repos or the PPA this script relies on -- if those
      # are what's failing, that is a genuine failure to surface, not a repo to drop.
      case "$(basename "${source}")" in
        ubuntu.sources|deadsnakes.list) continue ;;
      esac
      if grep -q "${host}" "${source}"; then
        log "  disabling $(basename "${source}") (unreachable: ${host})"
        asRoot mv "${source}" "${source}.disabled"
        disabledAny=1
      fi
    done
  done

  if [ "${disabledAny}" -eq 0 ]; then
    echo "error: apt-get update failed on ${failingHosts}, which no third-party source file matches." >&2
    printf '%s\n' "${output}" >&2
    exit 1
  fi

  log "re-running apt-get update"
  if ! asRoot apt-get update -qq; then
    echo "error: apt-get update still failing after disabling unreachable repos." >&2
    exit 1
  fi
}

installPython() {
  if command -v "python${pythonVersion}" >/dev/null 2>&1; then
    log "python${pythonVersion} already present: $(python${pythonVersion} --version)"
    return
  fi

  log "installing python${pythonVersion} from the deadsnakes PPA"
  requireRoot
  export DEBIAN_FRONTEND=noninteractive

  if [ ! -f "${deadsnakesKeyring}" ]; then
    log "fetching the deadsnakes signing key over HTTPS"
    asRoot mkdir -p /etc/apt/keyrings
    curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${deadsnakesFingerprint}" \
      | gpg --dearmor \
      | asRoot tee "${deadsnakesKeyring}" >/dev/null
  fi

  local codename
  codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
  echo "deb [signed-by=${deadsnakesKeyring}] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu ${codename} main" \
    | asRoot tee /etc/apt/sources.list.d/deadsnakes.list >/dev/null

  asRoot apt-get update -qq
  asRoot apt-get install -y -qq \
    "python${pythonVersion}" "python${pythonVersion}-venv" "python${pythonVersion}-dev"

  log "installed $(python${pythonVersion} --version)"
}

createVirtualEnvironment() {
  if [ -x "${venvPath}/bin/python" ]; then
    log "virtualenv already exists: $("${venvPath}/bin/python" --version)"
    return
  fi
  log "creating the virtualenv at ${venvPath}"
  "python${pythonVersion}" -m venv "${venvPath}"
}

installProject() {
  # Editable install with the test extra: this is the real dependency set from
  # pyproject (pydantic, sqlalchemy, numpy, pyyaml + pytest, statsmodels), never a
  # hand-guessed list. It also puts the `openfurrow` console script on PATH.
  log "installing openfurrow (editable, with test extras)"
  "${venvPath}/bin/pip" install --quiet --upgrade pip
  "${venvPath}/bin/pip" install --quiet --editable "${repoRoot}[test]"
}

verify() {
  log "verifying"
  "${venvPath}/bin/python" --version
  "${venvPath}/bin/python" -c "import openfurrow; print('openfurrow imports ok')"
  "${venvPath}/bin/openfurrow" --help >/dev/null && echo "openfurrow CLI ok"
  log "running the test suite"
  "${venvPath}/bin/python" -m pytest -q
}

sanitizeAptSources
installPython
createVirtualEnvironment
installProject
verify

cat <<EOF

Bootstrap complete. Activate the environment:

  source ${venvPath}/bin/activate

Then \`python\`, \`pytest\`, and \`openfurrow\` are the ${pythonVersion} venv's.
EOF
