#!/usr/bin/env bash
set -e

# ─── Определяем вариант сборки ─────────────────────────────────────────────
# Если скрипт запускают с аргументом "personal", собираем MySLAVA со всеми
# пользовательскими данными (scripts, sessions …). Иначе – чистую SLAVA.

VARIANT="${1:-clean}"

if [ "$VARIANT" = "personal" ]; then
  APP_NAME="MySLAVA"
  DMG_NAME="MySLAVA"
  SPEC_FILE="myslava.spec"
else
  APP_NAME="SLAVA"
  DMG_NAME="SLAVA"
  SPEC_FILE="slava_aig.spec"
fi

PY_VERSION="python3"
VENV_DIR="venv_build"

# 1. Создаём виртуальное окружение
$PY_VERSION -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# 2. Ставим зависимости
pip install --upgrade pip
pip install -r requirements.txt pyinstaller

# 3. Генерируем icon.icns (если ещё нет)
if [ -f "resources/icon.png" ] && [ ! -f "resources/icon.icns" ]; then
  mkdir -p resources
  echo "Конвертирую icon.png → icon.icns…"
  TMP_ICNS="/tmp/icon_$$.icns"
  sips -s format icns "resources/icon.png" --out "$TMP_ICNS" >/dev/null
  mv "$TMP_ICNS" "resources/icon.icns"
fi

# 4. Собираем .app (без --onefile)
pyinstaller -y "$SPEC_FILE"

# 5. Проверяем, что bundle имеет расширение .app
if [ ! -d "dist/$APP_NAME.app" ] && [ -d "dist/$APP_NAME" ]; then
  mv "dist/$APP_NAME" "dist/$APP_NAME.app"
fi

# 6. Подготавливаем папку для DMG с ярлыком Applications
rm -rf dmg_src
mkdir dmg_src
cp -R "dist/$APP_NAME.app" dmg_src/
ln -s /Applications dmg_src/Applications

# 7. Упаковка в dmg
DATE_TAG=$(date +%Y-%m-%d)
DMG_FILE="${DMG_NAME}_${DATE_TAG}.dmg"
hdiutil create -volname "$APP_NAME" \
  -srcfolder "dmg_src" \
  -ov -format UDZO "$DMG_FILE"

# 8. Очистка
rm -rf dmg_src

echo "Готово: $DMG_FILE" 