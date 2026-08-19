"""文書の数字が古びていないこと（RX-0012 / 変更手順 §17）。

## ⚠⚠ なぜ要るか

文書に数字を手書きすると、コードが変わったときに**誰も直しません**。
総監査で、次が繰り返し古くなっていました:

    pytest 件数 / Lua check 件数 / `bridge.lua` の行数 /
    テストファイル数 / DEV 件数

★2026-08-13 には DEV 件数が3文書でばらついていました:

    CLAUDE.md   27
    INDEX.md     9      ⚠ 3分の1
    README.md   27
    ★実測       30

⚠ 件数が3分の1に見えていると、**残り18件を見落とします**。

## ★ 直し方

    PYTHONUTF8=1 python scripts/count_facts.py --write

## ⚠ ここで見ないもの

**その時点の記録**（`docs/refactor/phase*.md`、`docs/30-command-log.md`、
監査の生データ）は見ません。★あれは古びて正しいものです。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

COUNTS = PROJECT_ROOT / "docs" / "90-counts.md"


def _facts(only=None):
    from scripts.count_facts import measure

    return {f.label: f.value for f in measure(only)}


def test_生成物がある():
    assert COUNTS.exists(), (
        "★docs/90-counts.md がありません"
        "（`python scripts/count_facts.py --write`）")


def test_表が壊れていない():
    """⚠ `|` を含むコマンドを素で書くと**セルが切れる**（★実際に壊した）。"""
    body = COUNTS.read_text(encoding="utf-8")
    rows = [l for l in body.splitlines() if l.startswith("| ")]
    assert len(rows) >= 4, rows
    for row in rows[2:]:
        # ★エスケープ済みの `\|` を除いてから数える
        cells = row.replace("\\|", "").strip().strip("|").split("|")
        assert len(cells) == 3, f"★セルが {len(cells)} 個: {row}"


# --- ★ 速い項目だけ毎回見る -------------------------------------------

FAST = {"test_files", "bridge_lines", "devs", "product_sources",
        "work_items", "probe_files", "probe_lines"}


def test_速く測れる数字が合っている():
    """★pytest の収集や Lua の構文確認は遅いので、ここでは見ない。

    ⚠ 遅いぶんは `test_全部の数字が合っている` が見る（★`--runslow`）。
    """
    from scripts.count_facts import read_written

    written = read_written()
    assert written, "★docs/90-counts.md から数字を読めない"
    bad = []
    for label, value in _facts(FAST).items():
        if label not in written:
            bad.append(f"⚠ 書かれていない: {label}")
        elif written[label] != value:
            bad.append(f"⚠ {label}: 書いてある {written[label]:,}"
                       f" / 実測 {value:,}")
    assert not bad, (
        bad + ["★`python scripts/count_facts.py --write` で直せます"])


def test_全部の数字が合っている():
    """★`--check` をそのまま回す（⚠ Lua の構文確認を含むので数秒かかる）。

    ⚠⚠ **pytest 件数は保存していない**（★毎コミット変わるため）。
      保存すると、テストを1件足すたびに赤くなり、
      いずれ中身を見ずに `--write` されるだけになる。
    """
    done = subprocess.run(
        [sys.executable, "scripts/count_facts.py", "--check"],
        capture_output=True, cwd=PROJECT_ROOT, timeout=600)
    err = (done.stderr or b"").decode("utf-8", "replace")
    assert done.returncode == 0, err


def test_揮発する数字は保存しない():
    """⚠ 「毎コミット変わる数字」を書き込んでいないこと。

    ★書けば必ず古くなる。⚠ 古くなる検査は、いずれ中身を見ずに直される。
    """
    from scripts.count_facts import FACTS, read_written

    written = read_written()
    volatile = {label for _k, label, _f, _c, vol in FACTS if vol}
    assert volatile, "★揮発する項目が1つも無い（⚠ この検査は空回り）"
    leaked = volatile & set(written)
    assert not leaked, f"⚠ 揮発する数字が保存されている: {leaked}"


# --- ⚠⚠ 数字を「書き写した」文書を見張る --------------------------------

#: ★その時点の記録。⚠ 古びて正しいので見ない
FROZEN = ("docs/refactor/", "docs/30-command-log.md", "docs/audit/findings",
          "docs/project/RETROUX_BACKLOG.md", "docs/90-counts.md",
          "docs/handoff.md", "docs/field-check.md",
          "docs/design/phase6-tactics-spec.md",
          "docs/design/battle-ai-refactor-phase0.md",
          "docs/design/battle-ai-test-inventory.md")

#: ★「いま」を語る文書。⚠ ここに古い数字があると読み手が誤解する
LIVE_DOCS = ("README.md", "CLAUDE.md", "AGENTS.md",
             "docs/00-project-policy.md", "docs/11-change-workflow.md",
             "docs/design/mvp1-spec.md",
             "docs/design/deviations-from-instruction.md")


#: ★**わざと昔の値を引いている行**の目印（2026-08-14）。
#:
#:  ⚠⚠ この計画の文書は「以前はこう書いてあった」を**残す**書き方をしている。
#:    ★それは履歴であって、古い主張ではない。
#:
#:      > ⚠ 2026-08-12 訂正: ここは長らく「**9箇所**」でした。
#:
#:    ⚠ これを「古い数字」と数えると、**訂正を書くほど赤くなる**。
#:      ★訂正を書きにくくするのは、この計画のやり方に逆行する。
HISTORY_MARKS = ("訂正", "以前は", "当時", "でした", "→ 実測", "旧記載")


def _is_history(line: str) -> bool:
    return any(mark in line for mark in HISTORY_MARKS)


def _live_texts():
    for name in LIVE_DOCS:
        path = PROJECT_ROOT / name
        if path.exists():
            yield name, path.read_text(encoding="utf-8")


def test_DEV件数が3文書でそろっている():
    """★★★ ⚠⚠ **2026-08-13 にこれで 18 件を見落とした** ★★★

    CLAUDE.md 27 / INDEX.md **9** / README 27 → ⚠ 実測 30。
    ★件数が3分の1に見えていると、残りを見落とす。
    """
    want = _facts({"devs"})["指示書との意図的な差異（DEV）"]
    span = re.compile(r"DEV-1〜(?:DEV-)?([0-9]+)")
    count = re.compile(r"([0-9]+)\s*箇所で(?:意図的に)?異な")
    bad = []
    seen = 0
    for name, text in _live_texts():
        for i, line in enumerate(text.splitlines(), 1):
            if _is_history(line):
                continue            # ★わざと昔の値を引いている行
            for pat, what in ((span, "DEV-1〜"), (count, "箇所")):
                for m in pat.finditer(line):
                    seen += 1
                    if int(m.group(1)) != want:
                        bad.append(f"⚠ {name}:{i} {what}{m.group(1)}"
                                   f"（★実測 {want}）")
    # ⚠⚠ **「0 件」と「1つも見ていない」を混ぜない**（★何度も踏んだ形）
    assert seen > 0, "★DEV 件数に触れている行が1つも無い（⚠ 検査が空回り）"
    assert not bad, bad


def test_いまを語る文書がテスト件数を書き写していない():
    """⚠ テスト件数は毎日変わる。★書き写すと必ず古くなる。

    ★件数に触れるなら `docs/90-counts.md` を指すこと。
    """
    pat = re.compile(r"(?:pytest|テスト|検査)[^\n]{0,16}?([0-9][0-9,]{3,})\s*件")
    bad = []
    for name, text in _live_texts():
        for i, line in enumerate(text.splitlines(), 1):
            if _is_history(line) or "90-counts" in line:
                continue
            m = pat.search(line)
            if m:
                bad.append(f"⚠ {name}:{i} に {m.group(1)} 件"
                           "（★90-counts.md を指してください）")
    assert not bad, bad


def test_歯止めが本当に効く():
    """★★ ⚠⚠ **「0 件」を信じない**（この計画で何度も踏んだ形）★★

    ★上の2つが「見つからなかった」のか「見ていなかった」のかを分ける。
      ⚠ わざと古い数字を混ぜて、**必ず見つかる**ことを確かめる。
    """
    want = _facts({"devs"})["指示書との意図的な差異（DEV）"]
    fake = f"仕様書は指示書と {want + 99} 箇所で意図的に異なります（DEV-1〜DEV-{want + 99}）。"
    assert not _is_history(fake), "★履歴扱いされてしまう"
    assert re.search(r"([0-9]+)\s*箇所で(?:意図的に)?異な", fake)
    got = int(re.search(r"([0-9]+)\s*箇所で", fake).group(1))
    assert got != want, "★古い数字を見分けられていない"

    # ⚠ 履歴の行は**見逃す**のが正しい
    history = f"> ⚠ 2026-08-12 訂正: ここは「**9箇所**」でした。"
    assert _is_history(history), "★訂正の行を古い数字として数えてしまう"
