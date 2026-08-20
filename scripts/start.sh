#!/usr/bin/env bash
set -Eeuo pipefail

cd /home/container 2>/dev/null || cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python}"
VENV_DIR="${KTD_VENV:-.venv}"
REQUIREMENTS="requirements.txt"
MARKER_FILE="${VENV_DIR}/.requirements.sha256"

if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

CURRENT_HASH="$(sha256sum "${REQUIREMENTS}" | awk '{print $1}')"
INSTALLED_HASH="$(cat "${MARKER_FILE}" 2>/dev/null || true)"
if [[ "${CURRENT_HASH}" != "${INSTALLED_HASH}" ]]; then
  "${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check -r "${REQUIREMENTS}"
  printf '%s' "${CURRENT_HASH}" > "${MARKER_FILE}"
fi

mkdir -p data/evidence data/transcripts data/backups logs
if [[ ! -f "${KTD_CONFIG:-config.yaml}" && -f config.example.yaml ]]; then
  cp config.example.yaml "${KTD_CONFIG:-config.yaml}"
fi

exec "${VENV_DIR}/bin/python" -m kingdom_tech_desk
