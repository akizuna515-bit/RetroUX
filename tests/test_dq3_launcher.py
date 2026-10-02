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
# ⚠ 2026-09-28（RX3-0459）: 旧 `DQ3.vbs` は退役しました（★入口は `DQ3.cmd`）。
#   ★この検査から `.vbs` への参照は無くなっています（下の `CMD` を見ます）。


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
    """★画面は作らずに、止める処理だけ借りる。

    ⚠⚠ **呼ぶたびに別のクラスを返します**（RX3-0479 / 2026-10-01）。
      ★`_stop_own_backup()` は 2 度目を黙って抜けるために
      `_backup_stop_signalled` を**自分へ**書きます。
      ⚠ ここで本体のクラスをそのまま返すと、1 つの検査が立てた印が
      ⚠⚠ **次の検査へ漏れて**「止めたつもり」で緑になります。
    """
    from dq3.ui.main_window import Dq3MainWindow

    return type("_StopProbe", (Dq3MainWindow,), {})


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
    """★札は**文字列として**探される。⚠ 書き方がずれたら見つからない。

    ⚠ 2026-09-28（RX3-0459）: 旧 `DQ3.vbs` の `InStr` を見ていた部分を外しました
      （★VBS は退役）。⚠ `json.dumps` の書き方そのものは**読む側が居るので残します**
      （`dq3/ui/main_window.py` の `_stop_own_backup`）。
    """
    import json

    body = json.dumps({"running": True, "session": "dq3-20260829-201530"})
    needle = '"session": "dq3-20260829-201530"'
    assert needle in body, "⚠⚠ json の区切りが変わった（★読む側も直すこと）"
    src = MAIN.read_text(encoding="utf-8")
    assert "_stop_own_backup" in src, "⚠ 札を読む側が無い"


def test_終了の道から呼ばれている():
    """⚠ 実装があっても**呼ばれていなければ**意味が無い。"""
    src = MAIN.read_text(encoding="utf-8")
    i = src.index("def quit_all")
    j = src.index("def _stop_own_backup")
    assert "self._stop_own_backup()" in src[i:j], (
        "⚠⚠ `quit_all` から呼んでいない")


# --- ★★ ⚠⚠ 閉じる 4 つの道（RX3-0479 / 2026-10-01）★★ ----------------

def test_窓のxでも控えに終わってもらう():
    """★★ ⚠⚠ **これが 2026-09-30 の実機の症状** ★★

    ```text
    ① 「終」ボタン      `quit_all()`  → ★前から呼んでいた
    ② 窓の ×           `closeEvent`  → ⚠⚠ **呼んでいなかった**
    ③ 外から WM_CLOSE   `closeEvent`  → ⚠⚠ 同じ（★控えの pythonw が残った）
    ④ launcher / FCEUX 側            → ⚠ Qt を通らない（★launcher の仕事）
    ```

    ★② と ③ は `closeEvent` という**同じ合流点**を通ります。
    ⚠ だからそこで呼べば 2 つ同時に直ります。
    """
    src = MAIN.read_text(encoding="utf-8")
    i = src.index("def closeEvent")
    body = src[i:]
    assert "self._stop_own_backup()" in body, (
        "⚠⚠ `closeEvent` から呼んでいません"
        "（★窓の × と外からの WM_CLOSE で控えが残ります）")
    # ⚠ 窓の位置を覚える**前**に合図を置く（★閉じる処理の途中で落ちても止まる）
    assert body.index("self._stop_own_backup()") < body.index(
        "self.save_window_positions()")


def test_2度呼んでも記録が二重にならない(tmp_path, monkeypatch):
    """★「終」ボタンは `quit_all` と `closeEvent` の**両方**を通ります。"""
    from dq3 import savestate_backup as SB

    cls = _window()
    monkeypatch.setenv(cls.SESSION_ENV, "dq3-テスト-1")
    log = tmp_path / "note.log"
    monkeypatch.setattr(SB, "WARN_LOG", log)
    lock = _status_with(tmp_path, "dq3-テスト-1")

    assert cls._stop_own_backup(cls, lock) is True
    assert cls._stop_own_backup(cls, lock) is True       # ★2 度目
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "⚠ 記録が二重になっています: %r" % lines
    assert "合図を置きました" in lines[0]


