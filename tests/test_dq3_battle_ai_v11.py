"""戦闘 AI v1.1 — 戦況を**正しく見る**ための入力（2026-09-09）。

```text
C  押す直前の legality check          RX3-0134
B  味方の状態を ctx へ（★分からないは nil）RX3-0135
D  敵の行動 64 種 → 抽象分類            RX3-0136
F  耐性: ダメージは倍率 / 状態は確率      RX3-0137
E  支援の効き目は ROM の表に無い          RX3-0138
14 実機カバレッジ                      RX3-0139
```

⚠⚠ **v1.1 は「戦術を増やす版」ではありません。** ★見える情報を増やす版です。
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rom() -> bool:
    from dq3.knowledge import spell_info as SI

    return SI.available()


# --- ★D 敵の行動（RX3-0136）--------------------------------------------

def test_行動64種がすべて分類できる():
    """⚠ 分類漏れがあると、★その敵は静かに「何もしてこない」ことになります。"""
    from dq3.battle_ai import generate as G
    from dq3rom import enemy_detail as ED

    for name in ED.MOVE_CATEGORY:
        assert name in G.ACTION_CLASS, "⚠ 分類の抜け: %s" % name
    assert set(G.ACTION_CLASS) == set(ED.MOVE_CATEGORY), "⚠ 余分な分類がある"


def test_敵139体の行動に未知が無い():
    if not _rom():
        pytest.skip("ROM が読めません")
    from dq3.battle_ai import generate as G
    from dq3.knowledge import rom_names as RN
    from dq3rom import enemies as EN
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    ident = P.load_and_identify(RN.DEFAULT_ROM)
    rows = EN.read_all(ident)
    details = ED.read_all(rows)
    assert len(details) >= 100
    unknown = sum(G._actions_summary(d)["unknown"] for d in details)
    assert unknown == 0, "⚠ 分類できない行動が %d 件" % unknown


def test_回復する敵と全体攻撃の敵が見分けられる():
    """★手で敵の表を作らないための検査（⚠ ROM から出た旗であること）。"""
    if not _rom():
        pytest.skip("ROM が読めません")
    from dq3.battle_ai import generate as G
    from dq3.knowledge import rom_names as RN
    from dq3rom import enemies as EN
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    ident = P.load_and_identify(RN.DEFAULT_ROM)
    got = [G._actions_summary(d) for d in ED.read_all(EN.read_all(ident))]
    heals = sum(1 for s in got if s["heal"])
    wide = sum(1 for s in got if s["party_attack"])
    status = sum(1 for s in got if s["status"])
    assert 0 < heals < len(got), "⚠ 回復する敵が全員 / 誰も居ない: %d" % heals
    assert 0 < wide < len(got), "⚠ 全体攻撃の敵が全員 / 誰も居ない: %d" % wide
    assert 0 < status < len(got), "⚠ 状態を掛ける敵が全員 / 誰も居ない: %d" % status


def test_生成物に敵の行動が載っている():
    """⚠⚠ 「Python では分かる」と「Lua まで届く」は別のこと。"""
    got = ROOT / "work" / "generated" / "dq3_ai.lua"
    if not got.exists():
        pytest.skip("生成物がありません")
    text = got.read_text(encoding="utf-8")
    assert "acts" in text and "party_attack" in text and "per_turn" in text


# --- ★F 耐性（RX3-0137）-----------------------------------------------

def test_ダメージ耐性は倍率で状態耐性は確率():
    """⚠⚠ v1 は**同じ表**を使っていました（★呪文が効かないと誤って見捨てた）。"""
    from dq3rom import enemy_detail as ED

    # ★ROM の 2 つの表（★どちらも `RX3-0039` が確定したもの）
    assert ED.RESIST_PERCENT == (100, 70, 30, 0), "★状態は確率"
    assert ED.DAMAGE_SCALE == (0xFF, 0xCC, 0x99, 0x80), "★ダメージは倍率"
    lua = (ROOT / "dq3" / "phase0" / "ai" / "catalog.lua").read_text(encoding="utf-8")
    assert "Catalog.DAMAGE_SCALE" in lua and "damage_scale" in lua
    for want in ("0.8", "0.6", "0.5"):
        assert want in lua, "⚠ 倍率 %s が入っていない" % want


def test_攻撃呪文は効く確率で見ている():
    """★RX3-0267: 攻撃呪文は効く / 効かない の二択（JP bank 4 `$A4BF`〜`$A4DE` / RX3-0266 の実機で確認）。

    ⚠⚠ RX3-0137 は「ダメージは倍率（段 3 でも 50% 通る）」と見ていた = 誤り（★倍率表を使うのはブレスだけ）。
    ★見込み = 呪文の耐性（系統ごと）の効く確率 × ダメージ。
    """
    src = (ROOT / "dq3" / "phase0" / "ai" / "actions.lua").read_text(encoding="utf-8")
    body = src.split("function Actions.spell_effect")[1].split("\nfunction ")[0]
    assert "rate_for(cat, grp, s.resist)" in body, "⚠ 呪文の耐性の確率で見ていない"
    assert "damage_scale" not in src, "⚠⚠ 攻撃呪文を倍率で見る道が残っている"
    from dq3rom import spells as SP

    # ★JP `$A4BF`: 0〜8 炎 / 9〜12 氷 / 13〜15 風 / 16〜17 雷
    assert [SP.RESIST_FIELD[s] for s in (0, 8, 9, 12, 13, 15, 16, 17)] == [
        "damage_reduction", "damage_reduction", "ice_spells", "ice_spells",
        "wind_spells", "wind_spells", "lightning_spells", "lightning_spells"]


def test_支援の耐性はROMの呪文表から取る():
    """⚠ ルカニに `damage_reduction` を当てていた手置きを消したこと。"""
    src = (ROOT / "dq3" / "phase0" / "ai" / "actions.lua").read_text(encoding="utf-8")
    assert "s.resist" in src, "⚠ 呪文の resist を使っていない"
    assert 'field = "damage_reduction"' not in src, "⚠⚠ 誤った手置きが残っている"
    from dq3rom import spells as SP

    assert SP.RESIST_FIELD.get(34) == "sleep", "★ラリホーは sleep 耐性"
    # ★RX3-0266 で確定（JP `$A81B LDA #$08` / 実機で 240 回）→ RX3-0267 で入れた
    assert SP.RESIST_FIELD.get(43) == SP.RESIST_FIELD.get(44) == "sap", "⚠ ルカニ・ルカナンは耐性 8（sap）"


# --- ★E 支援の効き目（RX3-0138）---------------------------------------

def test_支援呪文の効き目はROMの表に無い():
    """★「手置きを消せなかった理由」を記録として固定する。

    ⚠⚠ 威力・回復量の表はあるのに、★支援・妨害・即死は 1 件も数字を持ちません。
      → ⚠ 実測（実機）でしか出せない。★憶測で数字を作らない。
    """
    if not _rom():
        pytest.skip("ROM が読めません")
    from dq3.knowledge import rom_names as RN
    from dq3rom import profile as P
    from dq3rom import spells as SP

    ident = P.load_and_identify(RN.DEFAULT_ROM)
    prg = ident.rom.prg if hasattr(ident.rom, "prg") else bytes(ident.rom)
    rows = SP.read_all(prg)
    soft = [s for s in rows if s.kind in ("buff", "debuff", "instant")]
    assert soft, "⚠ 支援・妨害の呪文が 1 件も無い"
    assert all(s.base is None for s in soft), (
        "★ROM に数字が入った！ ⚠ 手置きの倍率を消せるはず: %r"
        % [s.effect for s in soft if s.base is not None])
    hard = [s for s in rows if s.kind in ("attack", "heal")]
    assert any(s.base is not None for s in hard), "⚠ 威力の表まで読めていない"


def test_手置きの倍率だと分かるように書いてある():
    src = (ROOT / "dq3" / "phase0" / "ai" / "actions.lua").read_text(encoding="utf-8")
    body = src.split("Actions.SUPPORT_EFFECTS")[0][-1400:]
    assert "目安" in body and "base = None" in body, "⚠ 未確定であることが書いていない"


# --- ★B 状態異常（RX3-0135）-------------------------------------------

def _profile() -> dict:
    import json

    return json.loads((ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                      .read_text(encoding="utf-8"))


def test_確かめた旗だけをLuaへ渡す():
    """⚠⚠ **推測の旗を置かない。** ★置くと、裏の取れていない読み方で人を外します。"""
    flags = _profile()["runtime"]["party"]["status_flags"]
    assert {f["confidence"] for f in flags.values()} == {"confirmed"}, (
        "⚠ 確かめていない旗が置いてある: %r"
        % {k: v["confidence"] for k, v in flags.items() if v["confidence"] != "confirmed"})
    for want in ("alive", "poisoned", "paralyzed"):
        assert want in flags, "⚠ %s が無い" % want
    # ★★ まひ は RX3-0252（2026-09-13）で確定して**わざと**置いた（ROM のコード $A09F / $8F37 と save7）。
    #   ★依頼者「RX3-0252 推奨案でOK」→ 戦闘 AI（roles.lua / legality.lua）も まひ を見始める（RX3-0135 の残り）
    # ⚠ 眠り・混乱は**まだ分からない**（★推測を置かない / NEED-FIXTURE）
    for gone in ("asleep", "confused"):
        assert gone not in flags, "⚠⚠ 確かめていない %s を置いている" % gone

    from dq3.phase0 import generate_lua as GL

    got = GL._party(_profile())
    assert set(got["status_flags"]) == set(flags), "⚠ 渡す旗が profile と食い違う"


def test_毒は上位バイトのbit5():
    """★2026-09-09 実測（RX3-0135）。⚠ 北米版から推測した**バイトが違っていた**。"""
    row = _profile()["runtime"]["party"]["status_flags"]["poisoned"]
    assert (row["byte"], row["bit"]) == (1, 5), (
        "⚠⚠ 毒の場所が変わっている: byte=%s bit=%s（★実測は 上位バイトの bit5）"
        % (row["byte"], row["bit"]))
    assert row["confidence"] == "confirmed"


def test_毒のfixtureで2人だけ毒と読める():
    """⚠ 依頼者の『スロット 0 は毒が 2 名』と、★読んだ数が合うこと。"""
    from dq3.testing import fixtures as FX

    if not FX.MANIFEST.exists():
        pytest.skip("fixture がまだありません")
    try:
        fx = FX.get("battle_ai_poisoned_party")
    except FX.FixtureError:
        pytest.skip("毒の fixture がまだありません")
    assert fx.expected["party_poisoned"] == 2, (
        "⚠ 毒の人数が合わない: %r" % fx.expected.get("party_poisoned"))
    assert fx.expected["party_count"] == 4
    now = FX.conditions_of(fx.path)
    assert now["party_poisoned"] == 2, "⚠ 読み直すと数が違う"


def test_毒のビットは健康なセーブで1度も立たない():
    """★1244 件の候補を 1 件に絞った対照（⚠ 1 本のセーブでは番地を決められない）。"""
    _never_set_in_healthy_saves("poisoned", "毒")


def test_まひは上位バイトのbit6():
    """★RX3-0252（2026-09-13 依頼者「save7 まひを満タンで直したい。まんげつそう or キアリク」）。

    ★ROM のコードで確かめた: bank 0 $A09F が `$073D,X AND #$40` → `AND #$BF` で落とす（まんげつそう $B27B から）/
      戦闘側 bank 4 $8F37 が `ORA #$40` でまひにする。⚠ 毒（bit5）と同じ上位バイトの隣のビット。
    """
    row = _profile()["runtime"]["party"]["status_flags"]["paralyzed"]
    assert (row["byte"], row["bit"]) == (1, 6), (
        "⚠⚠ まひの場所が変わっている: byte=%s bit=%s（★ROM は 上位バイトの bit6）"
        % (row["byte"], row["bit"]))
    assert row["confidence"] == "confirmed"
    assert "$A09F" in row.get("evidence", ""), "⚠ 根拠（ROM のコード）が書かれていない"


def test_まひのビットは健康なセーブで1度も立たない():
    """★RX3-0252: 立つのは まひ の人だけ（⚠ 健康なセーブで立てば、読み方が違う）。"""
    _never_set_in_healthy_saves("paralyzed", "まひ")


def _never_set_in_healthy_saves(name: str, label: str) -> None:
    """★健康なセーブ（`work/tests/savestates`）で、その旗が 1 度も立たないこと。"""
    from retroux.core.bgmap import savestate as ss

    row = _profile()["runtime"]["party"]["status_flags"][name]
    base, size = 0x073C, 2
    mask = 1 << int(row["bit"])
    seen = 0
    for path in sorted((ROOT / "work" / "tests" / "savestates").glob("DQ3_J*")):
        try:
            ram = ss.load(path).chunks["RAM"]
        except Exception:                              # noqa: BLE001
            continue
        for i in range(4):
            hp_max = ram[0x0724 + i * 2] + ram[0x0725 + i * 2] * 256
            if not 0 < hp_max <= 999:
                continue                               # ⚠ 居ない枠 / 壊れた記録
            seen += 1
            got = ram[base + i * size + int(row["byte"])]
            assert not (got & mask), (
                "⚠⚠ 健康なはずのセーブで%sのビットが立っている: %s p%d = %02X"
                % (label, path.name, i + 1, got))
    if seen < 20:
        pytest.skip("対照に使えるセーブが足りません（%d 枠）" % seen)


def test_状態を読む道がつながっている():
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert "PARTY.status_flags" in lua and "m.status = st" in lua
    roles = (ROOT / "dq3" / "phase0" / "ai" / "roles.lua").read_text(encoding="utf-8")
    assert "Roles.blocked_by" in roles
    assert "st.paralyzed == true" in roles, "⚠ `== true` でないと nil を真に取る"


def test_未観測と否定を混ぜていない():
    """★`false`（確かめた）と `nil`（分からない）を分ける（指示書 §12-2）。"""
    roles = (ROOT / "dq3" / "phase0" / "ai" / "roles.lua").read_text(encoding="utf-8")
    body = roles.split("function Roles.blocked_by")[1].split("\n--- ")[0]
    for flag in ("paralyzed", "asleep", "confused"):
        assert ("st.%s == true" % flag) in body, "⚠ %s を == true で見ていない" % flag


# --- ★C legality（RX3-0134）-------------------------------------------

def test_押す直前に見直している():
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert "AIX.legality" in lua and "legality.check" in lua
    body = lua.split("function AIX.decide")[1].split("\n--- ")[0]
    assert "read_enemies()" in body, "⚠ いまの敵を読み直していない"
    assert "AIX.plan.caps" in body, "⚠ できることを渡していない"


def test_見直しは再計画ではない():
    """⚠⚠ ここが再計画を始めると、★理由の説明が 1 ターンの中で揺れます。"""
    src = (ROOT / "dq3" / "phase0" / "ai" / "legality.lua").read_text(encoding="utf-8")
    for word in ("assess", "strategy", "needed", "assign"):
        assert word not in src, "⚠⚠ 再計画へ踏み込んでいる: %s" % word


# --- ★§14 カバレッジ（RX3-0139）---------------------------------------

def test_カバレッジが数えられる():
    from dq3.battle_ai import coverage as CV

    if not CV.RUN_DIR.is_dir():
        pytest.skip("実機 run の記録がありません")
    got = CV.collect()
    if not got["runs"]:
        pytest.skip("読める run がありません")
    assert got["actions"] > 0
    assert got["situation"].get("消化戦", 0) > 0, "⚠ 戦況を数えられていない"
    assert got["command"].get("attack", 0) > 0, "⚠ 実コマンドを数えられていない"


def test_未発火は警告であって失敗ではない():
    """★指示書 §14「未発火を自動で failed にしない」。"""
    from dq3.battle_ai import coverage as CV

    data = {"runs": ["x"], "actions": 1, "situation": {"消化戦": 1}, "role": {"物理": 1},
            "command": {"attack": 1}, "strategy": {}, "mp": {}, "fixtures": {}, "tests": {}}
    missing = CV.gaps(data)
    assert "戦況: 劣勢" in missing and "役割: 支援" in missing
    text = CV.as_markdown(data)
    assert "まだ 1 度も通っていない分岐" in text
    assert "失敗ではありません" in text, "⚠ 失敗のように読める"


def test_実機のrunnerがカバレッジを出す():
    # ⚠ `scripts/*.py` は公開版に同梱しません（RX3-0431 / 2026-09-26 実測）。
    path = ROOT / "scripts" / "dq3_battle_ai_run.py"
    if not path.exists():
        pytest.skip("★開発用スクリプトは公開版に無い（⚠ 開発側では走る）")
    src = path.read_text(encoding="utf-8")
    assert "coverage as CV" in src and "CV.as_markdown" in src
    assert "CV.gaps" in src, "⚠ 未発火を知らせていない"


# --- ★§17 NEED-FIXTURE -------------------------------------------------

def test_足りないfixtureが一覧になっている():
    """⚠ 作業を止めずに、★何が足りないかを名前で残す（指示書 §17）。"""
    from dq3.testing import fixtures as FX

    if not FX.MANIFEST.exists():
        pytest.skip("fixture がまだありません")
    rows = FX.needed()
    assert rows, "⚠ NEED-FIXTURE が空（★実機カバレッジに穴があるのに要求が無い）"
    ids = {r["id"] for r in rows}
    for want in ("battle_ai_disadvantage", "battle_ai_support_use", "battle_ai_item_heal"):
        assert want in ids, "⚠ %s が要求されていない" % want
    for row in rows:
        assert row.get("why"), "⚠ %s に理由が無い" % row["id"]
        assert "ready" in row


def test_台帳の検査がNEED_FIXTUREの形も見る():
    from dq3.testing import fixtures as FX

    if not FX.MANIFEST.exists():
        pytest.skip("fixture がまだありません")
    assert FX.check_registry() == [], FX.check_registry()
