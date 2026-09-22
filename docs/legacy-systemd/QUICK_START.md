# Быстрый старт установки

## Если возникла ошибка "Permission denied" при клонировании в /opt

### Решение: клонировать в домашнюю директорию

```bash
# От имени пользователя latexapi
su - latexapi

# Клонировать репозиторий в домашнюю директорию
cd ~
git clone https://github.com/emukhin96/chgkmsu-registration.git

# Проверить, что файлы скопированы
ls -la ~/chgkmsu-registration/latex-api-service/

# Выйти из latexapi (переключиться на root)
exit

# Скопировать latex-api-service в /opt от root
cp -r /home/latexapi/chgkmsu-registration/latex-api-service /opt/latex-api

# Установить правильного владельца
chown -R latexapi:latexapi /opt/latex-api

# Вернуться к пользователю latexapi
su - latexapi
cd /opt/latex-api

# Теперь можно продолжать установку
```

## Альтернативный вариант: дать права на /opt/latex-api

Если директория уже создана:

```bash
# От root
chown latexapi:latexapi /opt/latex-api
chmod 755 /opt/latex-api

# Теперь можно клонировать напрямую
su - latexapi
cd /opt
git clone https://github.com/emukhin96/chgkmsu-registration.git
# Или если репозиторий уже в /opt/chgkmsu-registration:
cp -r /opt/chgkmsu-registration/latex-api-service /opt/latex-api
```

