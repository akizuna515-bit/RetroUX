# RetroUX DQ2 を一発で立ち上げる（MVP2 Phase 1 / ★2026-10-03 RX-0154 で start-retroux.ps1 から改名し、start.ps1 を取り込んだ）。
#
# ★利用者の入口は DQ2.cmd だけ（★これを隠して呼ぶ）。RetroUX.cmd は DQ2.cmd を呼ぶだけの互換 stub。
#
#   powershell -ExecutionPolicy Bypass -File scripts\start-dq2.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start-dq2.ps1 -EmulatorOnly -Lua research\probes\active\hoimi_test.lua
#
# やること（この順番）:
#   1. 二重起動チェック（★これが本題のひとつ）
#   2. YAML -> Lua の変換（設定の反映漏れを防ぐ）
#   3. ログ世代（-NewLog のときだけ新しい世代を始める）
#   4. セーブステートの世代バックアップを開始
#   5. GUI を別ウィンドウで起動
#   5. FCEUX を起動（関数 Start-Dq2Emulator / ★旧 scripts\start.ps1。フォーカス移動の実績がある）
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
#   -EmulatorOnly ★FCEUX だけを起こす（控え・GUI・排他・ログに触らない / ★旧 start.ps1 -Lua の probe 用途）
#   -Fceux <path> FCEUX の exe（★空なら dq2_user_config.yaml の paths.fceux → tools\fceux / RX-0146）
#   -LegacyEntry  ★旧入口 RetroUX.cmd（互換 stub）から来たことを記録に 1 行（内部用）
#   -Quiet        ★公開用。コンソールへの案内を出さず、GUI とバックアップを
#                 pythonw.exe で起動する（コンソールを作らない）。
#                 ⚠ 失敗は**メッセージボックスとログ**で伝える
#                   （黙って終わると利用者から見て「何も起きない」）。
#
# ★★ 公開用の入口は DQ2.cmd（これを非表示で -Quiet で呼ぶ / RX-0154）★★
#   ★進捗をコンソールで見たいとき（開発用）は、このファイルを -Quiet 無しで直に実行する
#     （⚠ 旧 RetroUX.vbs・Start-RetroUX-Console.cmd は 2026-10-03 に削除 / RX-0153）。

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
    [switch]$Quiet,
    [switch]$EmulatorOnly,
    [string]$Fceux = "",
    [int]$FocusTimeoutSeconds = 8,
    [switch]$LegacyEntry
)

$ErrorActionPreference = "Stop"

# ★共通部品（Quiet の出力抑止・ログ・メッセージボックス・exe の選び分け）
. (Join-Path $PSScriptRoot "launcher-common.ps1")
# ★箱の題名と文面の製品名（RX-0155）
$script:RetroUXProductTitle = "RetroUX DQ2"

