# DQ3 を起動する（RX3-0019 / 2026-08-29）。★開発環境と配布 Runtime（DQ3.cmd）の両方から呼ばれる。
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
# ★DQ3 は 1.1.0 で公開対象になりました（RX3-0431 / 配布 Runtime は RX3-0469〜0472）。
#   ⚠ 2026-10-02 訂正（RX3-0488）: ここには「DQ3 は dev-only です。公開しません（RX3-0011）」と
#     書いてありましたが、★配布 ZIP に入るこのファイルの説明として古くなっていました。

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    # ★画面を出さずに FCEUX だけ起動したいとき
    [switch]$NoUi,
    # ★FCEUX を出さずに画面だけ見たいとき（⚠ state.json は前回の値のまま）
    [switch]$NoEmulator,
    # ⚠ 設定 Lua の作り直しを飛ばす（★普段は飛ばさないこと）
    [switch]$SkipGenerate,
    # ⚠⚠ 初回の「旧版から引き継ぎますか」を出さない（★検査と撮影から使います）
    [switch]$NoMigrateOffer,
    # ★★ ⚠⚠ セーブステートの控えを起こさない（★2026-10-02 に**宣言を足した**）★★
    #
    #   ⚠⚠ 本文（`if (-not $NoBackup)`）は前からこの名前を見ていましたが、
    #     ★`param()` に**無かった**ので、
    #     ⚠ `-NoBackup` を付けても**黙って無視**されていました
    #       （★`[CmdletBinding()]` が無い .ps1 は知らない引数を `$args` へ捨てます /
    #        `docs/50-playbook.md` / `RX-0132`）。
    #     ⚠ 未宣言の変数は `$null` なので `-not $null` = 真 → ★控えは**必ず**起きていました。
    #   ★既定は今までと同じ（= 控えを起こす）。⚠ 変わるのは「切れるようになった」だけです。
    [switch]$NoBackup
)

$ErrorActionPreference = "Stop"

function Fail([string]$message, [string]$detail = "") {
    $text = $message
    if ($detail) { $text = "$message`n`n$detail" }
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show($text, "DQ3 RetroUX", "OK", "Error") | Out-Null
    exit 1
}

# ★★ ⚠⚠ 設定がまだ無いときは「雛形から作りますか」を聞く（RX3-0471）★★
#
#   ⚠ 配布 Runtime に `user_config.yaml` は**入っていません**（利用者のものなので）。
#     ★ROM / FCEUX を外に置く人は必ずこの状態から始めます。
#   ⚠⚠ 以前の案内は「user_config.yaml に場所を書く」だけで、
#     ★**そのファイルがまだ無い**ことに触れていませんでした（→ 次の一手が無い）。
#
#   ⚠ 判断と文は **Python 側**（`dq3/first_run.py`）に置いてあります。
#     ★ここは「聞いて、呼ぶ」だけです（⚠ .ps1 に判断を書くと検査しにくい）。
#   ⚠⚠ **勝手に作りません**（★人が「作る」を押したときだけ）。
function FailWithConfigOffer([string]$message, [string]$detail = "") {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    # ⚠ 設定がもう在れば、★今までどおりの案内だけ（= 場所が違うという話）
    & $python -m dq3.first_run --check | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail $message $detail }

    $hint = (& $python -m dq3.first_run --check 2>$null) -join "`n"
    $text = "$message`n`n$hint`n`n★いま雛形から作りますか？"
    $answer = [System.Windows.Forms.MessageBox]::Show(
        $text, "DQ3 RetroUX", "YesNo", "Warning")
    if ($answer -eq "Yes") {
        $made = (& $python -m dq3.first_run --create 2>&1) -join "`n"
        [System.Windows.Forms.MessageBox]::Show(
            $made, "DQ3 RetroUX", "OK", "Information") | Out-Null
    }
    exit 1
}

$lua    = Join-Path $Root "dq3\phase0\dev.lua"

# ★★ Python の場所は共通の resolver が決める（RX3-0473 / 2026-09-29）★★
#
#   ⚠⚠ 以前はここで `.venv\Scripts\python.exe` を直に組み立てていました。
#     ★配布 Runtime には `.venv` が無く、同梱の `runtime\python` を使います。
#   ⚠ 判定を各 launcher にコピーしないこと（★`Get-RetroUXPython` の 1 か所）。
. (Join-Path $PSScriptRoot "launcher-common.ps1")

