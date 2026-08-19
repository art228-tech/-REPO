@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === Сборка ElevenLabsVoiceover.exe ===
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден. Установите его с https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю окружение...
    python -m venv .venv || (pause & exit /b 1)
)

set PY=.venv\Scripts\python.exe

"%PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%PY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
if errorlevel 1 (
    echo Не удалось установить зависимости сборки.
    pause
    exit /b 1
)

echo Собираю...
"%PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name ElevenLabsVoiceover ^
    --hidden-import tkinter ^
    app.py

if errorlevel 1 (
    echo.
    echo Сборка не удалась.
    pause
    exit /b 1
)

echo.
echo Готово: dist\ElevenLabsVoiceover.exe
echo Настройки и журналы программа хранит в %%APPDATA%%\ElevenLabsVoiceover
echo.
pause
endlocal
