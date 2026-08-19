"""実プレイの1地点ぶんを採る道具（2026-08-02 / 依頼者の指示）。

★★ 守りたい契約 ★★

  1. ⚠ 読めなかった項目は **None**（0 と混ぜない）
  2. ⚠ トレースが取れなかったことを**黙らない**
  3. ★`capture_id` ごとのディレクトリへまとめられる
  4. ⚠ セーブステートは Lua から保存できないので、**手順で補う**
  5. ★揃い具合（同じ行・同じ列・偶奇4組）を出す
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.tools import dq2_map_capture as tool

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = PROJECT_ROOT / "research" / "probes" / "active" / "map_capture_probe.lua"


def _write(path, *, cid="001", map_id=63, x=21, y=31, trace=True):
    lines = [
        f"capture_id={cid}", "frame=1234", f"map_id={map_id}",
        "map_ptr_a=41139", "map_ptr_b=46118", f"x={x}", f"y={y}",
        "scroll_x=112", "scroll_y=192",
        "ram_0C_13=1C 00 FF 0F 26 B4 15 1F",
        "ram_1F=02",
        "ram_20_27=24 13 17 B3 A0 26 B4 5B",
        "ram_31=3F", "prg_bank=02", "terrain_id=1C",
        "-- 画面のマス",
        "cell=8,7,A1A5A0A4,3",
        "cell=9,7,A3A7A2A6,3",
        "-- trace",
    ]
    lines.append("trace=DF29 ptr=B426 acc=00 val=1C" if trace
                 else "trace=unavailable")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- 読み取り -----------------------------------------------------------

def test_採取データを読める(tmp_path):
    p = tmp_path / "capture-001.txt"
    _write(p)
    cap = tool.Capture.load(p)
    assert cap.capture_id == "001"
    assert cap.int_of("map_id") == 63
    assert cap.int_of("x") == 21
    assert cap.bytes_of("ram_20_27") == [0x24, 0x13, 0x17, 0xB3,
                                         0xA0, 0x26, 0xB4, 0x5B]
    assert cap.cells[(8, 7)] == ("A1A5A0A4", "3")


def test_読めない欄はNone(tmp_path):
    """⚠ 0 と 不明を混ぜない。"""
    p = tmp_path / "capture-001.txt"
    _write(p)
    cap = tool.Capture.load(p)
    assert cap.int_of("ない欄") is None
    assert cap.bytes_of("ない欄") is None


def test_トレースが無いことを黙らない(tmp_path):
    """⚠⚠ `memory.registerexec` が無い FCEUX もある。

    ★取れなかったことが**分かる形**で残る。
    """
    p = tmp_path / "capture-001.txt"
    _write(p, trace=False)
    cap = tool.Capture.load(p)
    assert cap.has_trace is False
    _write(p, trace=True)
    assert tool.Capture.load(p).has_trace is True


# --- 整理 ---------------------------------------------------------------

def test_capture_idごとにまとめる(tmp_path, capsys):
    _write(tmp_path / "capture-001.txt", cid="001")
    _write(tmp_path / "capture-002.txt", cid="002", x=22)
    (tmp_path / "capture-001.png").write_bytes(b"\x89PNG")
    assert tool.cmd_organize(tmp_path) == 0
    assert (tmp_path / "001" / "capture.txt").exists()
    assert (tmp_path / "001" / "capture.png").exists()
    assert (tmp_path / "002" / "capture.txt").exists()
    out = capsys.readouterr().out
    # ⚠ セーブステートは手で置く、と伝える
    assert "セーブステートは手で置いて" in out


def test_採取データが無ければ止まる(tmp_path, capsys):
    assert tool.cmd_organize(tmp_path) == 1
    assert "採取データがありません" in capsys.readouterr().out


# --- 揃い具合 -----------------------------------------------------------

def test_足りない組み合わせを黙らない(tmp_path, capsys):
    """★依頼者の狙い（行・列・偶奇4組）が揃っているかを出す。"""
    _write(tmp_path / "capture-001.txt", cid="001", x=20, y=30)
    _write(tmp_path / "capture-002.txt", cid="002", x=21, y=30)
    assert tool.cmd_compare(tmp_path) == 0
    out = capsys.readouterr().out
    assert "組足りません" in out, "★足りないことを言わないのは困る"


def test_4組そろえば言う(tmp_path, capsys):
    for i, (x, y) in enumerate([(20, 30), (21, 30), (20, 31), (21, 31)]):
        _write(tmp_path / f"capture-{i:03d}.txt", cid=f"{i:03d}", x=x, y=y)
    tool.cmd_compare(tmp_path)
    assert "4組そろっています" in capsys.readouterr().out


# --- Lua 側の約束 -------------------------------------------------------

def test_プローブがある():
    assert PROBE.exists()


def test_プローブは押しっぱなしで連射しない():
    """⚠ キーを押し続けて何十地点も採られると困る。★立ち上がりで見る。"""
    text = PROBE.read_bytes().decode("utf-8")
    assert "prev_keys" in text
    assert "not prev_keys.C" in text


def test_プローブはトレースが無くても続ける():
    """⚠ `memory.registerexec` が無い FCEUX でも、残りは採る。"""
    text = PROBE.read_bytes().decode("utf-8")
    assert "memory.registerexec == nil" in text
    assert "trace=unavailable" in text


def test_プローブは終われる():
    """⚠ 窓が残ると邪魔（2026-08-02 に依頼者が踏んだ）。"""
    text = PROBE.read_bytes().decode("utf-8")
    assert "os.exit(0)" in text


def test_プローブはセーブステートを保存しようとしない():
    """⚠⚠ `savestate.persist()` は FCEUX 2.6.6 をハングさせる。

    ★手順で補う（人が `File > Save State` する）。
    """
    import re

    text = PROBE.read_bytes().decode("utf-8")
    # ⚠ 注釈には `savestate.persist()` と書いてある（何を避けたかの記録）。
    #   ★コードだけ見る（2026-08-02、`@apply` のときと同じ罠）。
    code = re.sub(r"^\s*--.*$", "", text, flags=re.M)
    assert "savestate.persist" not in code
    assert "Save State" in text, "★手順を書いておくこと"


def test_プローブは必要な値を全部採る():
    """★依頼者が挙げた項目が漏れていないこと。"""
    text = PROBE.read_bytes().decode("utf-8")
    for key in ("map_id", "map_ptr_a", "map_ptr_b", "ram_0C_13", "ram_1F",
                "ram_20_27", "ram_31", "prg_bank", "terrain_id",
                "scroll_x", "cell=", "trace="):
        assert key in text, f"★{key} が採れていない"


# --- 起動スクリプト -----------------------------------------------------

SCRIPT = PROJECT_ROOT / "scripts" / "capture-map-points.ps1"


def test_起動スクリプトがある():
    r"""⚠⚠ 2026-08-02、私が案内した一行コマンドが壊れました:

        powershell -Command "$env:RETROUX_ROOT='...'; & '...fceux64.exe' ..."

    → 外側の PowerShell が `$env:RETROUX_ROOT` を**先に展開して消す**ため
      「'=F:\...' は認識されません」になりました。

    ★スクリプトにすれば起きません。**一行コマンドで案内しないこと。**
    """
    assert SCRIPT.exists()


def test_起動スクリプトはBOM付きUTF8():
    """⚠ PowerShell 5.1 は BOM 無しを cp932 として読み、日本語が壊れる。"""
    assert SCRIPT.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_起動スクリプトは絶対パスで渡す():
    """⚠ FCEUX は相対パスを**自分の場所**から探す。"""
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "Join-Path $Root" in text
    assert "-lua research" not in text


def test_起動スクリプトは遊んでいる最中に走らない():
    """⚠ FCEUX をもう1つ起こすと、遊んでいる画面を掴む。"""
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "Get-Process fceux64" in text


def test_起動スクリプトは終了コードを鵜呑みにしない():
    """⚠ FCEUX は os.exit(0) でも 255 を返すことがある。

    ★採れたファイルの数で判断する。
    """
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "capture-*.txt" in text
    assert "$made -eq 0" in text


def test_READMEが壊れる一行コマンドを載せていない():
    """★依頼者が同じところで詰まらないように。"""
    import re

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    for block in re.findall(r"```[a-z]*(.*?)```", readme, re.S):
        assert 'powershell -Command "$env:' not in block, (
            "★外側の PowerShell が $env: を展開してしまう形")


# --- ⚠⚠ 前に採ったぶんを消さない（2026-08-02 の教訓）------------------

def test_採取は前回ぶんを上書きしない():
    """⚠⚠ **2026-08-02、これで 21 地点ぶん失いました。**

    連番だけだと、次に走らせたとき `capture-001` から始まり、
    前回のディレクトリを上書きします。
    ★走らせるたびに違う札（`os.time()`）を付けます。
    """
    text = PROBE.read_bytes().decode("utf-8")
    assert "SESSION" in text
    assert "os.time()" in text
    assert 'SESSION .. "-"' in text, "★札を id の頭に付けること"


def test_採取idに札が入る(tmp_path):
    """★`<札>-<連番>` の形でも読める。"""
    p = tmp_path / "capture-1754130000-001.txt"
    _write(p, cid="1754130000-001")
    cap = tool.Capture.load(p)
    assert cap.capture_id == "1754130000-001"
    assert tool.cmd_organize(tmp_path) == 0
    assert (tmp_path / "1754130000-001" / "capture.txt").exists()
