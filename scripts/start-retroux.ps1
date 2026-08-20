# RetroUX を一発で立ち上げる（MVP2 Phase 1）。
#
#   powershell -ExecutionPolicy Bypass -File scripts\start-retroux.ps1
#
# やること（この順番）:
#   1. 二重起動チェック（★これが本題のひとつ）
#   2. YAML -> Lua の変換（設定の反映漏れを防ぐ）
#   3. ログ世代（-NewLog のときだけ新しい世代を始める）
#   4. セーブステートの世代バックアップを開始
#   5. GUI を別ウィンドウで起動
#   5. FCEUX を起動（scripts\start.ps1 に任せる。フォーカス移動の実績がある）
#   6. 2つのウィンドウを 1920×1080 に整列
#
# ★★ 二重起動は3つの層で見る ★★
#
#   同じものが2つ動いたときの壊れ方が層ごとに違うので、別々に見る:
#
#   | 層 | 何が起きるか | 見方 |
#   | -- | -- | -- |
#   | この起動スクリプト | 下の全部が二重に立ち上がる | 名前付き Mutex |
#   | 取り込み（GUI/record） | **全戦闘が二重に記録**される | work\event_ingestor.lock の心拍 |
#   | セーブステートのバックアップ | **世代が倍の速さで流れ、戻りたい世代が押し出される** | work\savestate_backup.lock の心拍 |
#   | FCEUX | 2つが同じ events.jsonl へ書き、記録が混ざる | プロセス一覧 |
#
#   ⚠ 取り込みの二重起動は**見た目では気づけない**。数字だけが静かに倍になる。
#     「削減できた待ち時間」は中心指標なので、ここは硬く止める。
#
# オプション:
#   -ReadOnly     GUI を閲覧専用で起動する（記録は別プロセスに任せる）
#   -NoEmulator   FCEUX を起動しない（GUI だけ見たいとき）
#   -NoBackup     セーブステートの世代バックアップを起動しない
#   -NoAlign      ウィンドウを動かさない
#   -NewLog       今回から新しいログ世代を始める（前回までは .1 へ送る）
#   -Force        二重起動チェックを無視する（★非推奨。壊れ方を承知の上で）
#   -Lua <path>   FCEUX に流す Lua を差し替える（検証スクリプト用）
#   -Quiet        ★公開用。コンソールへの案内を出さず、GUI とバックアップを
#                 pythonw.exe で起動する（コンソールを作らない）。
#                 ⚠ 失敗は**メッセージボックスとログ**で伝える
#                   （黙って終わると利用者から見て「何も起きない」）。
#
# ★★ 公開用の入口は RetroUX.vbs（これを非表示で呼ぶ）★★
#   開発用は Start-RetroUX-Console.cmd（コンソールあり）。
#   仕様書 2.1: 公開用起動を作るために**開発用を削除・置換しない**。

