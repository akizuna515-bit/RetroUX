"""戦闘中の敵を RAM から読む（RX3-0033 / 2026-08-31）。

## ⚠⚠ ここで直したこと

  `RX3-0021`（2026-08-29）には「HP は探したが RAM に見つからなかった」と
  書いてありました。⚠ **8 bit で探していた**のが原因です
  （★「8 が 4 つ並ぶ場所は 0 件」という観測そのものは正しかった）。

  ★手がかりは北米版の逆アセンブル（`work/dq3-disasm/disassembly/ram.inc`）::

      _enemy_HP:  .WORD 0,0,0,0,0,0,0,0     ; enemy current HP during battle

## ⚠ HP はゆらぐ

  ★ROM の値は**上限**（スライム 8 → 実際 5）。
  ⚠ だから「ROM と一致するか」では確かめられません（★`0 < いま <= ROM`）。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from dq3.knowledge import battle_runtime as BR

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"
BATTLE_FLAG = 0x62


@pytest.fixture(scope="module")
def profile():
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _battles():
    """★戦闘中のセーブ（⚠ 番号で名指ししない / `RX3-0028`）。"""
    from dq3_states import BATTLE, pick
    from retroux.core.bgmap import savestate as ss

    got = [(p, ss.load(p).chunks["RAM"]) for p in pick(BATTLE)]
    assert got, "⚠⚠ 戦闘中のセーブが 1 本もありません"
    return got


def test_群と体数が読める(profile):
    for path, ram in _battles():
        got = BR.read(ram, profile)
        assert got.groups, "⚠ 群が 1 つも取れていない（%s）" % path.name
        want = sum(g["n"] for g in got.groups)
        assert got.total == min(want, BR.SLOTS), (path.name, want, got.total)


def test_HPは16bitで体数ぶんだけ読む(profile):
    """⚠⚠ **体数より後ろには前の戦闘の値が残る**（★実測 fc3/fc4 で 6,6,6）。"""
    for path, ram in _battles():
        got = BR.read(ram, profile)
        assert all(f.hp > 0 for f in got.foes), (
            "⚠ HP が 0 の個体がいる（%s）" % path.name)
        # ★体数ぶんしか作っていないこと
        assert len(got.foes) == sum(g["n"] for g in got.groups)


def test_ROMのHPを超えない(profile):
    """★ROM の値は**上限**。⚠ DQ3 は HP をゆらす。"""
    if not ROM.exists():
        pytest.skip("⚠ ROM がありません")
    from dq2rom import ines
    from dq3rom import enemies, profile as P

    ident = P.identify(ines.load(ROM))
    cap = {e.enemy_id: enemies.wide(e.raw, 7) for e in enemies.read_all(ident)}
    checked = 0
    for path, ram in _battles():
        for f in BR.read(ram, profile).foes:
            top = cap.get(f.enemy_id)
            if top is None:
                continue
            assert 0 < f.hp <= top, (
                "⚠⚠ %s の #%d が ROM の上限を超えている（%d > %d）"
                % (path.name, f.slot, f.hp, top))
            checked += 1
    assert checked >= 5, "⚠ 確かめた個体が %d しかない（★空回り）" % checked


def test_生きている印が立っている(profile):
    """★`$80` が「生きている」（⚠ 逆アセンブルの `L - alive?`）。"""
    for path, ram in _battles():
        got = BR.read(ram, profile)
        assert got.alive == got.total, (
            "⚠ 戦闘中のセーブなのに死んでいる個体がある（%s）" % path.name)


def test_番地はprofileから引く():
    """⚠⚠ **番地を UI やロジックに直書きしない**（★指示書 §19）。"""
    import io

    src = io.open(ROOT / "dq3" / "knowledge" / "battle_runtime.py",
                  encoding="utf-8", newline="").read()
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "_addr(profile" in body, "⚠ profile から引いていない"
    # ★fallback は関数の既定値としてだけ出てよい
    assert body.count("0x0500") <= 1, "⚠ 番地が本文に散らばっている"


def test_RAMが短ければ断る(profile):
    with pytest.raises(BR.BattleRuntimeError):
        BR.read(b"\x00" * 16, profile)


def test_表からはみ出さない(profile):
    """⚠ 8 体を超える数が書いてあっても、★表の外を読まない。"""
    ram = bytearray(0x800)
    ram[0x056D] = 0
    ram[0x0571] = 99            # ⚠ ありえない数
    got = BR.read(bytes(ram), profile)
    assert got.total == BR.SLOTS, "⚠⚠ 表からはみ出している: %d" % got.total


# --- ⚠⚠ 番地の取り違えを見つける検査（2026-08-31 に足した）-------------------

def test_同じ種類でも個体ごとにHPが違う(profile):
    """★★ `$0500`（HP）と `$0520`（しゅび力）を**区別する**唯一の検査。 ★★

    ⚠⚠ 2026-08-31 まで `$0520` を HP と呼んでいた。しゅび力も
    「0 < 値 <= ROM の HP」を満たすので、★それだけでは気づけなかった。

    ★HP は個体ごとにゆらぐ。しゅび力は**種類ごとに一定**。
      → 「同じ種類が 3 体以上いて、値が 2 種類以上ある」セーブが 1 本でもあれば
        番地を取り違えていないと言える。
    """
    seen = []
    for path, ram in _battles():
        got = BR.read(ram, profile)
        by_id = {}
        for f in got.foes:
            by_id.setdefault(f.enemy_id, []).append(f.hp)
        for eid, hps in by_id.items():
            if len(hps) >= 3:
                seen.append((path.name, eid, hps))
    assert seen, "⚠ 同じ種類が 3 体いるセーブが無い（★この検査は空回り）"
    varied = [s for s in seen if len(set(s[2])) >= 2]
    assert varied, (
        "⚠⚠ 同じ種類の個体が**全部同じ値**でした。★HP ではなく "
        "しゅび力（$0520）を読んでいる疑いがあります: %s" % seen)


def test_全滅したセーブでは生きている印が落ちる(profile):
    """⚠ 状態の**2 バイト目**を見ていることを固定する。

    ★`$62 = 1`（戦闘の終わり）のセーブは HP が全部 0 になる。
      ⚠ そのとき 1 バイト目は `$80` のまま残るので、
      1 バイト目を見ていると「全員生きている」と答えてしまう。
    """
    from dq3_states import BATTLE_OVER, pick
    from retroux.core.bgmap import savestate as ss

    over = pick(BATTLE_OVER)
    checked = 0
    for path in over:
        ram = ss.load(path).chunks["RAM"]
        got = BR.read(ram, profile)
        checked += 1
        assert all(f.hp == 0 for f in got.foes), path.name
        assert got.alive == 0, (
            "⚠⚠ 全滅しているのに %d 体が生きている扱い（★状態の 1 バイト目を"
            " 見ていませんか）: %s" % (got.alive, path.name))
        assert any(f.status[0] & BR.ALIVE_BIT for f in got.foes), (
            "⚠ 1 バイト目まで落ちていると、この検査は何も見ていない: %s" % path.name)
    assert checked >= 1, "⚠ 戦闘の終わり際のセーブが 1 本も無い（★空回り）"

