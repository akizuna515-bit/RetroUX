# DQ3 の開発版を起動する（RX3-0019 / 2026-08-29）。
#
#   powershell -ExecutionPolicy Bypass -File scripts\start-dq3.ps1
#
# ★これ 1 本で 2 つを起動する:
#
#     1. FCEUX + dq3/phase0/dev.lua   （★A 自動戦闘 / T ターボ / M まんたん）
#     2. DQ3 の画面（dq3/ui）          （★別ウィンドウの地図つき）
#
# ⚠⚠ このファイルは **UTF-8 + BOM** で保存すること。
#   PowerShell 5.1 は BOM の無い .ps1 を ANSI(cp932) として読むため、
#   日本語コメントが壊れて構文エラーになる（docs/50-playbook.md）。
#
# ⚠ DQ3 は dev-only です。公開しません（RX3-0011）。

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    # ★画面を出さずに FCEUX だけ起動したいとき
    [switch]$NoUi,
    # ★FCEUX を出さずに画面だけ見たいとき（⚠ state.json は前回の値のまま）
    [switch]$NoEmulator,
    # ⚠ 設定 Lua の作り直しを飛ばす（★普段は飛ばさないこと）
    [switch]$SkipGenerate
)

$ErrorActionPreference = "Stop"

function Fail([string]$message, [string]$detail = "") {
    $text = $message
    if ($detail) { $text = "$message`n`n$detail" }
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show($text, "DQ3 RetroUX", "OK", "Error") | Out-Null
    exit 1
}

$fceux  = Join-Path $Root "tools\fceux\fceux64.exe"
$rom    = Join-Path $Root "work\rom\DQ3_J.nes"
$lua    = Join-Path $Root "dq3\phase0\dev.lua"
$python = Join-Path $Root ".venv\Scripts\python.exe"
# ★黒い窓を出さない（⚠ 無ければ python.exe で代用する）
$pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $python }

if (-not (Test-Path -LiteralPath $python)) {
    Fail "Python の仮想環境がありません。" ("次で作れます:`n  uv venv --python 3.12`n  uv pip install -e .`n`n" + $python)
}
if (-not $NoEmulator) {
    if (-not (Test-Path -LiteralPath $fceux)) { Fail "FCEUX がありません:" $fceux }
    if (-not (Test-Path -LiteralPath $rom))   { Fail "DQ3 の ROM がありません:" ($rom + "`n`nここに DQ3_J.nes を置いてください。") }
    if (-not (Test-Path -LiteralPath $lua))   { Fail "Lua がありません:" $lua }
}

# ★Lua 側が既定値に頼らないよう、場所を環境変数で渡す
$env:RETROUX_ROOT = $Root

# ★★ この起動を見分ける札。
#
#   ⚠ 「終」で**今回立てた控えだけ**を止めるために要る。
#     画面（dq3.ui.app）はこの環境変数を引き継ぐ。
#
#   ⚠⚠ **空にしない。** 空のまま `--session` に渡すと
#     `error: argument --session: expected one argument` で
#     ★控えが**起動せずに死ぬ**（2026-08-29 に実際にそうなっていた）。
#     ⚠ pythonw なので画面には何も出ない。
$env:RETROUX_DQ3_SESSION = "dq3-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + $PID

# ★設定 → Lua を作り直す（⚠ 設定を変えたのに作り忘れる事故を防ぐ）
if (-not $SkipGenerate) {
    & $python -m dq3.phase0.generate_lua | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "設定 Lua を作れませんでした。" "python -m dq3.phase0.generate_lua" }
}

# --- 1.5 モンスターの絵（初回のみ ROM から作る / RX3-0431）------------
# ★clone しただけの環境には work/dq3-monster-art が無く、図鑑と戦闘画面で絵が出ない。
#   そろっていれば数 ms で抜ける。⚠ 失敗しても起動は止めない（絵は表示だけ）。
# ⚠ 日本語が化けないように、先に出力の文字コードをそろえる（RX-0064 と同じ）。
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& $python -m dq3.tools.monster_art_setup

