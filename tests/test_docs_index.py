"""目録（`docs/INDEX.md`）が黙って古くならないようにする（2026-08-11）。

依頼者の指示:

> ソースとリンクしないドキュメントや、メンテ漏れ（修正中みたいな文言）は最新化する
> 最後にルートのREADMEから、ドキュメント、ソースの目録に飛べるようにする事

## ★ここで固定すること

  1. README から目録へ飛べる
  2. `docs/**/*.md` が**どれも目録（か README）から辿れる**
     ⚠ 増やしたのに載せ忘れると、次の人は「無い」と思って作り直します
  3. 目録・README・変更史の**相対リンクが切れていない**
  4. ⚠ 「まだ繋いでいません／試作です」のような**古い断り書き**が残っていない
     （★実際に 2026-08-11 まで3ファイルで嘘になっていました）
  5. ⚠⚠ **もう解決した課題が「未解決」のまま書かれていない**
     （★同じ棚卸しで 7件見つかりました）
"""

from __future__ import annotations

import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"
INDEX = DOCS / "INDEX.md"
README = PROJECT_ROOT / "README.md"


def _read(path: pathlib.Path) -> str:
    # ⚠ README は BOM 付き（`utf-8-sig` で読む）
    return path.read_text(encoding="utf-8-sig")


def test_READMEから目録へ飛べる():
    assert INDEX.exists(), "★目録がありません"
    assert "docs/INDEX.md" in _read(README), (
        "⚠ README から目録へのリンクがありません")


def test_目録にソースの地図がある():
    """★ドキュメントだけでなく**ソース**の入口も要る（依頼者の指示）。"""
    text = _read(INDEX)
    for needed in ("retroux/", "core/", "ui/", "emulator/fceux/", "tests"):
        assert needed in text, f"⚠ 目録に {needed} の案内がありません"


def test_すべての文書が目録かREADMEから辿れる():
    """⚠⚠ **載せ忘れを黙って通さない。**

    ★フォルダごと案内している場合（`research/` など）はそれで通します。
    """
    index, readme = _read(INDEX), _read(README)
    missing = []
    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS).as_posix()
        parent = path.parent.relative_to(DOCS).as_posix()
        # ⚠ フォルダは「フォルダとして案内している」ときだけ通す。
        #   ★`f"{parent}/" in index` だと、同じフォルダの**別の1件**が
        #     載っているだけで全部通ってしまいます（2026-08-12 に発覚。
        #     書き出しスクリプト側の検査が 6 件見つけて気づきました）。
        listed = (rel in index or path.name in index
                  or rel in readme or path.name in readme
                  or (parent and f"]({parent}/)" in index))
        if not listed:
            missing.append(rel)
    assert not missing, (
        "⚠ 目録にも README にも出てこない文書があります"
        f"（{len(missing)} 件）: {missing[:5]}"
        "\n★`docs/INDEX.md` へ1行足してください")


def test_目録と変更史のリンクが切れていない():
    targets = [INDEX, README, DOCS / "history" / "ui-changes.md",
               DOCS / "history" / "map-decoder.md"]
    broken = []
    for md in targets:
        for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", _read(md)):
            link = m.group(1)
            if link.startswith(("http", "#", "mailto:")):
                continue
            if not (md.parent / link.split("#")[0]).resolve().exists():
                broken.append(f"{md.name} → {link}")
    assert not broken, f"⚠ 切れたリンク: {broken}"


#: ⚠ 実際に嘘になっていた断り書き（2026-08-11 に最新化）
STALE = ("GUI へは繋いでいません", "まだ GUI へ繋いでいません",
         "GUI統合しない", "試作です。GUI")


def test_古い断り書きが残っていない():
    """⚠⚠ 2026-08-09/11 に GUI へ繋いだのに、3ファイルが「繋いでいません」の
    ままでした。★**同じコミットで直す**という約束（CLAUDE.md）の歯止めです。
    """
    found = []
    for path in (PROJECT_ROOT / "retroux").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for phrase in STALE:
            if phrase in text:
                found.append(f"{path.relative_to(PROJECT_ROOT)}: {phrase}")
    assert not found, (
        f"⚠ 古い断り書きが残っています: {found}"
        "\n★繋いだのなら文言も同じコミットで直すこと")


# --- ⚠⚠ 「もう解決したのに未解決と書いてある」を止める --------------------
#
# 2026-08-11 の棚卸しで **7件** が古いまま残っていました
# （依頼者「いまとなっては解決できているものとかない？」）。

