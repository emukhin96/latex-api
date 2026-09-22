# Пошаговая инструкция по установке сервера компиляции

## Шаг 1: Подключение к серверу

```bash
# Подключитесь к серверу Timeweb с root доступом
ssh root@81.200.147.78
```

## Шаг 2: Создание пользователя для сервиса

```bash
# Создать пользователя (рекомендуется для безопасности)
useradd -m -s /bin/bash latexapi

# Установить пароль (или настроить SSH ключи)
passwd latexapi

# Создать директорию проекта
mkdir -p /opt/latex-api
chown latexapi:latexapi /opt/latex-api
```

## Шаг 3: Копирование файлов проекта

**Вариант A: Через Git (если репозиторий публичный или есть доступ)**

```bash
# Переключиться на пользователя latexapi
su - latexapi

# Клонировать в домашнюю директорию (у пользователя есть права)
cd ~

# Если репозиторий публичный, просто клонировать:
git clone https://github.com/emukhin96/chgkmsu-registration.git

# Если репозиторий приватный, нужен Personal Access Token:
# 1. Создайте токен на GitHub: Settings -> Developer settings -> Personal access tokens -> Tokens (classic)
# 2. Дайте права: repo (для приватных репозиториев)
# 3. Используйте токен как пароль:
git clone https://github.com/emukhin96/chgkmsu-registration.git
# Username: emukhin96
# Password: <ваш_токен>

# ИЛИ используйте SSH (если настроены ключи):
# git clone git@github.com:emukhin96/chgkmsu-registration.git

# Переключиться на root для перемещения в /opt
exit  # или выполнить команды от root
sudo cp -r /home/latexapi/chgkmsu-registration/latex-api-service /opt/latex-api
sudo chown -R latexapi:latexapi /opt/latex-api

# Вернуться к пользователю latexapi
su - latexapi
cd /opt/latex-api
```

**Вариант B: Через SCP (с локальной машины)**
```bash
# На вашей локальной машине:
scp -r latex-api-service/* root@your-server:/opt/latex-api/
# Затем:
ssh root@your-server
chown -R latexapi:latexapi /opt/latex-api
```

**Вариант C: Вручную через FTP/веб-интерфейс Timeweb**
- Загрузить файлы через FTP клиент
- Распаковать архив в `/opt/latex-api`

## Шаг 4: Установка TeX Live

```bash
# Переключиться на пользователя latexapi
su - latexapi
cd /opt/latex-api

# Сделать скрипт исполняемым
chmod +x scripts/install_texlive.sh

# Запустить установку (это займет 30-60 минут)
bash scripts/install_texlive.sh

# После установки обновить PATH
source ~/.bashrc

# Проверить установку
xelatex --version
# Должно показать: XeTeX 3.141592653-...
```

**Примечание:** Если установка не от root, TeX Live будет установлен в `$HOME/texlive`, и путь будет добавлен в `~/.bashrc`.

## Шаг 5: Установка Python зависимостей

```bash
# Все еще от имени latexapi
cd /opt/latex-api

# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Обновить pip
pip install --upgrade pip

# Установить зависимости
pip install -r requirements.txt
```

## Шаг 6: Настройка шрифтов

```bash
# Создать директорию для шрифтов
mkdir -p /opt/latex-api/fonts

# Скопировать шрифты с основного сервера
# На основном сервере (chgkmsu.ru):
# scp -r /path/to/static_custom/fonts/* root@timeweb-server:/opt/latex-api/fonts/

# Или загрузить через FTP вручную
# Структура должна быть:
# /opt/latex-api/fonts/
#     ├── CMU/
#     ├── Сirce/
#     ├── SanFranciscoProText/
#     └── PPNeueMachina/
#         └── PPNeueMachina-Ultrabold.ttf

# Установить права
chmod -R 755 /opt/latex-api/fonts
```

## Шаг 7: Копирование шаблонов

```bash
# LaTeX шаблон бланков состава
mkdir -p /opt/latex-api/templates
# scp public_html/templates/tex/roster_template.tex root@timeweb-server:/opt/latex-api/templates/

# Шаблон табличек (table signs)
mkdir -p /opt/latex-api/table_signs
# scp public_html/media/tournaments/table_signs/default_template.pdf root@timeweb-server:/opt/latex-api/table_signs/

# Или загрузить вручную через FTP
```

## Шаг 8: Настройка конфигурации

```bash
cd /opt/latex-api

# Скопировать пример конфигурации
cp config.example.py config.py

# Отредактировать конфигурацию
nano config.py
```

**Важные настройки в `config.py`:**
```python
# ОБЯЗАТЕЛЬНО ИЗМЕНИТЬ API ключ!
API_KEY = 'ваш_секретный_ключ_здесь'

# Проверить путь к xelatex (если не в PATH)
XELATEX_PATH = 'xelatex'  # или '/usr/local/texlive/2024/bin/x86_64-linux/xelatex'

# Настройки Flask
FLASK_HOST = '0.0.0.0'  # Слушать на всех интерфейсах
FLASK_PORT = 8000
```

