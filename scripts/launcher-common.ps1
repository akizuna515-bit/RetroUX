# 起動スクリプトの共通部品（2026-07-30 / リリース調整 仕様書 5章）。
#
# ★★ **公開用ではコンソールが見えない。** ★★
#   だから「Write-Error で終わり」は**利用者から見て「何も起きない」**。
#   仕様書 5.1:
#     > コンソール非表示時に以下が起きても、無反応に見せない。
#
# → 失敗は必ず次の3つを通す:
#
#     1. ログへ書く（あとから調べられる）
#     2. メッセージボックスを出す（いま気づける）
#     3. 終了コードを返す（呼んだ側が分かる）
#
# ⚠ スタックトレースは画面に出さない（仕様書 5.2）。ログへ。

# --- 出力（Quiet で黙る）---------------------------------------------

# 進捗の1行。★Quiet のときは**画面には出さないがログには出す**。
#   ⚠ ログにも出さないと、公開用で起動した経過が一切残らない。
function Write-Step {
    param([string]$Message)
    if (-not $script:RetroUXQuiet) { Write-Output $Message }
    Write-LauncherLog "INFO" $Message
}

# 警告。★Quiet でも**ログには必ず残す**。
function Write-Note {
    param([string]$Message)
    if (-not $script:RetroUXQuiet) { Write-Warning $Message }
    Write-LauncherLog "WARN" $Message
}

# --- ログ -------------------------------------------------------------

# 起動スクリプト自身のログ。★Python 側と**同じファイル**へ書く。
#   分けると、利用者に「どちらを見てください」と2つ案内することになる。
# ★ログへ出すパスを、プロジェクト直下からの相対にする（RX-0043 / 指示書 §26）。
#
# ⚠⚠ ログは GitHub の Issue などへ貼られる前提。絶対パスを出すと
#   **利用者名が混ざる**（ユーザープロファイル配下に置いた場合）。
#   ⚠ この開発環境では名前が出ておらず、★grep だけでは危険が見えない。
#
# ⚠ プロジェクトの外にあるパスは**そのまま返す**（★切ると意味が変わる）。
function Get-ShortPath {
    param([string]$Path)
    if (-not $Path) { return "" }
    if (-not $script:RetroUXRoot) { return $Path }
    $root = [System.IO.Path]::GetFullPath($script:RetroUXRoot)
    try { $full = [System.IO.Path]::GetFullPath($Path) } catch { return $Path }
    if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        # ⚠⚠ **`'\\'` は PowerShell では2文字**（★1文字ではない）。
        #   `TrimStart` は `[char[]]` を取るので、2文字の文字列は変換できず
        #   **例外で落ちる**。★2026-08-14 に実際に起動不能にした。
        #   → `[char[]]` を明示し、`"\\"` ではなく **char リテラル**を渡す。
        return $full.Substring($root.Length).TrimStart([char[]]@([char]92, [char]47))
    }
    return $Path
}

function Write-LauncherLog {
    param([string]$Level, [string]$Message)
    if (-not $script:RetroUXLogPath) { return }
    try {
        $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        # ★★ Python / Lua と**同じ並び**にする（RX-0044 / 2026-08-14）★★
        #
        #   ⚠⚠ 以前は段階が角括弧の**外**にあった。
        #     ★同じファイルに**3つ目の書式**があると、画面の段階絞り込み
        #     （main_window._show_in_gui）が**効かない**
        #     （段階を読めず「読めない行は出す」側へ倒れる）。
        #
        #       2026-08-14 08:39:27 INFO [launcher] ...   ← 旧
        #       2026-08-14 08:39:29 [INFO] console ...    ← Python
        #       2026-08-14 08:39:30 [INFO] lua ...        ← Lua
        $line = "$stamp [$Level] launcher $Message"
        # ⚠ 追記は**UTF-8で**。既定の ANSI で書くと日本語が化ける
        #   （README を全滅させたのと同じ形 / playbook）。
        Add-Content -LiteralPath $script:RetroUXLogPath -Value $line -Encoding utf8
    } catch {
        # ★ログに書けなくても起動は続ける（書けないこと自体は止める理由にならない）
    }
}

# --- メッセージボックス（仕様書 5.2）---------------------------------

