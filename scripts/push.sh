#!/usr/bin/env bash
# Деплой с Mac без git: rsync кода на сервер и запуск scripts/deploy.sh там.
#   ./scripts/push.sh            # на chemolymp-demo (алиас из ~/.ssh/config, пользователь deploy)
#   ./scripts/push.sh my-host    # на другой алиас/хост
# Не трогает на сервере .env, data/ (шрифты, ассеты, шаблоны), compile/, logs/.
set -euo pipefail

HOST="${1:-chemolymp-demo}"
APP_DIR="${APP_DIR:-/opt/latex-api}"
cd "$(dirname "$0")/.."

# --chmod (символьная форма: числовая D755,F644 недоступна в rsync 2.6.9 из macOS): в Dropbox файлы
# лежат с правами 600, а Docker COPY их сохраняет — конфиги в образе
# должны читаться пользователем сервиса; исполняемые биты скриптам вернёт deploy.sh
rsync -az --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
  --exclude '.git' --exclude '.env' --exclude 'data/' --exclude 'compile/' --exclude 'logs/' \
  --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  ./ "$HOST:$APP_DIR/"

ssh "$HOST" "cd $APP_DIR && chmod +x scripts/*.sh && ./scripts/deploy.sh"
