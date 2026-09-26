' DQ3 起動用ランチャー（2026-08-24 / RX3-0009、2026-08-29 に更新 / RX3-0019）
'
' 【注意】このファイルは **cp932(Shift-JIS) で保存すること**。
'   Windows Script Host は .vbs を常に ANSI として読むため、
'   UTF-8 で保存すると「閉じていない文字列型の定数です」で起動しない。
'   詳しくは RetroUX.vbs の冒頭の長い註を参照。
'   （警告記号(U+26A0)は cp932 に無いので、この中では【注意】と書く）
'
' ★このファイルは「DQ3 を始める」ための入口。
'   RetroUX 本体（DQ2 の公開版）には一切触らない。
'
' 【2026-08-29 の更新】
'   ここは長らく「Auto 戦闘 v0」と書きながら
'   collision の調査 probe を起動していた（表示と中身が食い違っていた）。
'   キーの説明も古く「Q キーで入り切り」のままだった（いまは A）。
'   → ［はい］を「開発版」に付け替え、scripts\start-dq3.ps1 に任せる。

Option Explicit

Dim fso, shell, root, fceux, rom, mode, lua, command, title, ps1
Dim pythonw, session

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

title = "DQ3"
root = fso.GetParentFolderName(WScript.ScriptFullName)
fceux = fso.BuildPath(root, "tools\fceux\fceux64.exe")
rom = fso.BuildPath(root, "work\rom\DQ3_J.nes")
ps1 = fso.BuildPath(root, "scripts\start-dq3.ps1")
pythonw = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")

' ---------------------------------------------------------------------
' セーブステートの世代バックアップを立てる。
'
' 【重要】遊ぶだけのモードにこそ要る。
'   上書き保存やロード間違いは、その瞬間に元が消える。
'   開発版は start-dq3.ps1 が立てるので、ここでは遊ぶモードだけ立てる。
'
' 【注意】2つ動くと世代が倍の速さで流れ、戻りたい世代が押し出される。
'   道具の側が心拍のロックで見て、二重なら自分から終わる。
'   だから、ここでは黙って呼んでよい。
'
' 【注意】失敗してもゲームは始める。控えが無いより、遊べないほうが困る。
Function StartBackup()
    StartBackup = ""
    If Not fso.FileExists(pythonw) Then Exit Function
    session = "dq3-vbs-" & Year(Now) & Right("0" & Month(Now), 2) & _
              Right("0" & Day(Now), 2) & "-" & Right("0" & Hour(Now), 2) & _
              Right("0" & Minute(Now), 2) & Right("0" & Second(Now), 2)
    On Error Resume Next
    ' 第2引数 0 = 窓を出さない / 第3引数 False = 待たない
    shell.Run """" & pythonw & """ -m retroux.tools.savestate_backup" & _
              " --session " & session, 0, False
    If Err.Number = 0 Then StartBackup = session
    On Error Goto 0
End Function

