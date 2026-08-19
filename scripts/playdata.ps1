# 遊んだ記録を退避して、まっさらから始める（2026-08-03 / 依頼者の要望）。
#
# ★★★ **利用者のデータを消すので、必ず確認してから動きます。** ★★★
#
# ⚠⚠ **消さないもの**
#   ・ROM
#   ・ゲームのセーブステート
#   ・解析の採取データ
#
# ⚠ 「最初からやる」のはゲーム側の話です。ここが消すのは
#   **RetroUX が貯めた記録**（歩いたマス・戦闘・図鑑）だけです。
#
# 使い方:
#   .\scripts\playdata.ps1 status    いま何があるか見る（★何も変えない）
#   .\scripts\playdata.ps1 backup    退避する（★消さない）
#   .\scripts\playdata.ps1 clear     退避してから消す（★まっさらに）
#   .\scripts\playdata.ps1 list      退避の一覧
#   .\scripts\playdata.ps1 restore 20260803-0930
#
# ⚠ -DryRun を付けると、数えるだけで何もしません。

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("status", "backup", "clear", "list", "restore")]
    [string] $Command,

    [Parameter(Position = 1)]
    [string] $Name,

    [string] $Label,

    [switch] $DryRun
)

$ErrorActionPreference = "Stop"

# ★このスクリプトの1つ上がプロジェクトの場所
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "✗ Python が見つかりません: $python" -ForegroundColor Red
    Write-Host "  ★先に .venv を作ってください。"
    exit 1
}

$callArgs = @("-m", "retroux.tools.playdata", $Command)
if ($Name) { $callArgs += $Name }
if ($Label) { $callArgs += @("--label", $Label) }

# ⚠⚠ 消す前に必ず確認する（★status と list は聞かない）
$destructive = @("clear", "restore")

if ((-not $DryRun) -and ($destructive -contains $Command)) {
    Write-Host ""
    Write-Host "=== ★まず、何が起きるか見せます ===" -ForegroundColor Cyan
    Push-Location $root
    try { & $python @callArgs } finally { Pop-Location }

    Write-Host ""
    if ($Command -eq "clear") {
        Write-Host "⚠⚠ 上の記録を消します。" -ForegroundColor Yellow
        Write-Host "★消す前に自動で退避します（work の playdata-archive）。"
        Write-Host "⚠ ROM とセーブステートは消えません。"
    }
    else {
        Write-Host "⚠⚠ いまの記録が上書きされます。" -ForegroundColor Yellow
        Write-Host "★上書きする前に、いまの状態も自動で退避します。"
    }
    Write-Host ""
    $answer = Read-Host "本当に実行しますか？ (yes と入力)"
    if ($answer -ne "yes") {
        Write-Host "★やめました。何も変えていません。" -ForegroundColor Green
        exit 0
    }
    $callArgs += "--apply"
}
elseif ((-not $DryRun) -and ($Command -eq "backup")) {
    # ★退避は何も消さないので、確認なしで実行してよい
    $callArgs += "--apply"
}

Push-Location $root
try {
    & $python @callArgs
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Host "⚠ うまくいきませんでした（終了コード $code）" -ForegroundColor Red
}
exit $code
