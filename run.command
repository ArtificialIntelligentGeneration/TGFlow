#!/bin/bash
# -----------------------------------------------------------------------------
# TGFlow – стартовый скрипт. Дважды кликните по файлу в Finder, чтобы
#   1. перейти в каталог приложения,
#   2. подготовить изолированное окружение Python 3.10 (venv),
#   3. установить зависимости,
#   4. запустить GUI.
# -----------------------------------------------------------------------------
set -e
cd "$(dirname "$0")"

# Предпочитаем установленный Python 3.10 из pyenv, если доступен
if [ -x "/Users/iiii/.pyenv/versions/3.10.14/bin/python3" ]; then
  BASE_PY="/Users/iiii/.pyenv/versions/3.10.14/bin/python3"
elif command -v python3 &>/dev/null; then
  BASE_PY="python3"
else
  BASE_PY="python"
fi

# Создаём/используем локальное окружение .venv310
VENV_DIR=".venv310"
if [ ! -d "$VENV_DIR" ]; then
  "$BASE_PY" -m venv "$VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"

# Обновляем pip и ставим зависимости внутрь venv (без --user)
"$VENV_PY" -m pip install -q --upgrade pip || true
"$VENV_PY" -m pip install -q -r requirements.txt || true

# Выравниваем связку Qt до 6.6.1 (совместимо с PyQt6==6.6.1)
"$VENV_PY" -m pip install -q "PyQt6==6.6.1" "PyQt6-Qt6==6.6.1" || true

# Запускаем приложение из venv, исключая пользовательские site-packages
exec env PYTHONNOUSERSITE=1 "$VENV_PY" main.py