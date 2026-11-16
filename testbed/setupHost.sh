#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Prepares a Debian or Ubuntu host to keep the OpenFurrow testbed running, and starts it.
#
#   sudo sh setupHost.sh <directory holding compose.yaml>
#
# Installs Docker from the distribution if it is missing, makes the testbed's password
# once (kept in <directory>/testbed.env, readable by root only), and brings every service
# up, waiting until each is healthy. Run it again to reprovision: the containers are
# recreated from compose.yaml, and `--fresh` also throws away their data and password.
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root (sudo)" >&2
  exit 1
fi
directory=${1:?usage: setupHost.sh <directory holding compose.yaml> [--fresh]}
fresh=${2:-}
if [ ! -f "$directory/compose.yaml" ]; then
  echo "$directory/compose.yaml does not exist" >&2
  exit 1
fi
if [ -n "$fresh" ] && [ "$fresh" != "--fresh" ]; then
  echo "unknown option $fresh" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose >/dev/null \
    || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-v2 >/dev/null
  systemctl enable --now docker
fi
docker compose version >/dev/null

environment="$directory/testbed.env"
if [ "$fresh" = "--fresh" ]; then
  docker compose --file "$directory/compose.yaml" --env-file "$environment" down --volumes 2>/dev/null || true
  rm -f "$environment"
fi
if [ ! -f "$environment" ]; then
  umask 077
  printf 'OPENFURROW_TESTBED_PASSWORD=%s\n' "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" > "$environment"
fi
docker compose --file "$directory/compose.yaml" --env-file "$environment" up --detach --wait --force-recreate
docker compose --file "$directory/compose.yaml" --env-file "$environment" ps
