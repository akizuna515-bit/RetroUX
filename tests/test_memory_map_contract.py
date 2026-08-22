"""memory_map.yaml の契約（Phase 6 P4-0 で足した耐性・拒否フラグ）。

★**なぜここに置くか。**
  抽出と裏取りは `research/probes/archived/probe_resist.py` / `research/probes/archived/add_resist.py` にあるが、
  **`work/` は Git 管理外**なので、あれだけでは検証が残らない。
  さらに ROM も配布しないため、他の環境では再抽出できない。
  → **公開データとの照合結果そのものを、ここで memory_map の値に対して固定化する。**
    以後、値が変わればテストが落ちる。

★2026-08-21（RX-0090）: 敵の表は memory_map.yaml から消え、**利用者の ROM から起こす**
  ようになった。耐性・行動の検査は `em`（ROM 由来の表）に対して行い、
  ROM もキャッシュも無い環境ではスキップする（⚠ 空で通さない）。

守りたい契約:
  1. 耐性は 0..7 で、全83体に6種そろっている（欠けを 0 で埋めていない）
  2. 公開データ（極限攻略 FC版）と一致する
  3. 唱えてはいけない呪文（メガンテ・パルプンテ・ルーラ）に拒否フラグと理由がある
  4. 回復呪文と拒否フラグが同時に立っていない
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

MAP_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "retroux" / "plugins" / "dq2" / "memory_map.yaml"
)

# 耐性の並び。**この順番と名前が変わったら気づきたい**ので固定する。
RESIST_KEYS = ("spell_damage", "sleep", "stopspell", "defeat",
               "defense_down", "surround")

# --- 裏取り用の公開データ（探索には使っていない）------------------------
#
# 出典: 極限攻略 https://kyokugen.info/dq2/dq2_monster1.html （FC版）
#   凡例「攻=攻撃呪文 / 眠=ラリホー / 黙=マホトーン / 死=ザラキ /
#         幻=マヌーサ / 守=ルカニ」「0は100%、…、7は0%程度の確率で有効」
#
# ★ROM の読み方を決めるのに**この表は使っていない**。
#   構造は逆アセンブル（bank4.asm:5079 のコメントと :6469 の実コード）から決め、
#   あとで突き合わせている（playbook「探索の当たりは、探索に使っていないデータで確かめる」）。
#
# ⚠ 公開データ側の列は 幻(マヌーサ) -> 守(ルカニ) の順で、ROM のビット順とは逆。
#   ここでは辞書のキー名で対応させる（順番の取り違えを起こさないため）。
PUBLISHED = {
    0x01: (0, 0, 7, 0, 0, 0),   # スライム
    0x06: (3, 3, 7, 1, 0, 0),   # ホイミスライム
    0x0A: (0, 0, 0, 1, 0, 1),   # まほうつかい
    0x0F: (0, 1, 7, 1, 0, 0),   # よろいムカデ
    0x12: (0, 7, 7, 7, 0, 1),   # リビングデッド
    0x30: (7, 7, 7, 7, 7, 7),   # メタルスライム
    0x42: (7, 7, 7, 7, 7, 7),   # はぐれメタル
    0x4E: (7, 7, 7, 7, 2, 2),   # アトラス
    0x4F: (4, 3, 7, 7, 4, 6),   # バズズ
    0x51: (3, 7, 4, 7, 7, 7),   # ハーゴン
    0x52: (7, 7, 7, 7, 2, 4),   # シドー
}


@pytest.fixture(scope="module")
def mm() -> dict:
    return yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def em() -> dict:
    """敵の表つき（ROM 由来）。無ければスキップ。"""
    from conftest import load_memory_map_with_enemies
    return load_memory_map_with_enemies()


# --- 耐性 --------------------------------------------------------------


def test_all_monsters_have_full_resist_set(mm, em):
    """全83体に6種そろっていること。**欠けを 0 で埋めていない**ことの担保。

    「分からないものは列を作らない」の裏返しで、列を作ったなら全員分そろっている。
    """
    stats = em["monster_stats"]
    assert len(stats) == 83, f"敵の数が {len(stats)} 体になっている"
    for mid, s in stats.items():
        assert "resist" in s, f"0x{mid:02X} に resist が無い"
        assert tuple(s["resist"]) == RESIST_KEYS, (
            f"0x{mid:02X} の耐性のキーか順番が違う: {tuple(s['resist'])}"
        )


def test_resist_values_are_three_bit(mm, em):
    """耐性は 3ビット（0..7）。成功率 = (7 - 値) / 7 なので 8 以上は意味を持たない。"""
    for mid, s in em["monster_stats"].items():
        for name, value in s["resist"].items():
            assert isinstance(value, int), f"0x{mid:02X}.{name} が整数でない"
            assert 0 <= value <= 7, f"0x{mid:02X}.{name}={value} が 0..7 の外"


def test_evade_is_four_bit(mm, em):
    """回避率は 4ビット（0..15）。判定は rand(0..63) < evade。"""
    for mid, s in em["monster_stats"].items():
        assert "evade" in s, f"0x{mid:02X} に evade が無い"
        assert 0 <= s["evade"] <= 15, f"0x{mid:02X}.evade={s['evade']} が 0..15 の外"


@pytest.mark.parametrize("mid", sorted(PUBLISHED), ids=lambda m: f"0x{m:02X}")
def test_resist_matches_published_data(mm, em, mid):
    """公開データと一致すること（探索に使っていないデータでの裏取り）。

    ★一致の中で決定的なもの:
      メタルスライム / はぐれメタル … 全項目 7（何も効かないという有名な事実）
      バズズ … sleep が 3（ラリホーが効くという定番の戦法）
    """
    got = tuple(em["monster_stats"][mid]["resist"][k] for k in RESIST_KEYS)
    assert got == PUBLISHED[mid], (
        f"0x{mid:02X}: memory_map {got} が公開データ {PUBLISHED[mid]} と違う"
        f"（{'/'.join(RESIST_KEYS)}）"
    )


def test_metal_slime_is_immune_to_everything(mm, em):
    """メタルスライム(0x30) は全耐性 7 = 完全耐性。

    ★これは「耐性7 を候補から外す」機能（依頼者の項目11「効かない攻撃はしない」）が
      意味を持つための前提。全員が 7 未満なら、その機能は一度も働かない。
    """
    resist = em["monster_stats"][0x30]["resist"]
    assert all(v == 7 for v in resist.values()), resist


def test_some_monsters_have_zero_resist(mm, em):
    """耐性 0（必ず効く）の敵が居ること。

    ★「弱点を突く」（項目10）が意味を持つための前提。
      全員が 7 なら、表の位置がずれている疑いでもある。
    """
    weak = [mid for mid, s in em["monster_stats"].items()
            if any(v == 0 for v in s["resist"].values())]
    assert len(weak) > 20, f"耐性0 の敵が {len(weak)} 体しかいない（表の位置を疑う）"


# --- 唱えてはいけない呪文 ----------------------------------------------


def test_dangerous_spells_are_denied(mm):
    """メガンテ・パルプンテ・ルーラを AI とマクロが選べないこと。

    ⚠⚠ 戦闘呪文リストの**枠7（列1・行3）**は ROM の SpellLevels によると
      サマルトリア LV28 -> メガンテ(0x0C)  … **唱えた本人が死ぬ**
      ムーンブルク LV25 -> パルプンテ(0x0F) … 効果がランダム
      になる。P3（回復呪文）は「heal かつ味方狙い」で絞っていたため
      構造的に候補に入らなかったが、攻撃呪文を許すとその絞りが効かなくなる。
    """
    spells = mm["spells"]
    for sid in (0x0C, 0x0F, 0x14):
        info = spells[sid]
        assert info.get("never_cast") is True, (
            f"0x{sid:02X} {info.get('name')} に never_cast が無い"
        )
        reason = info.get("never_cast_reason")
        assert isinstance(reason, str) and reason.strip(), (
            f"0x{sid:02X} に理由が無い。理由を出さない拒否は「動かない」と区別できない"
        )


def test_return_is_still_marked_irreversible(mm):
    """ルーラの `irreversible` を消していないこと。

    ★`irreversible` は「戻せない」という**事実**の記録、
      `never_cast` は「選ばない」という**方針**。意味が違うので両方残す。
      片方を書き忘れても止まるように、判定は両方を見る。
    """
    assert mm["spells"][0x14]["irreversible"] is True


def test_heal_spells_are_never_denied(mm):
    """回復呪文に拒否フラグが立っていないこと（機能を殺していない）。"""
    for sid, info in mm["spells"].items():
        if info.get("heal") or info.get("cure_poison"):
            assert not info.get("never_cast"), (
                f"0x{sid:02X} {info.get('name')} は回復呪文なのに拒否されている"
            )


# --- 敵の行動（2026-07-27）--------------------------------------------


# ★公開データ（探索には使っていない）。research/probes/archived/solve_actions.py --verify が
#   全82体で照合しているが、**ROM を配布しないので他の環境では再現できない**。
#   ここでは memory_map に入った値そのものに対して要点を固定化する。
#   出典: https://retro-video-game.com/guide/fc/dragon-quest-2/data/enemy
ACTION_SPOTS = {
    0x00: "通常攻撃",
    0x04: "防御",        # リビングデッドの 24.3% から確定
    0x05: "逃げる",      # スライムの 27.7% から確定
    0x0C: "ホイミ",      # ホイミスライムの 88.3% から確定
    0x1D: "２回攻撃",    # アトラスが 100% これ
    0x1E: "選び直し",    # ★有効な行動ではない
}


def test_action_table_is_complete(mm):
    """行動の対応表が32種類そろっていること（4ビット+代替ビット = 5ビット）。"""
    actions = mm["monster_actions"]
    assert len(actions) == 32, f"行動が {len(actions)} 種類しかない"
    assert set(actions) == set(range(32)), "0x00〜0x1F が連続していない"
    for aid, name in actions.items():
        assert isinstance(name, str) and name.strip(), f"0x{aid:02X} の名前が空"


@pytest.mark.parametrize("aid,name", sorted(ACTION_SPOTS.items()),
                         ids=lambda v: v if isinstance(v, str) else f"0x{v:02X}")
def test_action_names_match_published(mm, aid, name):
    """公開データから確定した行動名が変わっていないこと。"""
    assert mm["monster_actions"][aid] == name


def test_reroll_action_is_marked(mm):
    """0x1E が「選び直し」であること。

    ★これは**有効な行動ではない**。確率を出すときは除いて正規化する。
      混ぜると「アンデッドマンは12.5%で何もしない」と出てしまう
      （公開データは通常攻撃100%）。
    """
    assert mm["monster_actions"][0x1E] == "選び直し"


def test_action_rates_have_eight_slots(mm, em):
    """賢さ4種 × **8枠**の確率がそろい、合計100%になること。

    ⚠ 枠は8つ。7と数えて外した（乱数がどの閾値も超えたときの
      「8番目」が既定の行動になる / bank4.asm:8078）。
    """
    rates = em["action_rates"]
    assert set(rates) == {0, 1, 2, 3}, rates.keys()
    for wisdom, probs in rates.items():
        assert len(probs) == 8, f"賢さ{wisdom} の枠が {len(probs)} 個"
        assert abs(sum(probs) - 100.0) < 0.05, f"賢さ{wisdom} の合計 {sum(probs)}"


def test_wiser_monsters_favor_the_first_slot(mm, em):
    """賢さが高いほど枠0に寄ること。

    ★「賢さ」という名前と挙動が一致していることの確認。
      逆になっていたら確率表の読み方が反転している。
    """
    first = [em["action_rates"][w][0] for w in (0, 1, 2, 3)]
    assert first == sorted(first), f"枠0の確率が賢さ順に増えていない: {first}"
    assert first[0] == pytest.approx(12.5, abs=0.05), "賢さ0 は均等のはず"
    assert first[3] > 35, f"賢さ3 の枠0 が {first[3]}%（もっと高いはず）"


def test_every_monster_has_eight_actions(mm, em):
    """全83体に賢さと8枠の行動があること。"""
    behavior = em["monster_behavior"]
    assert len(behavior) == 83
    actions = mm["monster_actions"]
    for mid, b in behavior.items():
        assert b["wisdom"] in (0, 1, 2, 3), f"0x{mid:02X} の賢さ {b['wisdom']}"
        assert len(b["actions"]) == 8, f"0x{mid:02X} の枠が {len(b['actions'])} 個"
        for aid in b["actions"]:
            assert aid in actions, f"0x{mid:02X} に未知の行動 0x{aid:02X}"


def test_healer_casts_heal_and_atlas_attacks_twice(mm, em):
    """ROM の中身が「名前どおり」であることの抜き取り検査。

    ★ホイミスライムがホイミを、アトラスが２回攻撃を持っていなければ
      枠の読み方（偶数=上位ニブル / 代替ビットの合成）が違う。
    """
    behavior = em["monster_behavior"]
    actions = mm["monster_actions"]

    healer = [actions[a] for a in behavior[0x06]["actions"]]
    assert healer.count("ホイミ") == 7, healer
    assert healer.count("通常攻撃") == 1, healer

    atlas = [actions[a] for a in behavior[0x4E]["actions"]]
    assert atlas.count("２回攻撃") == 7, atlas
    # 8枠目は「選び直し」＝実際には常に２回攻撃になる（公開データ 100%）
    assert atlas.count("選び直し") == 1, atlas


def test_denied_spells_are_only_the_known_three(mm):
    """★拒否リストが**勢いで増えていない**こと。

    拒否を増やすのは簡単だが、増やしすぎると「なぜ動かないのか」が分からなくなる。
    増やすときはここも直す＝理由を書く場所が強制される。
    """
    denied = sorted(sid for sid, info in mm["spells"].items()
                    if info.get("never_cast"))
    assert denied == [0x0C, 0x0F, 0x14], (
        f"拒否している呪文が変わった: {[f'0x{s:02X}' for s in denied]}"
    )