$python  = Get-RetroUXPython -Root $Root
# ★黒い窓を出さない（⚠ 無ければ python.exe で代用される）
$pythonw = Get-RetroUXPython -Root $Root -Quiet

if (-not $python) {
    Fail "Python が見つかりません。" (Get-RetroUXPythonHint -Root $Root)
}
if (-not $pythonw) { $pythonw = $python }

# ★展開先が深すぎれば、何も始めずに理由を出して止める（RX3-0517 / ⚠ 深いと Qt が黙って止まる）
$depthProblem = Get-RetroUXDepthProblem -Python $python -Root $Root
if ($depthProblem) {
    Fail $depthProblem
}

# ★★ 製品間排他（RX3-0505 / 依頼者 2026-10-03「DQ2 / DQ3 の同時起動はサポートしない」）★★
#   ★DQ2 が動いていたら、設定・引き継ぎ・控え・FCEUX・画面の**どれも始めずに**理由を出して終わる。
#   ★ここは「早めに断る」ための 1 回目（⚠ 引き継ぎの窓を出す前）。
#   ★本当の判定は控えを起こす直前（下の 1. の前）で、起動の順番待ちを取ってからもう一度行う。
#   ⚠ FCEUX の有無では決めない（★他の用途の FCEUX・前回の残りを「DQ2 が起動中」と誤らない）。
$otherProduct = Get-RetroUXOtherProduct -Me "DQ3"
if ($otherProduct) { Fail (Get-RetroUXBusyMessage -Me "DQ3" -Other $otherProduct) }

# ★Lua 側が既定値に頼らないよう、場所を環境変数で渡す
#   ⚠ ROM / FCEUX の場所を聞く**前**に立てる（★書き先の判断に使う）
$env:RETROUX_ROOT = $Root

# ⚠ 日本語のパスが化けないように、先に出力の文字コードをそろえる（RX-0064 と同じ）
[Console]::OutputEncoding = [Text.Encoding]::UTF8

# ★★ ⚠⚠ **Python 側の出力も UTF-8 にする**（RX3-0470 / 2026-09-30）★★
#
#   ⚠ 実測: これが無いと、配布 Runtime で
#     `python -m dq3.ui.app --check` が
#     `UnicodeEncodeError: 'cp932' codec can't encode character '⚠'` で落ちます。
#   ★開発機では `PYTHONUTF8=1` が**常に立っている**ので出ませんでした
#     （⚠ `CLAUDE.md` の運用。★利用者の PC には立っていません）。
#   ⚠ 配布 Runtime 側には `sitecustomize.py` も入りますが、
#     ★`.venv` で動かす開発環境にはそれが無いので、**ここでも**立てます。
$env:PYTHONUTF8 = "1"

