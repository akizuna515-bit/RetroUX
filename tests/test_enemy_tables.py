"""敵の表を ROM から読む（RX-0090 / 2026-08-21）。

★旧 memory_map.yaml の静的表（2026-07-26 抽出）と**全項目一致**することを、
  表を消す前に実測で確かめた（83体 × 名前/ステータス/行動、確率表、経験値表 3×49）。
  ここではその一致を「公開データ」と「構造の不変条件」で固定する。
  ⚠ 旧表そのものは repo に残さない（残すと RX-0090 の目的が消える）。
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from dq2rom import enemies, ines
from retroux.core import enemy_tables, text

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "work" / "rom" / "DQ2_J.nes"
MAP = ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml"

needs_rom = pytest.mark.skipif(not ROM.is_file(), reason="ROM が無い環境では読めない")

# 公開データ（極限攻略 FC版）。2026-07-26 の裏取りと同じ 11 体 × 6 耐性。
# 順: spell_damage, sleep, stopspell, defeat, defense_down, surround
PUBLISHED_RESIST = {
    0x01: (0, 0, 7, 0, 0, 0),      # スライム
    0x30: (7, 7, 7, 7, 7, 7),      # メタルスライム
    0x42: (7, 7, 7, 7, 7, 7),      # はぐれメタル
    0x4F: (4, 3, 7, 7, 4, 6),      # バズズ（ラリホーが効く = sleep 3）
    0x53: (0, 0, 4, 1, 0, 0),      # まもののむれ
}
PUBLISHED_NAMES = {0x01: "スライム", 0x02: "おおナメクジ", 0x30: "メタルスライム", 0x53: "まもののむれ"}
PUBLISHED_STATS = {0x01: dict(max_hp=6, gold=2, exp=1, agility=3, attack=8, defense=5)}


def _memory_map() -> dict:
    return yaml.safe_load(MAP.read_text(encoding="utf-8"))


# --- 純ロジック（ROM 不要）----------------------------------------------------

def test_memory_mapには敵の表が入っていない():
    """⚠ 公開物からゲームデータの複製を消すのが目的。戻ったら赤にする。"""
    mm = _memory_map()
    for key in enemy_tables.ENEMY_KEYS:
        assert key not in mm, f"{key} が memory_map.yaml に戻っている（RX-0090）"
    # 行動IDの**名前**（私たちが付けた訳語）だけは残る
    assert "monster_actions" in mm


def test_行動確率は表のしきい値から導く():
    prg = bytearray(enemies.NAMES_OFFSET + 0x400)
    table = [0x1F, 0x3F, 0x5F, 0x7F, 0x9F, 0xBF, 0xDF]      # 賢さ0 = 均等
    prg[enemies.RATES_OFFSET:enemies.RATES_OFFSET + 7] = bytes(table)
    rates = enemies.read_action_rates(bytes(prg))
    assert rates[0] == [12.5] * 8


def test_ドロップは落とさない敵にキーを作らない():
    prg = bytearray(enemies.NAMES_OFFSET + 0x400)
    prg[enemies.DROPS_OFFSET + 0] = 0xC0 | 0x3C      # ID1: 1/128 で 0x3C
    prg[enemies.DROPS_OFFSET + 1] = 0                # ID2: 無し
    prg[enemies.DROPS_OFFSET + 0x50] = 0x05          # ID 0x51 ハーゴン: 値があっても落とさない
    drops = enemies.read_drops(bytes(prg))
    assert drops == {1: {"item": 0x3C, "denominator": 128}}


def test_別のROMでは辻褄が合わず表を足さない(tmp_path):
    """⚠ 位置が合わない ROM から読んだ嘘の表を使わない。"""
    prg = bytes(0x20000)                                # 全部ゼロ = 何も合わない
    tables = enemies.read_all(prg)
    assert enemies.verify(prg, tables)                  # 問題が列挙される


def test_キャッシュの往復でintキーが戻る(tmp_path):
    tables = {
        "monsters": {1: "スライム"},
        "monster_stats": {1: {"max_hp": 6, "resist": {"sleep": 0}}},
        "monster_behavior": {1: {"wisdom": 1, "actions": [5, 0, 5, 0, 0, 0, 0, 0]}},
        "action_rates": {0: [12.5] * 8},
        "exp_to_level": {"lorasia": {2: 12, 3: 32}},
    }
    path = tmp_path / "enemy_tables.json"
    enemy_tables.write_cache(path, tables, "ABC")
    got = enemy_tables.read_cache(path)
    assert got == (tables, "ABC")
    assert isinstance(next(iter(got[0]["monsters"])), int)
    assert isinstance(next(iter(got[0]["exp_to_level"]["lorasia"])), int)


def test_ROMもキャッシュも無ければ何も足さない(tmp_path):
    mm = {"text": {}}
    out = enemy_tables.attach(mm, tmp_path / "missing.nes", tmp_path / "cache.json")
    assert all(k not in out for k in enemy_tables.ENEMY_KEYS)


def test_ROMが無くてもキャッシュがあればそれを使う(tmp_path):
    tables = {k: {} for k in enemy_tables.ENEMY_KEYS}
    tables["monsters"] = {1: "スライム"}
    path = tmp_path / "cache.json"
    enemy_tables.write_cache(path, tables, "X")
    got, why = enemy_tables.resolve(tmp_path / "missing.nes", {}, path)
    assert got["monsters"] == {1: "スライム"}
    assert "キャッシュ" in why


def test_壊れたキャッシュは無視する(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")
    assert enemy_tables.read_cache(path) is None
    path.write_text(json.dumps({"schema": 99, "tables": {}}), encoding="utf-8")
    assert enemy_tables.read_cache(path) is None


# --- 実ROM（ある環境だけ）-----------------------------------------------------

@needs_rom
def test_実ROMから83体が読め公開データと一致する():
    prg = ines.load(ROM).prg
    tables = enemies.read_all(prg)
    assert enemies.verify(prg, tables) == []
    st = tables["monster_stats"]
    assert len(st) == 83
    for mid, row in PUBLISHED_RESIST.items():
        assert tuple(st[mid]["resist"][k] for k in enemies.RESIST_KEYS) == row, hex(mid)
    for mid, expect in PUBLISHED_STATS.items():
        assert {k: st[mid][k] for k in expect} == expect
    assert "drop" in st[0x01] and "drop" not in st[0x51] and "drop" not in st[0x53]
    names = enemy_tables.decode_names(tables["monster_name_bytes"], text.from_memory_map(_memory_map()))
    assert len(names) == 83
    for mid, n in PUBLISHED_NAMES.items():
        assert names[mid] == n
    exp = tables["exp_to_level"]
    assert set(exp) == {"lorasia", "samaltria", "moonbrooke"}
    assert exp["lorasia"][2] == 12 and exp["lorasia"][5] == 140
    assert all(len(rows) == 49 for rows in exp.values())


@needs_rom
def test_実ROMでattachすると5表が足されキャッシュができる(tmp_path):
    mm = _memory_map()
    cache = tmp_path / "enemy_tables.json"
    out = enemy_tables.attach(mm, ROM, cache)
    assert all(k in out for k in enemy_tables.ENEMY_KEYS)
    assert out["monsters"][0x01] == "スライム"
    assert cache.is_file()
    # 2回目はキャッシュ
    _, why = enemy_tables.resolve(ROM, mm, cache)
    assert "キャッシュ" in why
