# -*- coding: utf-8 -*-
"""
Общие части latex-api: логирование, аутентификация по ключу, лимиты, запуск TeX-движков.

Используется и новым универсальным эндпоинтом (/api/v1/compile, app.py), и старыми
эндпоинтами chgkmsu (legacy.py).
"""

import base64
import binascii
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import time

from flask import g, request

import config
from config import (
    API_KEYS,
    ASSETS_DIR,
    CLEANUP_AFTER_COMPILATION,
    COMPILE_DIR,
    COMPILE_TIMEOUT,
    ENGINES,
    LOG_BACKUP_COUNT,
    LOG_FILE,
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_TAIL_CHARS,
    LOG_TO_FILE,
    LOGS_DIR,
    LUALATEX_PATH,
    MAX_CONCURRENT_COMPILES,
    QUEUE_WAIT_SECONDS,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_PER_MINUTE,
)

# ---------- логирование ----------


def setup_logging() -> logging.Logger:
    root = logging.getLogger()
    if getattr(root, "_latex_api_configured", False):
        return logging.getLogger("latex-api")
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if LOG_TO_FILE:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    root._latex_api_configured = True  # type: ignore[attr-defined]
    return logging.getLogger("latex-api")


logger = setup_logging()

COMPILE_DIR.mkdir(parents=True, exist_ok=True)


# ---------- аутентификация ----------


def authenticate() -> str | None:
    """Возвращает имя клиента по ключу из `Authorization: Bearer …` или поля `api_key`
    в JSON-теле (старый способ chgkmsu). None — ключ не подошёл или ключей нет вовсе."""
    if not API_KEYS:
        return None
    key = ""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        key = auth_header[7:].strip()
    if not key and request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict) and isinstance(data.get("api_key"), str):
            key = data["api_key"]
    client = API_KEYS.get(key)
    if client:
        g.client = client
    return client


def check_api_key() -> bool:
    """Совместимость со старым кодом."""
    return authenticate() is not None


def client_name() -> str:
    return getattr(g, "client", None) or "anonymous"


# ---------- rate limit (по клиенту, выключен по умолчанию) ----------

_request_times: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()


def check_rate_limit(subject: str | None = None) -> bool:
    if not RATE_LIMIT_ENABLED:
        return True
    subject = subject or client_name()
    now = time()
    with _rate_lock:
        recent = [t for t in _request_times[subject] if now - t < 60]
        if len(recent) >= RATE_LIMIT_PER_MINUTE:
            _request_times[subject] = recent
            return False
        recent.append(now)
        _request_times[subject] = recent
    return True


# ---------- семафор на компиляции ----------

_slots = threading.BoundedSemaphore(MAX_CONCURRENT_COMPILES)


class Busy(Exception):
    """Все слоты компиляции заняты дольше QUEUE_WAIT_SECONDS."""


@contextmanager
def compile_slot():
    if not _slots.acquire(timeout=QUEUE_WAIT_SECONDS):
        raise Busy()
    try:
        yield
    finally:
        _slots.release()


# ---------- запуск движков ----------


class CompileError(Exception):
    """Движок вернул ненулевой код или не создал PDF. `log` — хвост .log/stdout."""

    def __init__(self, message: str, log: str = ""):
        super().__init__(message)
        self.log = log


class CompileTimeout(CompileError):
    pass


def engine_path(engine: str) -> str | None:
    """Абсолютный путь к движку или None, если он не установлен."""
    exe = ENGINES.get(engine)
    return shutil.which(exe) if exe else None


def _tex_env(workdir: Path) -> dict[str, str]:
    env = os.environ.copy()
    # Сначала рабочая папка запроса, потом общие ассеты (рекурсивно), потом стандартные пути.
    env["TEXINPUTS"] = f"{workdir}:{ASSETS_DIR}//:"
    env["TEXMFOUTPUT"] = str(workdir)  # .log/.aux сюда, даже если исходник read-only
    env.setdefault("max_print_line", "1000")
    return env


