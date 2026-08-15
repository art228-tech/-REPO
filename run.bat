@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Создаю окружение Python...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    echo Ставлю зависимости, это займёт несколько минут...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

".venv\Scripts\python.exe" main.py %*
goto :eof

:error
echo.
echo Не удалось подготовить окружение. Проверь, что установлен Python 3.10 или новее
echo и что при установке была отмечена галочка "Add Python to PATH".
pause