param(
    [string]$Root = "",
    [string]$Lua = "retroux\emulator\fceux\run.lua",
    [string]$Rom = "",
    [switch]$ReadOnly,
    [switch]$NoEmulator,
    [switch]$NoBackup,
    [switch]$NoAlign,
    [switch]$NewLog,
    [switch]$Force,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

# ★共通部品（Quiet の出力抑止・ログ・メッセージボックス・exe の選び分け）
. (Join-Path $PSScriptRoot "launcher-common.ps1")
$script:RetroUXQuiet = [bool]$Quiet

# ★Windows PowerShell 5.1 には三項演算子が無い。使うとパーサエラーになり、
#   「スクリプトが壊れている」ようにしか見えないので if で書く。
if ($Root -eq "") {
    if ($PSScriptRoot) { $Root = Split-Path -Parent $PSScriptRoot }
    else { $Root = (Get-Location).Path }
}
Set-Location $Root
$script:RetroUXLogPath = Join-Path $Root "work\retroux.log"
# ★パスを相対にするための基準（RX-0043 / 指示書 §26）。
#   ⚠ これが無いと Get-ShortPath は絶対パスをそのまま返す。
$script:RetroUXRoot = $Root
Write-LauncherLog "INFO" ("RetroUX 起動 (Quiet=" + [bool]$Quiet + ")")

# ★この起動を見分ける札（仕様書 6.3）。
#   ⚠⚠ **これが無いと「今回起動した子プロセスだけを止める」ができない。**
#     終了処理の統合は次フェーズだが、札は**今から渡しておく**
#     （あとから足すと、既に動いている子には札が無いので見分けられない）。
#   ⚠ 一度これを使い忘れて `$script:RetroUXSession` が未定義のまま
#     `--session` へ渡っていた（＝空の札）。PowerShell は未定義の変数を
#     $null として黙って通すので、**気づけない形の抜け**だった（2026-07-30）。
#   ★12文字に切る。ログに何度も出るので、長いと読みにくい。
$script:RetroUXSession = ([guid]::NewGuid().ToString("N")).Substring(0, 12)
Write-LauncherLog "INFO" ("この起動の札: " + $script:RetroUXSession)

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Stop-Launcher -Message ("Python の仮想環境が見つかりません。`n`n" +
        "次を実行して作ってください:`n" +
        "  uv venv --python 3.12`n  uv pip install -e .") -Detail $python
}
# ★GUI と常駐処理を起動する exe（Quiet なら pythonw.exe / 仕様書 4.1）
$guiPython = Get-PythonForGui -Root $Root -Quiet:$Quiet
# ★パスは相対で出す（⚠ 利用者名が混ざらないように / RX-0043）
Write-LauncherLog "INFO" ("GUI の起動に使う exe: " + (Get-ShortPath $guiPython))

# --- 1. 二重起動チェック ---------------------------------------------

# 1-a. この起動スクリプト自身。
#      ★Mutex はプロセスが死ねば OS が自動で解放する。
#        ファイルで見ると、異常終了した残骸で起動できなくなる事故が起きる。
$mutex = New-Object System.Threading.Mutex($false, "RetroUX_Launcher")
$gotMutex = $mutex.WaitOne(0)
if (-not $gotMutex -and -not $Force) {
    # ⚠ 公開用（Quiet）では**メッセージボックスで伝える**。
    #   コンソールが無いので Write-Warning だけでは誰にも届かない。
    Stop-Launcher -Message ("RetroUX は既に起動しています。`n`n" +
        "先に開いているウィンドウを確認してください。") -Code 1
}

