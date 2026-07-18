@echo off
rem ============================================================
rem  CapCut Automontazh - launch by double click (Windows)
rem  First run installs dependencies, next runs are fast.
rem  IMPORTANT: EXTRACT the ZIP first, run this from a real
rem  folder in Explorer - NOT from inside the archive (WinRAR).
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo(
echo ==================================================
echo   CapCut Automontazh
echo ==================================================
echo(

rem Find Python (py launcher first, then python)
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
    echo [ERROR] Python not found.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo During install CHECK the box "Add Python to PATH".
    echo(
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment ^(one time^)...
    %PY% -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo Installing / checking dependencies ^(may take a few minutes on first run^)...
echo(
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo(
    echo [ERROR] Failed to install dependencies. Copy the text above.
    pause
    exit /b 1
)

echo(
echo Starting the app...
python main.py
if errorlevel 1 (
    echo(
    echo [ERROR] App exited with an error. Copy the text above.
    pause
)
endlocal
