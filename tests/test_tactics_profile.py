"""戦術プロフィールの土台（仕様書 4章・10章 / 18.1・18.2）。

★★ **確かめたいことの中心** ★★

  1. 作成・保存・読み込み・複製・削除・**選択が再起動後も残る**
  2. ⚠ 見本（プリセット）は**消せない・上書きできない**（複製して編集）
  3. ⚠ **既定値では未実装フェーズの項目を持たない**
     （持つと同梱の見本を検証しただけで警告が54件出た）
  4. AI へ渡すのは**実装済みフェーズの項目だけ**（仕様書 20章）
  5. ⚠ 知らないキー（新しい版で作った設定）を**黙って捨てない**
  6. 保存に失敗しても**元のファイルを壊さない**
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.tactics import (
    CHARACTER_IDS, TacticsProfile, TacticsRepository, validate_profile,
)
from retroux.core.tactics import models
from retroux.core.tactics.profile_repository import build_presets


@pytest.fixture
def repo(tmp_path) -> TacticsRepository:
    return TacticsRepository(tmp_path / "profiles")


# --- 見本 -------------------------------------------------------------

def test_the_four_presets_are_there(repo):
    """仕様書 4.5 の見本。

    ⚠ 2026-08-04 に「いのちをだいじに」を足しました（指示書 §3・§8）。
      ★数を直書きせず、`build_presets()` と突き合わせます（表を写さない）。
    """
    from retroux.core.tactics.profile_repository import build_presets

    names = [p.name for p in repo.list_profiles()]
    assert names == [p.name for p in build_presets()]
    # ★依頼者が名指しした作戦が居ること（2026-08-11: 戦略名に合わせて改名）
    assert "ダンジョン探索" in names
    assert "レベル上げ" in names


def test_every_preset_validates_without_a_single_warning(repo):
    """★★ **同梱の見本が警告を1つも出さないこと。** ★★

    ⚠ 以前は既定値に未実装フェーズの項目まで入れていたため、
      見本を検証しただけで「いまは効きません」が**54件**出た。
      毎回出る通知は読まれない通知になり、本当に見たい警告が埋もれる。
    """
    for prof in repo.list_profiles():
        result = validate_profile(prof)
        assert result.errors == [], f"{prof.name}: {result.lines()}"
        assert result.unknowns == [], f"{prof.name}: {result.lines()}"
        assert result.warnings == [], f"{prof.name}: {result.lines()}"


def test_a_preset_cannot_be_deleted(repo):
    """★見本は消せない（仕様書 4.5）。"""
    preset = repo.get("balanced")
    assert preset.preset
    assert repo.delete(preset) is False
    assert repo.get("balanced") is not None
    assert any("消せません" in p for p in repo.problems)


def test_a_preset_cannot_be_overwritten(repo):
    """★見本は上書きできない。**複製してから編集する。**"""
    preset = repo.get("balanced")
    preset.set("lorasia", "healing", "ally_hp_threshold", 99)
    assert repo.save(preset) is False
    assert any("複製" in p for p in repo.problems)


def test_a_copy_of_a_preset_can_be_edited(repo):
    """★複製は `preset` を引き継がない（編集できる）。"""
    copied = repo.duplicate(repo.get("balanced"), "わたしの作戦")
    assert copied.preset is False
    copied.set("lorasia", "healing", "ally_hp_threshold", 99)
    assert repo.save(copied), repo.problems
    assert repo.get(copied.id).get("lorasia", "healing",
                                   "ally_hp_threshold") == 99


def test_every_preset_covers_all_three_characters(repo):
    for prof in repo.list_profiles():
        assert set(prof.characters) == set(CHARACTER_IDS), prof.name


def test_the_manual_preset_is_gone(repo):
    """⚠ 2026-08-19: 見本「手動中心」(manual) は廃止（RX-0067）。

    ★一覧に出ないこと。AI操作OFF は AUTO ボタンで足りるため。
    """
    assert repo.get("manual") is None
    assert "手動中心" not in [p.name for p in repo.list_profiles()]


# --- 作成・保存・複製・削除 -------------------------------------------

def test_a_new_profile_starts_from_the_defaults(repo):
    prof = repo.create("あたらしい作戦")
    assert prof.name == "あたらしい作戦"
    assert prof.get("lorasia", "healing", "ally_hp_threshold") == 50
    assert prof.schema_version == models.SCHEMA_VERSION


def test_saving_then_reading_gives_the_same_values(repo):
    prof = repo.create("保存の試し")
    prof.set("moonbrooke", "resources", "reserve_mp", 33)
    prof.set("moonbrooke", "safety", "fallback_action",
             models.FallbackAction.DEFEND)
    assert repo.save(prof), repo.problems
    again = repo.get(prof.id)
    assert again.get("moonbrooke", "resources", "reserve_mp") == 33
    assert again.get("moonbrooke", "safety", "fallback_action") == "defend"


def test_a_duplicate_gets_a_new_id_and_name(repo):
    first = repo.create("同じ名前")
    repo.save(first)
    second = repo.duplicate(first, "同じ名前")
    assert second.id != first.id
    assert second.name != first.name, "★画面で見分けられない名前になっている"


@pytest.mark.parametrize(("before", "after"), [
    # ⚠⚠ **英数字の名前で試すこと。** ★これを落として実際に穴になった。
    #   日本語名だと `slug()` が変換に失敗して元の `id` を返すため、
    #   「名前から id を作り直す」という壊し方でも id が変わらず、
    #   **壊しても試験が緑**だった（`break_tactics.py` で見つかった）。
    ("before_plan", "after_plan"),
    ("まえの名前", "あとの名前"),
])
def test_renaming_keeps_the_file_name(repo, before, after):
    """★`id`（ファイル名）は変えない。

    ⚠ 変えると別ファイルになり、古いほうが残る。
      「名前を変えたら2つになった」は分かりにくい壊れ方。
    """
    prof = repo.create(before)
    repo.save(prof)
    old_id = prof.id
    assert repo.rename(prof, after)
    repo.save(prof)
    assert prof.id == old_id, "★名前を変えたら id（ファイル名）も変わっている"
    made = [p for p in repo.list_profiles() if not p.preset]
    assert len(made) == 1, f"★2つになっている: {[p.id for p in made]}"
    assert made[0].name == after


def test_an_empty_name_is_refused(repo):
    prof = repo.create("なまえ")
    assert repo.rename(prof, "   ") is False
    assert prof.name == "なまえ"


def test_deleting_removes_the_file(repo):
    prof = repo.create("消すもの")
    repo.save(prof)
    assert repo.path_for(prof.id).exists()
    assert repo.delete(prof)
    assert not repo.path_for(prof.id).exists()


def test_a_dangerous_id_is_refused(repo):
    """⚠⚠ `id` は**ファイル名になる**。`../` を作らせない（仕様書 13章）。"""
    prof = TacticsProfile.create("../../etc/passwd", "わるいID")
    with pytest.raises(ValueError):
        repo.path_for(prof.id)
    assert repo.save(prof) is False


# --- 選択（再起動後も残る）-------------------------------------------

def test_the_selected_profile_survives_a_restart(repo, tmp_path):
    """★受入条件10: 選択プロフィールが再起動後も保持される。"""
    prof = repo.duplicate(repo.get("no_spells"), "わたしの戦術")
    repo.save(prof)
    assert repo.set_active(prof.id)

    # ★別のインスタンスで読み直す（=再起動と同じ）
    again = TacticsRepository(tmp_path / "profiles")
    assert again.active_id() == prof.id
    assert again.active().name == "わたしの戦術"


def test_no_selection_falls_back_to_the_default_preset(repo):
    """⚠ `None` を返さない。

    返すと呼ぶ側が「AIを止める」のか「既定で動く」のか決められない。
    **既定の見本で動く**とはっきりさせる。
    """
    assert repo.active_id() is None
    assert repo.active().id == "balanced"


def test_a_missing_selection_says_so_and_falls_back(repo):
    repo.set_active("nonexistent_profile")
    assert repo.active().id == "balanced"
    assert any("見つかりません" in p for p in repo.problems)


def test_deleting_the_selected_profile_clears_the_selection(repo):
    prof = repo.create("選んでから消す")
    repo.save(prof)
    repo.set_active(prof.id)
    repo.delete(prof)
    assert repo.active_id() is None
    assert repo.active().id == "balanced"


# --- AI へ渡す形（フェーズを混ぜない）--------------------------------

def test_only_implemented_phases_reach_the_ai(repo):
    """★★ **未実装の項目を AI へ渡さない**（仕様書 20章）。 ★★

    渡すと、あとで実装したときに
    **設定していない値で急に効き始める**。
    """
    prof = repo.get("no_spells")
    prof.set("samaltria", "actions", "support_spell", True)
    prof.set("samaltria", "actions", "group_spell_min_enemies", 2)
    prof.set("samaltria", "targeting", "prefer_summoner", True)
    payload = prof.for_ai()["characters"]["samaltria"]
    assert "healing" in payload and "resources" in payload
    # ⚠ フェーズ4の節はまるごと入っていないこと
    assert "targeting" not in payload
    # ★節ごと落とすのではなく、**未実装の項目だけ**落とすこと。
    assert "support_spell" not in payload["actions"]
    assert "group_spell_min_enemies" not in payload["actions"]
    assert "attack_spell" in payload["actions"]


def test_the_payload_says_which_phases_are_live(repo):
    """★Lua のログに出して、利用者が「いまどこまで効くか」を確かめられるように。"""
    payload = repo.get("balanced").for_ai()
    assert payload["_phases"] == list(models.IMPLEMENTED_PHASES)


def test_the_payload_keeps_percentages_as_integers(repo):
    """⚠ %（0〜100）で渡し、割合への変換は **Lua 側1か所**でやる。

    両側で変換すると 50 倍ずれる。
    """
    payload = repo.get("balanced").for_ai()
    healing = payload["characters"]["moonbrooke"]["healing"]
    # ★0〜100 の整数のまま渡すこと（0.5 のような割合にしない）
    assert healing["ally_hp_threshold"] == 50
    assert isinstance(healing["ally_hp_threshold"], int)


def test_the_no_spells_preset_really_uses_no_spells(repo):
    """★見本の名前と中身が食い違わないこと（2026-07-31）。

    ⚠ ふだんは「仲間を回復しない」より**緊急回復を優先**する
      （守ると設定どおりに全滅するため）。しかしこの見本は
      **名前のとおり呪文を使わない**のが目的なので、そこも切ってある。
    """
    healing = repo.get("no_spells").for_ai()["characters"]["moonbrooke"]["healing"]
    assert healing["self_enabled"] is False
    assert healing["ally_enabled"] is False
    # ⚠ 緊急回復は 2026-07-31 に廃止したので、項目そのものが無い
    assert "emergency_hp_threshold" not in healing


def test_the_ai_payload_agrees_with_the_yaml(repo):
    """★★ **画面・YAML・AIへ渡す形の3つが同じことを言う。** ★★

    ⚠ 実際に食い違った: YAML はローレシアの `healing` を省いていたのに、
      `for_ai()` は既定値を詰めて渡していた。
      画面では灰色なのに Lua には値が行っている＝
      「設定していないのに設定されている」状態。
    """
    prof = repo.get("balanced")
    payload = prof.for_ai()["characters"]
    for cid in CHARACTER_IDS:
        for field in models.FIELDS:
            if not field.implemented or field.section == "root":
                continue
            in_payload = field.key in (payload[cid].get(field.section) or {})
            meaningful = models.not_applicable(
                cid, field.section, field.key) is None
            assert in_payload == meaningful, (
                f"{cid}.{field.section}.{field.key}: "
                f"渡す={in_payload} 意味がある={meaningful}")


def test_lorasia_gets_no_healing_in_the_ai_payload(repo):
    payload = repo.get("balanced").for_ai()["characters"]
    assert "healing" not in payload["lorasia"]
    assert "resources" not in payload["lorasia"]
    # ★意味のある節は渡っている
    assert "items" in payload["lorasia"]
    assert payload["lorasia"]["enabled"] is True


# --- 既定値と未実装フェーズ -------------------------------------------

def test_the_defaults_do_not_include_unimplemented_fields():
    """★未実装の項目は既定値に入れない（検証のたびに警告が出るのを防ぐ）。

    ⚠ 2026-08-03、`actions` 節が**丸ごと未実装**ではなくなりました。
      「ガンガン行こうぜ」（`actions.attack_spell`）だけが実装済みです。
      ★節の有無ではなく、**項目ごと**に見ます。
    """
    made = models.default_character()
    assert "targeting" not in made
    assert made["role"] == models.Role.BALANCED.value
    # ★実装済みの1項目だけが入る（攻撃呪文を使う）
    assert made["actions"] == {"attack_spell": False}, \
        "★未実装の項目が既定値に入っている"


def test_all_phases_defaults_cover_every_remaining_field():
    """★★ 2026-08-10（UI整理 Phase 2）：未実装フィールドを全削除した。★★

    「既知だが未実装」の項目がもう無いので、`all_phases=True` でも
    実装済みと同じ項目になる。★削除したセクション（対象選択・連携）は
    既定値に出ない。
    """
    made = models.default_character(all_phases=True)
    assert made["actions"] == {"attack_spell": False}
    assert "targeting" not in made, "★削除したセクションが残っている"
    assert "teamwork" not in made


def test_reading_a_missing_field_gives_its_default(repo):
    """★古いプロフィール（項目が無い）でも動くこと。"""
    prof = TacticsProfile.create("bare", "からっぽ")
    prof.characters["lorasia"] = {}
    assert prof.get("lorasia", "healing", "ally_hp_threshold") == 50
    assert prof.get("lorasia", "root", "enabled") is True


def test_every_field_has_a_label_and_a_known_kind():
    """★画面が出せない項目を作らない。"""
    for field in models.FIELDS:
        assert field.label, field.key
        assert field.kind in ("bool", "int", "enum"), field.key
        if field.kind == "enum":
            assert field.enum_cls is not None, field.key
        if field.kind == "int":
            assert field.minimum is not None, field.key


def test_no_two_fields_share_a_path():
    """⚠ 同じ `(section, key)` が2つあると、片方が黙って消える。"""
    paths = [(f.section, f.key) for f in models.FIELDS]
    assert len(paths) == len(set(paths))


def test_every_character_has_a_japanese_label():
    assert set(models.CHARACTER_LABELS) == set(CHARACTER_IDS)


# --- 知らないキーを捨てない -------------------------------------------

def test_an_unknown_key_survives_a_save_and_load(repo):
    """★★ **新しい版で作った設定を、古い版が黙って壊さない。** ★★"""
    prof = repo.create("未来の設定つき")
    prof.characters["lorasia"]["future_section"] = {"future_key": 42}
    assert repo.save(prof), repo.problems
    again = repo.get(prof.id)
    assert again.characters["lorasia"]["future_section"]["future_key"] == 42


def test_the_yaml_keeps_the_field_order(repo):
    """★並びを固定するのは Git の差分を読めるようにするため（仕様書 10.2）。

    ⚠ **1人ぶんの中で**比べる。文字列全体で比べてはいけない
      （ローレシアには `resources` が無いので、`items` のほうが先に現れる）。
    """
    from retroux.core.tactics.import_export import profile_to_yaml

    text = profile_to_yaml(repo.get("balanced"))
    block = text[text.index("  moonbrooke:"):]
    for earlier, later in (("enabled", "role"), ("role", "safety"),
                           ("safety", "healing"), ("healing", "resources"),
                           ("resources", "items")):
        assert block.index(earlier) < block.index(later), \
            f"{earlier} が {later} より後にある"


def test_lorasia_gets_no_meaningless_healing_settings(repo):
    """★★ 意味の無い項目を持たせない。 ★★

    ⚠ 持たせると、YAML を読んだ人が
      「なぜローレシアに『回復開始HP』があるのか」と迷う。
      ローレシアは DQ2 では**呪文を覚えない**。
    """
    prof = repo.get("balanced")
    assert "healing" not in prof.characters["lorasia"]
    assert "resources" not in prof.characters["lorasia"]
    # ★意味のある項目は入っている
    assert "items" in prof.characters["lorasia"]
    assert prof.characters["lorasia"]["role"] == "attack"
    # ★他の2人には入っている
    assert "healing" in prof.characters["moonbrooke"]


def test_reading_a_not_applicable_field_still_gives_a_default(repo):
    """★無くても読める（呼ぶ側が場合分けしなくてよい）。"""
    prof = repo.get("balanced")
    assert prof.get("lorasia", "healing", "ally_hp_threshold") == 50


# --- 壊れない ---------------------------------------------------------

def test_a_repository_in_an_unwritable_place_does_not_raise(tmp_path):
    """⚠ 置き場が作れなくても**見本だけで動く**（ゲームは遊べる）。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("これはファイルなのでフォルダを作れない", encoding="utf-8")
    repo = TacticsRepository(blocker / "profiles")
    assert repo.ensure_dir() is False
    assert len(repo.list_profiles()) == len(build_presets()), "見本が出ていない"
    assert repo.active().id == "balanced"
    assert repo.save(repo.create("保存できないもの")) is False