' 立てたぶんに「終わってください」と伝える。
'
' 【重要】殺さない。合図のファイルを置くだけ。
'   コピーの途中で殺すと、途中まで書けた世代が
'   「戻れる状態」の顔をして並ぶ。
'
' 【重要】自分が立てたぶんでなければ、何もしない。
'   DQ2 の起動と同時に使うことがある。そちらを止めると、
'   相手は気づかないまま控えが残らなくなる。
'   札は状態ファイル（savestate_backup.status.json）に入っている。
Sub StopBackup(tag)
    Dim stopPath, statusPath, body
    If tag = "" Then Exit Sub
    statusPath = fso.BuildPath(root, "work\savestate_backup.status.json")
    If Not fso.FileExists(statusPath) Then Exit Sub
    On Error Resume Next
    body = fso.OpenTextFile(statusPath, 1).ReadAll()
    On Error Goto 0
    ' 立てたときの札が入っていなければ、他人のもの。
    If InStr(body, """session"": """ & tag & """") = 0 Then Exit Sub
    stopPath = fso.BuildPath(root, "work\savestate_backup.stop")
    On Error Resume Next
    fso.CreateTextFile(stopPath, True).Write "stop"
    On Error Goto 0
End Sub

If Not fso.FileExists(fceux) Then
    MsgBox "FCEUX が見つかりません:" & vbCrLf & fceux, vbCritical, title
    WScript.Quit 1
End If
If Not fso.FileExists(rom) Then
    MsgBox "DQ3 の ROM が見つかりません:" & vbCrLf & rom & vbCrLf & vbCrLf & _
           "この場所に DQ3_J.nes を置いてください。", vbCritical, title
    WScript.Quit 1
End If

' ★何をするかを先に選ぶ。
mode = MsgBox( _
    "DQ3 をどう起動しますか？" & vbCrLf & vbCrLf & _
    "［はい］開発版（おすすめ）" & vbCrLf & _
    "  FCEUX と RetroUX の画面を一緒に開きます。" & vbCrLf & _
    "    A  自動戦闘の入り切り" & vbCrLf & _
    "    T  ターボの入り切り" & vbCrLf & _
    "    M  まんたん（全員回復）" & vbCrLf & _
    "  【注意】ゲームの A ボタンはキーボードの F です。" & vbCrLf & _
    "  【注意】戦術判断はしません。分からない画面では止まります。" & vbCrLf & vbCrLf & _
    "［いいえ］遊びモード（調査用の重ね表示）" & vbCrLf & _
    "  現在地・宝箱・扉を画面に重ねます。" & vbCrLf & vbCrLf & _
    "［キャンセル］そのまま遊ぶ（Lua なし）", _
    vbYesNoCancel + vbQuestion, title)

If mode = vbYes Then
    ' ★開発版は PowerShell に任せる（FCEUX と画面の 2 つを起動するため）。
    If Not fso.FileExists(ps1) Then
        MsgBox "起動スクリプトが見つかりません:" & vbCrLf & ps1, vbCritical, title
        WScript.Quit 1
    End If
    command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """"
    ' 第2引数 0 = 窓を出さない / 第3引数 False = 待たない
    On Error Resume Next
    shell.Run command, 0, False
    If Err.Number <> 0 Then
        MsgBox "DQ3 を起動できませんでした:" & vbCrLf & Err.Description, vbCritical, title
        WScript.Quit 1
    End If
    On Error Goto 0
    WScript.Quit 0
ElseIf mode = vbNo Then
    lua = fso.BuildPath(root, "research\probes\active\dq3_helper.lua")
Else
    lua = ""
End If

If lua <> "" And Not fso.FileExists(lua) Then
    MsgBox "Lua が見つかりません:" & vbCrLf & lua, vbCritical, title
    WScript.Quit 1
End If

' 【注意】パスは必ず引用符で囲む（フォルダ名の空白で引数が切れる）。
' 【注意】FCEUX の -lua は、相対パスだと exe の場所を探しに行く。
'   ここでは必ず絶対パスを渡す（2026-08-24 に実際に踏んだ）。
If lua = "" Then
    command = """" & fceux & """" & " " & """" & rom & """"
Else
    command = """" & fceux & """ -lua """ & lua & """" & " " & """" & rom & """"
End If

' セーブステートの世代バックアップを先に立てる。
'
' 【重要】遊ぶモードにこそ要る。ここが今まで抜けていた（2026-08-29）。
'   実測: work の savestate-backup の中身は 24 件すべて DQ2 で、DQ3 は 0 件。
'   ゲームを触り始めてからでは、最初の 1 回を取り逃す。
session = StartBackup()

' Lua 側が既定値に頼らないよう、プロジェクトの場所を環境変数で渡す。
shell.Environment("PROCESS")("RETROUX_ROOT") = root

' 第3引数 True = FCEUX が終わるまで待つ。
'
' 【注意】ここを待たないと、控えを止める相手が居なくなる。
'   この .vbs は wscript から呼ばれるので、待っても窓は出ない。
On Error Resume Next
shell.Run command, 1, True
If Err.Number <> 0 Then
    MsgBox "DQ3 を起動できませんでした:" & vbCrLf & Err.Description, vbCritical, title
    WScript.Quit 1
End If
On Error Goto 0

' FCEUX が閉じた。立てたぶんの控えに終わってもらう。
StopBackup session