def run_engine(engine: str, workdir: Path, main_tex: str = "main.tex", passes: int = 1) -> Path:
    """Запускает `engine` над `workdir/main_tex` `passes` раз; возвращает путь к PDF.

    Без shell-escape: TeX-исходник приходит от клиента, и хотя клиент аутентифицирован,
    исполнять команды на сервере он не должен. Аргумент `-output-directory` держит все
    артефакты в `workdir`, который вызывающий код удаляет.
    """
    exe = engine_path(engine)
    if exe is None:
        raise CompileError(f"engine {engine!r} is not installed")
    cmd = [
        exe,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-no-shell-escape",
        f"-output-directory={workdir}",
        main_tex,
    ]
    pdf = workdir / (Path(main_tex).stem + ".pdf")
    log_file = workdir / (Path(main_tex).stem + ".log")
    output = ""
    for n in range(1, passes + 1):
        logger.info("[%s] %s pass %d/%d in %s", client_name(), engine, n, passes, workdir.name)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                env=_tex_env(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                timeout=COMPILE_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            raise CompileTimeout(
                f"{engine} timed out after {COMPILE_TIMEOUT}s", _log_tail(log_file, output)
            ) from exc
        output = proc.stdout or ""
        if proc.returncode != 0:
            raise CompileError(
                f"{engine} exited with code {proc.returncode}", _log_tail(log_file, output)
            )
    if not pdf.exists():
        raise CompileError("PDF was not produced", _log_tail(log_file, output))
    return pdf


def _log_tail(log_file: Path, fallback: str) -> str:
    text = fallback
    try:
        if log_file.exists():
            text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return text[-LOG_TAIL_CHARS:]


def tex_error_summary(log: str) -> str:
    """Первая строка вида `./main.tex:12: Undefined control sequence.` (или `! …`) из лога."""
    for line in log.splitlines():
        if re.match(r"^(\./)?[\w./-]+:\d+: ", line) or line.startswith("! "):
            return line.strip()[:300]
    return ""


# ---------- старые эндпоинты (chgkmsu, egormath): PDF с меткой времени в COMPILE_DIR ----------

LEGACY_ENGINE = config.LEGACY_ENGINE
LEGACY_PASSES = config.LEGACY_PASSES
_LEGACY_MAX_ASSETS = 20
_LEGACY_MAX_ASSET_BYTES = 5 * 1024 * 1024


def _write_legacy_assets(workdir: Path, assets) -> None:
    """`assets` у элемента tex_files (egormath): [{"filename", "content_base64"}] — рядом с .tex."""
    if not assets:
        return
    if not isinstance(assets, list) or len(assets) > _LEGACY_MAX_ASSETS:
        raise RuntimeError(f"too many assets (max {_LEGACY_MAX_ASSETS})")
    for asset in assets:
        if not isinstance(asset, dict):
            raise RuntimeError("asset must be an object")
        filename = asset.get("filename", "")
        if (
            not isinstance(filename, str)
            or not filename
            or filename != os.path.basename(filename)
            or "/" in filename
            or "\\" in filename
            or filename.startswith(".")
        ):
            raise RuntimeError(f"bad asset filename: {filename!r}")
        try:
            raw = base64.b64decode(asset.get("content_base64", ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError(f"bad asset content: {filename}: {exc}") from exc
        if len(raw) > _LEGACY_MAX_ASSET_BYTES:
            raise RuntimeError(f"asset too large: {filename}")
        (workdir / filename).write_bytes(raw)


def compile_tex(
    tex_content: str,
    output_name: str,
    assets=None,
    *,
    engine: str = LEGACY_ENGINE,
    passes: int = LEGACY_PASSES,
) -> Path:
    """Как на старом сервере после патча egormath: XeLaTeX в два прогона (номера страниц
    `\pageref{LastPage}`), картинки/пакеты из `assets` рядом с .tex. Каждый документ
    собирается в своей временной папке, готовый PDF переносится в COMPILE_DIR под именем
    с меткой времени — дальше старый код склеивает их как раньше."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    final_pdf = COMPILE_DIR / f"{output_name}_{timestamp}.pdf"
    workdir = Path(tempfile.mkdtemp(prefix=f"{client_name()}-", dir=COMPILE_DIR))
    try:
        (workdir / "main.tex").write_text(tex_content, encoding="utf-8")
        _write_legacy_assets(workdir, assets)
        try:
            pdf = run_engine(engine, workdir, "main.tex", passes=passes)
        except CompileError as exc:
            logger.error("%s failed for %s: %s", engine, output_name, tex_error_summary(exc.log))
            # хвост лога: фатальная ошибка в конце, а не предупреждения преамбулы
            raise RuntimeError(f"{engine} failed: {exc.log[-8000:]}") from exc
        shutil.move(str(pdf), final_pdf)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    logger.info("PDF created: %s (%d bytes)", final_pdf.name, final_pdf.stat().st_size)
    return final_pdf


def cleanup_temp_files(pattern: str = "*", older_than_hours: int | None = None) -> None:
    if not CLEANUP_AFTER_COMPILATION:
        return
    now = datetime.now().timestamp()
    for path in COMPILE_DIR.glob(pattern):
        try:
            if path.is_dir():
                continue  # рабочие папки /api/v1/compile удаляет сам эндпоинт
            if older_than_hours and now - path.stat().st_mtime < older_than_hours * 3600:
                continue
            path.unlink()
        except OSError as exc:
            logger.warning("Failed to delete %s: %s", path, exc)


__all__ = [
    "LEGACY_ENGINE",
    "LEGACY_PASSES",
    "Busy",
    "CompileError",
    "CompileTimeout",
    "LUALATEX_PATH",
    "authenticate",
    "check_api_key",
    "check_rate_limit",
    "cleanup_temp_files",
    "client_name",
    "compile_slot",
    "compile_tex",
    "config",
    "engine_path",
    "logger",
    "run_engine",
    "tex_error_summary",
]
