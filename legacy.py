# -*- coding: utf-8 -*-
"""
Старые эндпоинты chgkmsu — перенесены из app.py без изменения контракта:

  POST /api/v1/compile-latex   {"tex_files": [{"team_id", "tex_content"}]} → {"success", "pdf_base64", …}
  POST /api/v1/table-signs     таблички ReportLab поверх PDF-шаблона (JSON или application/pdf)
  POST /api/v1/compile-roster  DEPRECATED — рендер roster_template.tex на сервере

Поведение — как на старом сервере ПОСЛЕ патча egormath (egormath-web/deploy/
patch_latex_api_egormath.py), а не как в исходном app.py chgkmsu: compile-latex собирает
XeLaTeX в два прогона и принимает у каждого tex_file поле `assets`
[{"filename", "content_base64"}] (≤ 20 файлов по 5 МБ). Необязательные поля запроса
`engine` и `passes` переопределяют движок/число прогонов.

Отличия от прежней версии: ключ проверяется через core.authenticate (несколько ключей),
rate limit — по клиенту, а не по IP; компиляция идёт через общий семафор (503, если сервер
занят), без shell-escape и в отдельной папке на документ (assets разных запросов не пересекаются).
"""
import base64
import io
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import PyPDF2
from flask import Blueprint, jsonify, request, send_file

from config import (
    BASE_DIR,
    CLEANUP_AFTER_COMPILATION,
    CLEANUP_OLDER_THAN_HOURS,
    COMPILE_DIR,
    ENGINES,
    FONTS_DIR,
    MAX_TEAMS_PER_REQUEST,
)
from core import (
    LEGACY_ENGINE,
    LEGACY_PASSES,
    Busy,
    check_api_key,
    check_rate_limit,
    cleanup_temp_files,
    client_name,
    compile_slot,
    compile_tex,
    logger,
)

bp = Blueprint("legacy", __name__)


def validate_request(data: Dict) -> tuple[bool, Optional[str]]:
    """Валидация входящих данных."""
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object"

    # Проверка обязательных полей
    required_fields = ['event', 'teams']
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"

    # Проверка структуры event
    event = data['event']
    if not isinstance(event, dict):
        return False, "Field 'event' must be an object"

    required_event_fields = ['name', 'place', 'date', 'max_players_per_team']
    for field in required_event_fields:
        if field not in event:
            return False, f"Missing required field in 'event': {field}"

    # Проверка teams
    teams = data['teams']
    if not isinstance(teams, list):
        return False, "Field 'teams' must be an array"

    if len(teams) == 0:
        return False, "Field 'teams' cannot be empty"

    if len(teams) > MAX_TEAMS_PER_REQUEST:
        return False, f"Too many teams (max {MAX_TEAMS_PER_REQUEST})"

    # Проверка структуры каждой команды
    required_team_fields = ['id', 'name', 'header_badge', 'checkboxes_line', 'players']
    for i, team in enumerate(teams):
        if not isinstance(team, dict):
            return False, f"Team at index {i} must be an object"

        for field in required_team_fields:
            if field not in team:
                return False, f"Missing required field in team[{i}]: {field}"

    return True, None