# ★★ ROM と FCEUX の場所は `dq3/paths.py` が決める（RX3-0467 / RX3-0468）★★
#
#   ⚠⚠ **固定配置を必須にしない。** 配布版は任意のフォルダに置かれ、
#     ★ROM も FCEUX も RetroUX の外にあるのが普通です。
#   ★解決の順番: user_config.yaml の paths.* → 従来の場所 → 見つからない。
#   ⚠ 見つからないと終了コード 1 と空行が返る（★でたらめな道は返らない）。
#   ⚠⚠ **`Select-Object -First 1` を同じ行に書かないこと**（RX3-0478 / 2026-09-30）。
#     ★`-First` はパイプを**途中で止める**ので、⚠ PowerShell 5.1 は
#     `$LASTEXITCODE` を **-1** にします（★コマンドが成功していても）。
#     → ⚠ 判定が常に偽になり、**FCEUX が見つかりません**の案内が必ず出ました。
#     ★受け取り（`@(...)`）と exit code を先に取り、⚠ 1 行目を選ぶのは**あと**。
# ★★ ⚠⚠ **引き継ぎの誘いは、設定チェックより先に出す**（RX3-0481 / 2026-10-02）★★
#
# ## ⚠⚠ 何が起きていたか（★実機で判明 / 2026-10-02）
#
#   ★利用者が ZIP を別のフォルダへ展開して `DQ3.cmd` を叩くと、
#   ⚠ 「旧版から引き継ぎますか？」ではなく
#   **「user_config.yaml を作りますか？」**が出ました。
#
#   ```text
#   ⚠ 誘いは `dq3/ui/app.py` の中にある（★メイン画面を作る直前）
#   ⚠⚠ ところがこの下の設定チェックが先にあり、見つからないと **exit 1**
#   → ★`dq3.ui.app` に**永久に到達しない**（誘いの条件は満たしていた）
#   ```
#
#   ⚠⚠ さらに、案内で［はい］を押して雛形を作ると、★そのあと引き継いでも
#   `user_config.yaml` が「既にある」で**飛ばされ**、⚠ 旧版の ROM / FCEUX の
#   場所が**引き継げません**（★`outcome` が「一部完了」になる / 実測）。
#
# ## ★直し方（依頼者 2026-10-02 の案 A）
#
#   ⚠ 順番を 1 つ入れ替えるだけです。★起動の構造は変えません（案 B は採らない）。
#
#   ```text
#   ① Python とルートを解決           ★済（上）
#   ② 必要なら**引き継ぎの窓だけ**出す  ★ここ
#   ③ 結果で続行 / 終了               ★下の switch
#   ④ ROM / FCEUX を**改めて**解決     ★②で引き継いだ設定が効く
#   ⑤ 足りなければ雛形の案内           ★今までどおり
#   ⑥ 生成・控え・FCEUX・画面          ★今までどおり
#   ```
#
#   ⚠⚠ **数字の意味は書き写しません。** 正本は `dq3/migrate.py` の `EXIT_*` で、
#     ★`tests/test_dq3_migrate_launcher.py` がこのファイルと突き合わせます。
$migrateHandled = $false
if (-not $NoMigrateOffer) {
    & $python -m dq3.ui.app --migrate-offer-only
    $migrateCode = $LASTEXITCODE
    switch ($migrateCode) {
        0  { $migrateHandled = $true }      # ★誘う必要がなかった（★そのまま続行）
        10 { $migrateHandled = $true }      # ★引き継ぎ完了（★下で設定を読み直す）
        11 { $migrateHandled = $true }      # ★引き継がず開始（★雛形の案内へ進む）
        12 {
            # ⚠ × / 取り消し → 今回の起動は終了。★次回も聞きます（覚えを書いていない）
            Write-Output "★引き継ぎの案内を閉じたので、今回は起動しません（⚠ 次回また聞きます）。"
            exit 0
        }
        13 {
            Fail "引き継ぎが一部しか終わらなかったので、起動しません。" (
                "★引き継ぎの窓に出た内容を確かめてください。`n" +
                "⚠ 旧版のフォルダはそのまま残っています。`n`n" +
                "★記録: " + (Join-Path $Root "work\runtime\dq3-log\migration.log"))
        }
        14 {
            Fail "引き継ぎに失敗したので、起動しません。" (
                "★引き継ぎの窓に出た内容を確かめてください。`n" +
                "⚠ 旧版のフォルダはそのまま残っています（★1 バイトも変えていません）。`n`n" +
                "★記録: " + (Join-Path $Root "work\runtime\dq3-log\migration.log"))
        }
        default {
            # ⚠⚠ **黙って通常起動へ進めません**（★何が起きたか分からないまま
            #   引き継げるはずのデータを置いていくことになります）
            Fail "引き継ぎの画面を開けませんでした。" (
                "★終了コード: " + $migrateCode + "`n`n" +
                "⚠ そのまま起動すると、旧版のデータを引き継げないまま始まります。`n" +
                "★次のコマンドの出力を見てください:`n" +
                "    python -m dq3.ui.app --migrate-offer-only")
        }
    }
}

$fceuxLines = @(& $python -m dq3.paths --fceux 2>$null)
$fceuxFound = ($LASTEXITCODE -eq 0)
$fceux = ($fceuxLines | Select-Object -First 1)
$romLines = @(& $python -m dq3.paths --rom 2>$null)
$romFound = ($LASTEXITCODE -eq 0)
$rom = ($romLines | Select-Object -First 1)