@pytest.mark.parametrize("case,session,make_status,expect", [
    ("札が無い", None, True, "この起動の札が不明"),
    ("状態ファイルが無い", "dq3-1", False, "状態ファイルが無い"),
    ("別の起動のもの", "dq3-1", "retroux-別", "別の起動のものです"),
])
def test_静かに抜けずに理由を1行残す(tmp_path, monkeypatch, case, session,
                                     make_status, expect):
    """⚠⚠ **3 つの道すべてが静かに False を返していました**（RX3-0479）。

    ★そのため「止めようとして駄目だった」と「止める相手が居なかった」を
    ⚠ あとから区別できませんでした。→ ★記録に 1 行出します。
    """
    from dq3 import savestate_backup as SB

    cls = _window()
    if session is None:
        monkeypatch.delenv(cls.SESSION_ENV, raising=False)
    else:
        monkeypatch.setenv(cls.SESSION_ENV, session)
    log = tmp_path / "note.log"
    monkeypatch.setattr(SB, "WARN_LOG", log)

    if make_status is True:
        lock = _status_with(tmp_path, session or "dq3-1")
    elif make_status is False:
        lock = tmp_path / "savestate_backup.lock"
    else:
        lock = _status_with(tmp_path, make_status)

    assert cls._stop_own_backup(cls, lock) is False
    assert not (tmp_path / "savestate_backup.stop").exists(), (
        "⚠⚠ 止めてはいけない道で合図を置きました")
    body = log.read_text(encoding="utf-8")
    assert expect in body, "⚠ 理由が記録に出ていません（%s）: %r" % (case, body)


def test_失敗しても閉じることは続ける(tmp_path, monkeypatch):
    """⚠ 後始末で例外が出ても、★`False` を返して**黙らない**。"""
    from dq3 import savestate_backup as SB

    cls = _window()
    monkeypatch.setenv(cls.SESSION_ENV, "dq3-1")
    log = tmp_path / "note.log"
    monkeypatch.setattr(SB, "WARN_LOG", log)
    _status_with(tmp_path, "dq3-1")

    class _Boom:
        def with_suffix(self, _s):
            raise OSError("⚠ わざと")

        @property
        def parent(self):
            return tmp_path

    monkeypatch.setattr("retroux.core.backup_status.status_path",
                        lambda _lock: tmp_path / "savestate_backup.status.json")
    assert cls._stop_own_backup(cls, _Boom()) is False
    assert "控えの停止に失敗しました" in log.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# ★★ 入口から控えまでの道（RX3-0459 / 2026-09-28）
#
#   ⚠⚠ もとは `DQ3.vbs` が 3 択を出し、★［いいえ］／［キャンセル］は
#     **FCEUX を直接**起動していました（⚠ 控えは VBS 自身が立てていた）。
#
#   ★いまは入口が 1 本です。
#
#     DQ3.cmd → scripts/start-dq3.ps1 → 控え → FCEUX
#
#   ⚠ だから守るべきことは 1 つに減りました:
#     ★**FCEUX を直接起動する入口を作らない**（＝控えを飛ばす道を作らない）。
# ----------------------------------------------------------------------

CMD = ROOT / "DQ3.cmd"


def _cmd_code() -> list:
    """⚠ コメントを落とす（★説明に書いてあるだけで通さない）。"""
    body = CMD.read_bytes().decode("ascii")
    return [line.strip() for line in body.splitlines()
            if line.strip() and not line.strip().lower().startswith("rem")]


def test_入口は起動スクリプトを通る():
    """★控えは `start-dq3.ps1` が立てる（⚠ 上の検査 2 本が固定している）。"""
    want = "scripts\\start-dq3.ps1"
    assert any(want in line for line in _cmd_code()), (
        "⚠⚠ 入口が起動スクリプトを呼んでいない")


def test_入口はFCEUXを直接起動しない():
    """⚠⚠ **これが今回いちばん守りたいこと。**

    ★FCEUX を直接起動する道を作ると、⚠ 控えを立てずに遊び始められてしまう
      （★旧 `DQ3.vbs` の「遊びモード」「そのまま遊ぶ」がまさにそれでした）。
    """
    bad = [line for line in _cmd_code()
           if "fceux" in line.lower() or ".nes" in line.lower()]
    assert not bad, (
        "⚠⚠ 入口が FCEUX を直接起動している（★控えを飛ばせる）: %s" % bad)


def test_入口が消えていない():
    assert CMD.exists(), "⚠⚠ DQ3 のダブルクリックの入口が無い"


