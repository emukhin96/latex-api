# Руководство по API ключу

## Что такое API_KEY?

`API_KEY` - это секретный ключ для аутентификации запросов к API сервису компиляции LaTeX. Он используется для защиты API от несанкционированного доступа.

## Где он используется?

1. **На сервере компиляции (Timeweb):**
   - В файле `config.py` сервиса LaTeX API
   - Сервис проверяет этот ключ при каждом запросе

2. **На основном сервере (chgkmsu.ru):**
   - В `reg/local_settings.py` Django
   - Django отправляет этот ключ при запросах к API

**Важно:** Оба сервера должны использовать **один и тот же** API ключ!

## Как сгенерировать API_KEY?

### Вариант 1: Генератор случайных строк (рекомендуется)

На Linux/Mac:
```bash
# Генерация случайного ключа (32 символа)
openssl rand -hex 32

# Или более длинный (64 символа)
openssl rand -hex 64

# Или используя /dev/urandom
cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 64 | head -n 1
```

На Windows (PowerShell):
```powershell
# Генерация случайного ключа
-join ((65..90) + (97..122) + (48..57) | Get-Random -Count 64 | % {[char]$_})
```

Онлайн генераторы:
- https://www.random.org/strings/
- https://randomkeygen.com/

### Вариант 2: Простой ключ (для тестирования)

Для тестирования можно использовать простой ключ:
```python
API_KEY = 'test_secret_key_12345'
```

**⚠️ ВНИМАНИЕ:** Для production используйте длинный случайный ключ!

## Рекомендуемая длина и формат

- **Длина:** минимум 32 символа, рекомендуется 64+ символа
- **Формат:** буквы (a-z, A-Z), цифры (0-9), можно использовать дефисы и подчеркивания
- **Пример хорошего ключа:**
  ```
  a7f3b9c2d1e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0
  ```

## Установка API_KEY

### На сервере компиляции (Timeweb):

```bash
# От latexapi
cd /opt/latex-api

# Скопировать пример конфигурации
cp config.example.py config.py

# Отредактировать
nano config.py

# Найти строку:
API_KEY = os.environ.get('LATEX_API_KEY', 'change_me_to_secret_key_12345')

# Заменить на ваш ключ:
API_KEY = os.environ.get('LATEX_API_KEY', 'ваш_сгенерированный_ключ_здесь')
```

### На основном сервере (chgkmsu.ru):

Добавить в `reg/local_settings.py`:
```python
# LaTeX API настройки
LATEX_API_URL = 'https://your-timeweb-server.com'  # или IP:8000
LATEX_API_KEY = 'тот_же_ключ_что_и_на_сервере_компиляции'
```

## Безопасность

1. **Никогда не коммитьте ключ в Git!**
   - `config.py` должен быть в `.gitignore`
   - Используйте `local_settings.py` для Django (он тоже в `.gitignore`)

2. **Храните ключ в безопасном месте:**
   - Запишите его в менеджер паролей
   - Или в защищенном файле на вашем компьютере

3. **Если ключ скомпрометирован:**
   - Сгенерируйте новый ключ
   - Обновите на обоих серверах
   - Перезапустите сервисы

4. **Используйте HTTPS:**
   - В production обязательно используйте HTTPS для передачи ключа

## Пример использования в запросах

Django будет отправлять запросы так:

```python
import requests

response = requests.post(
    'https://latex-api-server.com/api/v1/compile-roster',
    json={
        'api_key': 'ваш_ключ',
        'event': {...},
        'teams': [...]
    }
)
```

Или через заголовок (если настроено в API):

```python
response = requests.post(
    'https://latex-api-server.com/api/v1/compile-roster',
    headers={'Authorization': 'Bearer ваш_ключ'},
    json={
        'event': {...},
        'teams': [...]
    }
)
```

## Быстрая генерация ключа

Если вы на сервере и нужно сгенерировать ключ прямо сейчас:

```bash
# На Linux/Mac
python3 -c "import secrets; print(secrets.token_urlsafe(64))"

# Или
openssl rand -hex 32
```

Скопируйте сгенерированный ключ и используйте его в `config.py`!

