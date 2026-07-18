@echo off
rem ============================================================
rem  CapCut Автомонтаж — запуск двойным кликом (Windows)
rem  Первый запуск создаст окружение и поставит зависимости.
rem  Дальше запускается почти мгновенно.
rem ============================================================
setlocal
cd /d "%~dp0"

rem Ищем Python (сначала лаунчер py, затем python)
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
    echo [ОШИБКА] Python не найден.
    echo Установите Python 3.11+ с https://www.python.org/downloads/
    echo При установке отметьте галочку "Add Python to PATH".
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Создаю окружение...
    %PY% -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo Проверяю зависимости...
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)

echo Запускаю CapCut Автомонтаж...
python main.py
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Приложение завершилось с ошибкой. Скопируйте текст выше.
    pause
)
endlocal
