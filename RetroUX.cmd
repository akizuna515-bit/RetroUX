@echo off
rem ============================================================
rem  RetroUX.cmd  --  compatibility stub (RX-0154)
rem
rem  The Dragon Quest II launcher is now DQ2.cmd.
rem  This file only calls DQ2.cmd and will be removed in a future
rem  minor release. Please use DQ2.cmd (or a shortcut to it).
rem
rem  No dialog is shown. DQ2 writes one line to its launcher log
rem  (work\runtime\dq2-log\retroux.log) saying the old entry was used.
rem
rem  ASCII only (cmd.exe comments included) and CRLF, on purpose.
rem  See tests/test_cmd_launchers.py
rem ============================================================

setlocal

if not exist "%~dp0DQ2.cmd" goto :no_dq2
call "%~dp0DQ2.cmd" -LegacyEntry %*
exit /b %ERRORLEVEL%

:no_dq2
echo.
echo  Could not start Dragon Quest II.
echo    Missing launcher: %~dp0DQ2.cmd
echo.
echo  Keep this file inside the RetroUX folder.
echo.
pause
exit /b 1
