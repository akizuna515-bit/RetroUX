"""DQ3 の起動スクリプト（RX3-0022 / 2026-08-29）。

⚠⚠ ここは **起動スクリプトそのものは動かしません**（★人の環境で FCEUX が
  立ち上がってしまう）。中身が正しいかを字面で見ます。
  ⚠ だから「呼んでいる」以上のことは言えません。

★例外がひとつ: 札を作る**式だけ**は PowerShell に渡して動かします
（`test_札がPowerShellで実際に作れる`）。⚠ 字面だけだと、`Get-Date` の
書式が壊れていても気づけないためです。
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PS1 = ROOT / "scripts" / "start-dq3.ps1"
MAIN = ROOT / "dq3" / "ui" / "main_window.py"
VBS = ROOT / "DQ3.vbs"


def _text() -> str:
    import codecs

    raw = PS1.read_bytes()
    # ⚠⚠ BOM が要る。★PowerShell 5.1 は BOM 無しの .ps1 を cp932 として
    #   読むので、日本語コメントで構文エラーになる（`docs/50-playbook.md`）。
    assert raw[:3] == codecs.BOM_UTF8, "⚠⚠ BOM がありません"
    return raw.decode("utf-8-sig")


def test_世代バックアップを起動する():
    """⚠⚠ **これが無いと、上書きしたセーブステートは二度と戻らない。**

    ★実測（2026-08-29）: `work/savestate-backup/` の中身は 24 件すべて DQ2 で、
    ⚠ **DQ3 は 0 件**だった。仕組みは前からあるのに、ここが呼んでいなかった。
    """
    t = _text()
    assert "retroux.tools.savestate_backup" in t, (
        "⚠⚠ 世代バックアップを起動していない")
    assert "$NoBackup" in t, "⚠ 切る道が無い（★検証で困る）"


def test_ゲームを触る前に起動する():
    """⚠ 守りたいのは「上書きされた瞬間に元が消える」事故。

    ★FCEUX が立ち上がってからでは、⚠ 最初の 1 回を取り逃す。
    """
    t = _text()
    backup = t.index("retroux.tools.savestate_backup")
    fceux = t.index("Start-Process -FilePath $fceux")
    assert backup < fceux, "⚠⚠ FCEUX のほうが先に立ち上がっている"


def test_二重に動かさない():
    """⚠⚠ 2 つ動くと**世代が倍の速さで流れ**、戻りたい世代が押し出される。

    ★心拍のロックで見る（`retroux.tools.session status --what backup`）。
    ⚠ 確かめられなかったときは**起動しない**（★二重のほうが危ない）。
    """
    t = _text()
    assert "session status --what backup" in t, "⚠ ロックを見ていない"
    assert "BUSY" in t
    i = t.index("session status --what backup")
    tail = t[i:i + 900]
    assert "$LASTEXITCODE -ne 0" in tail or "$LASTEXITCODE -eq 0" in tail, (
        "⚠ 確かめられなかった場合を書いていない")


def test_この起動を見分ける札を渡す():
    """⚠ 「終」で**今回のぶんだけ**止めるために要る。"""
    t = _text()
    assert "--session" in t, "⚠ 札を渡していない"
    assert "RETROUX_DQ3_SESSION" in t


def test_札を実際に作っている():
    """⚠⚠ **名前が出てくるだけでは足りない。**

    ★2026-08-29: 代入する行が**入っていなかった**のに、
    ⚠ 「`RETROUX_DQ3_SESSION` が出てくる」だけを見る検査は緑だった。

    ⚠ 空のまま `--session` へ渡すと argparse が
    `error: argument --session: expected one argument` で落ち、
    ★pythonw なので**画面には何も出ないまま控えが起動しない**。
    """
    t = _text()
    assert "$env:RETROUX_DQ3_SESSION =" in t, (
        "⚠⚠ 札を**作る**行が無い（★参照しているだけ）")
    made = t.index("$env:RETROUX_DQ3_SESSION =")
    used = t.index('"--session", $env:RETROUX_DQ3_SESSION')
    assert made < used, "⚠ 使うほうが先にある"


def test_空の札では起動しない():
    """⚠ 空だと**黙って死ぬ**ので、★渡す前に止める。"""
    t = _text()
    assert "IsNullOrWhiteSpace($env:RETROUX_DQ3_SESSION)" in t, (
        "⚠⚠ 空のまま渡している")


def test_起動スクリプトの改行がすべてCRLF():
    """⚠ Python から書き足すと **LF だけの行**が混ざる（★実際に 39 行あった）。

    ⚠ PowerShell は通すが、⚠⚠ **こちらの置換が黙って空振りする**
    （★CRLF で探しているのに LF で書かれているため）。それで
    「入れたはずの行が入っていない」が起きた。
    """
    raw = PS1.read_bytes()
    crlf = raw.count(bytes((13, 10)))
    lf = raw.count(bytes((10,))) - crlf
    assert lf == 0, "⚠⚠ LF だけの行が %d 行ある" % lf


def test_札がPowerShellで実際に作れる():
    """★ファイルにある式を**そのまま動かして**、形を確かめる。

    ⚠ 字面だけだと、`Get-Date` の書式が壊れていても気づけない。
    """
    import re
    import shutil
    import subprocess

    if shutil.which("powershell") is None:
        pytest.skip("⚠ PowerShell が無い環境")
    t = _text()
    line = [L for L in t.splitlines()
            if L.startswith("$env:RETROUX_DQ3_SESSION =")][0]
    expr = line.split("=", 1)[1].strip()
    got = subprocess.run(["powershell", "-NoProfile", "-Command", expr],
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, "⚠ 式が動かない: %s" % got.stderr[:200]
    tag = got.stdout.strip()
    assert re.fullmatch(r"dq3-[0-9]{8}-[0-9]{6}-[0-9]+", tag), (
        "⚠⚠ 札の形が違う: %r" % tag)
    # ⚠ 空白が入ると `-join " "` で引数が割れる
    assert " " not in tag, "⚠⚠ 札に空白がある"


def test_終了は殺さずに合図する():
    """⚠⚠ **コピーの途中で殺すと、世代のほうが壊れる。**

    ★守るために作ったものが壊れては本末転倒なので、合図のファイルを置くだけ。
    """
    src = MAIN.read_text(encoding="utf-8")
    assert "_stop_own_backup" in src, "⚠ 止める道が無い"
    assert '.with_suffix(".stop")' in src, "⚠⚠ 合図ではなく別の止め方をしている"
    for bad in ("taskkill", "terminate()", "os.kill", "Process.kill"):
        assert bad not in src, "⚠⚠ %s で殺している" % bad


def test_他人の起動は止めない():
    """⚠⚠ DQ2 の起動と**同時に使う**ことがある。

    ★そちらのぶんを止めると、⚠ 相手は気づかないまま控えが残らなくなる。
    ⚠ 札が無いときは**何もしない**（★分からないときは触らない）。
    """
    src = MAIN.read_text(encoding="utf-8")
    assert 'got.get("session") != mine' in src, (
        "⚠⚠ 相手の札を確かめずに止めている")
    assert "if not mine:" in src, "⚠ 札が無いときに止めてしまう"
    # ⚠⚠ ロックには札が入らない（★見る先を間違えると 1 度も動かない）
    assert "holder.session" not in src, (
        "⚠⚠ ロックの札を見ている。★入るのは状態ファイルのほう")


@pytest.mark.parametrize("name", ["DQ3_J.fc0", "DQ3_J.fc9", "DQ3_J.fcs"])
def test_DQ3のセーブステートが見張りの対象になる(name):
    """★道具は DQ2 のものがそのまま使える（⚠ ゲームを問わない）。

    ⚠ ここが外れると、⚠⚠ **静かに 1 件も控えが残らない**
    （2026-08-29 まで実際にそうだった）。
    """
    import fnmatch

    from retroux.tools.savestate_backup import PATTERNS

    assert any(fnmatch.fnmatch(name, pat) for pat in PATTERNS), (
        "⚠⚠ %s が見張りの対象から外れている" % name)


def test_控えの置き場をDQ3も共有する():
    """⚠ 別の場所にすると、★`--list` と `--restore` が DQ3 を見つけられない。"""
    from retroux.tools.savestate_backup import DEFAULT_DST, DEFAULT_SRC

    assert DEFAULT_SRC.name == "fcs"
    assert (DEFAULT_SRC / "DQ3_J.fc0").parent == DEFAULT_SRC
    assert DEFAULT_DST.name == "savestate-backup"


# ----------------------------------------------------------------------
# ★★ 字面ではなく**動かして**見る（⚠ ここがこの WI の急所）
# ----------------------------------------------------------------------

def _status_with(tmp_path, session):
    """★控えが書く「状態ファイル」を 1 つ作る。

    ⚠⚠ **ロックではなく、こちら。** `savestate_backup.py` は
      `RecorderLock` を**札なしで**作るので（`savestate_backup.py:348`）、
      ⚠ ロックには `session` が入らない。
      ★2026-08-29 に、ここをロックで見ていたせいで
      **止める処理が 1 度も動いていなかった**。
    """
    import json

    (tmp_path / "savestate_backup.status.json").write_text(
        json.dumps({"running": True, "pid": 999999, "session": session}),
        encoding="utf-8")
    return tmp_path / "savestate_backup.lock"


def _window():
    """★画面は作らずに、止める処理だけ借りる。"""
    from dq3.ui.main_window import Dq3MainWindow

    return Dq3MainWindow


def test_札はロックではなく状態ファイルに入る():
    """⚠⚠ **ここを間違えて、止める処理が 1 度も動かなかった**（2026-08-29）。

    ★`savestate_backup.py` は `RecorderLock` に `session=` を渡していない。
    ⚠ だからロックの `session` は**いつも None**。
    ★札が入るのは `write_status(..., session=args.session)` のほう。

    ⚠ 検査が緑だったのは、**自分で札を書いたロック**を渡していたから。
    """
    import inspect

    from retroux.tools import savestate_backup

    src = inspect.getsource(savestate_backup.main)
    i = src.index("lock = RecorderLock(")
    j = src.index(")", src.index("consequence", i))
    assert "session" not in src[i:j], (
        "★ロックにも札が入るようになった。⚠ ならこの註釈を直すこと")
    writer = inspect.getsource(savestate_backup.write_status)
    assert "session=session" in writer or "session=session" in src, (
        "⚠ 状態ファイルへ札を書いていない")


def test_自分が立てたぶんは止める(tmp_path, monkeypatch):
    cls = _window()
    monkeypatch.setenv(cls.SESSION_ENV, "dq3-テスト-1")
    lock = _status_with(tmp_path, "dq3-テスト-1")

    assert cls._stop_own_backup(cls, lock) is True
    assert (tmp_path / "savestate_backup.stop").exists(), "⚠ 合図が置かれていない"


def test_他人が立てたぶんは止めない(tmp_path, monkeypatch):
    """⚠⚠ DQ2 の起動を止めると、★相手は気づかないまま控えが残らなくなる。"""
    cls = _window()
    monkeypatch.setenv(cls.SESSION_ENV, "dq3-テスト-1")
    lock = _status_with(tmp_path, "retroux-別の起動")

    assert cls._stop_own_backup(cls, lock) is False
    assert not (tmp_path / "savestate_backup.stop").exists(), (
        "⚠⚠ 他人の控えを止めてしまった")


def test_札が無ければ何もしない(tmp_path, monkeypatch):
    """★手で起動したもの／直接 `python -m dq3.ui.app` したとき。

    ⚠ 分からないときは触らない、が安全側。
    """
    cls = _window()
    monkeypatch.delenv(cls.SESSION_ENV, raising=False)
    lock = _status_with(tmp_path, "dq3-テスト-1")

    assert cls._stop_own_backup(cls, lock) is False
    assert not (tmp_path / "savestate_backup.stop").exists()


def test_一度も動いていなければ何もしない(tmp_path, monkeypatch):
    """⚠ 状態ファイルが無いのに合図だけ置くと、★次に立てたものが即座に止まる。"""
    cls = _window()
    monkeypatch.setenv(cls.SESSION_ENV, "dq3-テスト-1")

    assert cls._stop_own_backup(cls, tmp_path / "savestate_backup.lock") is False
    assert not (tmp_path / "savestate_backup.stop").exists()


def test_状態ファイルの札の書き方が一致している(tmp_path):
    """⚠⚠ VBS は**文字列として**札を探す。★書き方がずれたら見つからない。

    ★`DQ3.vbs` の `StopBackup` が `InStr` で探す並びと、
    ⚠ `json.dumps` が書く並び（コロンのうしろに空白）が一致していること。
    """
    import json

    body = json.dumps({"running": True, "session": "dq3-vbs-20260829-201530"})
    needle = '"session": "dq3-vbs-20260829-201530"'
    assert needle in body, (
        "⚠⚠ json の区切りが変わった。★`DQ3.vbs` の InStr も直すこと")
    t = VBS.read_bytes().decode("cp932")
    assert 'InStr(body, """session"": """ & tag & """")' in t, (
        "⚠ VBS の探し方が変わっている")


