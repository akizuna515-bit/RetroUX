@echo off
rem RetroUX 開発・調査用ランチャー（2026-07-30 / リリース調整 仕様書 12章）
rem
rem ★★ **こちらはコンソールを出す。** ★★
rem   進捗・警告・二重起動の判定結果がその場で読める。
rem
rem 【注意】公開用（コンソールなし）は RetroUX.vbs。
rem   仕様書 2.1: 公開用を作るために**開発用を削除・置換しない**。
rem
rem 使い方:
rem   Start-RetroUX-Console.cmd                  そのまま起動
rem   Start-RetroUX-Console.cmd -ReadOnly        閲覧専用
rem   Start-RetroUX-Console.cmd -NoEmulator      GUI だけ
rem   Start-RetroUX-Console.cmd -NewLog          ログ世代を切る
rem   （start-retroux.ps1 のオプションはそのまま渡せます）

setlocal
set "ROOT=%~dp0"
rem ★末尾の \ を落とす（PowerShell の -Root へ渡すため）
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "SCRIPT=%ROOT%\scripts\start-retroux.ps1"
if not exist "%SCRIPT%" (
    echo.
    echo RetroUX を起動できませんでした。
    echo   起動スクリプトが見つかりません: %SCRIPT%
    echo   このファイルはプロジェクトのフォルダの中に置いたまま使ってください。
    echo.
    pause
    exit /b 1
)

rem 【注意】-Quiet は付けない（コンソールに出すのがこのランチャーの目的）
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Root "%ROOT%" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo 起動に失敗しました（終了コード %CODE%）。
    echo   ログ: %ROOT%\work\retroux.log
    echo.
    rem ★失敗したときだけ待つ。成功時に待つと、閉じ忘れた窓が残る
    pause
)
exit /b %CODE%
