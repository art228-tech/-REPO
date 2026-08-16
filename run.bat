@echo off
setlocal
cd /d "%~dp0"

set "PSEXE=powershell"
where pwsh >nul 2>&1 && set "PSEXE=pwsh"
where %PSEXE% >nul 2>&1 || goto :nops

%PSEXE% -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 goto :fail
endlocal
exit /b 0

:nops
echo.
echo PowerShell not found. It ships with Windows 7 and newer,
echo so this usually means it was removed or blocked by policy.
echo.
pause
endlocal
exit /b 1

:fail
echo.
echo Something went wrong - scroll up for the details.
echo If this window closes instantly, open a command prompt
echo in this folder and run:  run.bat
echo.
pause
endlocal
exit /b 1
