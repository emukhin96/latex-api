# -*- coding: utf-8 -*-
"""Тесты latex-api. Запуск: `pytest` из папки сервиса (нужен установленный xelatex/lualatex;
тесты, которым нужен движок, пропускаются, если его нет)."""

import base64
import importlib
import os
import shutil
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEY_A = "key-a-secret"
KEY_B = "key-b-secret"

MINIMAL_TEX = r"""\documentclass{article}
\begin{document}
Hello, latex-api.
\end{document}
"""

BROKEN_TEX = r"""\documentclass{article}
\begin{document}
\undefinedmacro
\end{document}
"""


@pytest.fixture(scope="session")
def home(tmp_path_factory):
    return tmp_path_factory.mktemp("latex-api-home")


@pytest.fixture(scope="session")
def modules(home):
    os.environ["LATEX_API_HOME"] = str(home)
    os.environ["LATEX_API_KEYS"] = f"alpha:{KEY_A}, beta:{KEY_B}"
    os.environ["LATEX_MAX_CONCURRENT"] = "1"
    os.environ["LATEX_QUEUE_WAIT"] = "1"
    os.environ["LATEX_COMPILE_TIMEOUT"] = "60"
    for name in ("config", "core", "legacy", "app"):
        sys.modules.pop(name, None)
    config = importlib.import_module("config")
    core = importlib.import_module("core")
    app = importlib.import_module("app")
    (home / "assets").mkdir(exist_ok=True)
    return config, core, app


@pytest.fixture
def client(modules):
    _, _, app = modules
    app.app.config["TESTING"] = True
    return app.app.test_client()


def _auth(key=KEY_A):
    return {"Authorization": f"Bearer {key}"}


def needs(engine):
    return pytest.mark.skipif(shutil.which(engine) is None, reason=f"{engine} not installed")


# ---------- auth / validation (без движка) ----------


def test_health_is_public(client):
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.get_json()
    assert body["service"] == "latex-api"
    assert "engines" in body and body["keys_configured"] == 2


def test_compile_requires_key(client):
    assert client.post("/api/v1/compile", json={"tex": MINIMAL_TEX}).status_code == 401
    resp = client.post("/api/v1/compile", json={"tex": MINIMAL_TEX}, headers=_auth("wrong"))
    assert resp.status_code == 401


def test_key_in_body_still_works_for_legacy(client, modules):
    """chgkmsu присылает api_key в JSON — старый способ должен работать."""
    resp = client.post("/api/v1/compile-latex", json={"api_key": KEY_B, "tex_files": []})
    assert resp.status_code == 400  # ключ принят, отказ уже по валидации tex_files
    assert "tex_files" in resp.get_json()["error"]


def test_validation_errors(client):
    h = _auth()
    assert client.post("/api/v1/compile", json={}, headers=h).status_code == 400
    assert client.post("/api/v1/compile", json={"tex": ""}, headers=h).status_code == 400
    bad_engine = client.post("/api/v1/compile", json={"tex": "x", "engine": "sh"}, headers=h)
    assert bad_engine.status_code == 400
    bad_passes = client.post("/api/v1/compile", json={"tex": "x", "passes": 9}, headers=h)
    assert bad_passes.status_code == 400
    for name in ("../etc/passwd", "a/b.png", ".hidden", "main.tex", "x y.png"):
        resp = client.post(
            "/api/v1/compile", json={"tex": "x", "assets": {name: "AA=="}}, headers=h
        )
        assert resp.status_code == 400, name
    not_b64 = client.post(
        "/api/v1/compile", json={"tex": "x", "assets": {"a.png": "@@@"}}, headers=h
    )
    assert not_b64.status_code == 400


def test_tex_too_large(client, modules):
    config = modules[0]
    big = "x" * (config.MAX_TEX_BYTES + 1)
    resp = client.post("/api/v1/compile", json={"tex": big}, headers=_auth())
    assert resp.status_code == 413


# ---------- реальная компиляция ----------


