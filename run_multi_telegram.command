#!/bin/bash

# Путь к Telegram Desktop (проверили, у вас установлен именно он)
TG_APP="/Applications/Telegram.app/Contents/MacOS/Telegram"

# Папка, где лежит этот скрипт
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSIONS_DIR="$SCRIPT_DIR/tdata_sessions"

# Проверяем наличие Telegram
if [ ! -f "$TG_APP" ]; then
    echo "Ошибка: Telegram не найден по пути $TG_APP"
    exit 1
fi

echo "Запускаем 5 экземпляров Telegram..."

for i in {1..5}; do
    WORKDIR="$SESSIONS_DIR/account_$i"
    mkdir -p "$WORKDIR"
    
    echo "Запуск аккаунта $i (папка: $WORKDIR)..."
    # Запускаем в фоне, отвязываем от терминала, чтобы окна не закрылись при закрытии терминала
    nohup "$TG_APP" -workdir "$WORKDIR" >/dev/null 2>&1 &
    
    # Небольшая пауза, чтобы окна не открывались все одновременно "пачкой"
    sleep 1
done

echo "Все экземпляры запущены."
echo "Авторизуйтесь в каждом окне."
echo "После авторизации папки 'tdata' будут находиться внутри:"
echo "$SESSIONS_DIR/account_N/tdata"





