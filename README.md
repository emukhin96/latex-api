# latex-api — сервис компиляции TeX → PDF

Один HTTP-сервис для всех проектов (chemolymp, egormath, chgkmsu): принимает TeX-исходник,
возвращает PDF. Живёт в Docker на демо-сервере chemolymp (`77.232.132.139`) за общим Caddy,
домен `latex.emukhin.ru`. История: изначально был частью chgkmsu (`chgkmsu/latex-api-service`)
и работал как systemd-сервис на отдельном VPS `81.200.147.78`, где его дополнительно патчил
egormath (`egormath-web/deploy/patch_latex_api_egormath.py`: xelatex, два прогона, assets).
Эта версия воспроизводит поведение того сервера **после** патча. Старые инструкции —
`docs/legacy-systemd/`.

## Устройство

```
Caddy (стек chemolymp, :443) ──edge──▶ latex-api:8000 (gunicorn, 1 процесс × 4 потока)
                                          │  семафор: ≤ LATEX_MAX_CONCURRENT компиляций
                                          ▼
                                    xelatex / lualatex / pdflatex (TeX Live, -no-shell-escape)
/opt/latex-api/                       — код (rsync с Mac или git)
/opt/latex-api/.env                   — ключи и лимиты (не в git)
/opt/latex-api/data/fonts/            → /opt/latex-api/fonts     (Circe, CMU, PPNeueMachina, …)
/opt/latex-api/data/assets/           → /opt/latex-api/assets    (фоны сертификатов, логотипы; \includegraphics по имени)
/opt/latex-api/data/table_signs/      → /opt/latex-api/table_signs (шаблон табличек chgkmsu)
/opt/latex-api/data/templates/        → /opt/latex-api/templates (roster_template.tex для deprecated-эндпоинта)
/opt/caddy/sites/latex-api.caddy      — сайт для Caddy, генерирует scripts/deploy.sh
```

Файлы: `app.py` (Flask, `/health`, `/api/v1/compile`), `core.py` (ключи, лимиты, запуск движков),
`legacy.py` (эндпоинты chgkmsu без изменений контракта), `config.py` (всё из env, секретов нет).

## API

Аутентификация — `Authorization: Bearer <ключ>`; ключи по проектам задаются в `.env`
(`LATEX_API_KEYS=chemolymp:…,egormath:…,chgkmsu:…`), имя проекта попадает в логи.
Старый способ — поле `api_key` в JSON — тоже работает.

### `POST /api/v1/compile` — универсальный (для chemolymp, egormath и новых интеграций)

```json
{"tex": "\\documentclass{article}…", "engine": "xelatex", "assets": {"logo.png": "<base64>"}, "passes": 1}
```

- `engine`: `xelatex` (по умолчанию), `lualatex`, `pdflatex`; `passes`: 1–3 (для оглавлений/ссылок).
- `assets`: файлы рядом с `main.tex` (имена — буквы, цифры, `. _ -`; до 25 МБ суммарно).
  Общие файлы кладутся на сервер в `data/assets/` (можно в подпапки) и доступны по имени:
  `\includegraphics{certificate-bg.pdf}`.
- Ответ: `200 application/pdf` (байты). `Accept: application/json` или `?format=json` →
  `{"success": true, "pdf": "<base64>"}`.
- Ошибки — JSON `{"success": false, "error": …}`: `400` плохой запрос, `401` ключ, `413` размер,
  `422` TeX не собрался (+ `summary` — строка ошибки, `log` — хвост `.log`),
  `503` + `Retry-After` — все слоты заняты (клиент повторяет с backoff), `429` — rate limit (по умолчанию выключен).
- Заголовки ответа: `X-Compile-Seconds`, `X-Client`.

```bash
curl -sS https://latex.emukhin.ru/api/v1/compile -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/pdf' \
  -d '{"tex":"\\documentclass{article}\\begin{document}Привет\\end{document}","engine":"xelatex"}' -o out.pdf
```

### Эндпоинты chgkmsu и egormath (контракт не менялся)

- `POST /api/v1/compile-latex` — `{"tex_files": [{"team_id", "tex_content", "assets": [{"filename", "content_base64"}]}]}`
  → `{"success", "pdf_base64", "total_pages", …}`. Каждый файл — XeLaTeX в **два прогона** (как на старом
  сервере после патча egormath: `\pageref{LastPage}`), `assets` (≤ 20 × 5 МБ) кладутся рядом с `.tex`
  (egormath шлёт так картинки задач, `egorbeamer.sty`, шрифты Inter). Необязательные поля запроса
  `engine`/`passes` меняют движок и число прогонов. Ошибка: `500 {"error": "… <хвост лога>", "log": …}`.
- `POST /api/v1/table-signs` — таблички ReportLab поверх `table_signs/default_template.pdf` (JSON или `Accept: application/pdf`).
- `POST /api/v1/compile-roster` — deprecated, рендер `templates/roster_template.tex` на сервере.
- `GET /health` — без ключа: `{"status", "engines": {…}, "lualatex_available", "keys_configured"}`.

