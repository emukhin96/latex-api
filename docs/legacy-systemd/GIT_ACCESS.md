# Решение проблем с доступом к Git репозиторию

## Ошибка: "Password authentication is not supported"

GitHub не поддерживает аутентификацию по паролю. Есть несколько решений:

## Решение 1: Personal Access Token (РЕКОМЕНДУЕТСЯ)

### Создание токена:
1. Зайдите на GitHub: https://github.com/settings/tokens
2. Нажмите "Generate new token" -> "Generate new token (classic)"
3. Задайте имя (например, "LaTeX API Server")
4. Выберите срок действия (рекомендуется 90 дней или custom)
5. Отметьте права: **repo** (для доступа к приватным репозиториям)
6. Нажмите "Generate token"
7. **ВАЖНО:** Скопируйте токен сразу (он показывается только один раз!)

### Использование токена:

```bash
# При клонировании используйте токен как пароль:
git clone https://github.com/emukhin96/chgkmsu-registration.git
# Username: emukhin96
# Password: <вставьте_токен_здесь>
```

### Сохранение токена в Git (опционально):

```bash
# Настроить Git credential helper
git config --global credential.helper store

# При следующем клонировании токен сохранится
git clone https://github.com/emukhin96/chgkmsu-registration.git
```

---

## Решение 2: SSH ключи

### Генерация SSH ключа на сервере:

```bash
# От имени пользователя latexapi
su - latexapi

# Создать SSH ключ (если еще нет)
ssh-keygen -t ed25519 -C "latexapi@timeweb-server"
# Нажать Enter для использования дефолтного пути
# Можно задать пароль для ключа или оставить пустым

# Показать публичный ключ
cat ~/.ssh/id_ed25519.pub
```

### Добавление ключа на GitHub:

1. Скопируйте вывод `cat ~/.ssh/id_ed25519.pub`
2. Зайдите на GitHub: https://github.com/settings/keys
3. Нажмите "New SSH key"
4. Вставьте публичный ключ
5. Нажмите "Add SSH key"

### Использование SSH для клонирования:

```bash
# Клонировать через SSH
git clone git@github.com:emukhin96/chgkmsu-registration.git
```

---

## Решение 3: Скачать архив через веб (ПРОСТОЙ ВАРИАНТ)

Если Git не работает, можно скачать архив:

```bash
# От root или latexapi
cd ~
# Скачать архив (если репозиторий публичный)
wget https://github.com/emukhin96/chgkmsu-registration/archive/refs/heads/main.zip

# Или использовать curl:
curl -L -o main.zip https://github.com/emukhin96/chgkmsu-registration/archive/refs/heads/main.zip

# Распаковать
unzip main.zip

# Переместить latex-api-service в /opt (от root)
exit
cp -r chgkmsu-registration-main/latex-api-service /opt/latex-api
chown -R latexapi:latexapi /opt/latex-api
```

---

## Решение 4: SCP с локальной машины (ЛУЧШИЙ ВАРИАНТ ДЛЯ ПРИВАТНОГО РЕПО)

Если у вас есть доступ к репозиторию локально:

```bash
# На вашей локальной машине (где есть доступ к репозиторию):
cd /path/to/chgkmsu-registration

# Скопировать latex-api-service на сервер через SCP
scp -r latex-api-service/* root@81.200.147.78:/opt/latex-api/

# Или через SFTP/FileZilla
# Просто скопировать папку latex-api-service на сервер
```

### На сервере:

```bash
# Установить права
chown -R latexapi:latexapi /opt/latex-api

# Переключиться на пользователя latexapi
su - latexapi
cd /opt/latex-api
```

---

## Рекомендация

Для простоты и скорости используйте **Решение 4 (SCP)** - скопируйте папку `latex-api-service` напрямую на сервер через SCP или SFTP. Это самый быстрый способ, если у вас уже есть доступ к репозиторию локально.

Если нужно автоматическое обновление из Git в будущем, настройте **Решение 1 (Personal Access Token)** или **Решение 2 (SSH ключи)**.

