# -*- coding: utf-8 -*-
"""
latex-api — HTTP-сервис компиляции TeX → PDF (общий для chemolymp, egormath, chgkmsu).

Универсальный эндпоинт (для всех новых интеграций):

  POST /api/v1/compile
    Authorization: Bearer <ключ проекта>
    {"tex": "<исходник>", "engine": "xelatex" | "lualatex" | "pdflatex",
     "assets": {"logo.png": "<base64>", …}, "passes": 1}
  → 200 application/pdf (байты) — если Accept содержит application/pdf или не задан;
    200 {"pdf": "<base64>"} — если Accept: application/json;
    400 {"error": …} — плохой запрос; 401 — ключ; 413 — превышен размер;
    422 {"error": …, "summary": "./main.tex:12: …", "log": "<хвост .log>"} — TeX не собрал;
    503 + Retry-After — все слоты компиляции заняты (клиент повторяет с backoff).

Ассеты запроса кладутся рядом с main.tex; общие файлы (фоны сертификатов, логотипы)
лежат в ASSETS_DIR на сервере и доступны по имени через TEXINPUTS (`\\includegraphics{bg.pdf}`).
Шрифты — в FONTS_DIR (fontconfig + OSFONTDIR, а также напрямую по пути /opt/latex-api/fonts/…).

Старые эндпоинты chgkmsu (/api/v1/compile-latex, /api/v1/table-signs, /api/v1/compile-roster) —
в legacy.py, контракт не менялся.
"""

import base64
import binascii
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

from config import (
    API_KEYS,
    APP_VERSION,
    COMPILE_DIR,
    DEFAULT_ENGINE,
    ENGINES,
    MAX_ASSETS_BYTES,
    MAX_PASSES,
    MAX_TEX_BYTES,
)
from core import (
    Busy,
    CompileError,
    authenticate,
    check_rate_limit,
    compile_slot,
    engine_path,
    logger,
    run_engine,
    tex_error_summary,
)
from legacy import bp as legacy_bp

app = Flask(__name__)
# Большие пакеты chgkmsu (100 бланков) и ассеты сертификатов: лимит тела 64 МБ.
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
app.register_blueprint(legacy_bp)

_ASSET_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def _error(status: int, message: str, **extra):
    payload = {"success": False, "error": message, **extra}
    return jsonify(payload), status


@app.get("/health")
def health():
    """Без аутентификации: используется healthcheck контейнера и мониторингом."""
    engines = {name: engine_path(name) is not None for name in ENGINES}
    ok = engines.get(DEFAULT_ENGINE, False)
    return jsonify(
        {
            "status": "ok" if ok else "degraded",
            "service": "latex-api",
            "version": APP_VERSION,
            "engines": engines,
            "lualatex_available": engines.get("lualatex", False),  # поле старого /health
            "keys_configured": len(API_KEYS),
        }
    ), (200 if ok else 503)


@app.post("/api/v1/compile")
def compile_generic():
    client = authenticate()
    if client is None:
        logger.warning("Invalid API key from %s", request.remote_addr)
        return _error(401, "Invalid or missing API key")
    if not check_rate_limit():
        return _error(429, "Rate limit exceeded")

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error(400, "Request body must be a JSON object")

    tex = data.get("tex")
    if not isinstance(tex, str) or not tex.strip():
        return _error(400, 'Field "tex" (string) is required')
    if len(tex.encode("utf-8")) > MAX_TEX_BYTES:
        return _error(413, f"tex is larger than {MAX_TEX_BYTES} bytes")

    engine = data.get("engine") or DEFAULT_ENGINE
    if engine not in ENGINES:
        return _error(400, f"Unknown engine {engine!r}; allowed: {', '.join(ENGINES)}")
    if engine_path(engine) is None:
        return _error(503, f"Engine {engine!r} is not installed on this server")

    passes = data.get("passes", 1)
    if not isinstance(passes, int) or isinstance(passes, bool) or not 1 <= passes <= MAX_PASSES:
        return _error(400, f'"passes" must be an integer from 1 to {MAX_PASSES}')

    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        return _error(400, '"assets" must be an object {filename: base64}')
    decoded: dict[str, bytes] = {}
    total = 0
    for name, b64 in assets.items():
        if not isinstance(name, str) or not _ASSET_NAME.match(name) or name.startswith("."):
            return _error(400, f"Bad asset name {name!r}: letters, digits, . _ - only")
        if name.lower() in {"main.tex", "main.pdf", "main.log", "main.aux"}:
            return _error(400, f"Asset name {name!r} is reserved")
        if not isinstance(b64, str):
            return _error(400, f"Asset {name!r} must be a base64 string")
        try:
            blob = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            return _error(400, f"Asset {name!r} is not valid base64")
        total += len(blob)
        if total > MAX_ASSETS_BYTES:
            return _error(413, f"Assets exceed {MAX_ASSETS_BYTES} bytes in total")
        decoded[name] = blob

    wants_json = _wants_json()
    started = datetime.now()
    workdir = Path(tempfile.mkdtemp(prefix=f"{client}-", dir=COMPILE_DIR))
    try:
        (workdir / "main.tex").write_text(tex, encoding="utf-8")
        for name, blob in decoded.items():
            (workdir / name).write_bytes(blob)
        try:
            with compile_slot():
                pdf_path = run_engine(engine, workdir, "main.tex", passes=passes)
        except Busy:
            logger.warning("[%s] all compile slots busy", client)
            body, status = _error(503, "Server busy, retry later")
            return body, status, {"Retry-After": "10"}
        except CompileError as exc:
            summary = tex_error_summary(exc.log)
            logger.warning("[%s] %s failed: %s", client, engine, summary or exc)
            return _error(422, str(exc), summary=summary, log=exc.log)
        pdf = pdf_path.read_bytes()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    elapsed = (datetime.now() - started).total_seconds()
    logger.info("[%s] %s ok: %d bytes in %.2fs", client, engine, len(pdf), elapsed)
    headers = {"X-Compile-Seconds": f"{elapsed:.2f}", "X-Client": client}
    if wants_json:
        b64 = base64.b64encode(pdf).decode("ascii")
        return jsonify({"success": True, "pdf": b64}), 200, headers
    return Response(pdf, status=200, mimetype="application/pdf", headers=headers)


def _wants_json() -> bool:
    """JSON только если клиент явно попросил (Accept: application/json без application/pdf,
    или ?format=json). По умолчанию — сырые байты PDF: короче и без base64-раздувания."""
    if request.args.get("format") == "json":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "application/pdf" not in accept


@app.errorhandler(404)
def not_found(exc):
    return _error(404, "Endpoint not found")


@app.errorhandler(405)
def method_not_allowed(exc):
    return _error(405, "Method not allowed")


@app.errorhandler(413)
def too_large(exc):
    return _error(413, "Request body too large")


@app.errorhandler(500)
def internal_error(exc):
    logger.error("Internal error: %s", exc, exc_info=True)
    return _error(500, "Internal server error")


if __name__ == "__main__":
    from config import FLASK_DEBUG, FLASK_HOST, FLASK_PORT

    logger.info("Starting latex-api %s on %s:%s", APP_VERSION, FLASK_HOST, FLASK_PORT)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
