"""まんたん設定モデルのテスト（2026-08-02 / 指示書 §15.1）。

★★ 守りたい契約 ★★

  1. 既定値のままで動く（設定ファイルが無くても困らない）
  2. ⚠⚠ **設定が壊れていても RetroUX を起動不能にしない**（指示書 §4.2）
     壊れた値は既定へ落とし、**理由を残す**（黙って直さない）
  3. 部分的な設定は、同梱の既定で埋める
  4. 保存で書きかけのファイルを残さない
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from retroux.core.mantan import (
    ITEM_POLICIES, MP_POLICIES, MantanSettings, from_dict, load, save,
    summary_lines,
)


# --- 1. 既定値（指示書 §3.3）------------------------------------------

def test_既定の目標HPは90パーセント():
    assert MantanSettings().target_hp_percent == 90
    assert MantanSettings().target_ratio == pytest.approx(0.9)


def test_やくそうの既定は呪文を優先():
    assert MantanSettings().herb_policy == "after_spells"


def test_どくけしそうの既定は呪文を優先():
    assert MantanSettings().antidote_policy == "after_spells"


def test_MP配分の既定は残存MP率を揃える():
    """★今回の新しい既定（指示書 §3.3・§14）。"""
    assert MantanSettings().mp_policy == "remaining_ratio_balance"


def test_戦術プロフィールの最低残存MPは既定でON():
    assert MantanSettings().use_tactics_reserve is True


def test_回復呪文と解毒は既定でON():
    s = MantanSettings()
    assert s.healing_spells_enabled is True
    assert s.poison_cure_enabled is True


# --- 2. 壊れた値（指示書 §4.2）----------------------------------------

def test_知らないpolicyは既定へ落ちて理由が残る():
    s, problems = from_dict({"items": {"herb": {"policy": "ぜんぶ使う"}}})
    assert s.herb_policy == "after_spells"
    assert any("ぜんぶ使う" in p for p in problems), problems


def test_policyが文字列でなくても止まらない():
    s, problems = from_dict({"mp_allocation": {"policy": 7}})
    assert s.mp_policy == "remaining_ratio_balance"
    assert problems


@pytest.mark.parametrize("bad", [0, 49, 101, 1000, -5])
def test_HP割合の範囲外は既定へ落ちる(bad):
    s, problems = from_dict({"target_hp_percent": bad})
    assert s.target_hp_percent == 90
    assert any(str(bad) in p for p in problems), problems


@pytest.mark.parametrize("ok", [50, 75, 90, 100])
def test_範囲内のHP割合はそのまま使う(ok):
    s, problems = from_dict({"target_hp_percent": ok})
    assert s.target_hp_percent == ok
    assert problems == []


def test_HP割合が文字列でも止まらない():
    s, problems = from_dict({"target_hp_percent": "きゅうわり"})
    assert s.target_hp_percent == 90
    assert problems


def test_真偽値でないものは既定へ落ちる():
    s, problems = from_dict({"healing_spells": {"enabled": "はい"}})
    assert s.healing_spells_enabled is True
    assert problems


def test_節の書き方が違っても止まらない():
    """⚠ `items` が辞書でない、のような形の崩れ。"""
    s, problems = from_dict({"items": "やくそう"})
    assert s.herb_policy == "after_spells"
    assert problems


def test_中身がまるごと読めなくても既定で動く():
    s, problems = from_dict("これは設定ではない")
    assert s == MantanSettings()
    assert problems


def test_Noneなら既定のまま_理由も出ない():
    s, problems = from_dict(None)
    assert s == MantanSettings()
    assert problems == []


def test_知らないschema_versionは理由を残して読む():
    s, problems = from_dict({"schema_version": 99, "target_hp_percent": 80})
    assert s.target_hp_percent == 80        # ★読めるところは読む
    assert any("99" in p for p in problems)


# --- 3. 部分設定のマージ（指示書 §4.1）--------------------------------

def test_書いてある項目だけ上書きする():
    base = MantanSettings(target_hp_percent=70, mp_policy="most_mp")
    s, problems = from_dict({"target_hp_percent": 100}, base)
    assert s.target_hp_percent == 100       # ★書いてあるので上書き
    assert s.mp_policy == "most_mp"         # ★書いていないので base のまま
    assert problems == []


def test_全部のpolicyが受け付けられる():
    for p in ITEM_POLICIES:
        s, problems = from_dict({"items": {"herb": {"policy": p}}})
        assert s.herb_policy == p
        assert problems == []
    for p in MP_POLICIES:
        s, problems = from_dict({"mp_allocation": {"policy": p}})
        assert s.mp_policy == p
        assert problems == []


# --- 4. 読み書き（指示書 §5.4・§15.1）---------------------------------

def test_保存して読み直すと同じ値になる(tmp_path):
    path = tmp_path / "mantan.yaml"
    want = MantanSettings(
        target_hp_percent=75, herb_policy="before_spells",
        antidote_policy="disabled", mp_policy="spent_mp_balance",
        healing_spells_enabled=False, poison_cure_enabled=False,
        use_tactics_reserve=False)
    save(want, path)
    got, problems, used = load(user_path=path,
                               plugin_path=tmp_path / "ない.yaml")
    assert got == want
    assert problems == []
    assert used is True


def test_設定ファイルが無ければ既定で動く(tmp_path):
    got, problems, used = load(user_path=tmp_path / "ない.yaml",
                               plugin_path=tmp_path / "これも無い.yaml")
    assert got == MantanSettings()
    assert used is False
    assert problems == []


def test_YAMLが壊れていても既定へ戻り理由が残る(tmp_path):
    """⚠⚠ **ここが落ちると、設定を1文字間違えただけで遊べなくなる。**"""
    path = tmp_path / "mantan.yaml"
    path.write_text("target_hp_percent: [壊れて\n  います:\n", encoding="utf-8")
    got, problems, used = load(user_path=path,
                               plugin_path=tmp_path / "ない.yaml")
    assert got == MantanSettings()
    assert used is False
    assert any("壊れ" in p for p in problems), problems


def test_保存は書きかけを残さない(tmp_path):
    path = tmp_path / "mantan.yaml"
    save(MantanSettings(), path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "mantan.yaml"]
    assert leftovers == [], leftovers


def test_保存したYAMLは人が読める形(tmp_path):
    path = tmp_path / "mantan.yaml"
    save(MantanSettings(target_hp_percent=80), path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#")             # ★何のファイルか書いてある
    data = yaml.safe_load(text)
    assert data["target_hp_percent"] == 80
    assert data["items"]["herb"]["policy"] == "after_spells"
    assert data["schema_version"] == 1


def test_同梱の設定を土台にして利用者の設定を重ねる(tmp_path):
    plugin = tmp_path / "config.yaml"
    plugin.write_text(
        yaml.safe_dump({"mantan": {"target_hp_percent": 60,
                                   "mp_allocation": {"policy": "most_mp"}}}),
        encoding="utf-8")
    user = tmp_path / "mantan.yaml"
    user.write_text(yaml.safe_dump({"target_hp_percent": 100}),
                    encoding="utf-8")
    got, problems, used = load(user_path=user, plugin_path=plugin)
    assert got.target_hp_percent == 100     # ★利用者が勝つ
    assert got.mp_policy == "most_mp"       # ★同梱の値が残る
    assert used is True
    assert problems == []


def test_同梱の設定の不備は利用者のものと区別して出す(tmp_path):
    plugin = tmp_path / "config.yaml"
    plugin.write_text(
        yaml.safe_dump({"mantan": {"mp_allocation": {"policy": "でたらめ"}}}),
        encoding="utf-8")
    got, problems, _used = load(user_path=tmp_path / "ない.yaml",
                                plugin_path=plugin)
    assert got.mp_policy == "remaining_ratio_balance"
    assert any(p.startswith("同梱の設定:") for p in problems), problems


# --- 5. ログの概要（指示書 §11.1）-------------------------------------

def test_実行開始時の概要に方針が出る():
    lines = summary_lines(MantanSettings())
    joined = "\n".join(lines)
    assert "目標90%" in joined
    assert "残存MP率を揃える" in joined
    assert "戦術プロフィールを使用" in joined


def test_保存先は既存の規則に合わせてある():
    """★`config/layout.yaml` `config/keybindings.yaml` と同じ場所。

    ⚠ 指示書 §3.1 は `user/manten.yaml` を推しているが、
      「既存のユーザー設定ディレクトリ規則があれば、それに合わせること」
      とも書いてある。★このプロジェクトの規則は `config/*.yaml`。
    """
    from retroux.core.mantan import USER_PATH
    parts = pathlib.Path(USER_PATH).parts
    assert parts[-2:] == ("config", "mantan.yaml"), USER_PATH
