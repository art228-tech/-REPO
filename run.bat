@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV=%ROOT%\.venv"
set "TOOLS=%ROOT%\tools"
set "CACHE=%ROOT%\.cache"
set "PYFALLBACK=3.12.10"
set "FFURL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

echo.
echo ============================================================
echo    Сборка роликов CapCut по шаблонам
echo    Подготовка окружения. Первый запуск - несколько минут.
echo ============================================================
echo.

if not exist "%CACHE%" mkdir "%CACHE%" >nul 2>&1

rem =====================================================  PYTHON
call :find_python
if defined PYEXE goto :python_ready

echo [1/5] Python не найден. Устанавливаю...
call :install_python
call :find_python
if not defined PYEXE goto :no_python

:python_ready
for /f "delims=" %%v in ('%PYEXE% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo [1/5] Python %PYVER% - в порядке

%PYEXE% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo      Внимание: в этом Python нет tkinter, поэтому окно не откроется.
    echo      Переустанови Python с python.org, отметив "tcl/tk and IDLE".
    echo      Пока можно работать из консоли: run.bat run --help
)

rem =====================================================  FFMPEG
call :find_ffmpeg
if defined FFOK goto :ffmpeg_ready

echo [2/5] FFmpeg не найден. Скачиваю, это около 110 МБ...
call :install_ffmpeg
call :find_ffmpeg
if not defined FFOK goto :no_ffmpeg

:ffmpeg_ready
echo [2/5] FFmpeg - в порядке

rem =====================================================  ОКРУЖЕНИЕ
if exist "%VENV%\Scripts\python.exe" goto :venv_ready
echo [3/5] Создаю окружение Python...
%PYEXE% -m venv "%VENV%"
if not exist "%VENV%\Scripts\python.exe" goto :no_venv

:venv_ready
set "VPY=%VENV%\Scripts\python.exe"
echo [3/5] Окружение - в порядке

rem =====================================================  ЗАВИСИМОСТИ
if exist "%VENV%\.deps_ok" goto :deps_ready
echo [4/5] Ставлю зависимости. Скачается около 300 МБ, это самый долгий шаг...
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VPY%" -m pip install --quiet --disable-pip-version-check -r "%ROOT%\requirements.txt"
if errorlevel 1 goto :no_deps
echo ok> "%VENV%\.deps_ok"

:deps_ready
echo [4/5] Зависимости - в порядке

rem =====================================================  МОДЕЛЬ РЕЧИ
if exist "%VENV%\.model_ok" goto :model_ready
echo [5/5] Скачиваю модель распознавания речи, около 250 МБ...
"%VPY%" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" >nul 2>&1
if errorlevel 1 (
    echo      Не удалось скачать заранее - программа скачает её при первом ролике.
) else (
    echo ok> "%VENV%\.model_ok"
)

:model_ready
echo [5/5] Модель распознавания - в порядке
echo.
echo ============================================================
echo    Всё готово, открываю программу
echo ============================================================
echo.

"%VPY%" "%ROOT%\main.py" %*
if errorlevel 1 pause
goto :end


rem ==========================================================
rem                     ПОДПРОГРАММЫ
rem ==========================================================

:find_python
set "PYEXE="
set "PYNUM="
for /f "delims=" %%v in ('py -3 -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2^>nul') do set "PYNUM=%%v"
if defined PYNUM if %PYNUM% GEQ 310 set "PYEXE=py -3"
if defined PYEXE goto :eof

set "PYNUM="
for /f "delims=" %%v in ('python -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2^>nul') do set "PYNUM=%%v"
if defined PYNUM if %PYNUM% GEQ 310 set "PYEXE=python"
if defined PYEXE goto :eof

rem Установщик мог не обновить PATH в этом окне - ищем в обычных местах.
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "%ProgramFiles%\Python313"
    "%ProgramFiles%\Python312"
    "%ProgramFiles%\Python311"
) do if exist "%%~d\python.exe" (
    set "PYEXE=%%~d\python.exe"
    goto :eof
)
goto :eof

:install_python
where winget >nul 2>&1
if errorlevel 1 goto :python_direct

echo      Пробую через встроенный установщик Windows...
winget install --exact --id Python.Python.3.12 --source winget ^
    --accept-source-agreements --accept-package-agreements --silent >nul 2>&1
call :find_python
if defined PYEXE goto :eof

:python_direct
echo      Скачиваю установщик Python %PYFALLBACK% с python.org...
set "PYSETUP=%CACHE%\python-%PYFALLBACK%-amd64.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/%PYFALLBACK%/python-%PYFALLBACK%-amd64.exe' -OutFile '%PYSETUP%' -UseBasicParsing } catch { exit 1 }"
if not exist "%PYSETUP%" goto :eof

echo      Устанавливаю Python только для тебя, без прав администратора...
"%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_tcltk=1 Include_launcher=1 AssociateFiles=0 Shortcuts=0
goto :eof

:find_ffmpeg
set "FFOK="
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    where ffprobe >nul 2>&1
    if not errorlevel 1 set "FFOK=1"
)
if defined FFOK goto :eof
if exist "%TOOLS%\ffmpeg\bin\ffmpeg.exe" if exist "%TOOLS%\ffmpeg\bin\ffprobe.exe" (
    set "PATH=%TOOLS%\ffmpeg\bin;%PATH%"
    set "FFOK=1"
)
goto :eof

:install_ffmpeg
set "FFZIP=%CACHE%\ffmpeg.zip"
if exist "%FFZIP%" goto :ffmpeg_unpack
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%FFURL%' -OutFile '%FFZIP%' -UseBasicParsing } catch { exit 1 }"
if not exist "%FFZIP%" goto :eof

:ffmpeg_unpack
echo      Распаковываю...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue';" ^
  "$tmp = Join-Path '%CACHE%' 'ffmpeg_unpack'; if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force };" ^
  "Expand-Archive -LiteralPath '%FFZIP%' -DestinationPath $tmp -Force;" ^
  "$bin = Get-ChildItem $tmp -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1;" ^
  "if (-not $bin) { exit 1 };" ^
  "$dest = Join-Path '%TOOLS%' 'ffmpeg\bin'; New-Item -ItemType Directory -Path $dest -Force | Out-Null;" ^
  "Copy-Item (Join-Path $bin.DirectoryName '*.exe') $dest -Force;" ^
  "Remove-Item $tmp -Recurse -Force"
goto :eof


rem ==========================================================
rem                        ОШИБКИ
rem ==========================================================

:no_python
echo.
echo Не удалось поставить Python автоматически.
echo Скачай его вручную: https://www.python.org/downloads/
echo При установке обязательно отметь галочку "Add Python to PATH",
echo затем закрой это окно и запусти run.bat заново.
echo.
start "" "https://www.python.org/downloads/"
pause
goto :end

:no_ffmpeg
echo.
echo Не удалось скачать FFmpeg. Скорее всего, нет интернета
echo или его блокирует антивирус.
echo Можно поставить вручную командой в PowerShell:
echo     winget install Gyan.FFmpeg
echo Либо скачать архив и положить ffmpeg.exe и ffprobe.exe в папку:
echo     %TOOLS%\ffmpeg\bin
echo.
pause
goto :end

:no_venv
echo.
echo Не удалось создать окружение Python. Проверь, что на диске
echo есть свободное место и что папку не блокирует антивирус.
echo.
pause
goto :end

:no_deps
echo.
echo Не удалось поставить зависимости. Обычно это интернет или антивирус.
echo Попробуй запустить run.bat заново - скачивание продолжится.
echo.
pause
goto :end

:end
endlocal
