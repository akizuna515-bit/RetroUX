"""戦術プロフィールの検証と YAML 入出力（仕様書 12章・13章 / 18.3〜18.5）。

★★ **確かめたいことの中心** ★★

  1. ⚠⚠ **範囲外は自動補正せずエラー**（仕様書 12.4）
     勝手に 100 へ丸めた値で戦うと、設定した戦術と違う戦い方になる
  2. ⚠⚠ **未知項目を勝手に無視しない**（仕様書 12.5）
     新しい版で作った戦術が、古い版で別物として動く
  3. ⚠⚠ **`yaml.safe_load` だけを使う**（仕様書 13章）
     もらったテキストを読むので、任意のコードを評価してはいけない
  4. 巨大な入力・異常な深さを拒否する
  5. ID/名前が重複したら**既定は別名保存**（上書きで消さない）
  6. 出して読み直したら同じ値になる
  7. 保存に失敗しても**元のファイルを壊さない**
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.tactics import TacticsRepository, validate_raw
from retroux.core.tactics import models
from retroux.core.tactics.import_export import (
    CONFLICT_CANCEL, CONFLICT_OVERWRITE, CONFLICT_RENAME, profile_summary,
    profile_to_yaml, read_profile_file, read_profile_text, resolve_conflict,
    write_profile_file,
)
from retroux.core.tactics.profile_validator import MAX_BYTES, MAX_DEPTH

MINIMAL = """
schema_version: 1
profile:
  id: my_plan
  name: わたしの作戦
characters:
  lorasia:
    enabled: true
    role: attack
  samaltria:
    enabled: true
    role: balanced
  moonbrooke:
    enabled: true
    role: healer
    healing:
      ally_hp_threshold: 70
"""


@pytest.fixture
def repo(tmp_path) -> TacticsRepository:
    return TacticsRepository(tmp_path / "profiles")


# --- 正常 -------------------------------------------------------------

def test_a_normal_yaml_is_read(repo):
    preview = read_profile_text(MINIMAL, repository=repo)
    assert preview.ok, preview.result.lines()
    assert preview.profile.name == "わたしの作戦"
    assert preview.profile.get("moonbrooke", "healing",
                               "ally_hp_threshold") == 70


def test_missing_characters_are_filled_with_defaults_and_reported():
    """★足りない人は既定で埋めるが、**足したことを言う**。"""
    text = MINIMAL.replace("""  moonbrooke:
    enabled: true
    role: healer
    healing:
      ally_hp_threshold: 70