def test_終了の道から呼ばれている():
    """⚠ 実装があっても**呼ばれていなければ**意味が無い。"""
    src = MAIN.read_text(encoding="utf-8")
    i = src.index("def quit_all")
    j = src.index("def _stop_own_backup")
    assert "self._stop_own_backup()" in src[i:j], (
        "⚠⚠ `quit_all` から呼んでいない")


# ----------------------------------------------------------------------
# ★★ ショートカットから起動したとき（依頼者 2026-08-29）
#
#   ショートカット → wscript.exe → `DQ3.vbs` → 3 通り
#
#     ［はい］開発版      → `scripts/start-dq3.ps1`  ★控えはそちらが立てる
#     ［いいえ］遊びモード → FCEUX を直接           ⚠ ここが抜けていた
#     ［キャンセル］素で遊ぶ → FCEUX を直接         ⚠ 同上
#
#   ⚠⚠ **遊ぶモードにこそ控えが要る。** ★上書き保存やロード間違いは、
#     そのモードで起きる。
# ----------------------------------------------------------------------

def _vbs() -> str:
    return VBS.read_bytes().decode("cp932")


def test_遊ぶモードでも控えを立てる():
    t = _vbs()
    assert "retroux.tools.savestate_backup" in t, (
        "⚠⚠ ショートカットから遊ぶと控えが 1 件も残らない")
    assert "session = StartBackup()" in t, "⚠ 遊ぶ道から呼んでいない"


