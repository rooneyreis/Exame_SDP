#!/usr/bin/env bash
# Runs the whole test suite (unit + integration) in a local virtualenv.
# Integration tests expect the Docker environment from docker-compose.yml.
set -euo pipefail

cd "$(dirname "$0")/.."
# No servidor as senhas internas vêm do .env gerado pelo deploy.sh
if [[ -f .env ]]; then set -a; source .env; set +a; fi

if [[ ! -x .venv/bin/python ]]; then
  echo "[test] A criar o ambiente virtual .venv..."
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements-dev.txt

echo "[test] Testes unitários (sem Docker)..."
.venv/bin/pytest -q tests/unit "$@" || [[ $? -eq 5 ]]   # 5 = no tests collected (early phases)

echo "[test] Testes de integração (ambiente Docker)..."
.venv/bin/pytest -q tests/integration "$@"
