#!/usr/bin/env bash
# Start the reservation API, voice agent, and browser UI from one command.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT/parse_voice_assessment_starter"
AGENT_DIR="$ROOT/voice_agent"
VENV="$AGENT_DIR/.venv"
PYTHON="$VENV/bin/python"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it with:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if [[ ! -f "$AGENT_DIR/.env" ]]; then
  echo "Missing $AGENT_DIR/.env"
  echo "Copy voice_agent/.env.example to voice_agent/.env and fill in the keys."
  exit 1
fi

echo "==> Python 3.12 venv"
uv python install 3.12 >/dev/null
if [[ ! -x "$PYTHON" ]]; then
  uv venv --python 3.12 "$VENV"
fi
uv pip install -r "$AGENT_DIR/requirements.txt" --python "$PYTHON"

cleanup() {
  trap - EXIT INT TERM
  echo
  echo "==> Stopping all services"
  if [[ -n "$(jobs -p 2>/dev/null)" ]]; then
    kill $(jobs -p) 2>/dev/null || true
  fi
  pkill -f "python -m agent.main" 2>/dev/null || true
  pkill -f "python -m web.token_server" 2>/dev/null || true
  pkill -f "uvicorn app:app" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

set -a
# shellcheck disable=SC1091
source "$AGENT_DIR/.env"
set +a

echo "==> Reservation API  http://127.0.0.1:8000"
(
  cd "$API_DIR"
  exec "$VENV/bin/uvicorn" app:app --host 127.0.0.1 --port 8000
) &

echo "==> Waiting for API"
for _ in $(seq 1 40); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo "==> Browser UI       http://127.0.0.1:8080"
(
  cd "$AGENT_DIR"
  exec "$PYTHON" -m web.token_server
) &

echo "==> Agent worker"
(
  cd "$AGENT_DIR"
  exec "$PYTHON" -m agent.main dev
) &

echo
echo "Ready. Open http://127.0.0.1:8080  (use this host for the mic)"
echo "Ctrl+C stops everything."
echo

if command -v open >/dev/null 2>&1; then
  (sleep 1 && open "http://127.0.0.1:8080") &
fi

wait
