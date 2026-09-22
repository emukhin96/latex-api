# LaTeX Compilation API Service

Сервис для компиляции LaTeX бланков составов команд на отдельном сервере с root доступом.

## 📋 Требования

- Ubuntu/Debian сервер с root доступом
- Python 3.8+
- Интернет соединение для установки пакетов

## 🚀 Быстрая установка

### 1. Подготовка окружения

```bash
# Войти на сервер с root доступом
ssh root@your-timeweb-server

# Обновить систему
apt update && apt upgrade -y

# Установить базовые пакеты
apt install -y python3 python3-pip python3-venv git curl wget

# Создать пользователя для сервиса (рекомендуется)
useradd -m -s /bin/bash latexapi
mkdir -p /opt/latex-api
chown latexapi:latexapi /opt/latex-api
```

### 2. Установка TeX Live (XeLaTeX)

```bash
# Переключиться на пользователя latexapi
su - latexapi
cd /opt/latex-api

# Запустить скрипт установки TeX Live
# (скрипт находится в latex-api-service/scripts/install_texlive.sh)
bash install_texlive.sh
```

Или вручную:
```bash
# Скачать установщик TeX Live
wget https://mirror.ctan.org/systems/texlive/tlnet/install-tl-unx.tar.gz
tar -xzf install-tl-unx.tar.gz
cd install-tl-*

# Запустить установку (интерактивный режим)
./install-tl

# Или автоматическая установка с профилем
./install-tl --profile=texlive.profile
```

После установки добавить в PATH:
```bash
# Для пользователя latexapi, добавить в ~/.bashrc:
export PATH="/usr/local/texlive/2024/bin/x86_64-linux:$PATH"
# или путь, куда установлен TeX Live
```

### 3. Установка Python зависимостей

```bash
# Создать виртуальное окружение
python3 -m venv /opt/latex-api/venv
source /opt/latex-api/venv/bin/activate

# Установить зависимости
cd /opt/latex-api
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Настройка шрифтов

```bash
# Создать директорию для шрифтов
mkdir -p /opt/latex-api/fonts

# Скопировать шрифты с основного сервера или загрузить вручную
# Структура должна быть:
# /opt/latex-api/fonts/
#     ├── CMU/
#     ├── Сirce/
#     ├── SanFranciscoProText/
#     └── PPNeueMachina/
#         └── PPNeueMachina-Ultrabold.ttf   ← для табличек

# Установить права
chmod -R 755 /opt/latex-api/fonts
```

**Вариант 1: Копирование через SCP с основного сервера**
```bash
# На основном сервере (chgkmsu.ru):
scp -r /path/to/static_custom/fonts/* root@timeweb-server:/opt/latex-api/fonts/
```

**Вариант 2: Загрузка через FTP/веб-интерфейс Timeweb**

### 5. Настройка конфигурации

```bash
# Создать файл конфигурации
cp config.example.py config.py
nano config.py  # Отредактировать настройки
```

### 6. Тестирование установки

```bash
# Проверить, что xelatex доступен
which xelatex
xelatex --version

# Запустить тестовую компиляцию
python3 test_compile.py
```

### 7. Запуск сервиса

**Вариант A: Запуск вручную (для тестирования)**
```bash
cd /opt/latex-api
source venv/bin/activate
python3 app.py
```

**Вариант B: Systemd сервис (рекомендуется)**
```bash
# Создать systemd unit файл
sudo nano /etc/systemd/system/latex-api.service
# (см. latex-api-service/systemd/latex-api.service)

# Включить и запустить
sudo systemctl daemon-reload
sudo systemctl enable latex-api
sudo systemctl start latex-api
sudo systemctl status latex-api
```

**Вариант C: Nginx + Gunicorn (для production)**
```bash
# Установить Gunicorn
pip install gunicorn

# Запустить через Gunicorn
gunicorn -w 2 -b 127.0.0.1:8000 app:app

# Настроить Nginx (см. latex-api-service/nginx/latex-api.conf)
```

## 🏷️ Таблички (Table Signs)

API поддерживает генерацию табличек с названиями команд (`/api/v1/table-signs`).
Используется ReportLab (не LaTeX) для наложения текста на шаблон PDF.

### Необходимые файлы

```
/opt/latex-api/
├── fonts/PPNeueMachina/
│   └── PPNeueMachina-Ultrabold.ttf     ← шрифт для табличек
└── table_signs/
    └── default_template.pdf             ← шаблон таблички (A4 landscape)
```

### Установка

```bash
# На API-сервере (от root или latexapi):

# 1. Шрифт
mkdir -p /opt/latex-api/fonts/PPNeueMachina
# Скопировать PPNeueMachina-Ultrabold.ttf любым способом:
scp user@main-server:chgkmsu/public_html/static_custom/fonts/PPNeueMachina/PPNeueMachina-Ultrabold.ttf \
    /opt/latex-api/fonts/PPNeueMachina/

# 2. Шаблон PDF
mkdir -p /opt/latex-api/table_signs
scp user@main-server:chgkmsu/public_html/media/tournaments/table_signs/default_template.pdf \
    /opt/latex-api/table_signs/

# 3. Установить reportlab (если ещё не установлен)
source /opt/latex-api/venv/bin/activate
pip install reportlab

# 4. Перезапустить сервис
sudo systemctl restart latex-api
```

### Проверка

```bash
curl -X POST http://localhost:8000/api/v1/table-signs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"teams": [{"number": 1, "name": "Тестовая команда"}]}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['success'], d.get('total_pages'))"
# Ожидаемый ответ: True 1
```

## 📁 Структура проекта

```
/opt/latex-api/
├── app.py                 # Основное Flask приложение
├── config.py              # Конфигурация (не в Git!)
├── requirements.txt       # Python зависимости
├── templates/
│   └── roster_template.tex   # LaTeX шаблон
├── fonts/                 # Шрифты (Circe, CMU, PPNeueMachina, etc.)
├── table_signs/           # Шаблоны табличек
│   └── default_template.pdf
├── compile/               # Рабочая директория для компиляции
│   └── .gitkeep
├── logs/                  # Логи сервиса
│   └── .gitkeep
└── scripts/               # Вспомогательные скрипты
    ├── install_texlive.sh
    └── setup_fonts.sh
```

## 🔒 Безопасность

1. **API ключи:** Хранить в `config.py` (не коммитить в Git)
2. **Firewall:** Открыть только необходимые порты (80, 443)
3. **SSL:** Использовать HTTPS (Let's Encrypt)
4. **Логирование:** Настроить ротацию логов

## 📝 Логирование

Логи сохраняются в:
- `/opt/latex-api/logs/latex-api.log` - основные логи
- Systemd journal: `sudo journalctl -u latex-api`

## 🔧 Обслуживание

```bash
# Перезапуск сервиса
sudo systemctl restart latex-api

# Просмотр логов
sudo journalctl -u latex-api -f

# Очистка временных файлов компиляции
find /opt/latex-api/compile -type f -mtime +1 -delete
```

