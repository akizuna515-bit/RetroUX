"""economy の資源配分を数える道具（RX3-0403 / 2026-09-23）。

```text
A  生ログでも report.md でも、同じ戦闘数になる
B  攻撃 MP と回復 MP を**別々に**数える（依頼者 §12）
C  道具は MP 0（★ROM の実測 / RX3-0395）。種類（attack / heal）で分ける
D  ⚠⚠ run.log の写しを戦闘と数えない（★2026-09-23 に 1 つずれた）
E  ⚠⚠ 0 件を**通過にしない**
F  shadow は「枠が無いだけで落ちた**有益な**手」だけ
G  足した MP と製品の mp_used が違えば、**違うと言う**
```

⚠ ROM は使いません（★呪文と道具の表を差し替えて回します）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dq3_economy_baseline as EB                           # noqa: E402

#: ★作り物の呪文（名前 → `(MP, 種類)`）
SPELLS = {"イオ": (5, "attack"), "ギラ": (4, "attack"), "ベホマ": (10, "heal"),
          "ピオリム": (3, "support")}
#: ★作り物の道具（名前 → 行）
ITEMS = {"けんじゃのいし": {"name": "けんじゃのいし", "kind": "heal"},
         "まどうしのつえ": {"name": "まどうしのつえ", "kind": "attack"}}


@pytest.fixture(autouse=True)
def _tables(monkeypatch):
    """★ROM の代わり（⚠ ROM が無い環境でも同じ結果になる）。"""
    monkeypatch.setattr(EB, "spell_table", lambda rom_path=None: SPELLS)
    monkeypatch.setattr(EB, "item_table", lambda rom_path=None: ITEMS)


def battle_log(no: int, moves, mp_used: int, hp_mp: str = "50/50 10/20  40/40 8/30") -> str:
    """★1 戦ぶんの生ログ（★決めた行 → 押した行 → 終わりの行）。"""
    lines = []
    for i, (slot, do) in enumerate(moves, 1):
        lines.append("AI %s 役割=魔法(第1) do=%s / 作り物" % (slot, do))
    for i, (slot, _do) in enumerate(moves, 1):
        kind = "attack"
        lines.append("AUTO_V0 turn=%d slot=%s action=%s target=none (作り物) hp_mp=%s"
                     % (i, slot, kind, hp_mp))
    lines.append("AUTO_V0_DONE 勝利 rounds=1 actions=%d strategy=economy mp_used=%d"
                 % (len(moves), mp_used))
    return "\n".join(lines)


# --- ★Case A ---------------------------------------------------------------

def test_A_生ログとreportで同じ戦闘数():
    raw = battle_log(1, [("p1", "spell:イオ")], 5) + "\n" + battle_log(2, [("p2", "attack→g1")], 0)
    assert len(EB.split_battles(raw)) == 2
    report = "\n".join([
        "### 1 戦目 — AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=5",
        "AI p1 役割=魔法(第1) do=spell:イオ / 作り物",
        "AUTO_V0 turn=1 slot=p1 action=spell target=none (作り物) hp_mp=50/50 10/20",
        "### 2 戦目 — AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=0",
        "AI p2 役割=物理(第1) do=attack→g1 / 作り物",
        "AUTO_V0 turn=1 slot=p2 action=attack target=none (作り物) hp_mp=50/50 10/20",
    ])
    assert len(EB.split_battles(report)) == 2


# --- ★Case B / C -----------------------------------------------------------

def test_B_攻撃MPと回復MPを分ける():
    text = battle_log(1, [("p1", "spell:イオ"), ("p2", "spell:ベホマ"), ("p3", "spell:ピオリム")], 18)
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["attack_mp"] == 5 and got["heal_mp"] == 10 and got["support_mp"] == 3
    assert got["total_mp"] == 18                           # ★足すと製品の mp_used と同じ


def test_C_道具はMP0で種類ごとに数える():
    text = battle_log(1, [("p1", "item:けんじゃのいし"), ("p2", "item:まどうしのつえ")], 0)
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["total_mp"] == 0
    assert got["kinds"]["item_heal"] == 1 and got["kinds"]["item_attack"] == 1
    assert got["items"] == {"けんじゃのいし": 1, "まどうしのつえ": 1}


# --- ★Case D ---------------------------------------------------------------

def test_D_runlogの写しを戦闘と数えない():
    # ⚠⚠ これが 2026-09-23 に実際に起きた形（★戦闘が 1 つずれ、MP の検算が合わなかった）
    text = "\n".join([
        battle_log(1, [("p1", "spell:イオ")], 5),
        "## 実行ログ",
        "[09:11:02]   ★1 戦目: AUTO_V0_DONE 勝利 rounds=1 actions=4 mp_used=5（AI 行 20 / 行動 4）",
        "[09:11:30]   ★2 戦目: AUTO_V0_DONE 勝利 rounds=1 actions=4 mp_used=0（AI 行 18 / 行動 4）",
    ])
    battles = [EB.read_battle(b) for b in EB.split_battles(text)]
    battles = [b for b in battles if b["actions"]]
    assert len(battles) == 1
    assert EB.summarize(battles)["total_mp"] == 5


# --- ★Case E ---------------------------------------------------------------

def test_E_0件を通過にしない():
    got = EB.summarize([])
    body = EB.markdown(got, "空")
    assert "⚠⚠" in body and "1 件も読めませんでした" in body
    assert "battles=0  wins=0" not in body                 # ⚠ 0 を並べて「通った」ように見せない


# --- ★Case F ---------------------------------------------------------------

def test_F_shadowは有益な手だけ():
    lines = [
        # ★枠が無いだけで落ちた（★これは数える）
        "AI tune p2 magic_candidate=イオラ resource_mp=6 magic_slot_counted=true "
        "decision=skip reason=assigned_other_role:physical val=80 phys=40 gain=0.42 mp=6",
        # ⚠ 得が無い（★数えない）
        "AI tune p3 magic_candidate=ギラ resource_mp=4 magic_slot_counted=true "
        "decision=skip reason=assigned_other_role:physical val=20 phys=30 gain=-0.11 mp=4",
        # ⚠ 無料の手は枠の外（RX3-0396 / ★数えない）
        "AI tune p4 magic_candidate=いなづまのけん resource_mp=0 magic_slot_counted=false "
        "decision=skip reason=assigned_other_role:physical val=90 phys=40 gain=0.61 mp=0",
        # ⚠ 枠ではない理由（★数えない）
        "AI tune p1 magic_candidate=ギラ resource_mp=4 magic_slot_counted=true "
        "decision=skip reason=physical_stronger val=20 phys=13 gain=0.30 mp=4",
    ]
    got = EB.shadow_rows(lines)
    assert [r["slot"] for r in got] == ["p2"]
    assert got[0]["spell"] == "イオラ" and got[0]["mp"] == 6


# --- ★Case F2: 予防の無料回復は行の**途中**に出る（2026-09-23 / RX3-0409）-------

def test_F2_予防の回復は役割の行の後ろに付く():
    """⚠⚠ 行頭で探していて、★実機の `decision=use` を 1 件も数えていませんでした。

    ★実機の形（`economy_stone` / 2026-09-23）:

    ```text
    AI 必要=ヒール→p3 魔法 魔法 魔法 / AI proactive_heal actor=p3 item=けんじゃのいし …
    ```
    """
    text = "\n".join([
        "AI 必要=ヒール→p3 魔法 魔法 魔法 / AI proactive_heal actor=p3 item=けんじゃのいし "
        "effective_heal=280 heal_per_action=255 alive=4 stone_gain=0.275 attack_gain=0.107 "
        "decision=use reason=free_heal_beats_attack",
        "AI p3 役割=ヒール(臨時) do=item:けんじゃのいし / けんじゃのいし（ベホマラー / MP 0）",
        "AUTO_V0 turn=1 slot=p3 action=item target=none (作り物) hp_mp=50/50 10/20",
        "AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=0",
    ])
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["proactive_use"] == 1                       # ⚠⚠ ここが 0 だった


def test_F2_見送りは数えない():
    text = "\n".join([
        "AI 必要=魔法 魔法 / AI proactive_heal actor=none item=none decision=skip reason=mop",
        "AI p1 役割=魔法(第1) do=attack→g1 / 作り物",
        "AUTO_V0 turn=1 slot=p1 action=attack target=none (作り物) hp_mp=50/50 10/20",
        "AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=0",
    ])
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["proactive_use"] == 0


# --- ★Case E2: 勝っていない戦闘を 0 の並びで隠さない（2026-09-23 / RX3-0409）---

def test_E2_人に返した戦闘は終わり方をそのまま出す():
    """⚠⚠ `窓の色 緑（HP 1/4 未満）` は `DANGER` の字面に当たりません。

    ★2026-09-23 実測: `battles=2 wins=0 danger_stop=0` とだけ出て、
    ⚠ **何が起きたのか読めません**でした。
    """
    text = "\n".join([
        "AI p1 役割=物理(第1) do=attack→g1 / 作り物",
        "AUTO_V0 turn=1 slot=p1 action=attack target=none (作り物) hp_mp=50/50 10/20",
        "AUTO_V0_DONE 窓の色 緑（HP 1/4 未満）（ここから手で戦う） rounds=2 actions=1 mp_used=0",
    ])
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["wins"] == 0 and got["handback"] == ["AUTO_V0_DONE 窓の色 緑（HP 1/4 未満）（ここから手で戦う）"]
    body = EB.markdown(got, "返した")
    assert "勝っていない戦闘 1 件" in body and "窓の色 緑" in body


def test_E2_勝った戦闘は並べない():
    text = "\n".join([
        "AI p1 役割=物理(第1) do=attack→g1 / 作り物",
        "AUTO_V0 turn=1 slot=p1 action=attack target=none (作り物) hp_mp=50/50 10/20",
        "AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=0",
    ])
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["handback"] == []
    assert "勝っていない戦闘" not in EB.markdown(got, "勝ち")


# --- ★Case G ---------------------------------------------------------------

def test_G_合わない戦闘は内訳から外す():
    """⚠⚠ 「決めた手」と「実際の MP の減り」が違う戦闘は、★内訳に入れない。

    ★実機で踏んだ形（2026-09-23）: `AUTO_V0_STOP reason=spell_not_found`。
    ⚠ 決めたのに唱えられず、★足すと合いませんでした。
    """
    text = battle_log(1, [("p1", "spell:イオ")], 9)        # ⚠ 製品は 9、足すと 5
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    body = EB.markdown(got, "ずれ")
    assert got["split_battles"] == 0 and got["attack_mp"] == 0  # ★内訳には入れない
    assert got["mp_used_product"] == 9                          # ★総量は製品の実測
    assert "外した" in body


def test_G_合っていれば内訳に入れる():
    text = battle_log(1, [("p1", "spell:イオ")], 5)
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["split_battles"] == 1 and got["attack_mp"] == 5
    assert "外した" not in EB.markdown(got, "一致")


# --- ★Case H: 途中で止まった run（2026-09-23）-------------------------------

def test_H_止まったrunは隔離先の生ログを読む(tmp_path, monkeypatch):
    """⚠⚠ `report.md` は**最後に**書かれます。★止まった run には在りません。"""
    run = tmp_path / "runs" / "20260923-105601"
    run.mkdir(parents=True)
    sbx = tmp_path / "sandbox" / "20260923-105601-battle-ai" / "work" / "dq3-probe"
    sbx.mkdir(parents=True)
    (sbx / "auto_v0.log").write_text("AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=0",
                                     encoding="utf-8")
    monkeypatch.setattr(EB, "SANDBOX", tmp_path / "sandbox")
    got = EB.find_log(run)
    assert got is not None and got.name == "auto_v0.log"


def test_H_reportがあればそちらを読む(tmp_path):
    run = tmp_path / "20260923-112026"
    run.mkdir()
    (run / "report.md").write_text("# 何か", encoding="utf-8")
    assert EB.find_log(run).name == "report.md"


# --- ★Case I: ザキ系は「役割」で分ける（2026-09-23 に取り違えた）---------------

def test_I_即死呪文は攻撃の席なら攻撃MP(monkeypatch):
    monkeypatch.setattr(EB, "spell_table",
                        lambda rom_path=None: {"ザラキ": (7, "instant"), "ラリホー": (3, "instant")})
    # ★実機の形: `AI p3 役割=魔法(第1) do=spell:ザラキ→g1`
    text = "\n".join([
        "AI p3 役割=魔法(第1) do=spell:ザラキ→g1 / 作り物",
        "AUTO_V0 turn=1 slot=p3 action=spell target=none (作り物) hp_mp=50/50 10/20",
        "AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=7",
    ])
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["attack_mp"] == 7 and got["support_mp"] == 0


def test_I_支援の席の即死呪文は支援MP(monkeypatch):
    monkeypatch.setattr(EB, "spell_table", lambda rom_path=None: {"ラリホー": (3, "instant")})
    text = "\n".join([
        "AI p3 役割=支援(第1) do=spell:ラリホー→g1 / 作り物",
        "AUTO_V0 turn=1 slot=p3 action=spell target=none (作り物) hp_mp=50/50 10/20",
        "AUTO_V0_DONE 勝利 rounds=1 actions=1 mp_used=3",
    ])
    got = EB.summarize([EB.read_battle(b) for b in EB.split_battles(text)])
    assert got["support_mp"] == 3 and got["attack_mp"] == 0
