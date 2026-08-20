#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .git ]]; then
  echo "This installation is not a Git checkout. Upload the new release over the application files instead."
  exit 1
fi

BRANCH="${GIT_BRANCH:-main}"
git fetch --prune origin "${BRANCH}"
git merge --ff-only "origin/${BRANCH}"
rm -f .venv/.requirements.sha256
printf '%s\n' "Update applied. config.yaml, data/, logs/, and .env were not replaced because they are untracked/ignored."