# --- ★★ FCEUX の起動（RX-0154: 旧 scripts\start.ps1 をここへ取り込んだ）★★ ---------------
#
# ★ねらい: 起動直後のフォーカスを「エミュレータ本体のウィンドウ」へ移す。
#   FCEUX を -lua 付きで起動すると「Lua Script」ウィンドウが前面に出てフォーカスを取る。
#   その状態で p（セーブステートのロード）などを押すと、スクリプトのファイル名入力欄に文字が入る（依頼者の報告）。
# ⚠ Windows は「前面でないプロセスが勝手にフォーカスを奪うこと」を禁止しているので、3 つの方法を順に試し、
#   実際に移ったかを毎回確かめる。
# ★検証スクリプトを流すときは -EmulatorOnly -Lua <path>（★旧 `start.ps1 -Lua`）。
function Start-Dq2Emulator {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [string]$Lua = "retroux\emulator\fceux\run.lua",
        [string]$Rom = "work\rom\DQ2_J.nes",
        # ★空なら従来どおり tools\fceux\fceux64.exe（★設定の paths.fceux は start-dq2 が resolver から渡す / RX-0146）
        [string]$Fceux = "",
        [int]$FocusTimeoutSeconds = 8
    )
    if ($Fceux -ne "") {
        if ([System.IO.Path]::IsPathRooted($Fceux)) { $fceux = $Fceux } else { $fceux = Join-Path $Root $Fceux }
    } else {
        $fceux = Join-Path $Root "tools\fceux\fceux64.exe"
    }
    # ★FCEUX へ渡すパスは絶対パスにする。
    #   相対パスだとエラーも出ずに何も起きない（docs/50-playbook.md #7）
    if ([System.IO.Path]::IsPathRooted($Lua)) { $luaPath = $Lua } else { $luaPath = Join-Path $Root $Lua }
    if ([System.IO.Path]::IsPathRooted($Rom)) { $romPath = $Rom } else { $romPath = Join-Path $Root $Rom }

    foreach ($p in @($fceux, $luaPath, $romPath)) {
        if (-not (Test-Path -LiteralPath $p)) {
            Stop-Launcher -Message ("FCEUX を起動できません。`n`n見つかりません: " + (Get-ShortPath $p)) -Detail $p
        }
    }

    $env:RETROUX_ROOT = $Root

    Write-Output "起動します:"
    Write-Output ("  FCEUX : " + $fceux)
    Write-Output ("  Lua   : " + $luaPath)
    Write-Output ("  ROM   : " + $romPath)

    # パスは引用符付きで渡す（スペースを含む場合の分割を防ぐ / playbook #11）
    # ★映像倍率は --xscale では変わらない（実測）。fceux.cfg の winsizemulx/y を
    #   起動前に書く（起動の段取り（start-dq2.ps1）が retroux.tools.fceux_scale を呼ぶ）。
    $argList = @("-lua", ('"' + $luaPath + '"'), ('"' + $romPath + '"'))
    $proc = Start-Process -FilePath $fceux -ArgumentList $argList -PassThru

    # --- フォーカスの移動 -------------------------------------------------
    # 3つの方法を順に試し、GetForegroundWindow で「実際に移ったか」を確認する。
    # 移ったつもりで終わらせないため。
    Add-Type -AssemblyName Microsoft.VisualBasic
    if (-not ("Win32.Focus" -as [type])) {
        Add-Type -Namespace Win32 -Name Focus -MemberDefinition @"
    [DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr hWnd);
    [DllImport("user32.dll")] public static extern void SwitchToThisWindow(System.IntPtr hWnd, bool fAltTab);
    [DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
"@
    }

    function Test-Focused($hwnd) {
        Start-Sleep -Milliseconds 200
        return ([Win32.Focus]::GetForegroundWindow() -eq $hwnd)
    }

    $deadline = (Get-Date).AddSeconds($FocusTimeoutSeconds)
    $moved = $false
    $method = ""
    while ((Get-Date) -lt $deadline -and -not $moved) {
        Start-Sleep -Milliseconds 400
        $proc.Refresh()
        if ($proc.HasExited) {
            Write-Warning "FCEUX が終了しました（検証スクリプトなら正常です）。"
            break
        }
        $hwnd = $proc.MainWindowHandle
        if ($hwnd -eq [System.IntPtr]::Zero) { continue }

        # 1) AppActivate（最も素直）
        try { [Microsoft.VisualBasic.Interaction]::AppActivate($proc.Id) } catch { }
        if (Test-Focused $hwnd) { $moved = $true; $method = "AppActivate"; break }

        # 2) SetForegroundWindow
        [void][Win32.Focus]::ShowWindow($hwnd, 5)   # SW_SHOW
        [void][Win32.Focus]::SetForegroundWindow($hwnd)
        if (Test-Focused $hwnd) { $moved = $true; $method = "SetForegroundWindow"; break }

        # 3) SwitchToThisWindow（Alt+Tab 相当。前2つが弾かれても通ることがある）
        [Win32.Focus]::SwitchToThisWindow($hwnd, $true)
        if (Test-Focused $hwnd) { $moved = $true; $method = "SwitchToThisWindow"; break }
    }

    if ($moved) {
        Write-Output ("フォーカスをエミュレータ本体へ移しました（" + $method + "）。")
        Write-Output "  そのまま p（セーブステートのロード）などを押せます。"
    } elseif (-not $proc.HasExited) {
        Write-Warning "フォーカスを移せませんでした。"
        Write-Warning "  Windows は前面でないプロセスからのフォーカス奪取を禁止しています。"
        Write-Warning "  このスクリプトを自分のターミナルから直接実行すると通りやすくなります。"
        Write-Warning "  それでも駄目なら、エミュレータの画面を一度クリックしてください。"
        Write-Warning "  Lua Script ウィンドウにフォーカスがあると、p がファイル名の入力欄に入ります。"
    }
}
$script:RetroUXQuiet = [bool]$Quiet

