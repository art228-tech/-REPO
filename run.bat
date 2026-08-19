@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === Озвучка ElevenLabs ===
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден.
    echo.
    echo Установите Python 3.9 или новее с https://www.python.org/downloads/
    echo При установке обязательно отметьте галочку "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю окружение, это займёт минуту...
    python -m venv .venv
    if errorlevel 1 (
        echo Не удалось создать окружение.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
    echo Устанавливаю зависимости...
    ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Не удалось установить зависимости.
        pause
        exit /b 1
    )
    echo Готово.
    echo.
)

".venv\Scripts\pythonw.exe" app.py
if errorlevel 1 (
    echo.
    echo Программа завершилась с ошибкой. Подробности в журнале:
    echo %%APPDATA%%\ElevenLabsVoiceover\logs
    pause
)

endlocal