def test_a_broken_file_is_skipped_and_the_rest_are_read(repo):
    repo.ensure_dir()
    good = repo.create("よいもの")
    repo.save(good)
    (repo.dir / "broken.yaml").write_text("これは: YAML ではない: {{{",
                                          encoding="utf-8")
    names = [p.name for p in repo.list_profiles()]
    assert "よいもの" in names
    assert any("broken.yaml" in p for p in repo.problems)


def test_installing_presets_does_not_overwrite_hand_edits(repo):
    """⚠ 手で直したファイルを上書きしない。"""
    repo.ensure_dir()
    path = repo.dir / "balanced.yaml"
    path.write_text("# 手で書いた\nschema_version: 1\n"
                    "profile: { id: balanced, name: 手で直した }\n"
                    "characters: { lorasia: {} }\n", encoding="utf-8")
    placed = repo.install_presets()
    # ★見本の数から1件（手で書いた balanced）を引いた数だけ置かれる。
    #   ⚠ 数を直書きしない（見本が増えるたびに落ちる / 表を写さない）。
    assert placed == len(build_presets()) - 1, "既にある1件を上書きしている"
    assert "手で直した" in path.read_text(encoding="utf-8")


def test_unique_id_and_name_do_not_collide(repo):
    for n in range(4):
        prof = repo.create("同じ名前")
        assert repo.save(prof), repo.problems
    made = [p for p in repo.list_profiles() if not p.preset]
    # ⚠ 見本の数とは無関係。**作った数**と同じだけ別々になること
    assert len({p.id for p in made}) == 4
    assert len({p.name for p in made}) == 4


