#!/usr/bin/env bash
# Деплой latex-api на сервере: cd /opt/latex-api && ./scripts/deploy.sh
# Запускается от deploy (группа docker). Идемпотентен: .env создаётся только если его нет,
# сеть edge — если её нет, образ пересобирается, контейнер перезапускается, сайт Caddy обновляется.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/latex-api}"
CADDY_SITES_DIR="${CADDY_SITES_DIR:-/opt/caddy/sites}"
CADDY_CONTAINER="${CADDY_CONTAINER:-chemolymp-caddy-1}"
cd "$APP_DIR"

env_get() {  # .env — dotenv, не shell: читаем построчно (значения могут содержать пробелы)
  local line
  line="$(grep -E "^${1}=" .env 2>/dev/null | tail -n 1 || true)"
  line="${line#*=}"; line="${line%$'\r'}"
  case "$line" in \"*\") line="${line#\"}"; line="${line%\"}";; \'*\') line="${line#\'}"; line="${line%\'}";; esac
  printf '%s' "$line"
}

if [ ! -f .env ]; then
  gen() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  sed -e "s/^LATEX_API_KEYS=.*/LATEX_API_KEYS=chemolymp:$(gen),egormath:$(gen),chgkmsu:$(gen)/" \
      -e "s/^LATEX_DOMAIN=.*/LATEX_DOMAIN=${LATEX_DOMAIN:-latex.emukhin.ru}/" .env.example > .env
  chmod 600 .env
  echo "==> .env создан со случайными ключами: $APP_DIR/.env"
  echo "    Ключ chgkmsu замените на прежний (config.py старого сервера), остальные — в .env проектов."
fi

mkdir -p data/fonts data/assets data/table_signs data/templates
docker network inspect edge >/dev/null 2>&1 || docker network create edge

echo "==> Building image (первый раз долго: база TeX Live ~5 ГБ)"
docker compose build

echo "==> Starting"
docker compose up -d --remove-orphans

PORT="$(env_get LATEX_API_PORT)"; PORT="${PORT:-8100}"
echo "==> Health (127.0.0.1:$PORT)"
ok=0
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
if [ "$ok" != 1 ]; then echo "!! /health не отвечает"; docker compose logs --tail=50; exit 1; fi
curl -sS "http://127.0.0.1:$PORT/health"; echo

DOMAIN="$(env_get LATEX_DOMAIN)"
# Сайт Caddy включаем только когда DNS домена уже смотрит на этот сервер: иначе Caddy начнёт
# запрашивать сертификат на чужой IP и упрётся в лимиты Let's Encrypt (см. chemolymp RUNBOOK §1.3).
# Обойти проверку (например, DNS ещё не разъехался по кэшам): FORCE_CADDY_SITE=1 ./scripts/deploy.sh
dns_ok=1
if [ -n "$DOMAIN" ] && [ -z "${FORCE_CADDY_SITE:-}" ]; then
  resolved="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')"
  my_ips="$(hostname -I 2>/dev/null) $(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || true)"
  dns_ok=0
  for ip in $resolved; do
    case " $my_ips " in *" $ip "*) dns_ok=1;; esac
  done
  if [ "$dns_ok" != 1 ]; then
    echo "!! DNS: $DOMAIN → ${resolved:-<не резолвится>}, а этот сервер — $my_ips"
    echo "   Сайт Caddy не настраиваю. Поправьте A-запись и повторите ./scripts/deploy.sh (или FORCE_CADDY_SITE=1)."
  fi
fi
if [ -n "$DOMAIN" ] && [ -d "$CADDY_SITES_DIR" ] && [ "$dns_ok" = 1 ]; then
  echo "==> Caddy site: $DOMAIN → $CADDY_SITES_DIR/latex-api.caddy"
  sed "s/__DOMAIN__/$DOMAIN/g" deploy/latex-api.caddy.tmpl > "$CADDY_SITES_DIR/latex-api.caddy.tmp"
  mv -f "$CADDY_SITES_DIR/latex-api.caddy.tmp" "$CADDY_SITES_DIR/latex-api.caddy"
  if docker exec "$CADDY_CONTAINER" caddy reload --config /etc/caddy/Caddyfile 2>&1 | tail -3; then
    echo "==> Caddy перечитал конфигурацию"
  else
    echo "!! не удалось перезагрузить Caddy ($CADDY_CONTAINER): проверьте, что стек chemolymp запущен"
    echo "   и что его compose.prod.yaml монтирует $CADDY_SITES_DIR (PR «latex-api on demo»)."
  fi
elif [ "$dns_ok" = 1 ]; then
  echo "!! LATEX_DOMAIN пуст или нет $CADDY_SITES_DIR — сайт Caddy не настроен (нужен scripts/server-prepare.sh от root)"
fi
echo "==> OK"