""", "")
    preview = read_profile_text(text)
    assert preview.ok
    assert "moonbrooke" in preview.profile.characters
    assert any("既定値にしました" in str(i) for i in preview.result.warnings)


def test_export_then_import_keeps_the_values(repo):
    """★受入条件18: 再エクスポートで内容が保たれる。"""
    original = repo.duplicate(repo.get("no_spells"), "行き来の試し")
    original.set("samaltria", "resources", "reserve_mp", 7)
    text = profile_to_yaml(original)
    back = read_profile_text(text)
    assert back.ok, back.result.lines()
    assert back.profile.to_dict()["characters"] == \
        original.to_dict()["characters"]


def test_a_japanese_name_and_description_survive(repo):
    """★日本語のプロフィール名・説明文（仕様書 18.4）。"""
    prof = repo.create("ボス戦・全力／MP解放")
    prof.description = "アトラス〜シドー用。ムーンブルクは回復に専念"
    text = profile_to_yaml(prof)
    back = read_profile_text(text)
    assert back.profile.name == "ボス戦・全力／MP解放"
    assert back.profile.description.startswith("アトラス")


def test_the_exported_yaml_explains_itself(repo):
    """★もらった人が「これは何で、どう使うか」を分かるように。"""
    text = profile_to_yaml(repo.get("balanced"))
    assert "RetroUX 戦術プロフィール" in text
    assert "手で編集できます" in text
    # ★どこまで効くかも書く
    assert "フェーズ1" in text


# --- 値の範囲（自動補正しない）----------------------------------------

@pytest.mark.parametrize(("line", "expect"), [
    ("      ally_hp_threshold: 101", "100 以下"),
    ("      ally_hp_threshold: -1", "0 以上"),
    ("      self_hp_threshold: 200", "100 以下"),
])
def test_an_out_of_range_percentage_is_an_error_not_a_correction(line, expect):
    """★★ **勝手に直さない**（仕様書 12.4）。 ★★

    100 へ丸めた値で戦うと、設定した戦術と違う戦い方になる。
    しかも本人は気づけない。
    """
    text = MINIMAL.replace("      ally_hp_threshold: 70", line)
    preview = read_profile_text(text)
    assert not preview.ok
    assert any(expect in i.message for i in preview.result.errors), \
        preview.result.lines()
    assert preview.profile is None, "★壊れたものからプロフィールを作っている"


def test_a_negative_reserve_mp_is_an_error():
    text = MINIMAL + "    resources:\n      reserve_mp: -5\n"
    preview = read_profile_text(text)
    assert not preview.ok
    assert any("0 以上" in i.message for i in preview.result.errors)


def test_a_value_below_the_minimum_is_an_error():
    """★下限を割る値はエラー（自動補正しない / 仕様書 12.4）。

    ⚠ 2026-08-10: 元は `group_spell_min_enemies: 0` で確かめていたが、
      その項目を削除したので、残っている `reserve_mp`（最低0）で確かめる。
    """
    text = MINIMAL + "    resources:\n      reserve_mp: -1\n"
    preview = read_profile_text(text)
    assert not preview.ok
    assert any("0 以上" in i.message for i in preview.result.errors)


def test_a_boolean_where_a_number_belongs_is_an_error():
    """⚠ Python では `True == 1`。**bool を整数として通さない**。"""
    text = MINIMAL.replace("      ally_hp_threshold: 70",
                           "      ally_hp_threshold: true")
    preview = read_profile_text(text)
    assert not preview.ok
    assert any("整数ではありません" in i.message
               for i in preview.result.errors)


def test_a_number_where_a_flag_belongs_is_an_error():
    text = MINIMAL.replace("    enabled: true", "    enabled: 1", 1)
    preview = read_profile_text(text)
    assert not preview.ok
    assert any("true / false" in i.message for i in preview.result.errors)


def test_an_unknown_role_is_an_error_with_the_allowed_values():
    """★何が使えるかを一緒に出す（直せるように）。"""
    text = MINIMAL.replace("role: attack", "role: すごく強い")
    preview = read_profile_text(text)
    assert not preview.ok
    message = " ".join(i.message for i in preview.result.errors)
    assert "知らない値" in message
    assert "conserve_mp" in message, "★使える値を出していない"


# --- 必須項目・版 -----------------------------------------------------

def test_a_missing_schema_version_is_an_error():
    preview = read_profile_text(MINIMAL.replace("schema_version: 1\n", ""))
    assert not preview.ok
    assert any(i.where == "schema_version" for i in preview.result.errors)


def test_a_future_schema_version_is_refused_not_guessed():
    """★★ **新しい版を勝手に読まない**（仕様書 10.3）。 ★★"""
    preview = read_profile_text(MINIMAL.replace("schema_version: 1",
                                               "schema_version: 99"))
    assert not preview.ok
    message = " ".join(i.message for i in preview.result.errors)
    assert "知らない版" in message
    assert "更新" in message, "★どうすればよいかを書いていない"


def test_a_missing_profile_id_is_an_error():
    preview = read_profile_text(MINIMAL.replace("  id: my_plan\n", ""))
    assert not preview.ok
    assert any(i.where == "profile.id" for i in preview.result.errors)


@pytest.mark.parametrize("bad_id", [
    "../../etc/passwd", "My Plan", "作戦", "a" * 100, "-leading",
])
def test_a_dangerous_or_odd_id_is_refused(bad_id):
    """⚠⚠ `id` は**ファイル名になる**（仕様書 13章）。"""
    preview = read_profile_text(MINIMAL.replace("id: my_plan", f"id: '{bad_id}'"))
    assert not preview.ok
    assert any(i.where == "profile.id" for i in preview.result.errors)


def test_an_unknown_character_is_an_error():
    """★誰の設定か決まらないので通さない。"""
    text = MINIMAL + "  hargon:\n    enabled: true\n"
    preview = read_profile_text(text)
    assert not preview.ok
    message = " ".join(i.message for i in preview.result.errors)
    assert "知らないキャラクター" in message
    assert "moonbrooke" in message, "★使える名前を出していない"


# --- 未知項目（勝手に無視しない）--------------------------------------

def test_an_unknown_key_is_reported_and_blocks_by_default():
    """★★ **勝手に無視しない**（仕様書 12.5）。 ★★"""
    text = MINIMAL + "    future_thing:\n      new_key: 1\n"
    preview = read_profile_text(text)
    assert preview.result.unknowns, "★未知項目を見つけていない"
    # ★既定ではインポートできない
    assert preview.can_import() is False
    # ★利用者が明示的に許せばできる
    assert preview.can_import(allow_unknown=True) is True


def test_an_unknown_top_level_key_is_reported():
    preview = read_profile_text(MINIMAL + "extra_root: 1\n")
    assert any(i.where == "extra_root" for i in preview.result.unknowns)


def test_there_are_no_unimplemented_known_fields_anymore():
    """★★ 2026-08-10（UI整理 Phase 2）：未実装フィールドを全削除した。★★

    元は「既知だが未実装のフィールドは警告つきで読める」を確かめていた
    （例: support_spell）。その手の項目を全部消したので、今は**残っている
    全フィールドが実装済み**であることを固定する。

    ⚠ 昔の YAML に残る旧キー（support_spell 等）は『未知の項目』として
      扱われる（下の unknown のテスト）。★エラーで落とさない。
    """
    from retroux.core.tactics import models

    assert all(f.implemented for f in models.FIELDS), \
        "★未実装フィールドが残っている（棚卸しの方針と食い違う）"

    # ★旧キーは「未知の項目」になる（警告ではなく unknown）。落ちないこと。
    text = MINIMAL + "    actions:\n      support_spell: true\n"
    preview = read_profile_text(text)
    assert preview.profile is not None, "★読み込み自体は成功する"
    assert any(i.where.endswith("support_spell")
               for i in preview.result.unknowns), "★未知の項目として拾う"


# --- 安全（もらったテキストを読む）------------------------------------

def test_yaml_that_would_build_a_python_object_is_refused():
    """★★ **`yaml.safe_load` だけを使う**（仕様書 13章）。 ★★

    `yaml.load` / `unsafe_load` なら任意の Python オブジェクトが作れてしまう。

    ⚠⚠ **最初この試験は穴だった**（`break_tactics.py` で見つかった）。
      前の版は `profile:` そのものを Python オブジェクトにしていたので、
      `unsafe_load` でも「profile がマッピングではない」というエラーになり、
      **コードが動いたのに試験は通った**。

    → **`unsafe_load` なら正しいプロフィールが出来上がる**形にする。
      そうすれば「読めてしまったこと」自体を捕まえられる。
    """
    evil = ("schema_version: 1\n"
            "profile:\n"
            "  id: taken_over\n"
            "  name: !!python/object/apply:builtins.str ['のっとられた']\n"
            "characters:\n"
            "  lorasia:\n"
            "    enabled: true\n")
    preview = read_profile_text(evil)
    # ★安全に読んでいれば、そもそも YAML として読めない
    assert not preview.ok, "★Python オブジェクトを作る YAML が読めてしまった"
    assert preview.profile is None
    assert any("YAML として読めません" in i.message
               for i in preview.result.errors), preview.result.lines()


def test_a_yaml_tag_that_calls_os_system_is_refused():
    """★副作用のあるものも当然拒否する（上と合わせて2方向から）。"""
    evil = ("schema_version: 1\n"
            "profile:\n"
            "  id: evil\n"
            "  name: !!python/object/apply:os.system ['echo pwned']\n"
            "characters: {}\n")
    preview = read_profile_text(evil)
    assert not preview.ok
    assert preview.profile is None


def test_a_huge_input_is_refused():
    """★上限を置く（仕様書 13章）。"""
    preview = read_profile_text("a: 1\n" * (MAX_BYTES // 2))
    assert not preview.ok
    assert any("大きすぎます" in i.message for i in preview.result.errors)


def test_a_deeply_nested_input_is_refused():
    """★異常な深さを拒否する（仕様書 13章）。"""
    body = "schema_version: 1\nprofile: {id: a, name: a}\ncharacters:\n"
    nested = "  lorasia:\n"
    for n in range(MAX_DEPTH + 4):
        nested += "  " * (n + 2) + f"level{n}:\n"
    nested += "  " * (MAX_DEPTH + 8) + "leaf: 1\n"
    preview = read_profile_text(body + nested)
    assert not preview.ok
    assert any("深すぎます" in i.message for i in preview.result.errors)


@pytest.mark.parametrize("text", ["", "   \n\n", None])
def test_empty_input_says_so(text):
    preview = read_profile_text(text)
    assert not preview.ok
    assert preview.result.errors


def test_broken_yaml_says_what_is_wrong():
    preview = read_profile_text("これは: YAML ではない: {{{")
    assert not preview.ok
    assert any("YAML として読めません" in i.message
               for i in preview.result.errors)


def test_a_list_at_the_top_is_refused():
    preview = read_profile_text("- 1\n- 2\n")
    assert not preview.ok
    assert any("マッピングではありません" in i.message
               for i in preview.result.errors)


def test_the_depth_counter_stops_instead_of_recursing_forever():
    """⚠ 数え切ろうとすると、守りたいものと同じ穴（深い再帰）に落ちる。"""
    from retroux.core.tactics.profile_validator import depth_of

    deep = {}
    node = deep
    for _ in range(500):
        node["x"] = {}
        node = node["x"]
    assert depth_of(deep) == MAX_DEPTH + 1


# --- 重複（既定は別名保存）--------------------------------------------

def test_a_duplicate_id_is_reported_in_the_preview(repo):
    prof = repo.duplicate(repo.get("balanced"), "そのまま")
    repo.save(prof)
    preview = read_profile_text(profile_to_yaml(prof), repository=repo)
    assert preview.conflict_id == prof.id
    assert preview.conflict_name == prof.name
    assert "同じID" in "\n".join(preview.lines())


def test_the_default_conflict_resolution_is_rename(repo):
    """★★ **上書きを既定にしない**（仕様書 12.6）。 ★★

    もらったプロフィールで自分の戦術が消えるのは取り返しがつかない。
    """
    mine = repo.duplicate(repo.get("balanced"), "わたしの作戦")
    mine.set("lorasia", "healing", "ally_hp_threshold", 11)
    repo.save(mine)

    theirs = read_profile_text(profile_to_yaml(mine), repository=repo).profile
    theirs.set("lorasia", "healing", "ally_hp_threshold", 99)
    resolved = resolve_conflict(theirs, repo, CONFLICT_RENAME)
    assert resolved.id != mine.id
    assert "インポート" in resolved.name
    repo.save(resolved)
    # ★わたしの作戦はそのまま残っている
    assert repo.get(mine.id).get("lorasia", "healing",
                                 "ally_hp_threshold") == 11


def test_overwrite_replaces_the_existing_one(repo):
    mine = repo.duplicate(repo.get("balanced"), "上書きされるもの")
    repo.save(mine)
    theirs = read_profile_text(profile_to_yaml(mine), repository=repo).profile
    theirs.set("lorasia", "healing", "ally_hp_threshold", 99)
    resolved = resolve_conflict(theirs, repo, CONFLICT_OVERWRITE)
    assert resolved.id == mine.id
    repo.save(resolved)
    assert repo.get(mine.id).get("lorasia", "healing",
                                 "ally_hp_threshold") == 99


def test_cancel_gives_nothing_back(repo):
    prof = read_profile_text(MINIMAL, repository=repo).profile
    assert resolve_conflict(prof, repo, CONFLICT_CANCEL) is None


def test_overwriting_a_preset_falls_back_to_rename(repo):
    """⚠ 見本は上書きできない（消せないものと同じ理由）。別名にする。"""
    text = profile_to_yaml(repo.get("balanced"))
    theirs = read_profile_text(text, repository=repo).profile
    resolved = resolve_conflict(theirs, repo, CONFLICT_OVERWRITE)
    assert resolved.id != "balanced"


# --- ファイル入出力（元を壊さない）------------------------------------

def test_writing_a_file_then_reading_it_back(repo, tmp_path):
    prof = repo.create("ファイルの試し")
    path = tmp_path / "out.yaml"
    assert write_profile_file(path, prof)
    again, issues = read_profile_file(path)
    assert again is not None, issues
    assert again.name == "ファイルの試し"
    assert again.path == path


def test_a_failed_write_leaves_the_original_alone(repo, tmp_path):
    """★★ **手で書いた戦術は戻らない**（仕様書 13章）。 ★★"""
    path = tmp_path / "keep.yaml"
    first = repo.create("だいじな作戦")
    assert write_profile_file(path, first)
    before = path.read_bytes()

    # ★書けない場所へ（フォルダを同名で作って邪魔する）
    blocked = tmp_path / "blocked.yaml"
    blocked.mkdir()
    assert write_profile_file(blocked, first) is False
    # 元のファイルはそのまま
    assert path.read_bytes() == before


def test_a_leftover_temp_file_is_cleaned_up(repo, tmp_path):
    blocked = tmp_path / "blocked.yaml"
    blocked.mkdir()
    write_profile_file(blocked, repo.create("失敗するもの"))
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], f"一時ファイルが残っている: {leftovers}"


def test_reading_a_missing_file_says_so(tmp_path):
    prof, issues = read_profile_file(tmp_path / "nope.yaml")
    assert prof is None
    assert issues


def test_reading_a_huge_file_is_refused(tmp_path):
    path = tmp_path / "big.yaml"
    path.write_text("a: 1\n" * (MAX_BYTES // 2), encoding="utf-8")
    prof, issues = read_profile_file(path)
    assert prof is None
    assert any("大きすぎます" in i.message for i in issues)


def test_reading_a_non_utf8_file_says_so(tmp_path):
    path = tmp_path / "sjis.yaml"
    path.write_bytes("プロフィール".encode("shift_jis"))
    prof, issues = read_profile_file(path)
    assert prof is None
    assert issues


# --- 要約 -------------------------------------------------------------

def test_the_summary_is_not_meant_to_be_reimported(repo):
    """★要約は人が読むもの（仕様書 11.4）。**YAML としては読めない**。"""
    text = profile_summary(repo.get("balanced"))
    preview = read_profile_text(text)
    assert not preview.ok, "★要約が YAML として読めてしまっている"


def test_validate_raw_returns_everything_at_once():
    """★1つ目で止めない（ほかにも問題があるか分からなくなる）。"""
    text = MINIMAL.replace("      ally_hp_threshold: 70",
                           "      ally_hp_threshold: 500")
    text = text.replace("role: attack", "role: へんな役割")
    import yaml

    result = validate_raw(yaml.safe_load(text))
    assert len(result.errors) >= 2, result.lines()


def test_the_issue_text_says_where_and_what():
    """★どこの話か分からない指摘は直せない。"""
    text = MINIMAL.replace("      ally_hp_threshold: 70",
                           "      ally_hp_threshold: 500")
    preview = read_profile_text(text)
    line = str(preview.result.errors[0])
    assert "moonbrooke" in line
    assert "ally_hp_threshold" in line


def test_the_preview_lines_show_the_roles(repo):
    """★保存の前に主要設定を見せる（仕様書 12.7）。"""
    preview = read_profile_text(MINIMAL, repository=repo)
    text = "\n".join(preview.lines())
    assert "わたしの作戦" in text
    assert "スキーマ：1" in text
    assert "ローレシア王子：攻撃重視" in text
    assert "ムーンブルク王女：回復重視" in text


def test_the_preview_of_a_broken_profile_says_it_cannot_be_read():
    preview = read_profile_text("こわれている: {{{")
    assert "読み込めませんでした" in "\n".join(preview.lines())