if (-not $NoEmulator) {
    if ((-not $fceuxFound) -or [string]::IsNullOrWhiteSpace($fceux) -or (-not (Test-Path -LiteralPath $fceux))) {
        FailWithConfigOffer "FCEUX が見つかりません。" (
            "★次のどちらかをしてください:`n`n" +
            "  1. user_config.yaml に場所を書く`n" +
            "       paths:`n" +
            "         fceux: `"C:/Emulators/FCEUX/fceux64.exe`"`n" +
            "       （★実行ファイルの名前まで書く / fceux.exe でも構いません）`n`n" +
            "  2. " + (Join-Path $Root "tools\fceux") + " に fceux64.exe を置く")
    }
    if ((-not $romFound) -or [string]::IsNullOrWhiteSpace($rom) -or (-not (Test-Path -LiteralPath $rom))) {
        FailWithConfigOffer "DQ3 の ROM が見つかりません。" (
            "★次のどちらかをしてください:`n`n" +
            "  1. user_config.yaml に場所を書く`n" +
            "       paths:`n" +
            "         dq3_rom: `"D:/ROM/DQ3_J.nes`"`n`n" +
            "  2. " + (Join-Path $Root "work\rom") + " に DQ3_J.nes を置く")
    }
    if (-not (Test-Path -LiteralPath $lua))   { Fail "Lua がありません:" $lua }
}

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
# ★clone しただけの環境には work/cache/dq3-monster-art が無く、図鑑と戦闘画面で絵が出ない。
#   そろっていれば数 ms で抜ける。⚠ 失敗しても起動は止めない（絵は表示だけ）。
# ⚠ 日本語が化けないように、先に出力の文字コードをそろえる（RX-0064 と同じ）。
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& $python -m dq3.tools.monster_art_setup

# --- 0. ★製品間排他（RX3-0505）: 起動の順番待ちを取ってから、もう一度 DQ2 を見る -----
#   ★ここから画面が名札を出すまで順番待ちを持つ（⚠ DQ2.cmd とほぼ同時に叩いても両方が通らない）。
#   ⚠ 引き継ぎの窓（上）は順番待ちの外（★人が考えている間、DQ2 の起動を待たせない）。
$productLaunch = Enter-RetroUXProductLaunch
if ($null -eq $productLaunch) {
    Fail "もう一方の RetroUX の起動が終わるのを待ちましたが、終わりませんでした。" "しばらくしてからもう一度起動してください。"
}
$otherProduct = Get-RetroUXOtherProduct -Me "DQ3"
if ($otherProduct) {
    Exit-RetroUXProductLaunch $productLaunch
    Fail (Get-RetroUXBusyMessage -Me "DQ3" -Other $otherProduct)
}

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
#
# ⚠⚠ **引き継ぎの案内を二度出しません**（RX3-0481 / 依頼者 2026-10-02 §3）。
#   ★上の段で誘いを処理したら、画面側では出しません。
#   ⚠ 覚え（`.migration-decision.json`）でも止まりますが、★窓が出ずに終わった
#     ときのために**明示的に**渡します（= 歯止めを 2 本にする）。
#   ★［管理］→「旧版からデータを引き継ぐ」は**いつでも**呼べます（⚠ ここは塞ぎません）。
if (-not $NoUi) {
    $uiArgs = @("-m", "dq3.ui.app")
    if ($migrateHandled) { $uiArgs += "--no-migrate-offer" }
    Start-Process -FilePath $pythonw -ArgumentList $uiArgs `
        -WorkingDirectory $Root
    # ★画面が製品の名札（RX3-0505）を出すまで、起動の順番待ちを持ったまま待つ
    if (-not (Wait-RetroUXProduct -Me "DQ3")) {
        Write-Output "  ⚠ 画面が製品の排他（RetroUX_Product_DQ3）を出すのを待ちきれませんでした。"
    }
}
# ★製品間の順番待ちを手放す（★画面の名札は画面自身が持つので、ここで離しても排他は続く）
Exit-RetroUXProductLaunch $productLaunch

Write-Output "起動しました。"
if (-not $NoBackup) {
    # ⚠⚠ ここを `retroux.tools.savestate_backup` に戻さないこと（RX3-0307）。
    #   ★`--restore` を既定の 10 世代で叩くと、たまった 90 世代が黙って消えます。
    Write-Output "  セーブステートの控え: python -m dq3.savestate_backup --list"
    Write-Output "  戻す:                 python -m dq3.savestate_backup --restore DQ3_J.fc0 --gen 3"
}
Write-Output "  A = 自動戦闘の入り切り / T = ターボ / M = まんたん"
Write-Output "  ゲームの A ボタンはキーボードの F です。"