def render_latex_template(event: Dict, team: Dict) -> str:
    """Рендерит LaTeX шаблон с данными команды."""
    template_path = BASE_DIR / 'templates' / 'roster_template.tex'

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    # Читаем шаблон
    template = template_path.read_text(encoding='utf-8')

    # Подготавливаем контекст для замены Django template переменных
    # Шаблон использует Django template syntax: {{ variable }} и {% for %}

    # Подготавливаем игроков в формате для шаблона
    players_rows = []
    for player in team['players']:
        full_name = player.get('full_name', '').strip()
        if not full_name:
            continue

        # Статус (роль) и комментарий (факультет)
        status = player.get('status', '\\hspace{8mm}')
        comment = player.get('faculty', '').strip() or '\\hspace{5cm}'

        # Формируем строку как в Django шаблоне
        players_rows.append({
            'status': status,
            'fullname': full_name,
            'comment': comment,
        })

    # Добавляем пустые строки до минимум 6 игроков
    while len(players_rows) < 6:
        players_rows.append({
            'status': '\\hspace{8mm}',
            'fullname': '',
            'comment': '\\hspace{5cm}',
        })

    # Подготавливаем контекст для замены
    context = {
        'team_number': str(team.get('number', team['id'])),
        'team_name': team['name'],
        'team_label': team.get('faculty', ''),
        'tournament_day_label': event.get('day_label', ''),
        'tournament_name': event['name'],
        'tournament_place': event['place'],
        'tournament_date': event['date'],
        'team_place': '',
        'team_alert': '',
        'team_alert_note': '',
        'players_number': len([p for p in team['players'] if p.get('full_name', '').strip()]),
        'header_badge': team['header_badge'],
        'checkboxes_line': team['checkboxes_line'],
        'max_players': str(event['max_players_per_team']),
        'players': players_rows,
    }

    # Простая замена Django template переменных
    result = template

    # Заменяем простые переменные {{ variable }}
    replacements = {
        '{{ team_number }}': context['team_number'],
        '{{ team_name }}': context['team_name'],
        '{{ team_label }}': context['team_label'],
        '{{ tournament_day_label }}': context['tournament_day_label'],
        '{{ tournament_name }}': context['tournament_name'],
        '{{ tournament_place }}': context['tournament_place'],
        '{{ tournament_date }}': context['tournament_date'],
        '{{ team_place }}': context['team_place'],
        '{{ team_alert }}': context['team_alert'],
        '{{ team_alert_note }}': context['team_alert_note'],
        '{{ players_number }}': str(context['players_number']),
        '{{ header_badge }}': context['header_badge'],
        '{{ checkboxes_line }}': context['checkboxes_line'],
        '{{ max_players }}': context['max_players'],
    }

    for key, value in replacements.items():
        result = result.replace(key, value)

    # Обрабатываем цикл {% for player in players %}
    # Находим блок цикла
    loop_pattern = r'{%\s*for\s+player\s+in\s+players\s*%}(.*?){%\s*endfor\s*%}'
    loop_match = re.search(loop_pattern, result, re.DOTALL)

    if loop_match:
        loop_template = loop_match.group(1)
        loop_content = ''

        for idx, player in enumerate(players_rows, 1):
            player_text = loop_template
            # Заменяем переменные внутри цикла
            player_text = player_text.replace('{{ forloop.counter }}', str(idx))
            player_text = player_text.replace('{{ player.status }}', player['status'])
            player_text = player_text.replace('{{ player.fullname }}', player['fullname'])
            player_text = player_text.replace('{{ player.comment }}', player['comment'])
            loop_content += player_text

        # Заменяем весь блок цикла на сгенерированный контент
        result = result[:loop_match.start()] + loop_content + result[loop_match.end():]

    return result


def merge_pdfs(pdf_files: List[Path]) -> Path:
    """Объединяет несколько PDF в один."""
    if not pdf_files:
        raise ValueError("No PDF files to merge")

    if len(pdf_files) == 1:
        return pdf_files[0]

    merger = PyPDF2.PdfMerger()

    for pdf_path in pdf_files:
        with open(pdf_path, 'rb') as f:
            merger.append(f)

    # Создаем выходной файл
    output_path = COMPILE_DIR / f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.pdf"
    with open(output_path, 'wb') as f:
        merger.write(f)

    logger.info(f"Merged {len(pdf_files)} PDFs into {output_path}")
    return output_path



