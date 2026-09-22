# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки установки и компиляции LaTeX.
Запускать после установки для проверки, что все работает.
"""
import sys
import shutil
import subprocess
from pathlib import Path

print("=" * 60)
print("Тест установки LaTeX API сервиса")
print("=" * 60)
print()

# Проверка Python
print("1. Проверка Python...")
print(f"   Версия: {sys.version}")
if sys.version_info < (3, 8):
    print("   ⚠️  Рекомендуется Python 3.8+")
else:
    print("   ✓ OK")
print()

# Проверка зависимостей
print("2. Проверка Python зависимостей...")
try:
    import flask
    print(f"   ✓ Flask {flask.__version__}")
except ImportError:
    print("   ✗ Flask не установлен")
    sys.exit(1)

try:
    import PyPDF2
    print(f"   ✓ PyPDF2 {PyPDF2.__version__}")
except ImportError:
    print("   ✗ PyPDF2 не установлен")
    sys.exit(1)
print()

# Проверка XeLaTeX
print("3. Проверка XeLaTeX...")
xelatex_cmd = shutil.which('xelatex')
if xelatex_cmd:
    print(f"   ✓ Найден: {xelatex_cmd}")
    try:
        result = subprocess.run(
            ['xelatex', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        version_line = result.stdout.split('\n')[0]
        print(f"   {version_line}")
    except Exception as e:
        print(f"   ⚠️  Ошибка при проверке версии: {e}")
else:
    print("   ✗ XeLaTeX не найден в PATH")
    print("   Проверьте установку TeX Live и PATH в config.py")
    sys.exit(1)
print()

# Проверка директорий
print("4. Проверка директорий...")
BASE_DIR = Path(__file__).parent
dirs = {
    'fonts': BASE_DIR / 'fonts',
    'templates': BASE_DIR / 'templates',
    'compile': BASE_DIR / 'compile',
    'logs': BASE_DIR / 'logs',
}

for name, path in dirs.items():
    if path.exists():
        print(f"   ✓ {name}/: {path}")
    else:
        print(f"   ⚠️  {name}/: не существует (будет создана автоматически)")
        path.mkdir(exist_ok=True)
print()

# Проверка шаблона
print("5. Проверка LaTeX шаблона...")
template_path = BASE_DIR / 'templates' / 'roster_template.tex'
if template_path.exists():
    print(f"   ✓ Шаблон найден: {template_path}")
    print(f"   Размер: {template_path.stat().st_size} байт")
else:
    print(f"   ⚠️  Шаблон не найден: {template_path}")
    print("   Скопируйте roster_template.tex в templates/")
print()

# Проверка шрифтов
print("6. Проверка шрифтов...")
fonts_dir = BASE_DIR / 'fonts'
if fonts_dir.exists():
    font_dirs = list(fonts_dir.iterdir())
    if font_dirs:
        print(f"   ✓ Найдено директорий шрифтов: {len(font_dirs)}")
        for font_dir in font_dirs:
            if font_dir.is_dir():
                files = list(font_dir.glob('*'))
                print(f"      {font_dir.name}: {len(files)} файлов")
    else:
        print("   ⚠️  Директория fonts/ пуста")
        print("   Скопируйте шрифты (CMU, Сirce, SanFranciscoProText)")
else:
    print("   ⚠️  Директория fonts/ не существует")
print()

# Проверка конфигурации
print("7. Проверка конфигурации...")
config_path = BASE_DIR / 'config.py'
if config_path.exists():
    print(f"   ✓ config.py существует")
    # Проверяем, что API ключ изменен
    config_content = config_path.read_text()
    if 'change_me_to_secret_key' in config_content:
        print("   ⚠️  ВНИМАНИЕ: API ключ не изменен!")
        print("   Обязательно измените API_KEY в config.py")
    else:
        print("   ✓ API ключ настроен")
else:
    print("   ✗ config.py не найден")
    print("   Выполните: cp config.example.py config.py")
    sys.exit(1)
print()

print("=" * 60)
print("РЕЗУЛЬТАТ:")
print("=" * 60)

# Итоговая проверка
all_ok = True
if not xelatex_cmd:
    all_ok = False
if not template_path.exists():
    all_ok = False
if not config_path.exists():
    all_ok = False

if all_ok:
    print("✓ Базовая установка в порядке!")
    print()
    print("Следующие шаги:")
    print("1. Убедитесь, что все шрифты скопированы в fonts/")
    print("2. Измените API ключ в config.py")
    print("3. Запустите сервис: python3 app.py")
    print("4. Проверьте: curl http://localhost:8000/health")
else:
    print("⚠️  Есть проблемы, которые нужно исправить перед запуском")
    sys.exit(1)

