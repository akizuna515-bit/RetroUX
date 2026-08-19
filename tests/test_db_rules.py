"""DB の触り方の規則（2026-08-01 の Phase 6 / 指示書 §9）。

★★ **今回すべてを分割しない。** ★★（§9.2）
  既存の SQL を動かすと、記録済みのデータを壊す危険がそのぶん増えます。
  代わりに「**これ以上増やさない**」を機械で守ります。

## 規則

  1. `database.py` は**新しい表**の SQL を持たない（§9.2）
     → 新しい機能の SQL は Repository へ
  2. `database.py` の仕事は 接続 / トランザクション / 移行 / 共通の補助（§9.1）
  3. 画面配置とキー設定は **YAML**。DB へ入れない（§9.2）
  4. Repository は `Database` の**正面口**から接続を借りる（§9.1）

⚠ ここは「内部の関数名」を固定しません（§14.2）。
  見るのは**どの表を触るか**だけなので、整理し直しても赤くなりません。
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DATABASE = PROJECT_ROOT / "retroux" / "core" / "db" / "database.py"

#: ★★ `database.py` が**読み書き**してよい表（2026-08-01 に凍結）★★
#   ⚠ **ここへ足さないこと。** 新しい表の読み書きは Repository が持つ（§9.2）。
#     足したくなったら、それは新しい機能なので置き場が違う。
#
#   ★`CREATE TABLE`（表の定義そのもの）は**別扱い**にしています。
#     §9.1 が「migration は database.py へ寄せる」と決めているためで、
#     実際 `MapEdge` などの Map 系7表は、ここで定義され
#     `core/navigation/repository.py` が読み書きしています。
#     ⚠ 定義まで禁じると、表を作る場所が無くなります。
FROZEN_TABLES = {
    "Rom",                  # ROM の登録
    "EncounteredMonster",   # 出会った敵
    "VisitedTile",          # 見たマス
    "BattleLog",            # 戦闘の記録
    "BattleEvent",          # 戦闘中の出来事
    "IngestState",          # どこまで取り込んだか
}

#: 読み書き（DML）。★ここに出る表が「機能別 SQL」を持っている合図
_DML = re.compile(r"\b(?:FROM|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_]*)",
                  re.IGNORECASE)
#: 表の定義（DDL）。★§9.1 により database.py の仕事
_DDL = re.compile(r"\bCREATE\s+(?:TABLE|INDEX)(?:\s+IF\s+NOT\s+EXISTS)?\s+"
                  r"([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)

#: SQL のキーワードは表の名前ではない（`UPDATE x SET` の SET など）
_NOT_A_TABLE = {"set", "select", "values", "where", "exists", "on"}


def _sql_strings(path: pathlib.Path) -> list[str]:
    """そのファイルの中の**文字列リテラル**だけを集める。

    ⚠⚠ 生の本文を検索しない。説明文（docstring）に書いた表の名前まで
      拾ってしまう（Phase 5 で実際に踏んだ）。
    ★AST で「文字列」を取り、さらに docstring を除く。

    ⚠ `utf-8-sig` で読む。`retroux/tools/__init__.py` に BOM が付いており、
      素の `utf-8` だと `ast.parse` が非表示文字で落ちる（2026-08-01 に実測）。
      ★Python の import は BOM を通すので、ファイル側は壊れていない。
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings]


def _tables(path: pathlib.Path, pattern=_DML) -> set[str]:
    found = set()
    for text in _sql_strings(path):
        for name in pattern.findall(text):
            if name.lower() not in _NOT_A_TABLE:
                found.add(name)
    return found


# --- 規則1: 新しい表を database.py へ足さない -------------------------

def test_the_database_does_not_gain_new_tables():
    """★★ **§9.2 の必須範囲** ★★

    ⚠ ここが赤くなったら、`database.py` に新しい表の SQL を書いています。
      **`FROZEN_TABLES` へ足して直さないでください。**
      新しい表は Repository（例: `core/navigation/repository.py`）が持ちます。
      分けておかないと、機能が増えるたびにこのファイルだけが太ります。
    """
    extra = _tables(DATABASE) - FROZEN_TABLES
    assert extra == set(), (
        f"database.py が新しい表を読み書きしています: {sorted(extra)}\n"
        "★Repository を作ってそちらへ書いてください（指示書 §9.2）。\n"
        "⚠ FROZEN_TABLES へ足して直さないでください。")