@needs("xelatex")
def test_compile_returns_pdf_bytes(client):
    resp = client.post(
        "/api/v1/compile",
        json={"tex": MINIMAL_TEX, "engine": "xelatex"},
        headers={**_auth(), "Accept": "application/pdf, application/json"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF")
    assert resp.headers["X-Client"] == "alpha"


@needs("xelatex")
def test_compile_json_format(client):
    resp = client.post(
        "/api/v1/compile?format=json", json={"tex": MINIMAL_TEX}, headers=_auth(KEY_B)
    )
    assert resp.status_code == 200
    pdf = base64.b64decode(resp.get_json()["pdf"])
    assert pdf.startswith(b"%PDF")
    resp2 = client.post(
        "/api/v1/compile",
        json={"tex": MINIMAL_TEX},
        headers={**_auth(), "Accept": "application/json"},
    )
    assert resp2.status_code == 200 and "pdf" in resp2.get_json()


@needs("xelatex")
def test_compile_error_gives_log(client):
    resp = client.post("/api/v1/compile", json={"tex": BROKEN_TEX}, headers=_auth())
    assert resp.status_code == 422
    body = resp.get_json()
    assert "Undefined control sequence" in body["log"]
    assert body["summary"].endswith("Undefined control sequence.")


@needs("xelatex")
def test_shell_escape_is_disabled(client):
    tex = r"""\documentclass{article}
\begin{document}
\immediate\write18{touch /tmp/latex-api-shell-escape-test}
ok
\end{document}
"""
    resp = client.post("/api/v1/compile", json={"tex": tex}, headers=_auth())
    assert resp.status_code == 200
    assert not os.path.exists("/tmp/latex-api-shell-escape-test")


@needs("xelatex")
def test_request_assets_and_shared_assets(client, modules):
    config = modules[0]
    # общий ассет на сервере: PDF, собранный тем же сервисом
    resp = client.post("/api/v1/compile", json={"tex": MINIMAL_TEX}, headers=_auth())
    shared = config.ASSETS_DIR / "sub"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "bg.pdf").write_bytes(resp.data)
    tex = r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
shared: \includegraphics[width=2cm]{bg.pdf}
request: \includegraphics[width=2cm]{logo.pdf}
\end{document}
"""
    resp = client.post(
        "/api/v1/compile",
        json={"tex": tex, "assets": {"logo.pdf": base64.b64encode(resp.data).decode()}},
        headers=_auth(),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)[:800]
    # рабочая папка запроса удалена
    leftovers = [p for p in config.COMPILE_DIR.iterdir() if p.is_dir()]
    assert leftovers == []


@needs("xelatex")
def test_busy_returns_503(client, modules):
    core = modules[1]
    assert core._slots.acquire(timeout=1)
    try:
        resp = client.post("/api/v1/compile", json={"tex": MINIMAL_TEX}, headers=_auth())
    finally:
        core._slots.release()
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "10"


@needs("xelatex")
def test_legacy_compile_latex_contract(client, modules):
    """chgkmsu: пакет tex_files → склеенный PDF в base64; движок и число прогонов — как на старом
    сервере после патча egormath (xelatex × 2)."""
    payload = {
        "api_key": KEY_B,
        "tex_files": [
            {"team_id": 1, "tex_content": MINIMAL_TEX},
            {"team_id": 2, "tex_content": MINIMAL_TEX},
        ],
    }
    resp = client.post("/api/v1/compile-latex", json=payload)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    body = resp.get_json()
    assert body["success"] is True and body["files_count"] == 2 and body["total_pages"] == 2
    assert base64.b64decode(body["pdf_base64"]).startswith(b"%PDF")
    config = modules[0]
    assert config.LEGACY_ENGINE == "xelatex" and config.LEGACY_PASSES == 2
    assert [p for p in config.COMPILE_DIR.iterdir() if p.is_dir()] == []


@needs("xelatex")
def test_legacy_assets_and_two_passes(client, modules):
    """egormath: assets у tex_file (картинки/пакеты рядом с .tex) и \\pageref{LastPage}
    (заполняется только вторым прогоном)."""
    first = client.post("/api/v1/compile", json={"tex": MINIMAL_TEX}, headers=_auth())
    sty = r"\ProvidesPackage{egortest}\newcommand{\hello}{HELLO-FROM-STY}"
    tex = r"""\documentclass{article}
\usepackage{graphicx,egortest,lastpage}
\begin{document}
\hello\ \includegraphics[width=1cm]{pic.pdf}\newpage
page \thepage/\pageref{LastPage}
\end{document}
"""
    payload = {
        "tex_files": [
            {
                "team_id": "doc",
                "tex_content": tex,
                "assets": [
                    {
                        "filename": "egortest.sty",
                        "content_base64": base64.b64encode(sty.encode()).decode(),
                    },
                    {
                        "filename": "pic.pdf",
                        "content_base64": base64.b64encode(first.data).decode(),
                    },
                ],
            }
        ]
    }
    resp = client.post("/api/v1/compile-latex", json=payload, headers=_auth(KEY_B))
    assert resp.status_code == 200, resp.get_data(as_text=True)[:800]
    body = resp.get_json()
    assert body["total_pages"] == 2
    pdf = base64.b64decode(body["pdf_base64"])
    assert pdf.startswith(b"%PDF")
    if shutil.which("pdftotext"):  # второй прогон подставил число страниц: «2/2»
        import subprocess

        text = subprocess.run(
            ["pdftotext", "-", "-"], input=pdf, capture_output=True, check=True
        ).stdout.decode()
        assert "HELLO-FROM-STY" in text and "2/2" in text
    # плохое имя ассета → 500 с текстом ошибки (как на старом сервере), а не путь наружу
    payload["tex_files"][0]["assets"] = [{"filename": "../x.sty", "content_base64": "AA=="}]
    resp = client.post("/api/v1/compile-latex", json=payload, headers=_auth(KEY_B))
    assert resp.status_code == 500 and "bad asset filename" in resp.get_json()["error"]
    assert "log" in resp.get_json()


@needs("xelatex")
def test_legacy_engine_override_and_error_log(client):
    payload = {"tex_files": [{"team_id": 1, "tex_content": BROKEN_TEX}], "passes": 1}
    resp = client.post("/api/v1/compile-latex", json=payload, headers=_auth())
    assert resp.status_code == 500
    body = resp.get_json()
    assert "Undefined control sequence" in body["log"]
    bad = client.post(
        "/api/v1/compile-latex",
        json={"tex_files": [{"team_id": 1, "tex_content": "x"}], "engine": "sh"},
        headers=_auth(),
    )
    assert bad.status_code == 400


def test_concurrent_requests_share_slots(client, modules):
    """Семафор общий для потоков: второй запрос ждёт, а не падает (QUEUE_WAIT=1 с достаточно,
    т. к. слот занят вручную лишь на 0.3 с)."""
    core = modules[1]
    if shutil.which("xelatex") is None:
        pytest.skip("xelatex not installed")
    results = []

    def hold():
        core._slots.acquire()
        threading.Event().wait(0.3)
        core._slots.release()

    t = threading.Thread(target=hold)
    t.start()
    results.append(client.post("/api/v1/compile", json={"tex": MINIMAL_TEX}, headers=_auth()))
    t.join()
    assert results[0].status_code == 200


def test_unknown_endpoint_is_json_404(client):
    resp = client.get("/nope")
    assert resp.status_code == 404 and resp.get_json()["error"] == "Endpoint not found"
    resp = client.get("/api/v1/compile")
    assert resp.status_code == 405 and resp.is_json


def _blank_pdf(width=842, height=596):
    import io

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.showPage()
    c.save()
    return buf.getvalue()


def test_table_signs_custom_template_and_font(client):
    import io

    import PyPDF2
    import reportlab

    font_path = os.path.join(os.path.dirname(reportlab.__file__), "fonts", "Vera.ttf")
    with open(font_path, "rb") as f:
        font_b64 = base64.b64encode(f.read()).decode()
    payload = {
        "teams": [
            {"number": 1, "name": "Short"},
            {"number": 2, "name": "A rather long team name for wrapping"},
        ],
        "template_base64": base64.b64encode(_blank_pdf()).decode(),
        "font_base64": font_b64,
        "text_box": [95, 18, 746, 142],
        "max_font_size": 60,
    }
    r = client.post("/api/v1/table-signs", json=payload,
                    headers={"Authorization": f"Bearer {KEY_A}", "Accept": "application/pdf"})
    assert r.status_code == 200, r.data[:500]
    reader = PyPDF2.PdfReader(io.BytesIO(r.data))
    assert len(reader.pages) == 2
    fonts = reader.pages[0]["/Resources"]["/Font"]
    # В PDF вшит шрифт из запроса (Bitstream Vera), а не PPNeueMachina сервера
    assert any("Vera" in str(fonts[k].get_object()["/BaseFont"]) for k in fonts)


def test_table_signs_bad_font(client):
    payload = {
        "teams": [{"number": 1, "name": "Team"}],
        "template_base64": base64.b64encode(_blank_pdf()).decode(),
        "font_base64": base64.b64encode(b"not a font").decode(),
    }
    r = client.post("/api/v1/table-signs", json=payload,
                    headers={"Authorization": f"Bearer {KEY_A}"})
    assert r.status_code == 400
    assert "font_base64" in r.get_json()["error"]


@pytest.mark.parametrize("font_b64", ["not base64 !!!", 12345])
def test_table_signs_bad_font_base64(client, font_b64):
    payload = {
        "teams": [{"number": 1, "name": "Team"}],
        "template_base64": base64.b64encode(_blank_pdf()).decode(),
        "font_base64": font_b64,
    }
    r = client.post("/api/v1/table-signs", json=payload,
                    headers={"Authorization": f"Bearer {KEY_A}"})
    assert r.status_code == 400
    assert "font_base64" in r.get_json()["error"]


def test_table_signs_font_not_kept_in_reportlab_registry(client):
    import reportlab
    from reportlab.lib import fonts as rl_fonts
    from reportlab.pdfbase import pdfmetrics

    font_path = os.path.join(os.path.dirname(reportlab.__file__), "fonts", "Vera.ttf")
    with open(font_path, "rb") as f:
        font_b64 = base64.b64encode(f.read()).decode()
    payload = {
        "teams": [{"number": 1, "name": "Team"}],
        "template_base64": base64.b64encode(_blank_pdf()).decode(),
        "font_base64": font_b64,
    }
    for _ in range(2):
        r = client.post("/api/v1/table-signs", json=payload,
                        headers={"Authorization": f"Bearer {KEY_A}", "Accept": "application/pdf"})
        assert r.status_code == 200
    assert not [n for n in pdfmetrics._fonts if n.startswith("SignFont-")]
    assert not [k for k in rl_fonts._ps2tt_map if k.startswith("signfont-")]
    assert not [f for f in pdfmetrics._dynFaceNames.values() if f.fontName.startswith("SignFont-")]


def _vera_bytes():
    import reportlab

    with open(os.path.join(os.path.dirname(reportlab.__file__), "fonts", "Vera.ttf"), "rb") as f:
        return f.read()


def test_table_signs_font_with_known_postscript_name(client, modules, monkeypatch):
    """Уже зарегистрированный шрифт с тем же PostScript-именем не подменяет шрифт запроса
    и не снимается с регистрации после него."""
    import io

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    import legacy

    server_font = TTFont("ServerVera", io.BytesIO(_vera_bytes()))
    pdfmetrics.registerFont(server_font)
    used = []
    real_register = legacy._register_request_font

    def spy(name, font):
        used.append(font)
        real_register(name, font)
        assert pdfmetrics.getFont(name) is font

    payload = {
        "teams": [{"number": 1, "name": "Team"}],
        "template_base64": base64.b64encode(_blank_pdf()).decode(),
        "font_base64": base64.b64encode(_vera_bytes()).decode(),
    }
    monkeypatch.setattr(legacy, "_register_request_font", spy)
    r = client.post("/api/v1/table-signs", json=payload,
                    headers={"Authorization": f"Bearer {KEY_A}", "Accept": "application/pdf"})
    assert r.status_code == 200
    assert used and used[0] is not server_font
    assert pdfmetrics.getFont("ServerVera") is server_font
    assert pdfmetrics._dynFaceNames[server_font.face.name] is server_font


def test_table_signs_font_base64_with_line_breaks(client):
    import textwrap

    wrapped = "\n".join(textwrap.wrap(base64.b64encode(_vera_bytes()).decode(), 76))
    payload = {
        "teams": [{"number": 1, "name": "Team"}],
        "template_base64": base64.b64encode(_blank_pdf()).decode(),
        "font_base64": wrapped,
    }
    r = client.post("/api/v1/table-signs", json=payload,
                    headers={"Authorization": f"Bearer {KEY_A}", "Accept": "application/pdf"})
    assert r.status_code == 200, r.data[:300]