## Шаг 9: Создание необходимых директорий

```bash
# Создать директории для компиляции и логов
mkdir -p /opt/latex-api/compile
mkdir -p /opt/latex-api/logs

# Установить права
chmod 755 /opt/latex-api/compile
chmod 755 /opt/latex-api/logs
```

## Шаг 10: Тестирование запуска

```bash
# Активировать виртуальное окружение
cd /opt/latex-api
source venv/bin/activate

# Запустить сервис вручную (для тестирования)
python3 app.py

# В другом терминале проверить:
curl http://localhost:8000/health
# Должно вернуть: {"status": "ok", ...}
```

**Если все работает, остановите сервис (Ctrl+C).**

## Шаг 11: Настройка systemd (автозапуск)

```bash
# Переключиться на root
exit  # или sudo su

# Скопировать systemd unit файл
cp /opt/latex-api/systemd/latex-api.service /etc/systemd/system/

# Отредактировать, если нужно (пути, пользователь)
nano /etc/systemd/system/latex-api.service

# Проверить, что пути в ExecStart правильные:
# - Путь к Python в venv: /opt/latex-api/venv/bin/python
# - Путь к app.py: /opt/latex-api/app.py

# Перезагрузить systemd
systemctl daemon-reload

# Включить автозапуск
systemctl enable latex-api

# Запустить сервис
systemctl start latex-api

# Проверить статус
systemctl status latex-api

# Посмотреть логи
journalctl -u latex-api -f
```

## Шаг 12: Настройка Nginx (опционально, для production)

```bash
# Установить Nginx (если не установлен)
apt install -y nginx

# Скопировать конфигурацию
cp /opt/latex-api/nginx/latex-api.conf /etc/nginx/sites-available/latex-api.conf

# Отредактировать домен
nano /etc/nginx/sites-available/latex-api.conf
# Заменить: latex-api.your-domain.com на ваш домен

# Создать симлинк
ln -s /etc/nginx/sites-available/latex-api.conf /etc/nginx/sites-enabled/

# Проверить конфигурацию
nginx -t

# Перезагрузить Nginx
systemctl reload nginx
```

## Шаг 13: Настройка SSL (Let's Encrypt)

```bash
# Установить certbot
apt install -y certbot python3-certbot-nginx

# Получить сертификат
certbot --nginx -d latex-api.your-domain.com

# Certbot автоматически обновит конфигурацию Nginx
# После этого можно раскомментировать HTTPS блок в конфигурации Nginx
```

## Шаг 14: Проверка работы

```bash
# Проверить health endpoint
curl http://your-server-ip:8000/health
# или через домен:
curl https://latex-api.your-domain.com/health

# Проверить логи
journalctl -u latex-api -n 50
```

## Шаг 15: Настройка firewall (если используется)

```bash
# Если используется ufw
ufw allow 80/tcp
ufw allow 443/tcp
# Для прямого доступа к Flask (не рекомендуется в production)
ufw allow 8000/tcp

# Если используется firewalld
firewall-cmd --permanent --add-service=http
firewall-cmd --permanent --add-service=https
firewall-cmd --reload
```

## ✅ Чеклист установки

- [ ] Пользователь latexapi создан
- [ ] Файлы проекта скопированы в /opt/latex-api
- [ ] TeX Live установлен и xelatex доступен
- [ ] Python зависимости установлены (venv)
- [ ] Шрифты скопированы в /opt/latex-api/fonts (CMU, Circe, PPNeueMachina)
- [ ] LaTeX шаблон скопирован в /opt/latex-api/templates
- [ ] Шаблон табличек скопирован в /opt/latex-api/table_signs/default_template.pdf
- [ ] config.py настроен с API ключом
- [ ] Директории compile/ и logs/ созданы
- [ ] Тестовый запуск прошел успешно
- [ ] Systemd сервис настроен и запущен
- [ ] Nginx настроен (опционально)
- [ ] SSL сертификат установлен (опционально)
- [ ] Health endpoint отвечает

## 🔧 Решение проблем

### XeLaTeX не найден
```bash
# Проверить PATH
echo $PATH
which xelatex

# Если не найден, добавить вручную в config.py:
XELATEX_PATH = '/usr/local/texlive/2024/bin/x86_64-linux/xelatex'
# или
XELATEX_PATH = '/home/latexapi/texlive/2024/bin/x86_64-linux/xelatex'
```

### Порт уже занят
```bash
# Проверить, что использует порт 8000
netstat -tulpn | grep 8000

# Изменить порт в config.py:
FLASK_PORT = 8001
```

### Ошибки прав доступа
```bash
# Проверить права на директории
ls -la /opt/latex-api

# Исправить права
chown -R latexapi:latexapi /opt/latex-api
chmod -R 755 /opt/latex-api
```

## 📝 Следующие шаги

После успешной установки:
1. Записать IP/домен сервера и API ключ для настройки Django
2. Протестировать API вручную через curl
3. Настроить интеграцию в Django приложении

