"""RAM解析ツールのテスト（MVP2 Phase 5 / 指示書の受入条件）。

受入条件:
  1. 戦闘前後の差分から候補を絞れる
  2. 解析結果を再利用可能な形で保存できる（CSV / YAML）
  3. 通常プレイ時は解析ログを無効化できる（→ battle_log.enabled / 既定オフの watch）

★偽のセーブステートを組み立ててテストする。利用者のセーブに依存しない
  （相手のデータが変わるとテストが落ちる、という形にしない）。
"""

from __future__ import annotations

import zlib

import pytest

from retroux.tools import ram as ram_mod
from retroux.tools import ramfind


def make_savestate(path, ram: bytes) -> None:
    """FCEUX 形式のセーブステートを作る（先頭16バイト + zlib）。"""
    body = b"RAM\x00" + len(ram).to_bytes(4, "little") + ram
    path.write_bytes(b"FCSX" + b"\x00" * 12 + zlib.compress(body))


@pytest.fixture
def fcs(tmp_path):
    d = tmp_path / "fcs"
    d.mkdir()
    base = bytearray(ram_mod.RAM_SIZE)
    base[0x100:0x104] = b"\x0a\x0f\x31\x5f"      # 変わらない値（名前のつもり）
    for i, hp in enumerate((30, 40, 50)):
        ram = bytearray(base)
        ram[0x200] = hp                          # スロットごとに変わる値
        make_savestate(d / f"DQ2_J.fc{i}", bytes(ram))
    return d


def test_read_savestate(fcs):
    snaps = ram_mod.load_all(fcs)
    assert len(snaps) == 3
    assert snaps[0].data[0x100] == 0x0A
    assert len(snaps[0].data) == ram_mod.RAM_SIZE


def test_broken_file_is_skipped_not_fatal(fcs):
    """★壊れたファイルで全部止めない（1枠だけ壊れていることがある）。"""
    (fcs / "DQ2_J.fc7").write_bytes("こわれている".encode("utf-8"))
    assert len(ram_mod.load_all(fcs)) == 3


def test_diff_finds_the_changed_address(fcs):
    snaps = ram_mod.load_all(fcs)
    d = ram_mod.diff(snaps[0], snaps[1])
    assert d == {0x200: (30, 40)}


def test_stable_finds_the_constant_run(fcs):
    """すべてのセーブで同値の区間（名前などを探すときの入口）。"""
    addrs = ram_mod.stable(ram_mod.load_all(fcs))
    assert 0x100 in addrs and 0x103 in addrs
    assert 0x200 not in addrs        # ここは動く


def test_value_command_narrows(fcs, capsys):
    """★受入条件1: 値の範囲で候補を絞れる。"""
    code = ramfind.main(["value", "--fcs", str(fcs), "--min", "30", "--max", "50",
                         "--start", "0x200", "--end", "0x200"])
    out = capsys.readouterr().out
    assert code == 0
    assert "$0200" in out


def test_value_excludes_when_one_save_fails(fcs, capsys):
    """1つでも条件を外れたら候補にしない（全件で成立するものだけ）。"""
    ramfind.main(["value", "--fcs", str(fcs), "--min", "30", "--max", "45",
                  "--start", "0x200", "--end", "0x200"])
    assert "$0200" not in capsys.readouterr().out


def test_csv_output(fcs, tmp_path, capsys):
    """★受入条件2: 再利用できる形で保存できる。"""
    csv_path = tmp_path / "out.csv"
    ramfind.main(["value", "--fcs", str(fcs), "--min", "30", "--max", "50",
                  "--start", "0x200", "--end", "0x200", "--csv", str(csv_path)])
    text = csv_path.read_text(encoding="utf-8")
    assert "addr_hex" in text and "$0200" in text


def test_yaml_output_is_candidate(fcs, capsys):
    """★候補は candidate で出す。「見つけた」と「確かめた」を混ぜない。"""
    ramfind.main(["value", "--fcs", str(fcs), "--min", "30", "--max", "50",
                  "--start", "0x200", "--end", "0x200", "--yaml"])
    out = capsys.readouterr().out
    assert "confidence: candidate" in out
    assert "addr: 0x0200" in out


def test_options_work_after_subcommand(fcs, capsys):
    """★道具は自然に書いた形で動いてほしい。

    argparse の既定では共通オプションをサブコマンドの後ろに置けず、
    `ramfind stable --start 0x100` が「知らない引数」で落ちていた。
    """
    code = ramfind.main(["stable", "--fcs", str(fcs), "--min-run", "3",
                         "--start", "0x100", "--end", "0x110"])
    assert code == 0
    assert "$0100" in capsys.readouterr().out


def test_table_search(tmp_path, capsys):
    """★受入条件1（ROM側）: N バイト刻みの表を条件で絞れる。"""
    prg = bytearray(4096)
    # 位置 100 から 5 バイト刻み。ID 1..10 の1バイト目に 10,20,30…
    for i in range(10):
        prg[100 + i * 5] = (i + 1) * 10
    rom = tmp_path / "fake.nes"
    rom.write_bytes(b"NES\x1a" + b"\x00" * 12 + bytes(prg))

    code = ramfind.main(["table", "--rom", str(rom), "--stride", "5",
                         "--count", "10", "--at", "3=30:30", "--at", "7=70:70"])
    out = capsys.readouterr().out
    assert code == 0
    assert "0x00064" in out          # 100 = 0x64
