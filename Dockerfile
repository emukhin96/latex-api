# latex-api: Flask + TeX Live (XeLaTeX/LuaLaTeX) в одном образе.
#
# База — официальный образ TeX Live (полная схема, ~5 ГБ на диске): в нём есть всё, что нужно
# шаблонам chgkmsu (moresize, babel), egormath и chemolymp (polyglossia, tikz, fontspec).
# Для экономии места можно собрать с `--build-arg TEXLIVE_IMAGE=texlive/texlive:latest-medium`,
# но тогда за отсутствующие пакеты придётся отвечать самому (tlmgr install …).
ARG TEXLIVE_IMAGE=texlive/texlive:latest
FROM ${TEXLIVE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# python для Flask; fontconfig + PT Serif/Sans (сертификаты chemolymp); curl для healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip fontconfig fonts-paratype curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# fontconfig видит шрифты TeX Live по имени семейства — но только OpenType/TrueType.
# Штатный texlive-fontconfig.conf подключает и type1/: тогда fontspec для «CMU Sans Serif»
# получает cmunss.pfb, а xdvipdfmx падает: «Error occurred while loading font …cmunss.pfb».
RUN dist="$(kpsewhich -var-value TEXMFDIST)" \
    && printf '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n  <dir>%s/fonts/opentype</dir>\n  <dir>%s/fonts/truetype</dir>\n</fontconfig>\n' "$dist" "$dist" \
       > /etc/fonts/conf.d/09-texlive.conf
COPY deploy/fonts.conf /etc/fonts/conf.d/10-latex-api.conf
RUN fc-cache -fs >/dev/null && fc-match "CMU Sans Serif" | grep -q '\.otf' \
    || { echo "!! fontconfig отдаёт для CMU не OpenType:"; fc-match "CMU Sans Serif"; exit 1; }

# Тот же путь, что на старом сервере: шаблоны chgkmsu ссылаются на /opt/latex-api/fonts/… напрямую.
WORKDIR /opt/latex-api
RUN useradd --system --create-home --home-dir /home/latexapi --shell /usr/sbin/nologin latexapi

COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

COPY --chown=latexapi:latexapi . .
RUN mkdir -p compile logs fonts assets table_signs templates \
    && chown -R latexapi:latexapi /opt/latex-api

USER latexapi
# luaotfload ищет системные шрифты и в fonts/ сервиса; кэш и texmf-var пользователя — в $HOME
ENV HOME=/home/latexapi \
    OSFONTDIR=/opt/latex-api/fonts// \
    LATEX_API_HOME=/opt/latex-api
# Прогрев базы шрифтов LuaLaTeX и форматов: без этого первый запрос после запуска идёт минуты.
RUN luaotfload-tool --update --force >/dev/null 2>&1 || true \
    && printf '\\documentclass{article}\\begin{document}warm-up\\end{document}\n' > /tmp/w.tex \
    && (cd /tmp && lualatex -interaction=batchmode w.tex >/dev/null 2>&1; xelatex -interaction=batchmode w.tex >/dev/null 2>&1; rm -f w.*)

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Один процесс + потоки: семафор компиляций (LATEX_MAX_CONCURRENT) общий на весь сервис.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", \
     "--timeout", "300", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
