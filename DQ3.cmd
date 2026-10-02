@echo off
rem ============================================================
rem  RetroUX launcher  --  Dragon Quest III
rem
rem  Double-click this file to start Dragon Quest III.
rem  No dialog is shown. Errors only are reported.
rem
rem  The project root is taken from THIS file's own folder,
rem  so the current working directory does not matter.
rem
rem  ASCII only (cmd.exe comments included) and CRLF, on purpose.
rem  See tests/test_launcher_encoding.py
rem ============================================================

setlocal

set "ROOT=%~dp0"
rem  strip the trailing backslash (PowerShell -Root does not want it)
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "SCRIPT=%ROOT%\scripts\start-dq3.ps1"
if not exist "%SCRIPT%" goto :no_script

rem  Hand over to PowerShell without a visible window and return at once.
rem  From here on, failures are reported by the PowerShell side
rem  (it shows a message box and writes work\retroux.log).
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden ^
  -File "%SCRIPT%" -Root "%ROOT%" %*
if errorlevel 1 goto :no_powershell
exit /b 0

:no_script
echo.
echo  Could not start Dragon Quest III.
echo    Missing startup script: %SCRIPT%
echo.
echo  Keep this file inside the RetroUX folder.
echo  (A desktop shortcut to it is fine.)
echo.
pause
exit /b 1

:no_powershell
echo.
echo  Could not start Dragon Quest III.
echo    Windows PowerShell could not be launched.
echo.
pause
exit /b 1
