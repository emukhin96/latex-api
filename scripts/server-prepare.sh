#!/usr/bin/env bash
# Разовая подготовка сервера chemolymp под latex-api. Запускать ОДИН раз от root:
#   scp scripts/server-prepare.sh root@77.232.132.139:/root/ && ssh root@77.232.132.139 'bash /root/server-prepare.sh'
#
# Предполагает, что сервер уже настроен chemolymp/scripts/server-bootstrap.sh (Docker, пользователь deploy).
# Делает: каталог сервиса и каталог сайтов Caddy (владелец deploy), общую docker-сеть `edge`.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/latex-api}"
CADDY_SITES_DIR="${CADDY_SITES_DIR:-/opt/caddy/sites}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"

id "$DEPLOY_USER" >/dev/null 2>&1 || { echo "!! нет пользователя $DEPLOY_USER — сначала chemolymp/scripts/server-bootstrap.sh"; exit 1; }
command -v docker >/dev/null || { echo "!! docker не установлен — сначала chemolymp/scripts/server-bootstrap.sh"; exit 1; }

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR" "$APP_DIR/data" \
  "$APP_DIR/data/fonts" "$APP_DIR/data/assets" "$APP_DIR/data/table_signs" "$APP_DIR/data/templates"
install -d "$CADDY_SITES_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$CADDY_SITES_DIR"   # мог быть создан docker'ом от root при первом up стека chemolymp
docker network inspect edge >/dev/null 2>&1 || docker network create edge

echo "==> Готово: $APP_DIR, $CADDY_SITES_DIR, сеть edge."
echo "Дальше с Mac: ./scripts/push.sh   (rsync кода + scripts/deploy.sh на сервере под $DEPLOY_USER)"
