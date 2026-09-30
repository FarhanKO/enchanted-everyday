#!/usr/bin/env bash
# Runs on the VPS (called by CI over SSH, or by hand). Usage: deploy.sh [git-sha]
set -euo pipefail

cd /opt/content-engine
git fetch --quiet origin
git checkout --quiet --detach "${1:-origin/main}"

docker compose build --pull
docker compose up -d --remove-orphans
docker image prune -f >/dev/null

# fail the deploy if the migrate job failed or a service isn't running
docker compose ps --all --format '{{.Service}} {{.State}} {{.ExitCode}}' | tee /dev/stderr \
  | awk '$1=="migrate" && $3!=0 {bad=1} $1!="migrate" && $2!="running" {bad=1} END {exit bad}'
echo "deployed $(git rev-parse --short HEAD)"