#: 解決したのに残っていた言い回し → ★いつ・何で解決したか
RESOLVED = {
    "日本版のマップ形式は未解読": "2026-08-02〜03 に解読（108/108・65536/65536）",
    "壁・扉・階段は出ません": "2026-08-09/11 に ROM の絵で描くようにした",
    "経験値のアドレスが未確定": "2026-07-31 に確定（$0633 から3バイト）",
    "睡眠の状態ビットが未確定": "2026-07-26 に確定（$062D の 0x40）",
    "キャラの名前を RAM から読めていない": "2026-07-29 に読めた（core/text.py）",
    "街とフィールドの対応表は未特定": "2026-08-02 に確定（$E20C / map_kind）",
    "個体別HPは未特定": "2026-07-26 に確定（instance_fields）",
}

#: ⚠ **当時の記録**なので直さない文書（★歴史は書き換えない）
EXEMPT = ("docs/history/", "docs/handoff.md", "docs/design/handoff-",
          "docs/90-retrospective.md", "docs/inventory/open_questions.md",
          "docs/design/mvp1-spec.md", "docs/design/phase6-tactics-spec.md",
          "docs/design/deviations-from-instruction.md",
          "docs/60-consult-brief.md", "docs/30-command-log.md",
          "docs/map-decoder-evidence.md", "docs/research/",
          "tests/test_docs_index.py")


def _targets():
    paths = (list((PROJECT_ROOT / "retroux").rglob("*.py"))
             + list((PROJECT_ROOT / "retroux").rglob("*.yaml"))
             + list((PROJECT_ROOT / "retroux").rglob("*.lua"))
             + list(DOCS.rglob("*.md"))
             + [README])
    for path in paths:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if any(e in rel for e in EXEMPT):
            continue
        yield rel, path.read_text(encoding="utf-8-sig")


def test_解決済みの課題が未解決のまま書かれていない():
    """⚠⚠ **一番ありがちなメンテ漏れ**（依頼者の指摘 / 2026-08-11）。

    ★消すのではなく「~~取り消し線~~ → 解決した」と書けば通ります
      （何がいつ解決したのかは残したいので）。
    """
    stale = []
    for rel, text in _targets():
        for line in text.split("\n"):
            if "~~" in line:
                continue                 # ★「~~未解決~~ → 解決」は通す
            for phrase, note in RESOLVED.items():
                if phrase in line:
                    stale.append(f"{rel}: 「{phrase}」（★{note}）")
    assert not stale, (
        "⚠ 解決済みなのに未解決のまま書かれています:\n  "
        + "\n  ".join(stale))


# --- ⚠⚠ 「作成時の状態」が固定されたまま（2026-08-12 の監査で発覚）---------
#
# 仕様書の冒頭に `状態: … 実装は未着手。` と書き、**そのあと実装しても
# 直していない**、という形が2本ありました。
#
#   monster-book-spec.md   「実装は未着手」→ ★monster_book_window.py（398行のテスト付き）
#   phase6-tactics-spec.md 「実装は未着手」→ ★core/tactics/ 7ファイル＋127項目
#
# ⚠ 読む人は冒頭の1行で判断するので、ここが古いと**丸ごと誤解**されます。

#: ⚠ 冒頭でこう名乗っているのに、実体があるもの
STATUS_CLAIMS = {
    "docs/design/monster-book-spec.md": (
        "実装は未着手", "retroux/ui/monster_book_window.py"),
    "docs/design/phase6-tactics-spec.md": (
        "実装は未着手", "retroux/core/tactics/lua_bridge.py"),
}


def test_仕様書の冒頭が実装の有無と食い違っていない():
    """★★ **冒頭の1行がいちばん読まれます。**

    ⚠ 「未着手」と書いたまま実装すると、次の人は
      **作り直すか、無いものとして設計します**。

    ★直し方: 消すのではなく「⚠⚠ 訂正 — 実装済み」と**上書きで書く**。
      当時の判断は本文に残るので、歴史は失われません。
    """
    bad = []
    for rel, (phrase, evidence) in STATUS_CLAIMS.items():
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        head = path.read_text(encoding="utf-8-sig")[:1500]
        exists = (PROJECT_ROOT / evidence).exists()
        # ★「訂正」と書いてあれば通す（★上書きで直した形）
        if exists and phrase in head and "訂正" not in head:
            bad.append(f"{rel}: 冒頭に「{phrase}」とあるのに {evidence} が実在")
    assert not bad, (
        "⚠⚠ 仕様書の冒頭が古いままです:\n  " + "\n  ".join(bad)
        + "\n★「⚠⚠ 訂正 — 実装済み」と上書きしてください")
