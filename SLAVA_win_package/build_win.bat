@echo off
REM Сборка приложения SLAVA/MySLAVA под Windows при помощи PyInstaller.
REM Использование: build_win.bat [personal]

setlocal enabledelayedexpansion

REM Имя приложения и spec-файл
set APP_NAME=SLAVA
set SPEC_FILE=slava_aig_win.spec

REM ─── Создаём виртуальное окружение ───────────────────────────────────────
set PYTHON=python
set VENV_DIR=venv_build

if not exist %VENV_DIR% (
    %PYTHON% -m venv %VENV_DIR%
)
call %VENV_DIR%\Scripts\activate.bat

REM ─── Устанавливаем зависимости ───────────────────────────────────────────
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

REM ─── Собираем exe (режим папка, без консоли) ─────────────────────────────
pyinstaller -y "%SPEC_FILE%"

REM ─── Готово ───────────────────────────────────────────────────────────────

echo.
echo ==== Сборка завершена ====
echo Исполняемый файл находится в dist\%APP_NAME%\%APP_NAME%.exe

deactivate
endlocal 