def test_ゲームを触る前に立てる():
    """⚠ FCEUX が動き出してからでは、★最初の 1 回を取り逃す。

    ⚠ 比べるのは**遊ぶモードの起動**（`shell.Run command, 1, True`）。
      ★開発版の分岐にも `shell.Run` があるが、そちらは
      `scripts/start-dq3.ps1` を呼ぶだけで、⚠ 控えはその中で立つ。
    """
    t = _vbs()
    assert t.index("session = StartBackup()") < t.index(
        "shell.Run command, 1, True"), "⚠⚠ FCEUX のほうが先"


def test_開発版は起動スクリプトに任せる():
    """⚠ VBS と ps1 の**両方**が立てると、★二重起動の判定に頼ることになる。

    ★開発版は `start-dq3.ps1` が札つきで立てる（⚠ 「終」で止められるように）。
    """
    t = _vbs()
    dev = t.index("start-dq3.ps1")
    play = t.index("session = StartBackup()")
    assert dev < play, "⚠ 並びが入れ替わっている"
    # ★開発版の分岐は、控えを立てずにそのまま終わる
    quit_at = t.index("WScript.Quit 0", dev)
    assert quit_at < play, "⚠⚠ 開発版でも VBS が控えを立てている（★二重）"


def test_FCEUXが閉じるまで待って合図する():
    """⚠ 待たずに終わると、★控えを止める相手が居なくなる。"""
    t = _vbs()
    assert "shell.Run command, 1, True" in t, (
        "⚠⚠ FCEUX の終了を待っていない（★第 3 引数が False）")
    assert "StopBackup session" in t, "⚠ 合図を置いていない"
    assert t.rstrip().endswith("StopBackup session"), (
        "⚠ FCEUX が閉じたあとで呼んでいない")


