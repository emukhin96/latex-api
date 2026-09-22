#!/usr/bin/env bash
# Деплой с Mac без git: rsync кода на сервер и запуск scripts/deploy.sh там.
#   ./scripts/push.sh            # на chemolymp-demo (алиас из ~/.ssh/config, пользователь deploy)
#   ./scripts/push.sh my-host    # на другой алиас/хост
# Не трогает на сервере .env, data/ (шрифты, ассеты, шаблоны), compile/, logs/.
set -euo pipefail

HOST="${1:-chemolymp-demo}"
APP_DIR="${APP_DIR:-/opt/latex-api}"
cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude '.git' --exclude '.env' --exclude 'data/' --exclude 'compile/' --exclude 'logs/' \
  --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  ./ "$HOST:$APP_DIR/"

ssh "$HOST" "cd $APP_DIR && chmod +x scripts/*.sh && ./scripts/deploy.sh"