def test_the_map_tables_are_defined_here_but_read_elsewhere():
    """★★ 定義は `database.py`、読み書きは Repository（§9.1 / §9.2）★★

    ⚠ この形が崩れると、地図の SQL が2か所に散らばる。
      ★実際、Map 系の7表はここで定義され、
        `core/navigation/repository.py` だけが読み書きしている。
    """
    defined = {t for t in _tables(DATABASE, _DDL) if t.startswith("Map")}
    assert defined, "Map 系の表が定義されていない"

    touched = _tables(DATABASE) & defined
    assert touched == set(), \
        f"database.py が地図の表を読み書きしています: {sorted(touched)}"

    repo = PROJECT_ROOT / "retroux" / "core" / "navigation" / "repository.py"
    assert _tables(repo) & defined, "Repository が地図の表を読み書きしていない"


def test_the_frozen_list_is_not_stale():
    """⚠ 消えた表を凍結表に残さない（守っているつもりで守っていない状態）。"""
    missing = FROZEN_TABLES - _tables(DATABASE)
    assert missing == set(), (
        f"凍結表にあるのに使われていません: {sorted(missing)}\n"
        "★Repository へ移したなら、この一覧からも外してください。")


# --- 規則2: database.py の仕事の範囲（§9.1）---------------------------

def test_the_database_does_not_know_about_the_screen():
    """⚠ DB が画面を知ると、記録を試すのに画面が要る。"""
    tree = ast.parse(DATABASE.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        bad += [n for n in names
                if n.startswith("PySide6") or "ui" in n.split(".")]
    assert bad == [], bad


# --- 規則3: 画面配置とキー設定は YAML（§9.2）--------------------------

@pytest.mark.parametrize("word", ["layout", "keybinding", "window_state"])
def test_the_layout_and_keys_are_not_stored_in_the_database(word):
    """★★ **既存DBへ無理に入れない**（§9.2）★★

    ⚠ 設定を DB へ入れると、人が開いて直せなくなる。
      配置とキーは**人が読んで直せること**が価値なので YAML に置く。
    """
    tables = {t.lower() for t in _tables(DATABASE)}
    assert not any(word in t for t in tables), \
        f"{word} を DB に入れています: {sorted(tables)}"


def test_the_layout_and_keys_really_live_in_yaml():
    """★上の裏返し。**在るべき所に在る**ことも見る。

    ⚠ 「DB に無い」だけでは、どこにも無い場合と区別が付かない。
    """
    config = PROJECT_ROOT / "retroux" / "config"
    assert (config / "default_layout.yaml").exists()
    assert (config / "default_keybindings.yaml").exists()


# --- 規則4: Repository は正面口から借りる（§9.1）----------------------

def test_repositories_borrow_the_connection_through_the_front_door():
    """★★ 私的な名前（`db._conn`）を外から触らない ★★

    ⚠ 外から使う以上それは規約なのに、`_` が付いていると
      「変えてよい」と誤解される。`Database.connection` を通す。
    """
    offenders = []
    for path in sorted((PROJECT_ROOT / "retroux").rglob("*.py")):
        if path == DATABASE:
            continue
        # ⚠ BOM 付きの .py がある（retroux/tools/__init__.py）ので utf-8-sig
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            # ★`何か.db._conn` / `何か.db._commit()` の形だけを見る
            if not isinstance(node, ast.Attribute):
                continue
            if node.attr not in {"_conn", "_commit"}:
                continue
            inner = node.value
            if isinstance(inner, ast.Attribute) and inner.attr == "db":
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()}: .db.{node.attr}")
    assert offenders == [], (
        f"私的な名前を外から触っています: {offenders}\n"
        "★`db.connection` / `db.commit()` を使ってください。")


def test_the_front_door_respects_bulk():
    """★★ `commit()` は `bulk()` の中では確定しない ★★

    ⚠ ここを飛ばして `connection.commit()` を直に呼ぶと、
      まとめている途中で確定してしまう。**実際に動かして**確かめる。
    """
    from retroux.core.db.database import Database

    db = Database(":memory:")
    try:
        with db.bulk():
            db.register_rom("h", "T", "JP")
            db.commit()                       # ★中では確定しないはず
            got = db.connection.execute(
                "SELECT COUNT(*) FROM Rom").fetchone()[0]
            assert got == 1, "同じ接続からは見える（まだ確定していないだけ）"
        assert db.connection.in_transaction is False, \
            "bulk を抜けたら確定していること"
    finally:
        db.close()


def test_the_connection_is_the_same_object_each_time():
    """⚠ 呼ぶたびに別の接続を返すと、`bulk()` がまたがらない。"""
    from retroux.core.db.database import Database

    db = Database(":memory:")
    try:
        assert db.connection is db.connection
    finally:
        db.close()