def test_控えを殺さない():
    """⚠⚠ コピーの途中で殺すと、★壊れた世代が「戻れる状態」の顔をして並ぶ。"""
    t = _vbs()
    assert "savestate_backup.stop" in t, "⚠ 合図のファイルを使っていない"
    for bad in ("taskkill", "Terminate", "TASKKILL"):
        assert bad not in t, "⚠⚠ %s で殺している" % bad


def test_控えが立たなくてもゲームは始まる():
    """★遊べないほうが困る（⚠ 控えが無いことは後で気づける）。"""
    t = _vbs()
    i = t.index("Function StartBackup()")
    j = t.index("End Function", i)
    body = t[i:j]
    assert "On Error Resume Next" in body, "⚠⚠ 失敗でゲームが始まらなくなる"
    assert "If Not fso.FileExists(pythonw) Then Exit Function" in body, (
        "⚠ Python が無い環境で止まる")


def test_VBSの改行がすべてCRLF():
    """⚠⚠ LF だけの行があると **Windows Script Host が構文で落ちる**。

    ★2026-08-29 に実際に 42 行を LF で書き込んでしまった
    （⚠ 見た目では気づけない）。
    """
    raw = VBS.read_bytes()
    crlf = raw.count(bytes((13, 10)))
    lf = raw.count(bytes((10,))) - crlf
    assert lf == 0, "⚠⚠ LF だけの行が %d 行ある" % lf