@bp.route('/api/v1/compile-latex', methods=['POST'])
def compile_latex():
    """
    Компилирует готовые .tex файлы в PDF.

    Принимает массив готовых .tex файлов (отрендеренных на стороне Django).
    """
    start_time = datetime.now()

    try:
        # Проверка API ключа
        if not check_api_key():
            logger.warning(f"Invalid API key from {request.remote_addr}")
            return jsonify({
                'success': False,
                'error': 'Invalid or missing API key'
            }), 401

        # Проверка rate limit
        if not check_rate_limit():
            logger.warning(f"Rate limit exceeded for {client_name()}")
            return jsonify({
                'success': False,
                'error': 'Rate limit exceeded'
            }), 429

        # Получаем данные
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body must be JSON'
            }), 400

        # Проверяем наличие tex_files
        tex_files = data.get('tex_files', [])
        if not tex_files or not isinstance(tex_files, list):
            return jsonify({
                'success': False,
                'error': 'Field "tex_files" is required and must be an array'
            }), 400

        if len(tex_files) > 100:  # Лимит
            return jsonify({
                'success': False,
                'error': 'Too many files (max 100)'
            }), 400

        # Движок и число прогонов — как на старом сервере (xelatex × 2); клиент может задать свои
        engine = data.get('engine') or LEGACY_ENGINE
        passes = data.get('passes', LEGACY_PASSES)
        if engine not in ENGINES:
            return jsonify({'success': False, 'error': f'Unknown engine {engine!r}'}), 400
        if not isinstance(passes, int) or isinstance(passes, bool) or not 1 <= passes <= 3:
            return jsonify({'success': False, 'error': '"passes" must be 1..3'}), 400

        logger.info(f"[{client_name()}] Compiling {len(tex_files)} LaTeX files ({engine} x{passes})")

        # Компилируем PDF для каждого .tex файла
        pdf_files = []
        for idx, tex_file in enumerate(tex_files):
            team_id = tex_file.get('team_id', idx)
            tex_content = tex_file.get('tex_content', '')

            if not tex_content:
                logger.warning(f"Empty tex_content for team {team_id}, skipping")
                continue

            try:
                # Компилируем (один слот семафора на весь пакет: файлы идут последовательно)
                with compile_slot():
                    pdf_path = compile_tex(
                        tex_content, f"team_{team_id}", assets=tex_file.get('assets'),
                        engine=engine, passes=passes)
                pdf_files.append(pdf_path)
                logger.info(f"✓ Compiled team {team_id}")

            except Busy:
                return jsonify({'success': False, 'error': 'Server busy, retry later'}), 503, {'Retry-After': '10'}
            except Exception as e:
                logger.error(f"Failed to compile team {team_id}: {type(e).__name__}: {e}")
                # egormath показывает data['log'] или data['error']; в error — хвост лога, как раньше
                return jsonify({
                    'success': False,
                    'error': f"Compilation failed for team {team_id}: {str(e)}",
                    'log': str(e),
                }), 500

        if not pdf_files:
            return jsonify({
                'success': False,
                'error': 'No PDF files were generated'
            }), 500

        # Объединяем PDFs в один файл (A5 страницы)
        # Объединение A5 в A4 будет выполнено на стороне Django сервера
        if len(pdf_files) > 1:
            final_pdf = merge_pdfs(pdf_files)
        else:
            final_pdf = pdf_files[0]

        logger.info(f"Объединённый A5 PDF: {final_pdf}")

        # Читаем PDF и кодируем в base64
        pdf_bytes = final_pdf.read_bytes()
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # Подсчитываем страницы (A5 страницы)
        with open(final_pdf, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            total_pages = len(pdf_reader.pages)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Successfully compiled {len(pdf_files)} files in {elapsed:.2f}s ({total_pages} pages)")

        # Очистка временных файлов
        if CLEANUP_AFTER_COMPILATION:
            cleanup_temp_files(older_than_hours=CLEANUP_OLDER_THAN_HOURS)

        return jsonify({
            'success': True,
            'pdf_base64': pdf_base64,
            'total_pages': total_pages,
            'files_count': len(pdf_files),
            'compilation_time': elapsed
        })

    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500


@bp.route('/api/v1/table-signs', methods=['POST'])
def generate_table_signs():
    """
    Generate table sign PDFs with team names overlaid on a template.

    Uses ReportLab (not LaTeX) to overlay text on a base PDF template.
    The text appears on both sides of a folded table sign.

    Request JSON:
        api_key: str
        teams: list of {number: int, name: str}
        template_base64: str (optional, base64 encoded PDF template)
        text_box: list of 4 floats [x1, y1, x2, y2] (optional)
        text_color_rgb: list of 3 floats (optional)
        max_font_size: int (optional)

    Response JSON:
        success: bool
        pdf_base64: str (base64 encoded merged PDF)
        total_pages: int
        teams_count: int
    """
    start_time = datetime.now()

    try:
        if not check_api_key():
            return jsonify({'success': False, 'error': 'Invalid or missing API key'}), 401

        if not check_rate_limit():
            return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body must be JSON'}), 400

        teams = data.get('teams', [])
        if not teams or not isinstance(teams, list):
            return jsonify({'success': False, 'error': '"teams" is required and must be a non-empty array'}), 400

        if len(teams) > 200:
            return jsonify({'success': False, 'error': 'Too many teams (max 200)'}), 400

        text_box = tuple(data.get('text_box', [80, 40, 670, 230]))
        text_color = tuple(data.get('text_color_rgb', [0.129, 0.106, 0.404]))
        max_font_size = data.get('max_font_size', 80)
        min_one_line_font = data.get('min_one_line_font', 50)
        line_spacing = data.get('line_spacing', 1.0)

        # Template PDF: from request (base64) or default on server
        template_b64 = data.get('template_base64')
        if template_b64:
            template_bytes = base64.b64decode(template_b64)
        else:
            template_path = FONTS_DIR.parent / 'table_signs' / 'default_template.pdf'
            if not template_path.exists():
                return jsonify({
                    'success': False,
                    'error': f'Default template not found at {template_path}. '
                             'Upload via template_base64 or place file on server.'
                }), 404
            template_bytes = template_path.read_bytes()

        # Font setup
        font_name = "PPNeueMachina"
        font_path = FONTS_DIR / 'PPNeueMachina' / 'PPNeueMachina-Ultrabold.ttf'
        if not font_path.exists():
            return jsonify({
                'success': False,
                'error': f'Font not found at {font_path}. '
                         'Place PPNeueMachina-Ultrabold.ttf in fonts/PPNeueMachina/'
            }), 404

        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.pdfbase import pdfmetrics as rl_pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont as rl_TTFont
        from reportlab.pdfbase.pdfmetrics import stringWidth as rl_stringWidth

        try:
            rl_pdfmetrics.getFont(font_name)
        except KeyError:
            rl_pdfmetrics.registerFont(rl_TTFont(font_name, str(font_path)))

        ASCENT_RATIO = 0.75
        DESCENT_RATIO = 0.25

        def fit_text(text, bw, bh):
            for size in range(max_font_size, min_one_line_font - 1, -1):
                if rl_stringWidth(text, font_name, size) <= bw and size * 0.8 <= bh:
                    return size, [text]
            for size in range(max_font_size, min_one_line_font - 1, -1):
                cw = rl_stringWidth("X", font_name, size)
                cpl = max(1, int(bw / cw))
                lines = textwrap.wrap(text, width=cpl, break_long_words=False, break_on_hyphens=False)
                if len(lines) == 2:
                    mlw = max(rl_stringWidth(l, font_name, size) for l in lines)
                    if mlw <= bw and size + size * line_spacing <= bh:
                        return size, lines
            for size in range(max_font_size, 4, -1):
                cw = rl_stringWidth("X", font_name, size)
                cpl = max(1, int(bw / cw))
                lines = textwrap.wrap(text, width=cpl, break_long_words=False, break_on_hyphens=False)
                mlw = max(rl_stringWidth(l, font_name, size) for l in lines)
                if mlw > bw:
                    continue
                if size + (len(lines) - 1) * size * line_spacing <= bh:
                    return size, lines
            size = 4
            cw = rl_stringWidth("X", font_name, size)
            cpl = max(1, int(bw / cw))
            return size, textwrap.wrap(text, width=cpl, break_long_words=False, break_on_hyphens=False)

        def make_overlay(pw, ph, team_name):
            buf = io.BytesIO()
            c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
            x1, y1, x2, y2 = text_box
            bw, bh = x2 - x1, y2 - y1
            fs, lines = fit_text(team_name, bw, bh)
            c.setFont(font_name, fs)
            lh = fs
            total_h = lh + (len(lines) - 1) * lh * line_spacing if len(lines) > 1 else lh
            mid_y = (y1 + y2) / 2
            if len(lines) == 1:
                start_y = mid_y - (ASCENT_RATIO - DESCENT_RATIO) * fs / 2
            else:
                start_y = mid_y + total_h / 2 - fs * ASCENT_RATIO
            c.setFillColorRGB(*text_color)
            for i, line in enumerate(lines):
                lw = rl_stringWidth(line, font_name, fs)
                c.drawString(x1 + (bw - lw) / 2, start_y - i * lh * line_spacing, line)
            c.save()
            buf.seek(0)
            return buf

        # Режим ответа:
        # - binary (рекомендуется): возвращает application/pdf, без base64
        # - json (legacy): возвращает pdf_base64
        wants_binary = (
            data.get('response_format') == 'binary'
            or 'application/pdf' in (request.headers.get('Accept') or '')
        )

        # Генерируем в чанках, чтобы не раздувать RAM на больших списках команд.
        chunk_size = int(data.get('chunk_size', 25))
        chunk_size = max(5, min(50, chunk_size))
        chunk_paths = []
        total_pages = 0

        for chunk_idx in range(0, len(teams), chunk_size):
            teams_chunk = teams[chunk_idx:chunk_idx + chunk_size]
            writer = PyPDF2.PdfWriter()

            for team in teams_chunk:
                team_name = team.get('name', '').strip()
                if not team_name:
                    continue

                try:
                    base_reader = PyPDF2.PdfReader(io.BytesIO(template_bytes))
                    page = base_reader.pages[0]
                    pw = float(page.mediabox.width)
                    ph = float(page.mediabox.height)

                    overlay_buf = make_overlay(pw, ph, team_name)
                    page.merge_page(PyPDF2.PdfReader(overlay_buf).pages[0])

                    step1_buf = io.BytesIO()
                    w1 = PyPDF2.PdfWriter()
                    w1.add_page(page)
                    w1.write(step1_buf)
                    step1_buf.seek(0)

                    rotated_reader = PyPDF2.PdfReader(step1_buf)
                    rp = rotated_reader.pages[0]
                    rw, rh = float(rp.mediabox.width), float(rp.mediabox.height)
                    t = PyPDF2.Transformation().translate(tx=-rw / 2, ty=-rh / 2).rotate(180).translate(tx=rw / 2, ty=rh / 2)
                    rp.add_transformation(t)
                    if "/Rotate" in rp:
                        del rp["/Rotate"]

                    overlay_buf2 = make_overlay(rw, rh, team_name)
                    rp.merge_page(PyPDF2.PdfReader(overlay_buf2).pages[0])

                    writer.add_page(rp)
                    logger.info(f"✓ Table sign for team #{team.get('number', '?')} '{team_name}'")

                except Exception as e:
                    logger.error(f"Failed for team '{team_name}': {e}")
                    continue

            if len(writer.pages) == 0:
                continue

            chunk_path = COMPILE_DIR / f"table_signs_chunk_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{chunk_idx}.pdf"
            with open(chunk_path, 'wb') as chunk_f:
                writer.write(chunk_f)

            chunk_pages = len(writer.pages)
            total_pages += chunk_pages
            chunk_paths.append(chunk_path)
            logger.info(f"Generated chunk {len(chunk_paths)}: {chunk_pages} pages")

        if not chunk_paths:
            return jsonify({'success': False, 'error': 'No table signs were generated'}), 500

        if len(chunk_paths) == 1:
            final_pdf_path = chunk_paths[0]
        else:
            final_pdf_path = COMPILE_DIR / f"table_signs_merged_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.pdf"
            merger = PyPDF2.PdfMerger()
            for path in chunk_paths:
                merger.append(str(path))
            with open(final_pdf_path, 'wb') as out_f:
                merger.write(out_f)
            merger.close()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Generated {total_pages} table signs in {elapsed:.2f}s")

        # Удаляем промежуточные chunk-файлы, если они не являются финальным файлом
        for path in chunk_paths:
            if path != final_pdf_path and path.exists():
                try:
                    path.unlink()
                except Exception as cleanup_error:
                    logger.warning(f"Failed to delete chunk file {path}: {cleanup_error}")

        if wants_binary:
            return send_file(
                str(final_pdf_path),
                mimetype='application/pdf',
                as_attachment=False,
                download_name='table_signs.pdf',
                conditional=True,
            )

        pdf_bytes = final_pdf_path.read_bytes()
        return jsonify({
            'success': True,
            'pdf_base64': base64.b64encode(pdf_bytes).decode('utf-8'),
            'total_pages': total_pages,
            'teams_count': len(teams),
            'generation_time': elapsed,
        })

    except Exception as e:
        logger.error(f"Table signs error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500


@bp.route('/api/v1/compile-roster', methods=['POST'])
def compile_roster():
    """
    DEPRECATED: Старый эндпоинт для компиляции бланков.

    Используйте /api/v1/compile-latex вместо этого.
    """
    start_time = datetime.now()

    try:
        # Проверка API ключа
        if not check_api_key():
            logger.warning(f"Invalid API key from {request.remote_addr}")
            return jsonify({
                'success': False,
                'error': 'Invalid or missing API key'
            }), 401

        # Проверка rate limit
        if not check_rate_limit():
            logger.warning(f"Rate limit exceeded for {client_name()}")
            return jsonify({
                'success': False,
                'error': 'Rate limit exceeded'
            }), 429

        # Получаем данные
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body must be JSON'
            }), 400

        # Валидация
        is_valid, error_msg = validate_request(data)
        if not is_valid:
            logger.warning(f"Validation failed: {error_msg}")
            return jsonify({
                'success': False,
                'error': error_msg
            }), 400

        event = data['event']
        teams = data['teams']

        logger.info(f"Compiling roster for event '{event['name']}', {len(teams)} teams")

        # Компилируем PDF для каждой команды
        pdf_files = []
        for team in teams:
            try:
                # Рендерим шаблон
                tex_content = render_latex_template(event, team)

                # Компилируем
                with compile_slot():
                    pdf_path = compile_tex(tex_content, f"team_{team['id']}")
                pdf_files.append(pdf_path)

            except Busy:
                return jsonify({'success': False, 'error': 'Server busy, retry later'}), 503, {'Retry-After': '10'}
            except Exception as e:
                logger.error(f"Failed to compile team {team['id']}: {type(e).__name__}: {e}")
                return jsonify({
                    'success': False,
                    'error': f"Compilation failed for team {team['id']}: {str(e)}"
                }), 500

        # Объединяем PDFs
        if len(pdf_files) > 1:
            final_pdf = merge_pdfs(pdf_files)
        else:
            final_pdf = pdf_files[0]

        # Читаем PDF и кодируем в base64
        pdf_bytes = final_pdf.read_bytes()
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # Подсчитываем страницы
        with open(final_pdf, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            total_pages = len(pdf_reader.pages)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Successfully compiled {len(teams)} teams in {elapsed:.2f}s ({total_pages} pages)")

        # Очистка временных файлов
        if CLEANUP_AFTER_COMPILATION:
            cleanup_temp_files(older_than_hours=CLEANUP_OLDER_THAN_HOURS)

        return jsonify({
            'success': True,
            'pdf_base64': pdf_base64,
            'total_pages': total_pages,
            'teams_count': len(teams),
            'compilation_time': elapsed
        })

    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f"Internal server error: {str(e)}"
        }), 500


