"""戦闘 AI v1（RX3-0126）— ★設定・生成（Python）と、判断・操作（Lua）を実機なしで。

```text
dq3/battle_ai/settings.py     設定の往復 / 役割の提案 / 人が触った枠を守る
dq3/battle_ai/generate.py     Lua が読む 1 本を作る（★ROM から）
dq3/phase0/ai/*.lua           判断（A〜H）   ← research/probes/active/dq3_ai_test.lua
dq3/phase0/auto_v0.lua        操作（▶ を寄せて A）← research/probes/active/dq3_auto_ai_test.lua
```

⚠ Lua の足場は「すべて合格」と OK の行で見る（★`test_dq3_restock_v0.py` と同じ作法）。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

from dq3.battle_ai import settings as S

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
JUDGE = ROOT / "research" / "probes" / "active" / "dq3_ai_test.lua"
DRIVER = ROOT / "research" / "probes" / "active" / "dq3_auto_ai_test.lua"
LEGAL = ROOT / "research" / "probes" / "active" / "dq3_ai_legality_test.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"
GENERATED = ROOT / "work" / "generated" / "dq3_ai.lua"


def _rom_available() -> bool:
    from dq3.knowledge import spell_info as SI

    return SI.available()


# --- ★設定 -------------------------------------------------------------

def test_設定は往復して壊れない():
    v = S.BattleAiSettings().with_strategy(S.SURVIVAL).with_mp(S.MP_FORBID)
    v = v.with_role("p2", S.HEAL, S.SUPPORT)
    back = S.BattleAiSettings.from_json(v.to_json())
    assert back.strategy == S.SURVIVAL and back.mp_policy == S.MP_FORBID
    assert back.role_of("p2") == S.RolePref(S.HEAL, S.SUPPORT)
    # ★with_role は第1・第2 の両方を人が決める（RX3-0198 §15 / 欄ごとの touched）
    assert back.touched == (("p2", S.FIRST), ("p2", S.SECOND))


def test_知らない値は既定に倒す():
    back = S.BattleAiSettings.from_json({"strategy": "berserk", "mp_policy": "all",
                                         "roles": {"p9": ["heal", "x"], "p1": ["x", "defend"]},
                                         "touched": ["p1", "zz"]})
    assert back.strategy == S.ECONOMY and back.mp_policy == S.MP_AUTO
    assert back.role_of("p1") == S.RolePref(None, S.DEFEND)
    # ★v1 の枠（"p1"）は両方の欄を人が決めたとみなす。⚠ 知らない枠（"zz"）は捨てる
    assert "p9" not in back.roles and back.touched == (("p1", S.FIRST), ("p1", S.SECOND))


def test_人が触った枠は提案で上書きしない(monkeypatch):
    monkeypatch.setattr(S, "suggest_roles", lambda members, rom_path=None: {
        "p1": S.RolePref(S.HEAL, S.SUPPORT), "p2": S.RolePref(S.MAGIC, S.HEAL)})
    v = S.BattleAiSettings().with_role("p1", S.PHYSICAL, S.DEFEND)
    got = S.effective_roles(v, [{"slot": "p1"}, {"slot": "p2"}])
    assert got["p1"] == S.RolePref(S.PHYSICAL, S.DEFEND), "⚠ 人が決めた枠が提案で戻った"
    assert got["p2"] == S.RolePref(S.MAGIC, S.HEAL)
    assert got["p3"] == S.RolePref(S.PHYSICAL, S.DEFEND), "⚠ 提案が無い枠の既定"


def test_UiSettingsへ保存して読める(tmp_path):
    from dq3.ui.ui_settings import UiSettings

    us = UiSettings(tmp_path / "ui.json")
    S.save(us, S.BattleAiSettings().with_mp(S.MP_SAVE))
    assert S.load(UiSettings(tmp_path / "ui.json")).mp_policy == S.MP_SAVE
    assert S.load(None) == S.BattleAiSettings()


@pytest.mark.skipif(not _rom_available(), reason="ROM が無い")
def test_役割の提案は職業でなく呪文と数字から():
    """★勇者（ホイミ持ち）→ ヒール、呪文なしの高攻撃 → 物理、支援呪文持ち → 第2 支援。"""
    from dq3rom import spell_flags as SF
    from dq3.knowledge import spell_info as SI

    blocks = SI._load()["blocks"]

    def bits(block_no: int, names: tuple) -> int:
        from dq3.knowledge import rom_names as RN

        got = 0
        for bit, sid in enumerate(blocks[block_no]):
            if sid != 0xFF and RN.spell(sid) in names:
                got |= 1 << bit
        return got

    hero = {"slot": "p1", "attack": 30, "class_gender": 0,
            "spells": [bits(0, ("ホイミ", "メラ")), 0, 0, 0, 0, 0, 0, 0]}
    soldier = {"slot": "p2", "attack": 60, "class_gender": 1, "spells": [0] * 8}
    mage = {"slot": "p3", "attack": 10, "class_gender": 4,
            "spells": [bits(SF.MAGE_BLOCKS[0], ("メラ", "ギラ", "スクルト")), 0, 0, 0, 0, 0, 0, 0]}
    got = S.suggest_roles([hero, soldier, mage])
    assert got["p1"].first == S.HEAL, got
    assert got["p2"] == S.RolePref(S.PHYSICAL, S.DEFEND), got
    assert got["p3"] == S.RolePref(S.MAGIC, S.SUPPORT), got


# --- ★生成 -------------------------------------------------------------

@pytest.mark.skipif(not _rom_available(), reason="ROM が無い")
def test_生成物は呪文と敵と道具を持つ(tmp_path):
    from dq3.battle_ai import generate as G

    data = G.regenerate(S.BattleAiSettings().with_mp(S.MP_FORBID), [], out_dir=tmp_path)
    assert data["ok"] is True, data.get("error")
    assert len(data["spells"]) >= 60 and len(data["blocks"]) == 12
    assert len(data["enemies"]) >= 100
    assert data["items"]["herb"]["tiles"], "⚠ やくそう のタイルが無い"
    text = (tmp_path / "dq3_ai.lua").read_text(encoding="utf-8")
    assert 'mp_policy = "forbid"' in text
    assert "revision" in text and not list(tmp_path.glob("*.tmp")), "⚠ 書きかけが残った"


@pytest.mark.skipif(not _rom_available(), reason="ROM が無い")
def test_生成物は道具の攻撃を持つ():
    """★RX3-0213: まどうしのつえ（$07）→ 呪文 0（メラ）/ 減らない / タイルは ROM の名前から。"""
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S2

    data = G.build(S2.BattleAiSettings(), [])
    assert data["ok"] is True, data.get("error")
    attack = data["items"]["attack"]
    wand = [it for it in attack if it["id"] == 0x07]
    assert wand, "⚠ まどうしのつえ が items.attack に無い: %s" % [it["id"] for it in attack]
    assert wand[0]["tiles"] == [41, 30, 13, 22, 35, 28, 14], wand[0]
    assert wand[0]["spell_id"] == 0 and wand[0]["consumed"] is False
    # ★どれも攻撃呪文として働き、減らない品だけ（⚠ 回復・補助の道具を混ぜない）
    for it in attack:
        assert data["spells"][it["spell_id"]]["kind"] == "attack", it
        assert it["consumed"] is False and it["tiles"], it
    assert data["tuning"]["magic_bonus_item"][S2.ECONOMY] == 1.0


def test_ROMが無ければokをfalseにして落ちない(tmp_path):
    from dq3.battle_ai import generate as G

    data = G.build(S.BattleAiSettings(), [], rom_path=tmp_path / "missing.nes")
    assert data["ok"] is False and "ROM" in data["error"]


def test_ai_reloadを頼める():
    from dq3.ui.commands import ACTIONS

    assert "ai_reload" in ACTIONS


# --- ★Lua（判断 A〜H / 操作）------------------------------------------

_lua_ok = DLL.exists() and RUNNER.exists()


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> pathlib.Path:
    """★足場が読む生成物は、検査が一時フォルダに作る（RX3-0213 / 2026-09-12）。

    ⚠⚠ 本物の `work/generated/dq3_ai.lua`（`GENERATED`）は、遊んでいる依頼者の RetroUX が
      パーティの変化で作り直す。★古いコードのまま書き直され、つえの足場が**全件検査の中でだけ**落ちた。
    """
    if not (_lua_ok and _rom_available()):
        pytest.skip("Lua か ROM が無い")
    from dq3.battle_ai import generate as G

    out = tmp_path_factory.mktemp("dq3-ai-generated")
    data = G.regenerate(S.BattleAiSettings(), [], out_dir=out)
    assert data.get("ok"), data.get("error")
    return out / ("%s.lua" % G.MODULE)


def _run(harness: pathlib.Path, generated: pathlib.Path | None = None) -> str:
    import os

    env = dict(os.environ)
    if generated is not None:
        env["DQ3_AI_GENERATED"] = str(generated).replace(chr(92), "/")
    done = subprocess.run([sys.executable, str(RUNNER), str(harness)], cwd=str(ROOT),
                          capture_output=True, timeout=300, text=True, env=env,
                          encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, "⚠⚠ 落ちました" + chr(10) + both
    return both


@pytest.fixture(scope="module")
def judge(generated) -> str:
    return _run(JUDGE, generated)


@pytest.fixture(scope="module")
def driver(generated) -> str:
    return _run(DRIVER, generated)


@pytest.fixture(scope="module")
def legality() -> str:
    """★押す直前の見直し（RX3-0134）。⚠ 生成物は要らない（★純粋な計算だけ）。"""
    if not (DLL.exists() and RUNNER.exists()):
        pytest.skip("Lua を動かせない")
    return _run(LEGAL)


def test_押す直前の見直しが全部通る(legality):
    assert "すべて合格" in legality, legality
    for line in ("OK 対象死亡", "OK 対象満タン", "OK 蘇生", "OK 敵群消滅",
                 "OK 術者死亡", "OK 術者行動不能", "OK MP不足", "OK item無し",
                 "OK 無事なら素通り", "OK 再計画していない"):
        assert any(ln.startswith(line) for ln in legality.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + legality)


def test_見直しのOKが減っていない(legality):
    n = sum(1 for line in legality.splitlines() if re.match(r"^OK\b", line))
    assert n >= 11, legality                               # ★RX3-0213 で 10 → 11（道具の攻撃）


def test_判断のAからHが全部通る(judge):
    """★RX3-0198: 「OK B レベル上げ」→「OK B 最短撃破」（⚠ 内部の語 leveling は保つ）。"""
    assert "すべて合格" in judge, judge
    for line in ("OK A 消化戦", "OK B 最短撃破", "OK C リソース節約", "OK D 均衡",
                 "OK E 劣勢", "OK F MP使用禁止", "OK G 転職キャラ", "OK H 役割代行",
                 "OK I 均衡でも、回復が来ない瀕死は防御する",
                 "OK MP温存", "OK 割当は 第1 → 第2 の順",
                 "OK J 麻痺", "OK J 未観測", "OK J 眠り",
                 "OK K 回復する敵", "OK K 全体攻撃", "OK L 耐性",
                 # ★RX3-0268: 敵の状態（全員かかっている群には ラリホー を唱えない）
                 "OK N 敵の状態"):
        assert any(ln.startswith(line) for ln in judge.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + judge)


def test_作戦ごとの攻撃呪文とMP制約が通る(judge):
    """★RX3-0198（2026-09-12 依頼者の指示書「魔法の評価 v1.1」/ 依頼者 save3「最短撃破でも魔術師が魔法使わない」）。

    ```text
    S3   save3 の写し: 合計では消化戦でも、物理 2 ターンなら最短撃破は群呪文（⚠ 1 体なら撃たない）
    C/C2 節約: はっきり短くならなければ物理 / 1 ターン以上短くなるなら撃つ（⚠ 禁止ではない）
    CA   雑魚 4 体 / CB 弱い 1 体（どの作戦も撃たない）/ CC 強敵 1 体（単体呪文）
    MP   最短撃破＋半分程度残す は床まで / 最短撃破＋使用禁止 は呪文ゼロで戦う / 生存＋使用禁止 も解禁しない
    ```
    """
    for line in ("OK S3 最短撃破", "OK C2 リソース節約", "OK CA 雑魚 4 体", "OK CB 弱い敵 1 体",
                 "OK CC 強敵 1 体", "OK CC2 強敵 1 体・呪文が小さい",
                 "OK MP 最短撃破＋半分程度残す", "OK MP 最短撃破＋使用禁止", "OK MP 生存＋使用禁止",
                 "OK 判断ログ", "OK first_hp"):
        assert any(ln.startswith(line) for ln in judge.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + judge)


def test_まどうしのつえを道具で使う(judge, driver, legality):
    """★RX3-0213（2026-09-12 依頼者「save3 魔術師がまどうしの杖を手に入れた。リソース節約で使えるようになる」）。

    ```text
    W1  節約でも どうぐ で群へ メラ（MP 0）/ つえが無ければ今までどおり
    W2  MP 使用禁止でも使う  W3 物理で片づく・弱い 1 体は物理  W4 最短撃破は 1 ターン早い呪文を優先
    操作  どうぐ → つえ（装備の印つき）→ 敵の群 → A / やくそう 0 個でも書き換えない
    ```
    """
    for line in ("OK W1 まどうしのつえ", "OK W2 まどうしのつえ", "OK W3 まどうしのつえ",
                 "OK W4 まどうしのつえ"):
        assert any(ln.startswith(line) for ln in judge.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + judge)
    for line in ("OK どうぐ → まどうしのつえ", "OK やくそう 0 個でも、道具の攻撃は",
                 "OK ★RX3-0330 まとめ"):
        assert any(ln.startswith(line) for ln in driver.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + driver)
    assert any(ln.startswith("OK 道具の攻撃") for ln in legality.splitlines()), legality


def test_リソース節約でマホトラを使う(judge):
    """★RX3-0260（2026-09-14 依頼者の小WI「リソース節約時のマホトラ活用」/ 正本 `docs/design/dq3-mahotora-spec.md`）。

    ```text
    MH1 節約・消化戦・ほかの人だけで倒せる → 寄与が低い人はマホトラ   MH2 最短撃破は使わない   MH3 MP 満タンは使わない
    MH4 効かない敵（最大 MP 0 / 耐性 2〜3 / 今の MP 0）には使わない    MH5 撃破に要る攻撃は攻撃
    MH6 均衡・劣勢は使わない   MH7 回復が要れば回復   MH8 半分程度残すでも使う・使用禁止は使わない   MH9 覚えていなければ今までどおり
    ```
    """
    for line in ("OK MH1 マホトラ", "OK MH2 マホトラ", "OK MH3 マホトラ", "OK MH4 マホトラ", "OK MH5 マホトラ",
                 "OK MH6 マホトラ", "OK MH7 マホトラ", "OK MH8 マホトラ", "OK MH9 マホトラ"):
        assert any(ln.startswith(line) for ln in judge.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + judge)


def test_判断のOKが減っていない(judge):
    n = sum(1 for line in judge.splitlines() if re.match(r"^OK\b", line))
    # ★RX3-0260 で 34 → 43 / ★RX3-0322 で 43 → 47 / ★RX3-0327（最短撃破 v1）で 64 → 81 / ★RX3-0330 で 84 / ★RX3-0331（v1.1）で 99
    assert n >= 99, judge


def test_最短撃破の新しい判定が通る(judge):
    """★RX3-0327（2026-09-20 依頼者「最短撃破 v1 実装修正指示」§14）。

    ```text
    SK0  TUNING          単体倍率 1.0 / gain 下限 0 / 即死の下限 0（★ほかは今までどおり）
    SKC  ケースC         単体敵・物理 2 ターン → 撃つ（⚠ 旧 magic_skip_rounds.single の撤廃）
    SKD  ケースD         物理の 1.5 倍の単体呪文を落とさない（⚠ 旧 magic_single_ratio の撤廃）
    SKE  ケースE         即死 30%・高 HP を候補に残す / SKE2 物理に負けるなら自然に落ちる
    SKP  物理 overkill   物理の見込みも残り HP で頭打ち（★呪文・即死と同じ物差し）
    ```
    """
    for line in ("OK SK0 最短撃破の TUNING", "OK SKC 単体敵で物理 2 ターン",
                 "OK SKD 単体呪文が物理の 1.5 倍", "OK SKE 即死 30%",
                 "OK SKE2 即死の期待値", "OK SKE3 即死の下限", "OK SKP 物理の見込み",
                 "OK SKF0 行動傾向の重み", "OK SKF 元僧侶の戦士", "OK SKF2 最短撃破",
                 "OK SKF3 ほかの作戦", "OK SKH0 回復の線", "OK SKH1 HP 30%",
                 "OK SKH2 HP 20%", "OK SKH3 瀕死の防御",
                 "OK SKM 魔法の重複撃ち", "OK SKM2 どの群も",
                 "OK SKM3 全体呪文", "OK SKM4 全体呪文", "OK SKM5 全体呪文の予約",
                 "OK SS0 分類", "OK SSA ケースA", "OK SSD ケースD", "OK SSG ケースG",
                 "OK SSI ほかの作戦", "OK SSF スクルト", "OK SSB 同程度なら攻撃",
                 "OK SSH 支援の重複防止",
                 "OK SSX0 前提", "OK SSX1 ケースE・F", "OK SSX2 ケースD",
                 "OK SSX3 ケースB", "OK SSX4 回復・防御", "OK SSX5 ほかの作戦",
                 "OK SSX6 ケースH"):
        assert any(ln.startswith(line) for ln in judge.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + judge)


def test_操作まで通る(driver):
    assert "すべて合格" in driver, driver
    for line in ("OK たたかう → 残りが少ない群", "OK 同じターンの 2 人目",
                 "OK 全員が決めたら次のターン", "OK 群が 1 つなら",
                 "OK じゅもん → ホイミ → 味方の一覧", "OK MP 使用禁止: どうぐ → やくそう",
                 "OK ai_reload で生成物を読み直す", "OK 名前が見つからなければ",
                 # ★RX3-0198: 終わりの行に作戦・行動の内訳・MP 消費
                 "OK 戦闘のまとめ",
                 # ★RX3-0240: 2 ページ目の呪文は → でページを替えて選ぶ
                 "OK RX3-0240 2 ページ目の呪文",
                 # ⚠⚠ RX3-0242（依頼者「save7 2ページ目で止まってしまう場合がある」）: 2 ページ目のまま開いた窓 / 動かない向き
                 "OK RX3-0242 2 ページ目のまま開いた窓",
                 "OK RX3-0242 押しても ▶ が動かない向きは覚えて",
                 # ⚠⚠ RX3-0270（RX3-0266 の実機の試行）: メラを頼んでメラミを唱えた = 呪文名の部分一致
                 "OK RX3-0270 頭が同じ呪文（ベホマズン）の上では決めず",
                 "OK RX3-0270 後ろが同じ呪文（ベホイミ）の中のホイミは探さず",
                 # ★RX3-0268: 敵の群とスロットは ROM の群の bit で組む（⚠ 旗が無ければ今までどおり）
                 "OK RX3-0268 敵の群とスロットは ROM の群の bit で組み",
                 "OK RX3-0268 群の旗が無い RAM では今までどおり"):
        assert any(ln.startswith(line) for ln in driver.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + driver)


def test_安全な戦闘だけ速くし勝ったら人に返す(driver):
    """★RX3-0166 → RX3-0237: A で AUTO＋TURBO / T は TURBO だけ（AUTO OFF でも）/ ENTERING では効かない / 勝ったら元の速さ。

    ★シンプルな勝利は結果の文も送り、レベルアップ・アイテムでは人に返す（依頼者 2026-09-11）。
    ⚠ 2026-09-13 まで「Auto OFF のとき Turbo は何もしない」「初見の敵は速くしない」を固定していた（★仕様で変えた）。
    """
    for line in ("OK A で AUTO を入れると、その場で TURBO も入る",
                 "OK 勝利に入ったそのフレームで元の速さへ戻し、ファンファーレの間は押さない",
                 "OK シンプルな勝利は、ファンファーレのあと結果の文も送ってフィールドまで戻す",
                 "OK レベルアップ（曲 $01）が出たら、そこで人に返す",
                 "OK レベルのバイトが増えたら、そこで人に返す",
                 "OK アイテムを手に入れたら（袋が変わったら）、そこで人に返す",
                 "OK hand_back は勝ったらすぐ人に返す",
                 "OK ファンファーレが終わったら（場所の曲に戻ったら）、上限を待たずに結果の文を送る",
                 "OK AUTO ON / TURBO ON で TURBO → AUTO ON / TURBO OFF",
                 "OK もう一度 T → AUTO ON / TURBO ON",
                 "OK AUTO 中に A を押すと AUTO OFF / TURBO OFF",
                 "OK AUTO OFF で TURBO → AUTO OFF / TURBO ON",
                 "OK AUTO OFF / TURBO ON で A → AUTO ON / TURBO ON",
                 "OK 戦闘の本体（ACTIVE）でないとき、A も T も効かない",
                 "OK 人が A で入れた AUTO は、初見の敵でも TURBO のまま",
                 "OK 遭遇したばかり（ENTERING）では A も効かず、速くしない"):
        assert any(ln.startswith(line) for ln in driver.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + driver)


def test_窓の色でAutoを人へ返す(driver):
    """★RX3-0225（2026-09-12 依頼者「３割という別論理ではなく、赤黄色ないし緑に画面がなったら止める
    （等速化ではなく、オート解除）」）。

    ★2026-09-13 依頼者「３割は廃止、劣勢はターボ＆オートを止める形にしたい」。

    ```text
    自動で入った Auto がはじめから劣勢なら返す / 人が A で入れた Auto ははじめから劣勢でも続ける /
    緑（$2A）でそのフレームに人へ返す・白に戻っても入れ直さない /
    人が A で入れた Turbo の Auto もオレンジ（$27）で返す / 自動で入る条件も窓の色（HP 28% でも白なら入る）
    ```
    """
    for line in ("OK 自動で入った Auto が、はじめから劣勢なら人へ返す",
                 "OK 人が A で入れた Auto は、はじめから劣勢でも続ける",
                 "OK 窓の色が緑（$2A）になったら、そのフレームで Auto を切って人へ返す",
                 "OK 人が A で入れた Turbo の Auto も、窓の色がオレンジ（$27）になったら人へ返す",
                 "OK 倒した敵でも、窓の色が緑（HP 1/4 未満）なら手動のまま",
                 "OK 倒した敵で窓の色が白なら、HP 28%（17/60）でも Auto に入る"):
        assert any(ln.startswith(line) for ln in driver.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + driver)


def test_生成物が無いときは今までどおり():
    """★`auto_v0.lua` は生成物が無ければ設定で動く（⚠ 足場が `DQ3_AI_PATH` で切っている）。"""
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert "AIX.decide(actor, members)" in lua
    assert 'rawget(_G, "DQ3_AI_PATH")' in lua
    # ⚠ 足場（research/probes/）は公開版に同梱しません（RX3-0431 / 2026-09-26 実測）。
    #   ★製品側の 2 行は上で見ているので、ここは**在るときだけ**見ます。
    path = ROOT / "research" / "probes" / "active" / "dq3_auto_v0_test.lua"
    if not path.exists():
        pytest.skip("★研究用ハーネスは公開版に無い（⚠ 開発側では走る）")
    harness = path.read_text(encoding="utf-8")
    assert "DQ3_AI_PATH" in harness and "__no_ai__" in harness
