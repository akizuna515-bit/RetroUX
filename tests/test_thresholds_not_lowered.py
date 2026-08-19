"""合格の閾値を**こっそり下げていない**こと（チェックリスト §7）。

## ⚠⚠ なぜ要るか

★テストが赤くなったとき、**直すより閾値を下げるほうが早い**。
⚠ 一度下げると誰も気づかない（★下げたことは差分にしか残らない）。

    assert ok / total >= 0.90     # ⚠ 0.85 にすれば緑になる

★この計画は「実測で確かめる」を旨としているので、
⚠ 閾値を下げるのは**測るのをやめる**のと同じ。

## ★ どうするか

**下げたら赤くなる**ようにする。⚠ 上げるぶんには自由。

★閾値を変えたいときは、ここの数字も同じコミットで直す。
その差分がレビューで見えるので、⚠ 黙って下がることがなくなる。

## ⚠ ここに入れないもの

範囲の検査（`0 < r <= 1.0`）や、単なる上限（`< 110.0 ms`）は入れない。
★「どれだけ合っていれば合格か」を決めている**品質の閾値**だけ。
"""

from __future__ import annotations

import pathlib
import re
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TESTS = PROJECT_ROOT / "tests"

#: ★★ **合格の閾値**（2026-08-19 実測）★★
#:
#:   `(ファイル, 探す語, 期待する値, なぜ)`
#:
#: ⚠⚠ **探す語に数字を入れないこと。**
#:   ★最初 `"rate >= 0.95"` を探していたが、⚠ **下げると見つからなくなり、
#:     そのまま通った**（2026-08-19 に実測で判明）。
#:   → ★語は `"rate >="` までにして、**数字は右側から読む**。
#:
#: ⚠ 下げるときは、ここも同じコミットで直すこと（★そうしないと赤になる）。
FLOORS = (
    ("test_bg_character_renderer.py", "assert best >=", 0.90,
     "★セーブステートからの再構成。⚠ これを割ると絵が信用できない"),
    ("test_dungeon_map.py", "assert ok / total >=", 0.90,
     "★街・ダンジョンの地形一致"),
    ("test_rom_tiles.py", "assert rate >=", 0.95,
     "★街の絵の再現"),
    ("test_rom_tiles.py", "assert max(r[3] for r in results) >=", 0.95,
     "★同上（最良のもの）"),
)

#: ★同じ語が複数ある場所は、**全部の値**を並べて確かめる
MULTI = (
    ("test_map_builder_stop_a.py", "assert ok / len(cells) >=",
     (0.93, 0.90),
     "★地図の組み立て（⚠ 歯止め。復号100%で発火中）"),
)

#: ★件数の下限（⚠ 「材料が減ったから通った」を防ぐ）
COUNT_FLOORS = (
    ("dq2rom/monsters/validator.py", "MIN_JUDGED =", 8,
     "★これ未満のマスしか比べられない撮影は「材料不足」"),
)

NUM = re.compile(r"(\d+\.\d+|\d+)")


def _find(path: pathlib.Path, needle: str) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            out.append((i, line.strip()))
    return out


def _values(path: pathlib.Path, needle: str) -> list[tuple[int, float]]:
    """その語の**右側**にある最初の数値を集める。★語に数字を入れない前提。"""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        at = line.find(needle)
        if at < 0:
            continue
        m = NUM.search(line[at + len(needle):])
        if m:
            out.append((i, float(m.group(1))))
    return out


def test_合格の閾値を下げていない():
    """★★★ ⚠⚠ **下げたら赤くする** ★★★

    ⚠⚠ **最初、これは効いていなかった**（2026-08-19）。
      探す語に `"rate >= 0.95"` と**数字まで入れていた**ので、
      ★下げると「見つからない」になり、⚠ **そのまま通った**。
      → ★語は `"assert rate >="` までにして、数字は右から読む。
    """
    bad = []
    for name, needle, floor, why in FLOORS:
        path = TESTS / name
        assert path.exists(), f"★{name} が無い（⚠ この検査の前提が崩れた）"
        got = _values(path, needle)
        if not got:
            bad.append(f"⚠ {name}: 「{needle}」が無い"
                       "（★書き換えたなら、ここも直すこと）")
            continue
        for line_no, value in got:
            if value < floor:
                bad.append(f"⚠⚠ {name}:{line_no} 閾値が {value} へ下がっている"
                           f"（★{floor} 以上 / {why}）")
    for name, needle, floors, why in MULTI:
        path = TESTS / name
        got = [v for _i, v in _values(path, needle)]
        if sorted(got, reverse=True) != sorted(floors, reverse=True):
            bad.append(f"⚠⚠ {name}: 閾値が {sorted(got, reverse=True)} に"
                       f"なっている（★{sorted(floors, reverse=True)} / {why}）")
    assert not bad, bad


def test_件数の下限を下げていない():
    """⚠ 「材料が減ったから通った」を防ぐ。"""
    bad = []
    for name, needle, floor, why in COUNT_FLOORS:
        path = PROJECT_ROOT / name
        got_all = _values(path, needle)
        assert got_all, f"⚠ {name}: 「{needle}」が無い"
        got = int(got_all[0][1])
        if got < floor:
            bad.append(f"⚠⚠ {name} が {got} へ下がっている"
                       f"（★{floor} 以上 / {why}）")
    assert not bad, bad


def test_この検査自身が空回りしていない():
    """⚠⚠ **「0 件」を信じない**（★この計画で何度も踏んだ形）。

    ★探す語が1つでも見つからなければ、上の検査は**何も見ていない**。
    """
    for name, needle, _floor, _why in FLOORS:
        assert _values(TESTS / name, needle), (
            f"⚠ {name}: 「{needle}」が見つからない（★検査が空回り）")
    for name, needle, _floors, _why in MULTI:
        assert _values(TESTS / name, needle), (
            f"⚠ {name}: 「{needle}」が見つからない（★検査が空回り）")


def test_skipで逃げていない():
    """⚠ 閾値を下げる代わりに `skip` する、も同じこと。

    ★見るのは「**理由を渡していない** `skip`」だけ。

    ⚠⚠ **最初これで誤検知した**（2026-08-19）:

        pytest.skip(out.strip())      # ★実行結果を理由として渡している

      ⚠ 「引用符が無い＝理由が無い」と決めつけていた。
      ★変数を渡す形も理由つき。⚠ 鳴りすぎも壊れ方（★この計画で6回目）。
    """
    bad = []
    for path in TESTS.glob("test_*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            t = line.strip()
            # ★引数が空のものだけが「理由が無い」
            if re.match(r"^pytest\.skip\(\s*\)", t):
                bad.append(f"{path.name}:{i} {t[:60]}")
    assert not bad, ["⚠ 理由の無い skip:"] + bad


def test_skipの検査が空回りしていない():
    """⚠ 「0 件」が「見ていない」でないこと。★`skip` 自体は在ること。"""
    found = 0
    for path in TESTS.glob("test_*.py"):
        found += path.read_text(encoding="utf-8").count("pytest.skip(")
    assert found > 10, f"★`pytest.skip` が {found} 件（⚠ 検査が空回り）"
