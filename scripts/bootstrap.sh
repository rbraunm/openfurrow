#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Bootstrap a development environment for OpenFurrow.
#
# The project targets Python 3.13 (pyproject: requires-python = ">=3.13"), but a
# fresh sandbox ships 3.12, which refuses `pip install -e .` outright. Without this
# script a session silently drifts: it hand-installs a guessed set of packages
# against the wrong interpreter and never runs the real target environment. Run this
# first, every session.
#
# Idempotent: safe to re-run. Already-satisfied steps are skipped.
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

installPython() {
  if command -v "python${pythonVersion}" >/dev/null 2>&1; then
    log "python${pythonVersion} already present: $(python${pythonVersion} --version)"
    return
  fi

  log "installing python${pythonVersion} from the deadsnakes PPA"
  requireRoot
  export DEBIAN_FRONTEND=noninteractive

  # A third-party repo whose signing key the sandbox cannot verify (e.g. a preinstalled
  # nodesource entry) makes every apt-get update fail, taking this script down with it.
  # Disable only repos that actually fail to fetch, and say so -- never silently.
  if ! asRoot apt-get update -qq 2>/dev/null; then
    log "apt-get update failed; disabling unreachable third-party repos"
    for source in /etc/apt/sources.list.d/*; do
      [ -e "${source}" ] || continue
      case "${source}" in
        *deadsnakes*|*ubuntu.sources) continue ;;
      esac
      log "  disabling $(basename "${source}")"
      asRoot mv "${source}" "${source}.disabled"
    done
    asRoot apt-get update -qq
  fi

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

installPython
createVirtualEnvironment
installProject
verify

cat <<EOF

Bootstrap complete. Activate the environment:

  source ${venvPath}/bin/activate

Then \`python\`, \`pytest\`, and \`openfurrow\` are the ${pythonVersion} venv's.
EOF