try {
    # 1-b. 取り込みプロセス（GUI / record）。心拍ファイルで見る。
    #      ★判定は Python 側と**同じコード**を呼ぶ。ここで独自に書くとずれる。
    # ★引用符を含む Python を -c で渡すと、Windows PowerShell が
    #   native exe への引数から引用符を落として壊す（実際に踏んだ）。
    #   処理はモジュール側に置き、名前で呼ぶ。
    $lockCheck = & $python -m retroux.tools.session status
    if ($LASTEXITCODE -ne 0) {
        Stop-Launcher -Message "記録の状態を確認できませんでした。" -Detail "session status"
    }

    if ($lockCheck.Trim() -eq "BUSY" -and -not $ReadOnly) {
        # ⚠ PowerShell 5.1 は**行頭の `+`** で式を続けられない。
        #   `+` は行末に置くこと（実際にパーサエラーになった）。
        Write-Note ("イベント取込プロセスが既に稼働しています。" +
            "GUI は閲覧専用で起動します（二重に記録すると全戦闘が2件になります）。")
        $ReadOnly = $true
    }

    # 1-c. セーブステートの世代バックアップ。
    #      ★2つ動くと**同じ変更を両方が世代に回す**。世代数は決まっているので
    #        倍の速さで流れ、**戻りたい世代が押し出される**。
    #        守っているのが取り返しのつかない事故なので、ここは硬く止める。
    $backupCheck = & $python -m retroux.tools.session status --what backup
    if ($LASTEXITCODE -ne 0) {
        Stop-Launcher -Message "セーブステート保護の状態を確認できませんでした。" -Detail "session status --what backup"
    }
    $backupBusy = ($backupCheck.Trim() -eq "BUSY")

    # ★ロックを持たない古い起動が残っていることがある（この仕組みを入れる前に
    #   手で起動したもの）。プロセス一覧でも見る。
    $backupProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*savestate_backup*' })
    if ($backupProcs.Count -gt 0 -and -not $backupBusy) {
        Write-Note ("セーブステート保護らしいプロセスが " + $backupProcs.Count +
            " 個動いています（ロックを持っていません）。二重に動くと世代が倍の速さで流れます。")
        $backupBusy = $true
    }

    # 1-d. FCEUX。2つ動くと同じ events.jsonl へ書き込み、記録が混ざる。
    $fceuxRunning = @(Get-Process -Name "fceux*" -ErrorAction SilentlyContinue)
    if ($fceuxRunning.Count -gt 0 -and -not $NoEmulator) {
        Write-Note ("FCEUX が既に " + $fceuxRunning.Count +
            " 個動いています。2つ動かすと記録が混ざります。")
        if (-not $Force) {
            Write-Note "エミュレータの起動は飛ばします（-Force で無視できます）。"
            $NoEmulator = $true
        }
    }

    # --- 2. YAML -> Lua の変換 ---------------------------------------
    # ★忘れると「設定を変えたのに黙って無視される」（実際に起きた事故）。
    #   起動のたびに走らせておけば、その事故が構造的に起きなくなる。
    Write-Step "設定を変換しています（YAML -> Lua）..."
    & $python -m retroux.core.config.generate_lua
    if ($LASTEXITCODE -ne 0) {
        Stop-Launcher -Message ("設定ファイルの変換に失敗しました。`n`n" +
            "retroux\plugins\dq2\config.yaml の書き方を確認してください。")
    }

    # --- 3. ログ世代 -------------------------------------------------
    # 既定は**続きに書く**（1本の時系列で読めるほうが調査しやすい）。
    # サイズによる世代分けは Python 側が自動で行う（10MB × 5世代）。
    # -NewLog は「今回のぶんだけ切り分けたい」ときの手動操作。
    if ($NewLog) {
        & $python -m retroux.tools.session rotate-log
    }

    # --- 4. セーブステートの世代バックアップ ---------------------------
    # ★GUI より先に出す。世代の保存は**ゲームを触る前から**効いていてほしい。
    if (-not $NoBackup) {
        if ($backupBusy) {
            Write-Step "セーブステート保護は既に動いています（起動しません）。"
        } else {
            Write-Step "セーブステートの世代バックアップを開始します..."
            # ★Quiet なら pythonw.exe（仕様書 4.1）。★窓の抑止は
            #   `Start-NoConsole` 側でやる（GUI と**同じ1つの方法**にそろえる）。
            #   ⚠ ここは以前 `-WindowStyle Hidden` だったので窓が出ていなかった。
            #     GUI 側にそれが無かったため**片方だけ窓が出て**いた。
            #   ⚠ セッションIDを渡す。GUI が「今回起動したものだけ」を
            #     見分けられるようにするため（仕様書 6.3 / 終了処理は次フェーズ）。
            $backupArgs = @("-m", "retroux.tools.savestate_backup",
                            "--session", $script:RetroUXSession)
            Start-NoConsole -FilePath $guiPython -Arguments $backupArgs | Out-Null
        }
    }

    # --- 5. GUI ------------------------------------------------------
    $guiArgs = @("-m", "retroux.gui", "--session", $script:RetroUXSession)
    if ($ReadOnly) { $guiArgs += "--read-only"; $role = "閲覧専用" } else { $role = "記録あり" }
    Write-Step ("GUI を起動します（" + $role + "）...")
    # ⚠⚠ **ここが R-1 の急所。`Start-NoConsole` を使う。** ★★
    #
    #   2026-07-30 の実機確認で「黒い窓が出る」と分かった。窓の題名は
    #   `F:\...\.venv\Scripts\pythonw.exe`、クラスは `ConsoleWindowClass`。
    #   ★`pythonw` を選んでいるのにコンソールが出るのは uv の venv 固有の話で、
    #     理由と対策は `launcher-common.ps1:Start-NoConsole` に書いてある。
    #
    #   ⚠ `-WindowStyle Hidden` で直そうとすると**Qt の窓まで隠れる**
    #     （実測済み。プロセスは生きているのに画面に何も出ない）。
    #
    #   ★`& $python ...`（同期呼び出し）は親のコンソールを継ぐので問題ない。
    #     新しく窓が増えるのは、別プロセスとして起こすときだけ。
    $gui = Start-NoConsole -FilePath $guiPython -Arguments $guiArgs
    Start-Sleep -Milliseconds 800
    $gui.Refresh()
    if ($gui.HasExited) {
        # ⚠ Quiet では Write-Warning は誰にも届かない。
        #   GUI が出ないのは**起動できなかったのと同じ**なので、止めて知らせる。
        Stop-Launcher -Message ("GUI が起動直後に終了しました。`n`n" +
            "ログに原因が残っています。") -Detail (Join-Path $Root "work\retroux.log")
    }

    # --- 6. エミュレータ ---------------------------------------------
    if (-not $NoEmulator) {
        $env:RETROUX_ROOT = $Root
        $startArgs = @{ Root = $Root; Lua = $Lua }
        if ($Rom -ne "") { $startArgs["Rom"] = $Rom }
        # ★映像倍率を user_config から読んで FCEUX へ渡す（既定 2 倍）。
        try {
            $scaleOut = (& $python -c "from retroux.core.config.user_config import load; print(load()[0].emulator.window_scale)") 2>$null
            if ("$scaleOut".Trim() -match '^\d+$') { $startArgs["Scale"] = [int]"$scaleOut".Trim() }
        } catch { }
        Write-Step "FCEUX を起動します..."
        & (Join-Path $Root "scripts\start.ps1") @startArgs
    }

    # --- 7. 整列 -----------------------------------------------------
    if (-not $NoAlign) {
        Write-Step "ウィンドウを整列します（出そろうまで待ちます）..."
        # ★固定の待ち時間で当てにいかない。Qt の起動にかかる時間は環境で違う。
        #   実際、2.3秒では GUI のウィンドウがまだ無く整列できなかった。
        # ★失敗しても起動は続ける（整列は補助であって本体ではない）。
        & $python -m retroux.tools.align_windows --wait 20
    }

    if ($Quiet) {
        # ★公開用ではここで案内を出さない（コンソールが無いので誰も読まない）。
        #   代わりにログへ1行残す。同じ内容は GUI の画面に出ている。
        Write-LauncherLog "INFO" "起動しました（Quiet）"
        return
    }

    Write-Output ""
    Write-Output "起動しました。"
    Write-Output ("  ログ   : " + (Join-Path $Root "work\retroux.log"))
    if ($ReadOnly) { $roleText = "閲覧専用（記録は別プロセス）" } else { $roleText = "このGUIが記録" }
    Write-Output ("  役割   : " + $roleText)
    if ($NoBackup) { $backupText = "起動していません" }
    elseif ($backupBusy) { $backupText = "既に動いています" }
    else { $backupText = "開始しました" }
    Write-Output ("  バックアップ: " + $backupText)
    Write-Output "  終了時 : GUI と FCEUX のウィンドウを閉じてください。"
    Write-Output "           バックアップは別ウィンドウで動き続けます（Ctrl+C で終了）。"
}
finally {
    if ($gotMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
