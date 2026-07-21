@echo off
rem ============================================================
rem  CapCut Automontazh - launch (Windows), with logging.
rem  Everything is written to run_log.txt next to this file,
rem  so even if the window closes you can send me that log.
rem  IMPORTANT: EXTRACT the ZIP first, run from a real folder
rem  in Explorer - NOT from inside the archive (WinRAR).
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "LOG=%~dp0run_log.txt"
echo ==== run.bat start %date% %time% ==== > "%LOG%"

echo(
echo ==================================================
echo   CapCut Automontazh
echo   (log is saved to run_log.txt)
echo ==================================================
echo(

rem Find Python (py launcher first, then python)
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
    echo [ERROR] Python not found. >> "%LOG%"
    echo [ERROR] Python NOT found.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo During install CHECK the box "Add Python to PATH", then run again.
    echo(
    echo === Send me the file run_log.txt if unclear ===
    pause
    exit /b 1
)
echo Using Python: %PY% >> "%LOG%"
%PY% --version >> "%LOG%" 2>&1

if not exist ".venv" (
    echo Creating virtual environment ^(one time^)...
    %PY% -m venv .venv >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Could not create venv. See run_log.txt
        type "%LOG%"
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

echo Installing / checking dependencies ^(first run takes a few minutes^)...
python -m pip install --disable-pip-version-check -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Sending log below:
    type "%LOG%"
    echo(
    echo === Please send the file run_log.txt ===
    pause
    exit /b 1
)

rem OCR (search buttons by text) is OPTIONAL: install softly, DO NOT abort the
rem app if it fails (e.g. on the newest Python). Without OCR the app still runs
rem and falls back to image templates.
echo Installing OCR ^(optional, for reliable button search^)...
echo ---- optional OCR install ---- >> "%LOG%"
python -m pip install --disable-pip-version-check -r requirements-ocr.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [WARN] OCR not installed - app will use image templates. >> "%LOG%"
    echo [WARN] OCR not installed - continuing without it.
)

echo Starting the app...
echo ---- launching main.py ---- >> "%LOG%"
python main.py >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] App exited with an error. Log below:
    type "%LOG%"
    echo(
    echo === Please send the file run_log.txt ===
    pause
    exit /b 1
)

echo App closed normally.
endlocal