# ★Windows PowerShell 5.1 には三項演算子が無い。使うとパーサエラーになり、
#   「スクリプトが壊れている」ようにしか見えないので if で書く。
if ($Root -eq "") {
    if ($PSScriptRoot) { $Root = Split-Path -Parent $PSScriptRoot }
    else { $Root = (Get-Location).Path }
}
Set-Location $Root

# ★★ FCEUX だけを起こす（RX-0154 / ★旧 `scripts\start.ps1 -Lua …` の probe 用途）★★
#   ★控え・GUI・製品間排他・ログには触らない（★検証スクリプトを流すための道）。
#     例: powershell -ExecutionPolicy Bypass -File scripts\start-dq2.ps1 -EmulatorOnly -Lua research\probes\active\hoimi_test.lua
if ($EmulatorOnly) {
    $emuArgs = @{ Root = $Root; Lua = $Lua; FocusTimeoutSeconds = $FocusTimeoutSeconds }
    if ($Rom -ne "") { $emuArgs["Rom"] = $Rom }
    if ($Fceux -ne "") { $emuArgs["Fceux"] = $Fceux }
    Start-Dq2Emulator @emuArgs
    exit 0
}

# ★DQ2 のログは work\runtime\dq2-log\（RX-0149）。⚠ 旧 work\retroux.log は DQ3 の控えも書くので離れる（旧ログは動かさない）。
#   ★フォルダはここで作る（⚠ FCEUX の Lua は io.open("a") で開くので、フォルダが無いと黙って書けない）。
$script:RetroUXLogPath = Join-Path $Root "work\runtime\dq2-log\retroux.log"
try { New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:RetroUXLogPath) | Out-Null } catch { }
# ★パスを相対にするための基準（RX-0043 / 指示書 §26）。
#   ⚠ これが無いと Get-ShortPath は絶対パスをそのまま返す。
$script:RetroUXRoot = $Root
Write-LauncherLog "INFO" ("RetroUX DQ2 起動 (Quiet=" + [bool]$Quiet + ")")
if ($LegacyEntry) {
    # ★旧入口（RetroUX.cmd = 互換 stub / RX-0154）から来た。⚠ 箱は出さない（記録に 1 行だけ）
    Write-LauncherLog "INFO" "旧入口 RetroUX.cmd から起動しました（★DQ2.cmd を使ってください / RetroUX.cmd は次のマイナー更新で削除予定）"
}

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