# --- 1. セーブステートの世代バックアップ ------------------------------
#
# ⚠⚠ **これが無いと、上書きしたセーブステートは二度と戻らない。**
#   ★実測（2026-08-29）: `work/savestate-backup/` の中身は 24 件すべて DQ2 で、
#   ⚠ **DQ3 は 0 件**だった。仕組みは前からあるのに、ここが呼んでいなかった。
#
# ⚠ 2 つ動かすと、同じ変更を両方が世代に回して**世代が倍の速さで流れ**、
#   ★戻りたい世代が押し出される。→ 心拍のロックで見てから起動する。
if (-not $NoBackup) {
    $backupBusy = $false
    $status = & $python -m retroux.tools.session status --what backup 2>$null
    if ($LASTEXITCODE -eq 0) {
        $backupBusy = ($status.Trim() -eq "BUSY")
    } else {
        # ⚠ 確かめられないときは**起動しない**（★二重に動かすほうが危ない）
        Write-Output "  ⚠ セーブステート保護の状態を確認できませんでした。起動を見送ります。"
        $backupBusy = $true
    }
    if ($backupBusy) {
        Write-Output "  ★セーブステート保護は既に動いています（起動しません）。"
    } else {
        # ⚠ セッションIDを渡す（★「終」で今回のぶんだけ止められるように）
        # ⚠⚠ 空の札を渡すと argparse が落ちて、★控えが黙って起動しない。
        if ([string]::IsNullOrWhiteSpace($env:RETROUX_DQ3_SESSION)) {
            Fail "この起動の札を作れませんでした。" "RETROUX_DQ3_SESSION"
        }
        # ★DQ3 の入口を通す（`dq3.savestate_backup` / RX3-0307）。
        #   ⚠⚠ ここで `retroux.tools.savestate_backup` を直に呼ぶと**既定の 10 世代**に戻ります。
        #     ★仕組みは同じもの（あちらを import しているだけ）。違うのは既定が 100 なことだけ。
        $backupArgs = @("-m", "dq3.savestate_backup",
                        "--session", $env:RETROUX_DQ3_SESSION)
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $pythonw
        $psi.Arguments = ($backupArgs -join " ")
        $psi.WorkingDirectory = $Root
        # ★この 2 つが揃って初めて黒い窓が出なくなる（`launcher-common.ps1`）
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        [System.Diagnostics.Process]::Start($psi) | Out-Null
        Write-Output "  ★セーブステートの世代バックアップを開始しました（スロットごとに 100 世代）。"
    }
}

# --- 2. FCEUX ---------------------------------------------------------
if (-not $NoEmulator) {
    # ⚠⚠ 既に FCEUX が動いていると、fcs/ と fceux.cfg を取り合う。
    #   ★実行のたびに結果が変わるので、先に知らせる（run_probe.py と同じ約束）。
    $running = @(Get-Process -Name "fceux64" -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $answer = [System.Windows.Forms.MessageBox]::Show(
            ("FCEUX が既に " + $running.Count + " 個動いています。`n`n" +
             "セーブステートと設定を取り合うため、実行のたびに結果が変わります。`n`n" +
             "このまま起動しますか？"),
            "DQ3 RetroUX", "YesNo", "Warning")
        if ($answer -ne "Yes") { exit 0 }
    }
    # ★★ 画面の見え方（RX-0140 / 2026-09-18 依頼者「レトロ感だと pal3x だね」）。
    #   ⚠⚠ フィルタは **exe の隣の fceux.cfg** しか見ない（★-cfg で渡しても効かない / RX-0108 で実測）。
    #   ★だから起こす直前に winspecial の行だけ書き換える（⚠ 触るのはその 1 行）。
    #   ⚠ 失敗しても起動は止めない（★見え方だけの話）。
    & $python -m dq3.emulator_video
    # ⚠ -lua は相対パスだと exe の場所を探しに行く。★必ず絶対パスを渡す
    Start-Process -FilePath $fceux -ArgumentList @("-lua", "`"$lua`"", "`"$rom`"") `
        -WorkingDirectory (Split-Path -Parent $fceux)
}

# --- 3. 画面 ----------------------------------------------------------
if (-not $NoUi) {
    Start-Process -FilePath $pythonw -ArgumentList @("-m", "dq3.ui.app") `
        -WorkingDirectory $Root
}

Write-Output "起動しました。"
if (-not $NoBackup) {
    # ⚠⚠ ここを `retroux.tools.savestate_backup` に戻さないこと（RX3-0307）。
    #   ★`--restore` を既定の 10 世代で叩くと、たまった 90 世代が黙って消えます。
    Write-Output "  セーブステートの控え: python -m dq3.savestate_backup --list"
    Write-Output "  戻す:                 python -m dq3.savestate_backup --restore DQ3_J.fc0 --gen 3"
}
Write-Output "  A = 自動戦闘の入り切り / T = ターボ / M = まんたん"
Write-Output "  ゲームの A ボタンはキーボードの F です。"
