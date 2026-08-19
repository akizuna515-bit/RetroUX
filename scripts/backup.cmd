@echo off
rem ============================================================
rem  セーブステートの世代バックアップを起動する
rem
rem  ダブルクリックで起動できます。
rem  プレイ中はこのウィンドウを開いたままにしてください。
rem  終了は Ctrl+C か、ウィンドウを閉じる。
rem
rem  ★このファイルは cp932(Shift-JIS) で保存すること。
rem    最初は UTF-8 で書き、先頭に chcp 65001 を置いていたが、
rem    cmd はバッチをバイト位置で読み進めるため、途中でコードページを
rem    変えると多バイト文字とずれ、行の途中から別コマンドとして解釈された
rem    （'保存先' is not recognized... というエラーが出た）。
rem
rem  引数はそのまま渡せます:
rem    backup.cmd --list
rem    backup.cmd --restore DQ2_J.fc8 --gen 1
rem ============================================================

rem uv run はプロジェクトのフォルダを基準に動く。確実に移動してから起動する。
cd /d "%~dp0.."

where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo [エラー] uv が見つかりません。PATH を確認してください。
  echo.
  pause
  exit /b 1
)

echo ============================================================
echo  セーブステートの世代バックアップ
echo ------------------------------------------------------------
echo  プロジェクト : %CD%
echo  監視するもの : tools/fceux/fcs のセーブステート
echo  保存先       : work/savestate-backup
echo.
echo  世代を作るのは中身が変わったときだけです。10世代まで残します。
echo  このウィンドウは開いたままにしてください。
echo ============================================================
echo.

uv run python -m retroux.tools.savestate_backup %*
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" echo [終了コード %RC%] 問題が起きた可能性があります。

rem ダブルクリック（引数なし）のときだけ止める。
if "%~1"=="" pause
exit /b %RC%