def test_VBSの入れ子がそろっている():
    """⚠ `End Function` の書き忘れは、★開いたときの構文エラーでしか出ない。"""
    import re

    lines = [L.strip() for L in _vbs().split(chr(13) + chr(10))]
    opens = {"Function": 0, "Sub": 0, "If": 0}
    closes = {"Function": 0, "Sub": 0, "If": 0}
    for line in lines:
        if line.startswith("'"):
            continue
        low = line.lower()
        if re.match(r"end[ ]+function$", low):
            closes["Function"] += 1
        elif re.match(r"end[ ]+sub$", low):
            closes["Sub"] += 1
        elif re.match(r"end[ ]+if$", low):
            closes["If"] += 1
        elif re.match(r"function[ ]+[A-Za-z_]", low):
            opens["Function"] += 1
        elif re.match(r"sub[ ]+[A-Za-z_]", low):
            opens["Sub"] += 1
        elif re.match(r"if[ ].*[ ]then$", low):
            opens["If"] += 1
    for key in opens:
        assert opens[key] == closes[key], (
            "⚠ %s の開き %d と閉じ %d が合わない"
            % (key, opens[key], closes[key]))
    assert opens["Function"] >= 1 and opens["Sub"] >= 1


# ----------------------------------------------------------------------
# ★★ 検査そのものが、遊んでいる人の控えを止めないこと
#
#   ⚠⚠ 2026-08-29 に実際に起きた:
#
#     20:29:44  依頼者がショートカットから起動 → 控えが立つ
#     20:30:41  ⚠⚠ 控えが止まった（running: false）
#     20:31:24  work/savestate_backup.stop が書かれていた
#
#   ★犯人は走っていた pytest。DQ2 の画面の `closeEvent` が、後始末で
#   **本物の** `work/savestate_backup.stop` を書く。
#   ⚠ 検査を回すたびに、守るはずの控えが黙って止まっていた。
# ----------------------------------------------------------------------

def test_検査中は本物のロックを掴まない():
    """★`conftest.py` が `backup_lock` を一時フォルダへ逃がしていること。

    ⚠ ここが外れると、⚠⚠ **検査を回すたびに人の控えが止まる**。
    ★止まったことは画面に出ないので、気づけるのは後から `--list` を見たとき。
    """
    from retroux.core.config.user_config import PathsConfig, UserConfig

    # ⚠ 利用者の `user_config.yaml` は**読まない**（★中身を決めつけない）。
    #   ★既定値の設定で `path()` を呼べば、逃がす仕掛けが効いているか分かる。
    got = UserConfig().path("backup_lock")
    # ★名前は変えない（⚠ この名前そのものを見る検査がある）
    assert got.name == pathlib.Path(PathsConfig().backup_lock).name
    assert ROOT not in got.parents and got.parent != ROOT / "work", (
        "⚠⚠ 本物の場所を掴んでいる: %s" % got)


def test_逃がす仕掛けがconftestにある():
    """⚠ 仕掛けが消えても、上の検査だけでは**理由**が分からない。"""
    src = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "backup_lock" in src, "⚠⚠ 逃がす仕掛けが消えている"
    assert "autouse=True" in src, "⚠ 自動で効く形になっていない"