Отличия от старой версии: несколько ключей, лимит одновременных компиляций вместо лимита по IP
(все проекты ходят с одного сервера — IP-лимит их бы душил), `-no-shell-escape`, `503` при перегрузке,
каждый документ собирается в своей временной папке (assets разных запросов не пересекаются).

Что нужно egormath на сервере (переносит `scripts/migrate-data-from-old-server.sh`): `egor.sty`,
`chem.sty`, `egorbeamer*.sty` → `data/assets/egormath/` (виден через `TEXINPUTS`, как раньше TEXMFLOCAL),
шрифты SchoolBookC/TextBookC → `data/fonts/egor/`, CMU → `data/fonts/cmu/` (в образе они есть и так —
пакет `cm-unicode` TeX Live виден fontconfig как «CMU Serif»), `home.jpeg`/`kolba-round.png` →
`data/assets/egormath/`. `mathspec` и `beamer` входят в полный TeX Live образа.

## Развёртывание на демо-сервере chemolymp

Предпосылки: сервер настроен `chemolymp/scripts/server-bootstrap.sh` (Docker, пользователь `deploy`,
алиас `ssh chemolymp-demo`), в стек chemolymp влит PR «latex-api on demo» (Caddy импортирует
`/opt/caddy/sites/*.caddy` и состоит в сети `edge`), DNS `latex.emukhin.ru` → `77.232.132.139`.

```bash
# 1. Один раз от root: каталоги, сеть edge                                  [Mac]
scp scripts/server-prepare.sh root@77.232.132.139:/root/ && ssh root@77.232.132.139 'bash /root/server-prepare.sh'

# 2. Перенести шрифты/шаблоны/таблички и узнать старый ключ chgkmsu        [Mac]
OLD=root@81.200.147.78 NEW=chemolymp-demo ./scripts/migrate-data-from-old-server.sh

# 3. Код на сервер + сборка + запуск + сайт Caddy (первый раз 10–20 минут: база TeX Live ~5 ГБ)   [Mac]
./scripts/push.sh

# 4. Ключи: в /opt/latex-api/.env заменить chgkmsu:… на старый ключ, остальные раздать проектам   [сервер]
ssh chemolymp-demo 'nano /opt/latex-api/.env && cd /opt/latex-api && docker compose up -d'

# 5. Проверка                                                                 [Mac]
curl -sS https://latex.emukhin.ru/health
```

`scripts/deploy.sh` идемпотентен: повторный `./scripts/push.sh` пересобирает образ и перезапускает
контейнер; `.env` и `data/` не трогаются. Логи: `ssh chemolymp-demo 'cd /opt/latex-api && docker compose logs -f'`.

**Автодеплой из GitHub.** `.github/workflows/ci.yml` (ruff + pytest с настоящим xelatex) и
`deploy.yml`: после зелёного CI на `main` код уезжает на сервер по rsync и там запускается
`scripts/deploy.sh` — deploy-ключ репозитория на сервере не нужен. Секреты репозитория те же, что у
chemolymp: `DEMO_SSH_HOST` = `77.232.132.139`, `DEMO_SSH_KEY` = `~/.ssh/chemolymp-actions`; environment `demo`.

Ресурсы: контейнер ограничен `mem_limit: 1536m`, `cpus: 1.5`; `LATEX_MAX_CONCURRENT=2` — две
компиляции параллельно, остальные ждут до `LATEX_QUEUE_WAIT` секунд, потом `503`. При переезде
на сервер помощнее меняются только эти три числа.

## Переключение проектов

| Проект | Настройка |
|---|---|
| chemolymp | `.env`: `LATEX_API_URL=https://latex.emukhin.ru/api/v1/compile`, `LATEX_API_TOKEN=<ключ chemolymp>`, `LATEX_API_ENGINE=xelatex`; фон сертификата — файл в `data/assets/chemolymp/`, имя в `CERTIFICATE_BACKGROUND` (например `chemolymp/certificate-bg.pdf`) |
| chgkmsu | `LATEX_API_URL=https://latex.emukhin.ru` (без пути; ключ прежний, если перенесён в `LATEX_API_KEYS=chgkmsu:…`); шаблоны ссылаются на `/opt/latex-api/fonts/…` — путь внутри контейнера тот же |
| egormath | `.secrets/LATEX_API_URL=https://latex.emukhin.ru`, `LATEX_API_KEY` = ключ `egormath:…` (сейчас egormath ходит с ключом chgkmsu — при переключении URL выдать свой); `compile-latex` работает как прежде, новый код можно писать на `/api/v1/compile` |

Смена ключа проекта: поменять в `.env` сервера и в `.env` проекта, `docker compose up -d`.

## Локальная разработка

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
LATEX_API_KEYS=dev:dev .venv/bin/python app.py          # http://localhost:8000 (нужен xelatex в PATH)
.venv/bin/pytest -q                                      # тесты с реальным движком (пропускаются без него)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
docker compose build && LATEX_API_KEYS=dev:dev docker compose up   # как на сервере (сеть edge: docker network create edge)
```
