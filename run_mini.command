#!/bin/bash
set -e

# Получаем директорию скрипта
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Имя виртуального окружения
VENV_NAME="venv"

# Определяем базовый python
if command -v python3.10 &>/dev/null; then
    PYTHON_CMD="python3.10"
elif command -v python3.9 &>/dev/null; then
    PYTHON_CMD="python3.9"
elif command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
else
    echo "Ошибка: Python 3 не найден. Пожалуйста, установите Python 3."
    exit 1
fi

echo "Используется базовый интерпретатор: $PYTHON_CMD"

# Создаем venv если нет
if [ ! -d "$VENV_NAME" ]; then
    echo "Создание виртуального окружения..."
    "$PYTHON_CMD" -m venv "$VENV_NAME"
fi

# Путь к python в venv
VENV_PYTHON="$DIR/$VENV_NAME/bin/python"
VENV_PIP="$DIR/$VENV_NAME/bin/pip"

# Устанавливаем переменную для изоляции от глобальных пакетов пользователя
export PYTHONNOUSERSITE=1

# Проверка и установка зависимостей
echo "Проверка зависимостей..."
"$VENV_PIP" install -q --upgrade pip
"$VENV_PIP" install -q -r requirements.txt

# Запуск мини-приложения
echo "Запуск TGFlow Mini..."
"$VENV_PYTHON" mini_broadcast.py
