"""調査コードの置き場の検査（2026-08-01 のリファクタ指示書 §13）。

★★ **`research/probes/` は本体ではない。** ★★
  ここが壊れても製品は動く。だが「どう測ったか」が失われると、
  番地や仕様の**根拠が消える**ので、置き場だけは機械で見張る。

## ⚠ なぜテストが要るのか

  `work/` に平置きだった 242 本を3つの区分へ分けたとき、
  **隣を import していたものが隣でなくなった**。
  Python の import は**実行するまで落ちない**ので、
  pytest も luacheck も全部緑のまま、実機で初めて落ちた
  （`verify_no_console.py` -> `window_watch`）。
  ★Phase 2 の「呼び出しだけ残って関数が無い」と同じ構図。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBES = PROJECT_ROOT / "research" / "probes"
BUCKETS = ("active", "reusable", "archived")


def _scripts(*exts: str) -> list[pathlib.Path]:
    if not PROBES.exists():                            # pragma: no cover
        return []
    return sorted(p for p in PROBES.rglob("*")
                  if p.suffix.lower() in exts and "__pycache__" not in p.parts)


def _where() -> dict[str, str]:
    """モジュール名 -> 区分。"""
    return {p.stem: p.parent.name for p in _scripts(".py")}


# --- 置き場そのもの ---------------------------------------------------

def test_the_buckets_exist():
    """★3つの区分（指示書 §13.1）。"""
    missing = [b for b in BUCKETS if not (PROBES / b).is_dir()]
    assert missing == [], missing


def test_every_probe_sits_in_a_bucket():
    """⚠ 区分の外に置くと、配布ZIPの絞り込みから漏れる。"""
    stray = [p.relative_to(PROBES).as_posix()
             for p in _scripts(".py", ".lua", ".ps1")
             if p.parent.name not in BUCKETS]
    assert stray == [], f"区分の外にある: {stray}"


# --- ⚠⚠ 実機でしか落ちなかった不具合を、ここで捕まえる ----------------

def test_no_probe_imports_across_buckets():
    """★★ 区分をまたぐ import を素で書かない ★★

    ⚠ `work/` に平置きだった頃は隣を `import` できた。区分に分けた今は
      **隣ではない**ので、`sys.path` に足さないと落ちる。
      ★足してあるものは見逃す（下の検査が「足したか」を見る）。
    """
    where = _where()
    bad = []
    for path in _scripts(".py"):
        text = path.read_text(encoding="utf-8")
        # ★`sys.path` を触っているなら、書き手は分かって書いている
        if "sys.path" in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:                            # pragma: no cover
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 \
                    and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in where and where[name] != path.parent.name:
                    bad.append(f"{path.parent.name}/{path.name}"
                               f" -> {name}（{where[name]}）")
    assert bad == [], f"区分をまたぐ import: {bad}"


def test_probes_find_the_project_root_at_the_right_depth():
    """★`probes/<区分>/x.py` から根は **3つ上**。

    ⚠ `work/` に居た頃は `parents[1]` だった。移動時に 50 本直している。
      ★区分をもう1階層深くすると、ここが赤くなる（それが狙い）。
    """
    wrong = []
    for path in _scripts(".py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#")[0]
            if "__file__" in code and "parents[" in code \
                    and "parents[3]" not in code:
                wrong.append(f"{path.parent.name}/{path.name}: {line.strip()}")
    assert wrong == [], wrong


def test_the_active_probes_do_not_depend_on_archived_ones():
    """★「終わった調査」を現役が呼ばない。

    ⚠ 呼んでいるなら、それは**終わっていない**ので `active` へ移す
      （`verify_no_console.py` が実際にこれだった）。
    ★配布ZIPは archived を入れないので、呼んでいると相手先で動かない。
    """
    bad = []
    for path in _scripts(".py", ".lua", ".ps1"):
        if path.parent.name != "active":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "probes/archived/" in line or "probes\\archived\\" in line:
                bad.append(f"{path.name}: {line.strip()[:80]}")
    assert bad == [], bad


# --- 配布ZIP の約束（指示書 §13.3）------------------------------------

def test_the_review_zip_leaves_out_the_archived_probes():
    """⚠ 既定で `archived` を入れない（174 件あり、相談の判断材料でない）。"""
    script = PROJECT_ROOT / "scripts" / "export-for-review.ps1"
    text = script.read_text(encoding="utf-8")
    assert "WithArchived" in text, "archived を含める逃げ道が無い"
    assert 'probeSkip += "archived"' in text, \
        "既定で archived を除いていない"


# --- 説明があるか -----------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "research/probes",          # 場所の名指し
    "探索対象",                  # 通常実装では見ない、という約束
])
def test_claude_md_says_not_to_explore_the_probes(phrase):
    """★★ 指示書 §13.4 ★★

    ⚠ 242 本・約3万行あり、**仮説が外れて捨てたもの**も混ざっている。
      素で読ませると間違った前提を拾うので、明記しておく。
    """
    text = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert phrase in text, f"CLAUDE.md に「{phrase}」の記載が無い"


def test_探査は必ずFCEUXを閉じる():
    """⚠⚠ 2026-08-02 に依頼者から「ウィンドウ出っぱなし」と指摘された。

    ★★ **`os.exit` を書いただけでは閉じない。** ★★
      探査の途中で `return` すると、下にある `os.exit` に届かず、
      FCEUX の窓が開いたまま残る。読み込み失敗の分岐で実際に起きた。

    ★ここでは「`os.exit` を持つ探査で、それより手前に裸の `return` が
      無いこと」を見る。⚠ 早期に抜けるなら、抜ける前に閉じること。
    """
    import re

    bad = []
    for path in sorted((PROJECT_ROOT / "research" / "probes" / "active")
                       .glob("*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "os.exit" not in text:
            continue                      # ★FCEUX を使わない探査は対象外
        for m in re.finditer(r"^[ \t]*return[ \t]*$", text, re.M):
            head = text[:m.start()]
            if "os.exit" not in head and "finish(" not in head:
                line = head.count("\n") + 1
                bad.append(f"{path.name}:{line}")
                break
    assert not bad, (
        "★閉じずに抜ける経路がある（FCEUX の窓が残る）: " + ", ".join(bad))
