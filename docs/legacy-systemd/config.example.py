# -*- coding: utf-8 -*-
"""
Конфигурация для LaTeX API сервиса.
Скопируйте этот файл в config.py и отредактируйте значения.
"""

import os
from pathlib import Path

# Базовый путь к проекту
BASE_DIR = Path(__file__).parent

# API ключ для аутентификации (ОБЯЗАТЕЛЬНО ИЗМЕНИТЬ!)
API_KEY = os.environ.get('LATEX_API_KEY', 'change_me_to_secret_key_12345')

# Пути к директориям
FONTS_DIR = BASE_DIR / 'fonts'
COMPILE_DIR = BASE_DIR / 'compile'
LOGS_DIR = BASE_DIR / 'logs'

# Настройки компиляции
# LuaLaTeX часто даёт лучшее качество шрифтов, особенно для кириллицы
LUALATEX_PATH = os.environ.get('LUALATEX_PATH', 'lualatex')  # Обычно просто 'lualatex' если в PATH
LUALATEX_TIMEOUT = 60  # Таймаут компиляции в секундах
MAX_TEAMS_PER_REQUEST = 100  # Максимум команд в одном запросе

# Настройки Flask
FLASK_HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(os.environ.get('FLASK_PORT', 8000))
FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# Логирование
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LOG_FILE = LOGS_DIR / 'latex-api.log'
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5

# Безопасность
RATE_LIMIT_ENABLED = True
RATE_LIMIT_PER_MINUTE = 10  # Максимум запросов в минуту с одного IP

# Очистка временных файлов
CLEANUP_AFTER_COMPILATION = True
CLEANUP_OLDER_THAN_HOURS = 1  # Удалять файлы старше N часов