# ★Python の場所は共通の resolver が決める（RX3-0473 / 2026-09-29）。
#   ⚠ 判定をここへコピーしないこと（★`Get-RetroUXPython` の 1 か所）。
#   ⚠ DQ2 の portable 化そのものは今回していません（★解決の入口だけ揃えた）。
$python = Get-RetroUXPython -Root $Root
if (-not $python) {
    Stop-Launcher -Message ("Python が見つかりません。`n`n" +
        (Get-RetroUXPythonHint -Root $Root)) -Detail $Root
}
# ★展開先が深すぎれば、何も始めずに理由を出して止める（RX-0166 / ⚠ 深いと Qt が黙って止まる）
$depthProblem = Get-RetroUXDepthProblem -Python $python -Root $Root
if ($depthProblem) {
    Stop-Launcher -Message $depthProblem -Detail $Root
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

# 1-0. ★★ 製品間排他（RX-0152 / 依頼者 2026-10-03「DQ2 / DQ3 の同時起動はサポートしない」）★★
#      ★DQ3 が動いていたら、控え・GUI・FCEUX の**どれも起こさずに**理由を出して終わる。
#      ★起動の順番待ちを取ってから見る（⚠ DQ3.cmd とほぼ同時に叩いても両方が通らない）。
#      ⚠ FCEUX の有無では決めない（★他の用途の FCEUX・前回の残りを「DQ3 が起動中」と誤らない）。
$productLaunch = Enter-RetroUXProductLaunch
if ($null -eq $productLaunch) {
    Stop-Launcher -Message ("もう一方の RetroUX の起動が終わるのを待ちましたが、終わりませんでした。`n`n" +
        "しばらくしてからもう一度起動してください。") -Code 1
}
$otherProduct = Get-RetroUXOtherProduct -Me "DQ2"
if ($otherProduct) {
    Exit-RetroUXProductLaunch $productLaunch
    Stop-Launcher -Message (Get-RetroUXBusyMessage -Me "DQ2" -Other $otherProduct) -Code 1
}

# ★RX-0170: この起動で立てた控え（セーブステートの世代バックアップ）を、起動に失敗したときに止める。
#   ⚠ 以前は GUI がすぐ終わると控えだけが残り、次の起動は「既に動いています」で使い回し、
#     終了時も「別の起動のもの」として止めないので、残り続けた（2026-10-05 実機: 翌日も動いていた）。
#   ★止めるのは札（$script:RetroUXSession）が合う控えだけ（Python 側 `--stop-session`）。
$script:BackupStartedHere = $false
$script:BackupStopAsked = $false
$gui = $null
function Stop-OwnDq2Backup {
    if (-not $script:BackupStartedHere -or $script:BackupStopAsked) { return }
    $script:BackupStopAsked = $true
    try {
        $answer = (& $python -m retroux.tools.dq2_savestate_backup --stop-session $script:RetroUXSession --wait 8) 2>$null
        Write-LauncherLog "INFO" ("起動に失敗したので、この起動の控えに停止を伝えました: " + "$answer".Trim())
    } catch { }
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
        # ★誰が握っているのかを言う（2026-08-22 / RX-0064）。
        #   ⚠ 「既に稼働しています」だけだと、何を閉じれば直るのか分からない。
        # ⚠⚠ **日本語を native exe から受け取るときは復号を UTF-8 にする**
        #   （2026-08-22 実測）。PowerShell 5.1 は [Console]::OutputEncoding で
        #   バイト列を復号するので、既定の cp932 のままだと
        #   「最終心拍」が「譛邨ょｿ・牛」になってメッセージボックスに出る。
        #   ★これまでの捕捉は BUSY / FREE（ASCII）だけだったので露見しなかった。
        #   ⚠ コンソールが無い（Quiet）と設定できないことがあるので try で包む。
        $lockWho = Get-PythonText -Python $python -OutFile (Join-Path $Root "work\lock-holder.txt") -Arguments @("-m", "retroux.tools.session", "status", "--who")

        # ★★ ⚠⚠ **2枚目の GUI は開かない**（2026-08-22 / RX-0064 / 依頼者の判断 a）★★
        #
        #   ⚠ ここは長らく「閲覧専用で開く」だった。⚠ しかし二重起動のときは
        #     FCEUX もセーブステート保護も**起動を飛ばす**ので、開くのは
        #     **記録も保存もしない空の窓**でしかない。
        #   ⚠ しかも Quiet 起動（RetroUX.vbs）には**コンソールが無い**ので、
        #     下の Write-Note は**ログにしか出ない**。画面には同じ窓がもう1枚
        #     増えるだけで、利用者には「何も変わらない」ように見えていた（実測 15:06）。
        #   ★開かずに、**誰が記録役かをメッセージボックスで**言って終わる。
        #   ★閲覧専用が要る人は `-ReadOnly` を明示する（下の分岐を通らない）。
        Write-LauncherLog "WARN" ("イベント取込プロセスが既に稼働しています（記録役: " +
            $lockWho + "）。★2枚目の GUI は開きません。")
        # ★見るだけの2枚目は `-ReadOnly`（開発用）。⚠ VBS からは渡せないので
        #   **ダイアログには書かない**（2026-08-22 依頼者「用途が不明」）。ログにだけ残す。
        Write-LauncherLog "INFO" "  ★見るだけの2枚目が要るときは -ReadOnly（開発用）。"
        # ⚠ ダイアログは**利用者がいまできること**だけを書く。
        #   ⚠ 「閉じて起動し直すとこの起動が記録役に」は、開かないと決めた以上
        #     成り立たない（★この起動はもう終わる）。書かない。
        Stop-Launcher -Message ("RetroUX は既に起動しています。`n`n" +
            "先に開いているウィンドウを使ってください。`n`n" +
            "記録役: " + $lockWho) -Code 1
    }

    # 1-c. セーブステートの世代バックアップ。
    #      ★2つ動くと**同じ変更を両方が世代に回す**。世代数は決まっているので
    #        倍の速さで流れ、**戻りたい世代が押し出される**。
    #        守っているのが取り返しのつかない事故なので、ここは硬く止める。
    #      ★DQ2 専用の控え（RX-0144）。⚠ DQ3 の控えのロック（work\savestate_backup.lock）は見ない。
    #        以前は共通のロックを見ていて、DQ3 が先に立っていると DQ2 の控えを起動せず、
    #        DQ2 のセーブを DQ3 の控え（100 世代）に任せていた（調査 Q1・Q2）。
    $backupCheck = & $python -m retroux.tools.dq2_savestate_backup --status
    if ($LASTEXITCODE -ne 0) {
        Stop-Launcher -Message "セーブステート保護の状態を確認できませんでした。" -Detail "dq2_savestate_backup --status"
    }
    $backupBusy = ($backupCheck.Trim() -eq "BUSY")

    # ★ロックを持たない古い起動が残っていることがある（この仕組みを入れる前に
    #   手で起動したもの）。プロセス一覧でも見る。
    #   ⚠ DQ2 専用の控えだけを数える（★`dq3.savestate_backup` には当てない / 調査 D9）。
    $backupProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*retroux.tools.dq2_savestate_backup*' })
    if ($backupProcs.Count -gt 0 -and -not $backupBusy) {
        Write-Note ("セーブステート保護らしいプロセスが " + $backupProcs.Count +
            " 個動いています（ロックを持っていません）。二重に動くと世代が倍の速さで流れます。")
        $backupBusy = $true
    }

    # 1-d. FCEUX。2つ動くと同じ events.jsonl へ書き込み、記録が混ざる。
    #      ★数えるのは DQ2 の FCEUX だけ（RX-0145）。⚠ 以前は `fceux*` を全部数えていて、
    #        DQ3 の FCEUX が動いていると DQ2 の FCEUX を黙って起動しなかった（調査 D4）。
    #        ★DQ2 の FCEUX = コマンドラインに retroux\emulator\fceux\run.lua がある（start.ps1 が -lua に渡す）。
    $fceuxRunning = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'fceux%'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*retroux\emulator\fceux\run.lua*' })
    if ($fceuxRunning.Count -gt 0 -and -not $NoEmulator) {
        Write-Note ("FCEUX が既に " + $fceuxRunning.Count +
            " 個動いています。2つ動かすと記録が混ざります。")
        if (-not $Force) {
            Write-Note "エミュレータの起動は飛ばします（-Force で無視できます）。"
            $NoEmulator = $true
        }
    }

    # 1-e. ★★ DQ2 のデータの版（RX-0157 / D-45）★★
    #      ★知らない版・印と DB の食い違い・途中で終わった移行では、FCEUX も GUI も起動しない。
    #      ★新しく始めるとき（遊んだデータが無い）は印 work\dq2-data.json を書く。
    #      ⚠ 旧版のデータ（印なし）はその場で読めるので止めない（★移行は python -m retroux.migration）。
    #      ★結果は UTF-8 のファイルで受け取る（⚠ 標準出力の日本語は 5.1 で化ける / Get-PythonText）。
    $gateText = Get-PythonText -Python $python -OutFile (Join-Path $Root "work\runtime\dq2-log\data-gate.txt") -Arguments @("-m", "retroux.core.dq2_data", "--gate")
    $gateLines = @($gateText -split "`r?`n")
    if ($gateLines.Count -eq 0 -or $gateLines[0].Trim() -ne "OK") {
        $gateDetail = ($gateLines | Select-Object -Skip 1) -join "`n"
        if (-not $gateText) { $gateDetail = "python -m retroux.core.dq2_data --gate が結果を書きませんでした" }
        Stop-Launcher -Message ("DQ2 のデータを確認できないため起動しません。`n`n" +
            "記録やセーブを守るため、FCEUX と画面は開いていません。") -Detail $gateDetail
    }
    foreach ($line in ($gateLines | Select-Object -Skip 1)) {
        if ($line.Trim()) { Write-LauncherLog "INFO" $line }
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

    # --- 2.5 モンスターの絵（初回のみ ROM から展開 / RX-0086）----------
    # ★clone しただけの環境には work/monster-art-rom が無く、敵の絵が出ない。
    #   そろっていれば数msで抜ける。⚠ 失敗しても起動は止めない（絵は表示だけ）。
    & $python -m retroux.tools.monster_art_setup

    # --- 2.6 マップの大きさ表（初回のみ ROM から生成 / RX-0093）--------------
    # ★同じく clone 直後には work/map-data/maps.json が無く、世界地図が
    #   「歩いた範囲だけ」の描き方になる。無ければ dq2rom maps export で作る。
    & $python -m retroux.tools.map_meta_setup

    # --- 3. ログ世代 -------------------------------------------------
    # 既定は**続きに書く**（1本の時系列で読めるほうが調査しやすい）。
    # サイズによる世代分けは Python 側が自動で行う（10MB × 5世代）。
    # -NewLog は「今回のぶんだけ切り分けたい」ときの手動操作。
    if ($NewLog) {
        # ★DQ2 のログを送る（RX-0149）。⚠ `retroux.tools.session rotate-log` は旧 work\retroux.log
        #   （DQ3 の控えも書く）を送るので使わない。
        & $python -m retroux.tools.dq2_log rotate
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
            #   ★DQ2 専用の控え（RX-0144）。DQ2 ROM のセーブだけを見張り、
            #     work\runtime\dq2-backup\ に世代を残す。
            $backupArgs = @("-m", "retroux.tools.dq2_savestate_backup",
                            "--session", $script:RetroUXSession)
            Start-NoConsole -FilePath $guiPython -Arguments $backupArgs | Out-Null
            $script:BackupStartedHere = $true
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
    # ★GUI が製品の名札（RX-0152）を出すまで、起動の順番待ちを持ったまま待つ
    #   （⚠ 出る前に手放すと、その隙に DQ3 の起動スクリプトが「誰も動いていない」と見てしまう）
    if (-not (Wait-RetroUXProduct -Me "DQ2")) {
        Write-Note "GUI が製品の排他（RetroUX_Product_DQ2）を出すのを待ちきれませんでした。"
    }
    Exit-RetroUXProductLaunch $productLaunch
    $productLaunch = $null
    Start-Sleep -Milliseconds 800
    $gui.Refresh()
    if ($gui.HasExited) {
        # ⚠ Quiet では Write-Warning は誰にも届かない。
        #   GUI が出ないのは**起動できなかったのと同じ**なので、止めて知らせる。
        # ★知らせる箱より先に、この起動の控えを止める（RX-0170 / ⚠ 箱を閉じるまで待たせない）
        Stop-OwnDq2Backup
        Stop-Launcher -Message ("GUI が起動直後に終了しました。`n`n" +
            "ログに原因が残っています。") -Detail $script:RetroUXLogPath
    }

    # --- 6. エミュレータ ---------------------------------------------
    if (-not $NoEmulator) {
        $env:RETROUX_ROOT = $Root
        # ★映像倍率を user_config から読み、起動前に fceux.cfg へ書く。
        #   ⚠ --xscale は効かない（実測）。窓倍率は winsizemulx/y が制御する。
        # ★DQ2 の場所（ROM・FCEUX・fceux.cfg）を 1 か所から受け取る（RX-0146）。
        #   ⚠ 以前は ROM も FCEUX も固定で、dq2_user_config.yaml の paths.rom / paths.fceux が FCEUX の起動に効かなかった。
        #   ★JSON は ASCII（日本語や空白を含む場所でもコンソールの文字コードに左右されない）。
        $launch = $null
        try {
            $launchOut = (& $python -m retroux.core.dq2_paths --launch-json) 2>$null
            if ($LASTEXITCODE -eq 0 -and "$launchOut".Trim() -ne "") { $launch = ("$launchOut" | ConvertFrom-Json) }
        } catch { $launch = $null }
        if ($null -eq $launch) {
            Write-Note "DQ2 の場所を設定から決められませんでした。既定の場所（tools\fceux / work\rom）で起動します。"
        }
        # ★場所の設定に使えない文字（\f など）があれば、FCEUX を起こさずに理由を出して止める（RX-0168）
        #   ⚠ 以前はそのまま進み、FCEUX の起動で記録も箱も無く止まっていた（2026-10-05 実機）
        if ($null -ne $launch -and $launch.problems -and @($launch.problems).Count -gt 0) {
            Stop-Launcher -Message ("DQ2 の設定（dq2_user_config.yaml）の場所に、使えない文字があります。`n`n" +
                (@($launch.problems) -join "`n`n")) -Detail "dq2_user_config.yaml の paths"
        }
        try {
            # ★DQ2 専用の設定（dq2_user_config.yaml / 無ければ旧 user_config.yaml を読むだけ / RX-0147）
            $scaleOut = (& $python -c "from retroux.core.config.dq2_user_config import load; print(load()[0].emulator.window_scale)") 2>$null
            $scale = "$scaleOut".Trim()
            if ($scale -match '^\d+$' -and [int]$scale -ge 1) {
                if ($null -ne $launch) {
                    # ★fceux.cfg は DQ2 の FCEUX の隣（⚠ exe の隣にしか置けない / RX-0108）
                    # ⚠ exe が無いときは書かない（RX-0169 / ⚠ 以前は存在しない場所にフォルダごと作っていた）
                    if (Test-Path -LiteralPath $launch.fceux) {
                        & $python -m retroux.tools.fceux_scale $scale --cfg $launch.fceux_cfg | Out-Null
                    }
                } else {
                    & $python -m retroux.tools.fceux_scale $scale | Out-Null
                }
            }
        } catch { }
        $startArgs = @{ Root = $Root; Lua = $Lua }
        if ($null -ne $launch) {
            $startArgs["Fceux"] = $launch.fceux
            $startArgs["Rom"] = $launch.rom
        }
        # ★起動スクリプトの -Rom / -Fceux を明示したときは、そちらが勝つ（従来どおり）
        if ($Rom -ne "") { $startArgs["Rom"] = $Rom }
        if ($Fceux -ne "") { $startArgs["Fceux"] = $Fceux }
        Write-Step "FCEUX を起動します..."
        # ★旧 scripts\start.ps1 をこのファイルの関数へ取り込んだ（RX-0154）
        # ⚠ 失敗を黙らせない（RX-0169）: 以前は例外で記録も箱も無く終わり、画面だけが FCEUX を待っていた
        try {
            Start-Dq2Emulator @startArgs
        } catch {
            Stop-Launcher -Message ("FCEUX を起動できませんでした。`n`n" + $_.Exception.Message) -Detail ("FCEUX: " + $startArgs["Fceux"])
        }
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
    Write-Output ("  ログ   : " + $script:RetroUXLogPath)
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
    # ★RX-0170: GUI が立っていない・もう終わったまま抜けるなら、この起動の控えを止める
    #   （★Stop-Launcher の exit でもここを通る / ⚠ GUI が動いていれば GUI の後始末に任せる）
    $guiAlive = $false
    if ($null -ne $gui) {
        try { $gui.Refresh(); $guiAlive = -not $gui.HasExited } catch { $guiAlive = $false }
    }
    if (-not $guiAlive) { Stop-OwnDq2Backup }
    # ★製品間の順番待ちを手放す（★GUI の名札は GUI 自身が持つので、ここで離しても排他は続く）
    Exit-RetroUXProductLaunch $productLaunch
    if ($gotMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