def test_presets_returned_are_copies(repo):
    """⚠ 見本の実体を渡すと、画面で触ったときに元が変わる。"""
    first = repo.presets[0]
    first.set("lorasia", "healing", "ally_hp_threshold", 1)
    assert repo.get(first.id).get("lorasia", "healing",
                                  "ally_hp_threshold") != 1


def test_build_presets_is_deterministic():
    """★見本はコードから作る。呼ぶたびに同じであること。"""
    a = {p.id: p.to_dict()["characters"] for p in build_presets()}
    b = {p.id: p.to_dict()["characters"] for p in build_presets()}
    assert a == b


def test_the_summary_is_readable_japanese(repo):
    """★人が読む要約（仕様書 11.4）。英語の値を出さない。"""
    lines = repo.get("no_spells").summary_lines()
    text = "\n".join(lines)
    assert "呪文を使わない" in text
    assert "ムーンブルク王女" in text
    assert "MP温存" in text
    # ★★ 「しない」も書くこと（沈黙で伝えない / 2026-07-31）★★
    assert "仲間を回復しない" in text, "回復を切ったことが要約に出ていない"
    assert "自分を回復しない" in text
    for raw in ("healer", "attack", "minimum_sufficient", "defend"):
        assert raw not in text, f"英語の値がそのまま出ている: {raw}"


def test_the_summary_of_a_manual_character_says_so(repo):
    """★役割「手動」(AI操作OFF) の人は要約でそう言う。

    ⚠ 2026-08-19: 見本「手動中心」を廃止（RX-0067）したので、★見本ではなく
      **作った作戦**で手動役割を立てて確かめる（役割 Role.MANUAL 自体は残る）。
    """
    prof = repo.create("手動の試し")
    for cid in CHARACTER_IDS:
        prof.set(cid, "root", "role", models.Role.MANUAL)
        prof.set(cid, "root", "enabled", False)
    lines = prof.summary_lines()
    assert sum(1 for line in lines if "AI操作しない" in line) == 3
