#!/usr/bin/env bash
# Dev menu for the Proposal Scorer backend (BACKEND.md §18/§20). Run from anywhere.
set -euo pipefail

cd "$(dirname "$0")"

# Model: env var > .env > plan default
env_model=""
[[ -f .env ]] && env_model="$(grep -E '^OLLAMA_MODEL=' .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | xargs || true)"
MODEL="${OLLAMA_MODEL:-${env_model:-qwen2.5:7b}}"
API_URL="http://localhost/api"             # through nginx; backend has no host port
SAMPLES="$(cd .. && pwd)/sample_data"

c()   { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info(){ echo "$(c '1;34' '›') $*"; }
ok()  { echo "$(c '1;32' '✓') $*"; }
warn(){ echo "$(c '1;33' '!') $*"; }
err() { echo "$(c '1;31' '✗') $*" >&2; }

confirm() {
  read -rp "$(c '1;33' '? ')$1 [y/N] " a
  [[ "$a" =~ ^[Yy]$ ]]
}

up() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    warn "created .env from .env.example (ollama test mode)"
  fi
  info "building + starting services..."
  docker compose up -d --build
  ok "services up. api → $API_URL  (docs: http://localhost/api/docs)"
  pull_model
}

pull_model() {
  info "ensuring model '$MODEL' is present..."
  if docker compose exec -T ollama ollama list 2>/dev/null | grep -qF "$MODEL"; then
    ok "model '$MODEL' already pulled."
  else
    docker compose exec -T ollama ollama pull "$MODEL"
    ok "pulled '$MODEL'."
  fi
}

logs() {
  docker compose logs -f "${1:-}"
}

health() {
  if curl -fsS "$API_URL/health" >/dev/null 2>&1; then
    ok "api healthy at $API_URL"
  else
    err "api not responding at $API_URL"
  fi
}

status() {
  docker compose ps
  echo
  health
}

score() {
  local sample="${1:-response_1_weak.md}"
  info "POST $API_URL/score with $sample vs rfp_nordframe.md (slow on a local 7B)..."
  python3 - "$SAMPLES/rfp_nordframe.md" "$SAMPLES/$sample" <<'PY' |
import json, pathlib, sys
print(json.dumps({
  "rfp": pathlib.Path(sys.argv[1]).read_text(),
  "proposal": pathlib.Path(sys.argv[2]).read_text(),
}))
PY
    curl -sS "$API_URL/score" -H 'Content-Type: application/json' -d @- | python3 -m json.tool
}

regression() {
  info "running tests/regression.py inside the backend container..."
  docker compose exec -T backend python tests/regression.py /sample_data
}

reset() {
  warn "this deletes containers, volumes (incl. pulled models), and local project images."
  confirm "reset everything?" || {
    info "skipped."
    return
  }
  docker compose down -v --rmi local
  ok "reset complete."
}

menu() {
  echo
  echo "$(c '1;36' 'proposal-scorer — dev menu')"

  cat <<'MENU'
  1) up          build + start + pull model
  2) logs        follow backend logs
  3) status      containers + health
  4) health      api health check
  5) pull-model  ensure ollama model present
  6) score       smoke-test /score with the weak sample
  7) regression  run all 4 samples, assert weak < medium < strong
  8) reset       full reset
  q) quit
MENU

  read -rp "$(c '1;36' 'choose› ')" choice

  case "$choice" in
    1) up ;;
    2) logs backend ;;
    3) status ;;
    4) health ;;
    5) pull_model ;;
    6) score ;;
    7) regression ;;
    8) reset ;;
    q|Q) exit 0 ;;
    *) warn "unknown option" ;;
  esac
}

if [[ $# -gt 0 ]]; then
  cmd="$1"
  shift

  case "$cmd" in
    up)              up ;;
    logs)            logs "${1:-}" ;;
    status)          status ;;
    health)          health ;;
    pull-model|pull) pull_model ;;
    score)           score "${1:-}" ;;
    regression)      regression ;;
    reset)           reset ;;
    *)               err "unknown command: $cmd"; exit 1 ;;
  esac
else
  while true; do
    menu
  done
fi
