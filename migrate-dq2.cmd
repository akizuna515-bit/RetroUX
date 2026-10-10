@echo off
rem ============================================================
rem  RetroUX DQ2  --  move your play data from an older RetroUX DQ2
rem
rem  Double-click this file, or drop the OLD RetroUX folder onto it.
rem  The old folder is only read. Nothing in it is changed (RX-0165).
rem  The data is copied into THIS folder (the new RetroUX DQ2).
rem
rem  Messages are shown by Python (retroux.migration --interactive).
rem  Close RetroUX (DQ2 and DQ3) before running this.
rem
rem  ASCII only (cmd.exe comments included) and CRLF, on purpose.
rem  See tests/test_migrate_cmd.py
rem ============================================================

setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

rem  Bundled Python first, then the development .venv (same order as
rem  scripts\launcher-common.ps1). PATH is never used.
set "PY=%ROOT%\runtime\python\python.exe"
if not exist "%PY%" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" goto :no_python

cd /d "%ROOT%"
if "%~1"=="" (
  "%PY%" -X utf8 -m retroux.migration --dest "%ROOT%" --interactive
) else (
  "%PY%" -X utf8 -m retroux.migration --source "%~1" --dest "%ROOT%" --interactive
)
exit /b %ERRORLEVEL%

:no_python
echo.
echo  Could not find Python for RetroUX DQ2.
echo    Looked for: %ROOT%\runtime\python\python.exe
echo           and: %ROOT%\.venv\Scripts\python.exe
echo.
echo  Keep this file inside the RetroUX DQ2 folder.
echo.
pause
exit /b 1
