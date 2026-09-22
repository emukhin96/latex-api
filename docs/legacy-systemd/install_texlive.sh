#!/bin/bash
# Скрипт для автоматической установки TeX Live на сервере

set -e

echo "=========================================="
echo "Установка TeX Live для LaTeX компиляции"
echo "=========================================="
echo ""

# Проверка прав root (для установки в систему)
if [ "$EUID" -eq 0 ]; then
    echo "⚠️  Запуск от root. Рекомендуется запускать от пользователя latexapi."
    read -p "Продолжить? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Определяем директорию установки
if [ "$EUID" -eq 0 ]; then
    TEXLIVE_INSTALL_DIR="/usr/local/texlive"
else
    TEXLIVE_INSTALL_DIR="$HOME/texlive"
fi

echo "Директория установки: $TEXLIVE_INSTALL_DIR"
echo ""

# Создаем временную директорию
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "📥 Скачивание установщика TeX Live..."
wget -q --show-progress https://mirror.ctan.org/systems/texlive/tlnet/install-tl-unx.tar.gz

echo "📦 Распаковка..."
tar -xzf install-tl-unx.tar.gz
# Найти директорию установщика
INSTALL_DIR=$(ls -d install-tl-* | head -n 1)
if [ -z "$INSTALL_DIR" ]; then
    echo "Ошибка: не найдена директория установщика"
    exit 1
fi
cd "$INSTALL_DIR"

echo ""
echo "🚀 Запуск установки TeX Live..."
echo "⚠️  ВАЖНО: Выберите профиль установки."
echo "   Рекомендуется: 'scheme-full' для полной установки"
echo "   Или 'scheme-medium' для экономии места (около 2GB)"
echo ""

# Создаем профиль для автоматической установки
# Определяем год (2024 или 2025)
TEXLIVE_YEAR="2025"
cat > texlive.profile <<EOF
# TexLive installation profile
selected_scheme scheme-medium
TEXDIR $TEXLIVE_INSTALL_DIR/$TEXLIVE_YEAR
TEXMFLOCAL $TEXLIVE_INSTALL_DIR/texmf-local
TEXMFHOME $HOME/texmf
TEXMFVAR $HOME/.texlive$TEXLIVE_YEAR/texmf-var
TEXMFCONFIG $HOME/.texlive$TEXLIVE_YEAR/texmf-config
TEXMFSYSCONFIG $TEXLIVE_INSTALL_DIR/$TEXLIVE_YEAR/texmf-config
TEXMFSYSVAR $TEXLIVE_INSTALL_DIR/$TEXLIVE_YEAR/texmf-var
collection-langcyrillic 1
collection-fontsrecommended 1
collection-xetex 1
instopt_adjustpath 1
instopt_adjustrepo 1
instopt_letter 0
instopt_portable 0
instopt_write18_restricted 1
EOF

# Запускаем установку
echo "Начинаем установку (это может занять 30-60 минут)..."
./install-tl --profile=texlive.profile --no-interaction

# Добавляем в PATH
echo ""
echo "📝 Настройка PATH..."

if [ "$EUID" -eq 0 ]; then
    # Системная установка
    TEXLIVE_BIN="$TEXLIVE_INSTALL_DIR/2025/bin/x86_64-linux"
    
    # Добавляем в /etc/profile.d
    cat > /etc/profile.d/texlive.sh <<EOFPROFILE
export PATH="\$PATH:$TEXLIVE_BIN"
EOFPROFILE
    chmod +x /etc/profile.d/texlive.sh
    
    echo "✅ PATH добавлен в /etc/profile.d/texlive.sh"
else
    # Установка пользователя
    TEXLIVE_BIN="$TEXLIVE_INSTALL_DIR/2025/bin/x86_64-linux"
    
    # Добавляем в ~/.bashrc
    if ! grep -q "texlive" ~/.bashrc; then
        echo "" >> ~/.bashrc
        echo "# TeX Live" >> ~/.bashrc
        echo "export PATH=\"\$PATH:$TEXLIVE_BIN\"" >> ~/.bashrc
    fi
    
    echo "✅ PATH добавлен в ~/.bashrc"
    echo "   Выполните: source ~/.bashrc"
fi

# Очистка
cd /
rm -rf "$TEMP_DIR"

echo ""
echo "=========================================="
echo "✅ Установка TeX Live завершена!"
echo "=========================================="
echo ""
echo "📋 Следующие шаги:"
echo "1. Перезагрузите shell или выполните: source ~/.bashrc (если установка не от root)"
echo "2. Проверьте установку: xelatex --version"
echo "3. Если нужно, обновите PATH в config.py сервиса"
echo ""

