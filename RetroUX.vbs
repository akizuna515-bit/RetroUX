' RetroUX 公開用ランチャー（2026-07-30 / リリース調整 仕様書 4.2）
'
' ★★ **一般利用者がダブルクリックする正式な入口。** ★★
'   PowerShell のウィンドウを**出さずに** scripts\start-retroux.ps1 -Quiet を呼ぶ。
'
' なぜ VBS か（仕様書 4.2 が VBS 方式を認めている）:
'   ・Windows に標準で入っている（追加の実行ファイルを配らなくてよい）
'   ・WScript.Shell の Run に「ウィンドウを隠す」指定がある（第2引数 0）
'   ・ショートカットの -WindowStyle Hidden は**一瞬ウィンドウが見える**ことがある
'
' 【注意】失敗を黙って捨てない（仕様書 5.1）。
'   ・PowerShell が見つからない -> ここでメッセージを出す
'   ・起動スクリプトが無い       -> ここでメッセージを出す
'   ・それ以降の失敗             -> start-retroux.ps1 がメッセージボックスを出す
'
' 開発・調査でコンソールを見たいときは Start-RetroUX-Console.cmd を使う。
'
' 【注意】【注意】**このファイルは cp932(Shift-JIS) で保存すること。**
'   Windows Script Host は .vbs を**既定で ANSI として読む**。
'   UTF-8 で保存すると日本語のバイト列が文字列の途中で切れて
'     「閉じていない文字列型の定数です」というコンパイルエラーになり、
'     **ダブルクリックしても何も起きない**（2026-07-30 に実測して発覚）。
'
'   ★実測（cscript で4通り試した結果）:
'     UTF-8 / BOM なし     -> NG（閉じていない文字列型の定数です）
'     UTF-8 / BOM あり     -> NG（無効な文字です / WSH は UTF-8 BOM 非対応）
'     cp932 / BOM なし     -> OK  ★これを採用
'     UTF-16LE / BOM あり  -> OK（ただし他の道具で扱いにくい）
'
'   【注意】`.ps1` は逆に **UTF-8 + BOM** が要る。拡張子ごとに違う。
'     他のファイルで使っている警告記号(U+26A0)は cp932 に無いので、
'     この中では【注意】と書く。

Option Explicit

Dim fso, shell, root, script, powershell, command, code
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' ★このファイルが置かれている場所をプロジェクトルートとする。
'   （作業ディレクトリに依存しない / 仕様書 4.2「作業ディレクトリをルートへ」）
root = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(root, "scripts\start-retroux.ps1")

If Not fso.FileExists(script) Then
    MsgBox "RetroUX を起動できませんでした。" & vbCrLf & vbCrLf & _
           "起動スクリプトが見つかりません:" & vbCrLf & script & vbCrLf & vbCrLf & _
           "RetroUX.vbs は、プロジェクトのフォルダの中に置いたまま使ってください" & vbCrLf & _
           "（ショートカットを作って、それをデスクトップに置くのは問題ありません）。", _
           vbCritical, "RetroUX"
    WScript.Quit 1
End If

' ★Windows PowerShell 5.1 の場所。★環境変数から組み立てる
'   （64bit / 32bit や Windows のフォルダ名の違いを吸収する）
powershell = fso.BuildPath(shell.ExpandEnvironmentStrings("%SystemRoot%"), _
                           "System32\WindowsPowerShell\v1.0\powershell.exe")
If Not fso.FileExists(powershell) Then
    MsgBox "RetroUX を起動できませんでした。" & vbCrLf & vbCrLf & _
           "Windows PowerShell が見つかりません:" & vbCrLf & powershell, _
           vbCritical, "RetroUX"
    WScript.Quit 1
End If

' 【注意】【注意】**引用符で囲む**（仕様書 4.2）。
'   フォルダ名に空白が入っていると、囲まないと別の引数として切れる。
'   実際「F:\My Projects\...」のような置き方は普通にある。
command = """" & powershell & """" & _
          " -NoProfile -ExecutionPolicy Bypass" & _
          " -File """ & script & """" & _
          " -Root """ & root & """" & _
          " -Quiet"

' ★第2引数 0 = ウィンドウを表示しない / 第3引数 True = 終わるまで待つ
'   【注意】待つ理由: 起動スクリプトが失敗したときの終了コードを見たいから。
'     待たないと、失敗しても VBS は「起動した」と思って終わる。
'   ★start-retroux.ps1 は GUI を起動したら**自分は終わる**作りなので、
'     ここで待っても遊んでいる間ずっと待つことにはならない。
On Error Resume Next
code = shell.Run(command, 0, True)
If Err.Number <> 0 Then
    MsgBox "RetroUX を起動できませんでした。" & vbCrLf & vbCrLf & _
           Err.Description, vbCritical, "RetroUX"
    WScript.Quit 1
End If
On Error Goto 0

' 【注意】失敗のメッセージは start-retroux.ps1 が既に出している。
'   ここで**二重に出さない**（同じことを2回言われると、
'   利用者は2つ別の問題が起きたと思う）。
WScript.Quit code
