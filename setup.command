#!/bin/bash

# Создаем папку на рабочем столе
DESKTOP_DIR="$HOME/Desktop/Telegram Sender"
mkdir -p "$DESKTOP_DIR"

# Копируем все необходимые файлы
cp main.py "$DESKTOP_DIR/"
cp requirements.txt "$DESKTOP_DIR/"
cp -r sessions "$DESKTOP_DIR/"

# Создаем скрипт запуска
cat > "$DESKTOP_DIR/Start.command" << 'EOL'
#!/bin/bash
cd "$(dirname "$0")"
python main.py
EOL

# Делаем скрипт запуска исполняемым
chmod +x "$DESKTOP_DIR/Start.command"

echo "Приложение установлено на рабочем столе в папке 'Telegram Sender'"
echo "Для запуска дважды кликните по файлу 'Start.command'" 