# 失敗を利用者に見せる。★**公開用でも必ず出る**のがこの関数の役目。
#
# ⚠ `System.Windows.Forms` を読み込めない環境（Server Core など）でも
#   落ちないようにする。出せないなら**ログに書いて終わる**。
function Show-LauncherError {
    param(
        [string]$Message,
        [string]$Detail = ""
    )
    Write-LauncherLog "ERROR" ($Message + " " + $Detail)

    $body = "RetroUX を起動できませんでした。`n`n" + $Message
    if ($script:RetroUXLogPath) {
        $body += "`n`n詳細:`n" + $script:RetroUXLogPath
    }

    # ★コンソールがあるときは、そちらにも出す（開発時に見やすい）
    if (-not $script:RetroUXQuiet) { Write-Warning $body }

    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show(
            $body, "RetroUX",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch {
        # ⚠ ここで諦めても**ログには残っている**（上の Write-LauncherLog）。
        #   メッセージボックスが出せないことを理由に、原因の記録まで失わない。
        if (-not $script:RetroUXQuiet) {
            Write-Warning "メッセージボックスを出せませんでした（ログを見てください）。"
        }
    }
}

# 失敗して終わる。★**必ずこれを通す**（Write-Error で直接終わらない）。
function Stop-Launcher {
    param([string]$Message, [string]$Detail = "", [int]$Code = 1)
    Show-LauncherError -Message $Message -Detail $Detail
    exit $Code
}

# --- Python の出力（日本語）を受け取る（2026-08-22 / RX-0064）----------
#
# ⚠⚠ **PowerShell 5.1 は native exe の出力を [Console]::OutputEncoding で復号する。**
#   既定は cp932 なので、Python が UTF-8 で書いた日本語が化ける
#   （実測: 「最終心拍 0.4 秒前」→「譛邨ょｿ・牛 0.4 遘貞燕」）。
#   ★これまで捕捉していたのは BUSY / FREE（ASCII）だけだったので露見しなかった。
# ★UTF-8 に切り替えて捕捉し、必ず元へ戻す。
#   ⚠ コンソールが無い起動（Quiet）では設定できないことがあるので try で包む。
function Get-PythonText {
    param([string]$Python, [string[]]$Arguments, [string]$OutFile)
    # ★Python 側に `--out <file>` で UTF-8 のファイルを書かせ、こちらは
    #   **エンコーディングを明示して読む**。⚠ 標準出力を経由しない。
    #   （[Console]::OutputEncoding の差し替えは、コンソールが無い起動で
    #     効かないことを実測した / 2026-08-22）
    if (Test-Path -LiteralPath $OutFile) { Remove-Item -LiteralPath $OutFile -Force }
    & $Python @Arguments "--out" $OutFile 2>$null | Out-Null
    if (-not (Test-Path -LiteralPath $OutFile)) { return "" }
    $text = Get-Content -LiteralPath $OutFile -Encoding UTF8 -Raw
    Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
    if ($null -eq $text) { return "" }
    return $text.Trim()
}

# --- 実行ファイルの選び分け（仕様書 4.1）------------------------------

# GUI と常駐処理をどの exe で起動するか。
#
#   公開用（Quiet）: pythonw.exe … コンソールを作らない
#   開発用          : python.exe  … 標準出力が見える
#
# ⚠⚠ **pythonw.exe では標準出力・標準エラーが消える**（仕様書 4.1）。
#   だから Python 側で例外を必ずログへ書くこと。
#   `retroux/gui.py` と `retroux/tools/savestate_backup.py` はそうしてある。
function Get-PythonForGui {
    param([string]$Root, [switch]$Quiet)
    $pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if ($Quiet -and (Test-Path -LiteralPath $pythonw)) { return $pythonw }
    return (Join-Path $Root ".venv\Scripts\python.exe")
}

# ★★ **コンソールを作らせずにプロセスを起こす（2026-07-30 / R-1 の急所）** ★★
#
# ⚠⚠ **なぜ `Start-Process -WindowStyle Hidden` では駄目なのか。**
#
#   `-WindowStyle Hidden` は STARTUPINFO の `wShowWindow` に SW_HIDE を入れる。
#   これは**コンソールだけでなく、そのプロセスが最初に出す窓すべて**に効く。
#   Qt は最初の表示に SW_SHOWDEFAULT を使うため、この指定を**そのまま拾って
#   GUI の窓まで隠れる**（実測: `IsWindowVisible` が False。
#   プロセスは生きているのに画面に何も出ない＝黒い窓より悪い）。
#
# ★対して `CREATE_NO_WINDOW` は「コンソールを作らない」という指定で、
#   `wShowWindow` を触らない。だから **GUI の窓は普通に出る**。
#
# ⚠ なぜコンソールが作られるのか（uv の venv 固有）:
#     .venv\Scripts\pythonw.exe   ← uv のトランポリン（47KB）
#        └─ 起動するのは base の **python.exe**（コンソール版）
#             └─ conhost.exe が付いて窓が出る
#   ★`python.exe` と `pythonw.exe` が同じ 47104 バイト＝中身が同じ。
#     つまり **pythonw を選んだだけでは足りない**。
#
# ⚠ `Start-Process` に `CREATE_NO_WINDOW` を渡す方法は無いので、
#   .NET の `ProcessStartInfo` を直に使う。
function Start-NoConsole {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = ""
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    # ⚠ 空白を含む引数は囲む（`F:\My Projects\...` のような置き方があるため）
    $quoted = foreach ($a in $Arguments) {
        if ($a -match '\s') { '"' + $a + '"' } else { $a }
    }
    $psi.Arguments = ($quoted -join " ")
    if ($WorkingDirectory -ne "") { $psi.WorkingDirectory = $WorkingDirectory }
    # ★この2つが揃って初めて CREATE_NO_WINDOW になる
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    return [System.Diagnostics.Process]::Start($psi)
}
