#!/usr/bin/env bash
# Launch all agents in separate Konsole tabs (or background shells if Konsole is unavailable).

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

# Agent commands (title:command)
AGENTS=(
  "audit:python -m Audit.main"
  "file:python -m FileAgent.agent"
  "reading:python -m ReadingAgent.agent"
  "synthesis:python -m SynthesisAgent.agent"
  "ratio:python -m RatioAgent.agent"
  "merge:python -m MergeAgent.agent"
  "training:python -m TrainingAgent.agent"
  "shell:python -m ShellAgent.agent"
  "data:python -m DataProcessingAgent.agent"
  "protocol:python -m ProtocolConverterAgent.agent"
  "batch_proc:python -m ProtocolBatchAgent.agent"
)

for entry in "${AGENTS[@]}"; do
  title="${entry%%:*}"
  cmd="${entry#*:}"
  cmd='AGENT_RELOAD=${AGENT_RELOAD:-1} '"${cmd}"
  launch_tab "${title}" "${cmd}"
done

echo "All agent processes launched (uvicorn reload where available)."
