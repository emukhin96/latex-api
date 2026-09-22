# -*- coding: utf-8 -*-
"""
Конфигурация latex-api. Всё — из переменных окружения (см. .env.example), файл коммитится:
секретов в нём нет. Старый config.py с API_KEY внутри больше не нужен.
"""

import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_api_keys() -> dict[str, str]:
    """`LATEX_API_KEYS="chemolymp:abc,egormath:def"` → {"abc": "chemolymp", "def": "egormath"}.
    Ключ → имя клиента (имя идёт в логи и в лимиты). `LATEX_API_KEY` (один ключ, как раньше)
    поддерживается под именем `default`."""
    keys: dict[str, str] = {}
    for item in _env("LATEX_API_KEYS").split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, key = item.partition(":")
        if not sep or not key.strip():
            raise ValueError(f"LATEX_API_KEYS: expected name:key, got {item!r}")
        keys[key.strip()] = name.strip() or "default"
    legacy = _env("LATEX_API_KEY")
    if legacy and legacy != "change_me_to_secret_key_12345":
        keys.setdefault(legacy, "default")
    return keys


# Базовый путь: в контейнере /opt/latex-api, локально — папка с кодом.
BASE_DIR = Path(_env("LATEX_API_HOME") or Path(__file__).resolve().parent)

# Ключи API: значение → имя клиента. Пусто = сервис отвечает 401 на всё, кроме /health.
API_KEYS: dict[str, str] = _parse_api_keys()

# Каталоги. fonts/ и templates/ — по тем же путям, что и раньше: шаблоны chgkmsu ссылаются
# на /opt/latex-api/fonts/... напрямую (fontspec Path=).
FONTS_DIR = BASE_DIR / "fonts"
ASSETS_DIR = BASE_DIR / "assets"  # общие файлы для \includegraphics (фоны сертификатов и т. п.)
TEMPLATES_DIR = BASE_DIR / "templates"
TABLE_SIGNS_DIR = BASE_DIR / "table_signs"
COMPILE_DIR = Path(_env("LATEX_COMPILE_DIR") or BASE_DIR / "compile")
LOGS_DIR = BASE_DIR / "logs"

# Движки. Имя → исполняемый файл (переопределяется через *_PATH, если не в PATH).
ENGINES: dict[str, str] = {
    "xelatex": _env("XELATEX_PATH") or "xelatex",
    "lualatex": _env("LUALATEX_PATH") or "lualatex",
    "pdflatex": _env("PDFLATEX_PATH") or "pdflatex",
}
DEFAULT_ENGINE = _env("LATEX_DEFAULT_ENGINE") or "xelatex"
LUALATEX_PATH = ENGINES["lualatex"]
# Старые эндпоинты (compile-latex, compile-roster): на старом сервере после патча egormath
# (egormath-web/deploy/patch_latex_api_egormath.py) — XeLaTeX в два прогона. Так и оставляем.
LEGACY_ENGINE = _env("LATEX_LEGACY_ENGINE") or "xelatex"
LEGACY_PASSES = max(1, min(3, _env_int("LATEX_LEGACY_PASSES", 2)))

# Лимиты компиляции
COMPILE_TIMEOUT = _env_int("LATEX_COMPILE_TIMEOUT", 90)  # секунд на один проход
LUALATEX_TIMEOUT = COMPILE_TIMEOUT
MAX_PASSES = 3
MAX_TEX_BYTES = _env_int("LATEX_MAX_TEX_BYTES", 2 * 1024 * 1024)
MAX_ASSETS_BYTES = _env_int("LATEX_MAX_ASSETS_BYTES", 25 * 1024 * 1024)
MAX_TEAMS_PER_REQUEST = _env_int("LATEX_MAX_TEAMS", 100)
# Отладка: LATEX_KEEP_FAILED=1 — не удалять рабочую папку упавшей сборки (посмотреть .log, картинки)
KEEP_FAILED_WORKDIRS = _env_bool("LATEX_KEEP_FAILED", False)
LOG_TAIL_CHARS = 8000  # сколько хвоста .log отдаём клиенту при ошибке компиляции

# Параллельность: одновременно компилируется не больше N документов, остальные ждут слот
# до QUEUE_WAIT_SECONDS, потом 503 (клиенты повторяют с backoff). Это защита демо-сервера
# от массовой генерации сертификатов, а не rate limit по IP.
MAX_CONCURRENT_COMPILES = max(1, _env_int("LATEX_MAX_CONCURRENT", 2))
QUEUE_WAIT_SECONDS = _env_int("LATEX_QUEUE_WAIT", 30)

# Rate limit по клиенту (запросов в минуту). 0 — выключен (по умолчанию: все проекты ходят
# с одного сервера, лимит по IP не имеет смысла; нагрузку сдерживает семафор выше).
RATE_LIMIT_PER_MINUTE = _env_int("LATEX_RATE_LIMIT_PER_MINUTE", 0)
RATE_LIMIT_ENABLED = RATE_LIMIT_PER_MINUTE > 0

# Flask (только для `python app.py`; в контейнере запускает gunicorn)
FLASK_HOST = _env("FLASK_HOST") or "0.0.0.0"
FLASK_PORT = _env_int("FLASK_PORT", 8000)
FLASK_DEBUG = _env_bool("FLASK_DEBUG", False)

# Логирование: stdout всегда (docker собирает), файл — по желанию
LOG_LEVEL = (_env("LOG_LEVEL") or "INFO").upper()
LOG_TO_FILE = _env_bool("LOG_TO_FILE", False)
LOG_FILE = LOGS_DIR / "latex-api.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# Очистка временных файлов старых эндпоинтов (compile/*.tex|pdf с временными метками)
CLEANUP_AFTER_COMPILATION = True
CLEANUP_OLDER_THAN_HOURS = 1

APP_VERSION = "2.0.0"
