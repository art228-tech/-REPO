@echo off
rem ============================================================
rem  Сборка одного .exe (Windows). Запустить ОДИН раз.
rem  Готовый файл появится в папке dist\.
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo [ОШИБКА] Python не найден. Установите Python 3.11+ и повторите.
    pause
    exit /b 1
)

if not exist ".venv" ( %PY% -m venv .venv )
call ".venv\Scripts\activate.bat"

echo Ставлю зависимости и PyInstaller...
python -m pip install --disable-pip-version-check -q -r requirements.txt
python -m pip install --disable-pip-version-check -q pyinstaller

echo Собираю .exe (это может занять несколько минут)...
pyinstaller --noconfirm --onefile --windowed ^
    --name "CapCut Автомонтаж" ^
    --collect-all imageio_ffmpeg ^
    main.py

if errorlevel 1 (
    echo [ОШИБКА] Сборка не удалась. Скопируйте текст выше.
    pause
    exit /b 1
)

echo.
echo Готово! Файл: dist\CapCut Автомонтаж.exe
echo Скопируйте этот .exe куда угодно — рядом с ним создадутся папки "Ассеты" и логи.
pause
endlocal
