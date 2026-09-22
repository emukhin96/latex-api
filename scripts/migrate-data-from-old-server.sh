#!/usr/bin/env bash
# Перенос данных latex-api со старого сервера (systemd, /opt/latex-api) на новый (docker, /opt/latex-api/data).
# Запускать с Mac: у него есть ssh и туда, и туда; серверы друг друга по ssh не знают.
#   OLD=root@81.200.147.78 NEW=chemolymp-demo ./scripts/migrate-data-from-old-server.sh
# Переносит данные chgkmsu (fonts/, table_signs/, templates/) и egormath (egor.sty и шрифты из
# системных путей) и печатает старый API-ключ (для LATEX_API_KEYS=chgkmsu:… и egormath:…).
set -euo pipefail

OLD="${OLD:-root@81.200.147.78}"
NEW="${NEW:-chemolymp-demo}"
OLD_DIR="${OLD_DIR:-/opt/latex-api}"
NEW_DIR="${NEW_DIR:-/opt/latex-api/data}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

copy() {  # copy <src на старом> <dst относительно $NEW_DIR>
  local src="$1" dst="$2"
  echo "==> $OLD:$src → $NEW:$NEW_DIR/$dst"
  mkdir -p "$TMP/$dst"
  if rsync -az "$OLD:$src/" "$TMP/$dst/" 2>/dev/null; then
    rsync -az "$TMP/$dst/" "$NEW:$NEW_DIR/$dst/"
  else
    echo "   (нет на старом сервере — пропускаю)"
  fi
}

# chgkmsu: шрифты по путям /opt/latex-api/fonts/… (шаблоны ссылаются на них напрямую), таблички, roster
copy "$OLD_DIR/fonts"        fonts
copy "$OLD_DIR/table_signs"  table_signs
copy "$OLD_DIR/templates"    templates
# egormath (egormath-web/deploy/DEPLOY.md): пакеты egor.sty/chem.sty/egorbeamer.sty из TEXMFLOCAL,
# шрифты CMU/SchoolBookC/TextBookC из /usr/local/share/fonts, картинки \home/\kolba из compile/
copy "/usr/local/texlive/texmf-local/tex/latex/egor" assets/egormath
copy "/usr/local/share/fonts/cmu"   fonts/cmu
copy "/usr/local/share/fonts/egor"  fonts/egor
mkdir -p "$TMP/egormath-pics"
for f in home.jpeg kolba-round.png; do
  rsync -az "$OLD:$OLD_DIR/compile/$f" "$TMP/egormath-pics/" 2>/dev/null || true
done
if [ -n "$(ls -A "$TMP/egormath-pics")" ]; then
  rsync -az "$TMP/egormath-pics/" "$NEW:$NEW_DIR/assets/egormath/"
fi

echo "==> Старый API-ключ (подставьте в LATEX_API_KEYS=chgkmsu:… на новом сервере):"
ssh "$OLD" "grep -E '^API_KEY' $OLD_DIR/config.py || echo '   (config.py не найден — ключ берётся из окружения systemd?)'"
echo "==> Готово. Проверьте на новом сервере: ls -la $NEW_DIR/fonts"
