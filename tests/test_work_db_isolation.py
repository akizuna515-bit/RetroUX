"""検査が本物の SQLite を開かない（RX3-0480 / 2026-10-01）。

## ⚠⚠ なぜ要るか

★2026-10-01 の全件走行で `work/retroux.sqlite3-wal` / `-shm` が出ました。
⚠ 1 度しか再現せず「SQLite が開いた跡」として片づけましたが、
★`sqlite3.connect` を記録したら **2 本**が名指しで出ました:

```text
tests/test_map_passability.py::test_実際に歩いた先を通れないと言っていない   1 回
tests/test_icon_buttons_have_tooltips.py::test_the_main_window_icon_buttons…  6 回
```

⚠⚠ **読むだけでも `-wal` / `-shm` は出来ます**（★WAL の DB を読み書きで開くため）。
★`-wal` を消すと、⚠ 本体へ反映前の変更が**失われます**。

## ★この検査が守るもの

⚠ 「`-wal` が出ていない」だけでは弱い（★たまたま誰も開かなかった走行でも通る）。
→ ★`conftest._isolate_real_sqlite` の**付け替えそのもの**を見ます。
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import conftest as CF  # noqa: E402

REAL_WORK = (ROOT / "work").resolve()


def test_包めている():
    """⚠⚠ ここが偽だと、下の検査は**何も見ていません**（★0 件は通っていないだけ）。"""
    assert CF._sqlite_orig is not None, (
        "⚠⚠ `sqlite3.connect` を包めていません（★`pytest_sessionstart` を確かめる）")
    assert sqlite3.connect is not CF._sqlite_orig


#: ⚠ 名前は走行ごとに変えます（★写しは**使い回す**ので、前の走行の表が残っています）
PROBE_NAME = "_m8_isolation_probe_%d.sqlite3" % os.getpid()


def test_本物のworkへの接続は写しへ向く():
    """★本物の道で開いても、⚠ 本物のファイルは**出来ません**。"""
    target = REAL_WORK / PROBE_NAME
    assert not target.exists(), "⚠ 前の走行の置き土産が残っています: %s" % target
    con = sqlite3.connect(str(target))
    try:
        con.execute("create table t(x)")
        con.execute("insert into t values (1)")
        con.commit()
    finally:
        con.close()
    # ⚠⚠ 本物の work/ には 1 バイトも出来ていないこと（★`-wal` / `-shm` も）
    for suffix in ("", "-wal", "-shm", "-journal"):
        got = REAL_WORK / (PROBE_NAME + suffix)
        assert not got.exists(), "⚠⚠ 本物の work/ に出来ました: %s" % got
    # ★付け替え先には出来ていること（⚠ 「書けていない」で通してはいけない）
    moved = [p for p in CF._db_redirects if p.endswith(PROBE_NAME)]
    assert moved, "⚠ 付け替えの記録がありません: %s" % sorted(CF._db_redirects)
    got = pathlib.Path(moved[0])
    assert got.is_file()
    # ⚠⚠ 写しの道で開き直しても**もう一度付け替えない**こと
    #   （★隔離先は `work/tests/lua-sandbox/` = 本物の `work/` の中にある / 2026-10-01 に実測）
    before = set(CF._db_redirects)
    con = sqlite3.connect(str(got))
    try:
        assert con.execute("select x from t").fetchall() == [(1,)]
        assert set(CF._db_redirects) == before, (
            "⚠⚠ 隔離先の道を**もう一度**付け替えました: %s"
            % sorted(set(CF._db_redirects) - before))
    finally:
        con.close()
        for suffix in ("", "-wal", "-shm", "-journal", ".stamp"):
            try:
                pathlib.Path(str(got) + suffix).unlink()
            except OSError:
                pass        # ⚠ 片付けられなくても検査の結論は変わらない


def test_本物のDBは読むときも写しから読む():
    """⚠ 読むだけの接続も隔離の対象（★WAL では読み書きで開くので `-shm` が出来る）。"""
    real = REAL_WORK / "retroux.sqlite3"
    if not real.is_file():
        import pytest

        pytest.skip("⚠ 本物の DQ2 の記録 DB がありません（★`work/` は Git の外）")
    con = sqlite3.connect(str(real))
    try:
        con.execute("select 1").fetchone()
    finally:
        con.close()
    for suffix in ("-wal", "-shm"):
        got = REAL_WORK / ("retroux.sqlite3" + suffix)
        assert not got.exists(), "⚠⚠ 本物の DB を開いた跡が出来ました: %s" % got


def test_workの外はそのまま(tmp_path):
    """⚠ 付け替えすぎない（★`tmp_path` の DB はそのまま使えること）。"""
    target = tmp_path / "plain.sqlite3"
    con = sqlite3.connect(str(target))
    try:
        con.execute("create table t(x)")
        con.commit()
    finally:
        con.close()
    assert target.is_file()
    assert str(target) not in CF._db_redirects


def test_見張りは大きいファイルも中身で見る():
    """⚠⚠ 見張りの盲点（★RX3-0480 / 2026-10-01 に見つけた）。

    ★`_work_snapshot` は `WORK_GUARD_MAX_BYTES` を超えるものを
    **大きさだけ**（`size:<n>`）で控えていました。⚠ `work/retroux.sqlite3` は 42 MB。
    ★SQLite のページは固定長なので、⚠ WAL を本体へ反映しても**大きさが変わらない**
    ことがあり、→ ★見張りは「無事」と言い続けます。
    """
    real = REAL_WORK / "retroux.sqlite3"
    if not real.is_file():
        import pytest

        pytest.skip("⚠ 本物の DQ2 の記録 DB がありません（★`work/` は Git の外）")
    assert real.stat().st_size > 4 * 1024 * 1024, (
        "⚠ この検査は 4 MB を超える本物のファイルで見ています")
    got = CF._work_snapshot().get("retroux.sqlite3")
    assert got, "⚠ 見張りが `work/retroux.sqlite3` を見ていません"
    assert not got.startswith("size:"), (
        "⚠⚠ 大きさだけで控えています（★中身の変化に気づけません）: %s" % got)
    size, _, digest = got.partition(":")
    assert int(size) == real.stat().st_size
    assert len(digest) == 16 and all(c in "0123456789abcdef" for c in digest), got


def test_メモリのDBは触らない():
    con = sqlite3.connect(":memory:")
    try:
        assert con.execute("select 1").fetchone() == (1,)
    finally:
        con.close()
