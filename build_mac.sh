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

# 3. Подготавливаем иконку для сборки
mkdir -p resources

# Проверяем наличие ICNS файла в корне проекта
if [ -f "icon.icns" ]; then
  echo "Использую ICNS иконку из корня проекта: icon.icns"
  cp "icon.icns" "resources/icon.icns"
elif [ -f "28538791-c5e2-4ec8-9091-498b7e3e2ebd-_1_.ico" ]; then
  echo "Использую основную иконку: 28538791-c5e2-4ec8-9091-498b7e3e2ebd-_1_.ico"
  # Копируем ICO файл в resources для использования в spec-файлах
  cp "28538791-c5e2-4ec8-9091-498b7e3e2ebd-_1_.ico" "resources/icon.ico"

  # Пытаемся создать ICNS версию для лучшей совместимости с macOS
  if [ ! -f "resources/icon.icns" ]; then
    echo "Создаю ICNS версию иконки для macOS..."
    # Если есть PNG файл, используем его для конвертации
    if [ -f "resources/icon.png" ]; then
      TMP_ICNS="/tmp/icon_$$.icns"
      if sips -s format icns "resources/icon.png" --out "$TMP_ICNS" >/dev/null 2>&1; then
        mv "$TMP_ICNS" "resources/icon.icns"
        echo "✓ ICNS версия создана из PNG"
      else
        echo "⚠️ Не удалось создать ICNS из PNG, будет использоваться ICO"
      fi
    else
      echo "⚠️ PNG файл не найден, ICNS не создан"
    fi
  fi
else
  echo "⚠️ Ни ICNS, ни основная ICO иконка не найдены"
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