# ----------------------------------------------------------------------
# RX3-0478 — ⚠⚠ `Select-Object -First 1` の後の `$LASTEXITCODE` は当てにならない
#
#   ★2026-09-30 の実機確認で起きたこと:
#
#     $fceux = (& $python -m dq3.paths --fceux 2>$null | Select-Object -First 1)
#     $fceuxFound = ($LASTEXITCODE -eq 0)
#           ↓
#     ⚠ 値は正しい（C:\Tools\... / Test-Path も True）のに $LASTEXITCODE が **-1**
#           ↓
#     ⚠⚠ 「FCEUX が見つかりません」の案内が**必ず**出て、起動できなかった
#
#   ★`-First` はパイプを途中で止めるので、PowerShell 5.1 は打ち切りを -1 で表します。
#     ⚠ `2>$null` は無関係（★どちらでも起きる / 実測）。
# ----------------------------------------------------------------------

def _powershell_or_skip():
    import shutil

    if shutil.which("powershell") is None:
        pytest.skip("⚠ PowerShell が無い環境")


def test_場所を聞く行でFirstと終了コードを同じ行に書かない():
    """⚠⚠ これが再発すると、★DQ3 は**1 度も起動できません**。"""
    lines = _text().splitlines()
    for i, line in enumerate(lines):
        if "Select-Object -First" not in line or "dq3.paths" not in line:
            continue
        near = " ".join(lines[i:i + 3])
        assert "$LASTEXITCODE" not in near, (
            "⚠⚠ %d 行目: `-First` でパイプを止めた直後に $LASTEXITCODE を見ています"
            "（★-1 になります）: %s" % (i + 1, line.strip()))


def test_場所を聞いた結果と終了コードを別々に受け取る():
    """★直したあとの形（⚠ 受け取り → 終了コード → 1 行目、の順）。"""
    text = _text()
    for name in ("fceux", "rom"):
        assert "@(& $python -m dq3.paths --%s" % name in text, (
            "⚠ --%s の結果を配列で受け取っていない（★`@(...)`）" % name)


def test_Firstを挟むと終了コードが当てにならないこと自体を実機で確かめる():
    """⚠ 字面の検査だけでは「なぜ駄目か」が失われます（★根拠を実行で残す）。

    ⚠⚠ ここで見るのは **PowerShell の挙動**です（★製品ではありません）。
      直したほうの形が「本当の終了コードを返す」ことが、★私たちが頼っている性質です。
    """
    import subprocess

    _powershell_or_skip()
    script = (
        "$ErrorActionPreference='Continue';"
        # ★直した形: 受け取り → 終了コード → 1 行目
        "$lines = @(cmd /c 'echo hello& exit 0');"
        "$fixed = $LASTEXITCODE;"
        "$head = ($lines | Select-Object -First 1);"
        # ⚠ 壊れた形: 同じ行で -First を挟む
        "$h2 = (cmd /c 'echo hello& exit 0' | Select-Object -First 1);"
        "$broken = $LASTEXITCODE;"
        "Write-Output \"fixed=$fixed broken=$broken head=$head\"")
    # ★★ ⚠ 壊れた形は**競争**です（RX3-0489 / 2026-10-02）★★
    #   `-First` がパイプを止めるより先に cmd が終わると、たまたま 0 が返ります。
    #   ⚠ 公開木の全件（xdist で並列 / 負荷が高い）で 1 回だけ `broken=0` になり、赤くなりました
    #     （★単独では 5 / 5 で `broken=-1`）。
    #   → ★「`-First` を挟むと**当てにならないことがある**」が言いたいことなので、
    #     ⚠ 数回試して 1 度でも 0 以外が出れば足ります（★1 度も出なければ前提が崩れた = 赤のまま）。
    for _attempt in range(5):
        got = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=120)
        assert got.returncode == 0, got.stderr[:300]
        out = got.stdout.strip()
        assert "fixed=0" in out, "⚠⚠ 直した形でも終了コードが取れない: %r" % out
        assert "head=hello" in out, "⚠ 1 行目が取れていない: %r" % out
        if "broken=0" not in out:
            break
    assert "broken=0" not in out, (
        "⚠ `-First` を挟んでも 0 が返るようになった（★PowerShell の挙動が変わった？）"
        "→ ⚠⚠ この WI の前提を見直してください: %r" % out)
