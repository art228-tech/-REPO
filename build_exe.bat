@echo off
rem ============================================================
rem  Build a single .exe (Windows). Run ONCE.
rem  Result appears in the dist\ folder.
rem  IMPORTANT: EXTRACT the ZIP first and run this from a real
rem  folder in Explorer - NOT from inside the archive (WinRAR).
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.11+ and retry.
    pause
    exit /b 1
)

if not exist ".venv" ( %PY% -m venv .venv )
call ".venv\Scripts\activate.bat"

echo Installing dependencies and PyInstaller...
python -m pip install --disable-pip-version-check -r requirements.txt
python -m pip install --disable-pip-version-check pyinstaller
rem OCR is optional (search buttons by text). Soft install - do not fail build.
python -m pip install --disable-pip-version-check -r requirements-ocr.txt
set "OCR_COLLECT="
python -c "import rapidocr" 2>nul && set "OCR_COLLECT=--collect-all rapidocr"

echo(
echo Building .exe ^(may take several minutes^)...
pyinstaller --noconfirm --onefile --windowed ^
    --name "CapCut Automontazh" ^
    --collect-all imageio_ffmpeg ^
    %OCR_COLLECT% ^
    --add-data "src/ui_automation/reference_defaults;reference_defaults" ^
    main.py

if errorlevel 1 (
    echo [ERROR] Build failed. Copy the text above.
    pause
    exit /b 1
)

echo(
echo Done! File: dist\CapCut Automontazh.exe
echo Copy this .exe anywhere - folders "Assets" and logs are created next to it.
pause
endlocal
