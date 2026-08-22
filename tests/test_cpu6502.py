"""ROM のルーチンをそのまま動かす小さな 6502（2026-08-02）。

★★ **なぜ書いたか** ★★

  ⚠⚠ マップ展開ルーチンを手で Python へ写して**2回続けて誤りました**。
    手で写す限り、また間違えます。
  ★ならば**写さずに動かす**。実機の RAM（セーブステート）を初期状態に
    すれば、私の解釈は一切入りません。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import savestate
from retroux.core.bgmap.cpu6502 import Cpu, UnknownOpcode

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
STATES = PROJECT_ROOT / "tools" / "fceux" / "fcs"
_found = sorted(STATES.glob("DQ2_J*.fc[0-9]")) if STATES.exists() else []


def _readable(paths):
    """★**読めたものだけ**返す（RX-0100）。⚠ 「ある」と「読める」は別。"""
    got = []
    for p in paths:
        try:
            savestate.load(p)
        except Exception:                 # noqa: BLE001
            continue
        got.append(p)
    return got


_states = _readable(_found)

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
needs_state = pytest.mark.skipif(
    not _states, reason="読めるセーブステートが無い")


def _on_a_map(paths):
    """★マップ上のものだけ（RX-0100）。⚠ 世界地図・未読込は突き合わせられない。"""
    got = []
    for p in paths:
        map_id = savestate.load(p).byte(0x31)
        if map_id is not None and map_id not in (0x00, 0x01):
            got.append(p)
    return got


_ON_MAP = _on_a_map(_states)
#: ⚠ 1本あたり 49 か所しか試さないので、3本ないと 100 か所に届かない
needs_maps3 = pytest.mark.skipif(
    len(_ON_MAP) < 3,
    reason=f"マップ上のセーブステートが {len(_ON_MAP)} 本（3本必要）")


def _prg(code: bytes, at: int = 0xC000) -> bytes:
    """固定バンク（$C000-）に置いた 16KB を作る。"""
    bank = bytearray(0x4000)
    bank[at - 0xC000:at - 0xC000 + len(code)] = code
    return bytes(bank)


def test_足し算ができる():
    # LDA #$05 / CLC / ADC #$03 / STA $10 / RTS
    cpu = Cpu(_prg(b"\xA9\x05\x18\x69\x03\x85\x10\x60"), bytes(0x800))
    cpu.run(0xC000)
    assert cpu.ram[0x10] == 8


def test_分岐ができる():
    # LDA #$01 / CMP #$02 / BCS +2 / LDA #$FF / STA $10 / RTS
    cpu = Cpu(_prg(b"\xA9\x01\xC9\x02\xB0\x02\xA9\xFF\x85\x10\x60"),
              bytes(0x800))
    cpu.run(0xC000)
    assert cpu.ram[0x10] == 0xFF, "★桁上がりの判定が逆になっている"


def test_間接読みができる():
    ram = bytearray(0x800)
    ram[0x25], ram[0x26] = 0x00, 0xC1        # ★$25/$26 = $C100
    code = bytearray(b"\xA0\x02\xB1\x25\x85\x10\x60")   # LDY #2 / LDA ($25),Y
    bank = bytearray(0x4000)
    bank[0:len(code)] = code
    bank[0x100:0x104] = b"\xAA\xBB\xCC\xDD"
    cpu = Cpu(bytes(bank), bytes(ram))
    cpu.run(0xC000)
    assert cpu.ram[0x10] == 0xCC


def test_知らない命令で止まる():
    """⚠ 黙って飛ばして嘘の答えを出さない。"""
    cpu = Cpu(_prg(b"\x02"), bytes(0x800))
    with pytest.raises(UnknownOpcode):
        cpu.run(0xC000)


def test_回りすぎたら止まる():
    """⚠ 無限に回りうるループを残さない。"""
    cpu = Cpu(_prg(b"\x4C\x00\xC0"), bytes(0x800))   # JMP $C000
    with pytest.raises(RuntimeError, match="回りすぎ"):
        cpu.run(0xC000, limit=1000)


def test_JSRを横取りできる():
    """★バンク切替は本物を走らせず、ここで差し替える。"""
    class _Hook(Cpu):
        def on_jsr(self, target):
            self.hooked = target
            return True

    cpu = _Hook(_prg(b"\x20\x95\xFE\xA9\x07\x85\x10\x60"), bytes(0x800))
    cpu.run(0xC000)
    assert cpu.hooked == 0xFE95
    assert cpu.ram[0x10] == 7        # ★横取りしても続きが動く


# --- ★★ 本物と写しが一致するか ★★ ------------------------------------

@needs_rom
@needs_maps3
def test_写したデコーダは本物と同じ答えを返す():
    """★★ **これで「写し間違い」の疑いが消えました**（2026-08-02）。

    実機の RAM を初期状態にして `$E03C` をそのまま動かし、
    手で Python へ写した `terrain_at()` と突き合わせます。

    ⚠ 一致するのに画面と合わないなら、**写し間違いではなく
      追っているルーチンが違う**、ということになります。
    """
    from retroux.core.bgmap.rom_map import read_header, terrain_at
    from retroux.core.bgmap.rom_tiles import load_prg
    from retroux.core.bgmap.savestate import load

    class _MapCpu(Cpu):
        def on_jsr(self, target):
            if target in (0xFE95, 0xFE9A, 0xFE9F, 0xC2D0):
                self.bank = {0xFE95: 2, 0xFE9A: 3, 0xFE9F: 5}.get(
                    target, self.bank)
                return True
            return False

    from retroux.core.bgmap.savestate import NotASaveState

    prg = load_prg(ROM)
    checked = 0
    for path in _ON_MAP:      # ★使える物は先に数えてある
        st = load(path)
        header = read_header(prg, st.byte(0x31))
        for y in range(0, 20, 3):
            for x in range(0, 20, 3):
                cpu = _MapCpu(prg, st.ram, bank=2)
                cpu.ram[0x12], cpu.ram[0x13] = x, y
                cpu.run(0xE03C)
                assert cpu.ram[0x0D] == terrain_at(prg, header, x, y), (
                    f"{path.name} ({x},{y})")
                checked += 1
        if checked > 200:
            break
    assert checked > 100, f"★{checked} 件しか確かめていない"


@needs_rom
@needs_state
def test_E03Cは見た目のルーチンではない():
    """⚠⚠ **これが 2026-08-02 の結論**。

    本物を動かしても、街（map $0B）で返るのは**ほぼ全部 0**でした。
    画面には `$91` `$D9` `$94` `$C5` `$A1` `$F9` と多様な絵があるのに、です。

    ★呼び出し元を見ると:

        JSR $E03C / LDA $0D / CMP $1D / BNE …   （$1E649）
        JSR $E03C / LDA $0D / STA $1D           （$1E6F4）

      **前回の値と比べている** = 「変わったか」を見ている。
      ★`$E03C` が返すのは**地形の見た目ではなく、区分のような値**です。

    ⚠ 見た目を決めるルーチンは別にあります（未特定）。
    ★見た目が取れるようになったら、このテストを直して前へ進めること。
    """
    from retroux.core.bgmap.rom_map import read_header, terrain_at
    from retroux.core.bgmap.rom_tiles import load_prg
    from retroux.core.bgmap.savestate import load

    from retroux.core.bgmap.savestate import NotASaveState

    def _town(path):
        try:
            return load(path).byte(0x31) == 0x0B
        except NotASaveState:
            return False

    town = [p for p in _states if _town(p)]
    if not town:
        pytest.skip("街のセーブステートが無い")
    st = load(town[0])
    prg = load_prg(ROM)
    header = read_header(prg, 0x0B)
    px, py = st.byte(0x16), st.byte(0x17)
    values = {terrain_at(prg, header, px + dx, py + dy)
              for dy in range(-7, 3) for dx in range(-8, 8)}
    assert len(values) <= 2, (
        f"★街で {len(values)} 種類返るようになった（{sorted(values)}）。"
        "見た目が取れたのなら、この歯止めを外して前へ進めること")
