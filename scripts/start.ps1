# RetroUX の起動スクリプト。
#
# ★ねらい: 起動直後のフォーカスを「エミュレータ本体のウィンドウ」へ移す。
#
# FCEUX を -lua 付きで起動すると「Lua Script」ウィンドウが前面に出てフォーカスを
# 取る。その状態で p（セーブステートのロード）などを押すと、
# スクリプトのファイル名入力欄に文字が入ってしまう（依頼者の報告）。
# FCEUX の設定（tools/fceux/fceux.cfg）に Lua ウィンドウを隠す項目は無いため、
# 起動側でフォーカスを移す。
#
# ⚠ Windows は「前面でないプロセスが勝手にフォーカスを奪うこと」を禁止している。
#   そのため **このスクリプトを自分のターミナルから実行する**必要がある
#   （そのターミナルが前面なら、その権利を使って切り替えられる）。
#   別プロセスから自動実行した場合は失敗しうるので、3つの方法を順に試し、
#   実際に移ったかを毎回確認する。
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Lua research\probes\active\hoimi_test.lua
#
# 検証用スクリプトを流すときにも使える（-Lua で差し替える）。

param(
    [string]$Root = "F:\Projects\260721_RetroUX",
    [string]$Lua = "retroux\emulator\fceux\run.lua",
    [string]$Rom = "work\rom\DQ2_J.nes",
    [int]$FocusTimeoutSeconds = 8
)

$ErrorActionPreference = "Stop"

$fceux = Join-Path $Root "tools\fceux\fceux64.exe"
# ★FCEUX へ渡すパスは絶対パスにする。
#   相対パスだとエラーも出ずに何も起きない（docs/50-playbook.md #7）
if ([System.IO.Path]::IsPathRooted($Lua)) { $luaPath = $Lua } else { $luaPath = Join-Path $Root $Lua }
if ([System.IO.Path]::IsPathRooted($Rom)) { $romPath = $Rom } else { $romPath = Join-Path $Root $Rom }

foreach ($p in @($fceux, $luaPath, $romPath)) {
    if (-not (Test-Path -LiteralPath $p)) { Write-Error "見つかりません: $p" }
}

$env:RETROUX_ROOT = $Root

Write-Output "起動します:"
Write-Output ("  FCEUX : " + $fceux)
Write-Output ("  Lua   : " + $luaPath)
Write-Output ("  ROM   : " + $romPath)

# パスは引用符付きで渡す（スペースを含む場合の分割を防ぐ / playbook #11）
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
