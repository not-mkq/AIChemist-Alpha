#!/usr/bin/env bash
# Launch backend (uvicorn) and frontend (Vite dev server) in separate Konsole tabs.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv"
ENV_FILE="${ROOT}/.env"

if [[ ! -f "${VENV}/bin/activate" ]]; then
  echo "Virtualenv not found at ${VENV}/bin/activate. Please create it first." >&2
  exit 1
fi

activate_cmd="source \"${VENV}/bin/activate\""
env_cmd='if [ -f "'"${ENV_FILE}"'" ]; then set -a; source "'"${ENV_FILE}"'"; set +a; fi'

launch_tab() {
  local title="$1"; shift
  local cmd="$*"
  if command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="${title}" -e bash -lc "cd \"${ROOT}\" && ${activate_cmd}; ${env_cmd}; ${cmd}"
  else
    echo "konsole not found; running '${cmd}' in current shell (background)." >&2
    (cd "${ROOT}" && eval "${activate_cmd}"; eval "${env_cmd}"; eval "${cmd}") &
  fi
}

backend_cmd='uvicorn app.service:app --reload --host 127.0.0.1 --port 8000'
frontend_cmd='cd frontend && npm run dev -- --host 127.0.0.1 --port 5173'

launch_tab "backend" "${backend_cmd}"
launch_tab "frontend" "${frontend_cmd}"

echo "Backend and frontend launch commands issued."
