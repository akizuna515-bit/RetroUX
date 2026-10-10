"""pytest の共通設定。

★これがある理由: `dq2rom` はリポジトリ直下の独立パッケージで、
  `retroux` と違って editable install に入っていない環境でも
  テストが通るようにしたい。
  ルートに conftest.py があると pytest がリポジトリ直下を sys.path へ入れるので、
  `import dq2rom` が通る。

  （`pyproject.toml` の `packages` にも `dq2rom` を足してあるので、
  `uv pip install -e .` をやり直せばこの conftest 抜きでも通る。
  どちらか一方に頼らないための二重化。）
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- ⚠⚠ `tmp_path` の置き場を `work/` に逃がす（2026-09-18 / RX3-0282 の作業中）---
#
# ## ⚠⚠ 何が起きていたか
#
#   Windows の Temp に、pytest が作る `pytest-of-<user>/pytest-current` という
#   リンクが**壊れた状態**で残った（★11:40 に発生 / 目印を読むことすらできない:
#   `readlink` / `unlink` / `rmdir` / `dir` すべて WinError 5）。
#
#   pytest は走り終わりに、その置き場の**死んだリンクを掃除**しようとして落ちる。
#
#     ...........                    [100%]   ★検査は全部緑
#     PermissionError: [WinError 5] pytest-current
#     exit=1                                  ⚠⚠ 緑なのに終了コード 1
#
#   ⚠ これは「検査が赤い」ように見え、⚠⚠ `pytest && git commit` の鎖も止める。
#   ★壊れたリンクは消せなかった（管理者でも `chkdsk` の領分）。
#
# → ★置き場を Temp の**別のフォルダ**に移す（`<Temp>/retroux-pytest`）。
#   ★`PYTEST_DEBUG_TEMPROOT` は pytest が `pytest-of-<user>` を作る**親**を決める。
#   ⚠ 外から指定されていれば、それを尊重する（★CI や別環境の邪魔をしない）。
#
# ⚠⚠ **リポジトリの中（`work/` など）に置いてはいけない。**
#   ★最初 `work/pytest-tmp` にしたら、⚠ 隔離の見張り 2 件が赤くなった（★見張りが正しい）:
#     `tests/test_dq3_launcher.py::test_検査中は本物のロックを掴まない`
#     `tests/test_lua_sandbox.py::test_戦術ファイルは本物を指していない`
#   → ★どちらも「一時ファイルがリポジトリの外にあること」で隔離を確かめている。
if not os.environ.get("PYTEST_DEBUG_TEMPROOT"):
    import tempfile

    _temproot = pathlib.Path(tempfile.gettempdir()) / "retroux-pytest"
    _temproot.mkdir(parents=True, exist_ok=True)
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_temproot)


# --- ⚠⚠ 検査の**書き先ごと**を repo の外へ逃がす（RX-0141 / 2026-09-18）------
#
# ## ⚠⚠ 何が起きていたか
#
#   ★`work/dq3-knowledge/` は**依頼者が遊んだ記録の正本**です。
#   ⚠ そこを守る仕掛けが無く、検査が既定パスで書けていました。
#
#     2026-09-18  location-book.json が全件検査の間に 2 回以上書き換わった
#                 （★`tests/test_dq3_sandbox.py` が「本番が変わった」で赤くなって気づいた）
#     2026-09-18  隠し道具の検査が `memo_path` を渡し忘れ、本物の memos.jsonl に 1 行書いた
#
#   ⚠ それまでの守りは**口ごと**でした（tactics.lua / 生成物 / 窓の位置 / 控えのロック）。
#   ★`paths.work("dq3-knowledge", …)` の既定は **25 か所**あり、
#   ⚠⚠ 1 つずつ差し替える形だと**足し忘れた口から素通り**します。
#
# ## ★直し方 — 親を差し替える
#
#   ★`dq3/paths.py` は書き先を `RETROUX_WRITE_ROOT` で決めます（Lua と同じ環境変数）。
#   → ⚠ **import より前**に立てれば、25 か所の定数も**これから増える口も**まとめて逃げます。
#   ★逃がすのは「書くもの」だけです（プレイデータ・記録・state.json・生成物・IPC）。
#   ⚠ ROM・fixture・ffmpeg は `paths.repo()` か repo 直下の道なので**動きません**。
#
#   ⚠ 本物のプレイデータを**読みたい**検査は `paths.repo("work", …)` と書いてください
#     （★`tests/test_dq3_reachable.py` の 2 件がそれ / ⚠ `paths.work` は書き先です）。
#   ⚠ 走行ごと・プロセスごとに分けます（★xdist の worker どうしで取り合わない）。
#   ⚠⚠ repo の中に置かないこと（★隔離の見張り 2 件が「repo の外」で確かめている）。
if not os.environ.get("RETROUX_WRITE_ROOT"):
    import tempfile

    _write_root = (pathlib.Path(tempfile.gettempdir()) / "retroux-pytest"
                   / ("write-%d" % os.getpid()))
    (_write_root / "work").mkdir(parents=True, exist_ok=True)
    os.environ["RETROUX_WRITE_ROOT"] = str(_write_root)

# ⚠⚠ 製品間排他（RX-0152 / RX3-0505）の Mutex を、検査では**本物の名前で取らない**。
#   ★遊んでいる DQ2 / DQ3 と取り合うと、検査が「起動中です」の箱を出して止まる / 遊んでいる側の起動を拒む。
#   ★プロセスごとに分ける（xdist の worker どうしで取り合わない）。
if not os.environ.get("RETROUX_PRODUCT_LOCK_PREFIX"):
    os.environ["RETROUX_PRODUCT_LOCK_PREFIX"] = "Local\\RetroUX_ProductTest_%d" % os.getpid()


# --- ⚠⚠ Lua の隔離先を走行ごとに分ける（RX-0114 Phase 1 / 2026-08-30）------
#
# ## ⚠⚠ 何が起きるところだったか
#
#   `research/probes/reusable/lua_run.py` は、実 Lua を動かす前に
#   `work/tests/lua-sandbox/work/events.jsonl` と `retroux.log` を**空にする**。
#   ★110 個の検査ファイルが、この**同じ 1 か所**を使っていた。
#
#     worker A: lua を動かす → 書く →           読む
#     worker B:          lua を動かす（★ここで空にする）
#     worker A:                                 ⚠ 読むと空
#
#   ⚠ 並列にした瞬間、**ときどき落ちる検査**になる。しかも
#     「書いたはずのものが無い」という顔で出るので、原因に見えない。
#
# ## ★分け方
#
#   `work/tests/lua-sandbox/<worker>-<pid>/`。
#   ⚠ pytest の `tmp_path_factory` を使わないのは、**検査ファイルが
#     import 時に隔離先を定数へ入れている**ため（fixture より早い）。
#     ★`pytest_configure` は collection より前に走るので間に合う。
#
#   ★`<pid>` も付けるのは、⚠ 同じ機械で pytest を 2 本同時に走らせたとき
#     （★私と依頼者が同時に叩く）に worker 番号がぶつかるため。

SANDBOX_ENV = "RETROUX_TEST_SANDBOX"

#: ★置き場そのものを変えたいとき（⚠ ふだんは使いません）
SANDBOX_HOME_ENV = "RETROUX_TEST_SANDBOX_HOME"

SANDBOX_HOME = ROOT / "work" / "tests" / "lua-sandbox"

#: ⚠ これより古い置き土産は片付ける（★秒）。
SANDBOX_KEEP_SECONDS = 24 * 60 * 60


def _sweep_old_sandboxes(now: float) -> None:
    """★古い隔離先を片付ける。

    ⚠ 走行ごとに作るので、**放っておくと増え続ける**。
    ★ただし片付けるのは `work/tests/lua-sandbox/` の中の、
      `<worker>-<pid>` という形の folder だけ（⚠ 既定の `work/` は残す）。
    """
    home = _sandbox_home()
    if not home.is_dir():
        return
    for child in home.iterdir():
        if not child.is_dir() or "-" not in child.name:
            continue  # ★既定の `work/` など
        try:
            if now - child.stat().st_mtime < SANDBOX_KEEP_SECONDS:
                continue
            shutil.rmtree(child, ignore_errors=True)
        except OSError:
            pass  # ⚠ 誰かが使っている最中なら触らない


def _sandbox_home() -> pathlib.Path:
    got = os.environ.get(SANDBOX_HOME_ENV)
    return pathlib.Path(got) if got else SANDBOX_HOME


def pytest_configure(config) -> None:
    """⚠ collection より前に隔離先を決める（★定数の解決に間に合わせる）。

    ## ⚠⚠ 「外から指定されていれば尊重する」で足をすくわれました

      ★最初、こう書いていました。

      ```python
      if os.environ.get(SANDBOX_ENV):
          return          # ⚠ 外から指定されているなら尊重する
      ```

      ⚠⚠ **xdist の worker は、親の環境をそのまま引き継ぎます。**
        親が立てた `RETROUX_TEST_SANDBOX` が worker にも入っているので、
        ★8 つの worker が**全員この return で抜け、同じ隔離先を共有**して
        いました。分けたつもりで、⚠ **1 つも分かれていませんでした**。

      ★見つかり方（2026-08-30）:

      ```text
      8 worker で Lua の検査だけを 6 回まわす
        test_log_sandbox::test_隔離先に実際に書かれている   ⚠ 5/6 で失敗
        test_logging_mode::test_実Luaでdiagnosticには出る    ⚠ 3/6 で失敗
        さらに error が 2〜12 件
      ```

      → ★**必ず自分の pid で作り直します**（⚠ 引き継いだ値は使わない）。
        置き場そのものを変えたいときは `RETROUX_TEST_SANDBOX_HOME`。
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER") or "main"
    mine = _sandbox_home() / ("%s-%d" % (worker, os.getpid()))
    (mine / "work").mkdir(parents=True, exist_ok=True)
    # ★RX3-0495: 足場の Lua が結果を書く置き場（⚠ Lua はフォルダを作れない）
    (ROOT / "work" / "tests" / "out").mkdir(parents=True, exist_ok=True)
    os.environ[SANDBOX_ENV] = str(mine)
    _sweep_old_sandboxes(time.time())


def test_sandbox() -> pathlib.Path:
    """★検査ファイルから隔離先を引くための入口。

    ⚠ `pytest_configure` より前（import 時）でも呼べるように、
      環境変数が無ければ既定を返す。
    """
    got = os.environ.get(SANDBOX_ENV)
    return pathlib.Path(got) if got else SANDBOX_HOME


# --- 敵の表（RX-0090 / 2026-08-21）-------------------------------------------
#
# ★memory_map.yaml には敵の表が**入っていない**（利用者の ROM から起こす）。
#   図鑑・戦況パネルのテストは実値（スライムの HP 6 など）を見るので、
#   ROM（またはそのキャッシュ）が無い環境では**スキップ**する。
#   ⚠ 0 や空で埋めて通さない（「動いた」と嘘をつくことになる）。

import pytest  # noqa: E402


# --- ★テストの段（RX-0114 §20 / 2026-08-30）--------------------------------
#
#   fast        毎回          ⚠ 既定。★目標 1〜2 分
#   validation  節目          ⚠⚠ `--runslow`。★金型との突き合わせなど
#
# ⚠⚠ **既定で走らなくなるものは、走らなくなったと分かるようにします。**
#   ★「0 件は通っていないだけだった」を、この計画では既に踏んでいます。
#   → ⚠ 何件外したかを、走行のたびに画面へ出します。

SLOW_MARK = "slow"
SLOW_FLAG = "--runslow"


# --- ★★ ⚠⚠ 本物の `work/` へ書かせない（RX3-0480 / 2026-10-01）★★ ---------
#
# ## ⚠⚠ 何が起きていたか（★実測）
#
#   2026-10-01 に全件を回して、**本物の `work/` の 3 つが書き換わりました**。
#
#   ```text
#   work/window-state.json  538 → 284 bytes   ⚠⚠ **依頼者の DQ2 の窓の配置が痩せた**
#   work/state_test.json                      ★Lua の検査の出力
#   work/_desktop.png                         ⚠ **開発機の画面を撮った画像**
#   ```
#
#   ★DQ3 側は `RX-0141` / `D-33` で `RETROUX_WRITE_ROOT` に逃がしてあります。
#   ⚠ DQ2 側は手付かずで、`retroux/ui/window_state.py:32` の
#     `DEFAULT_PATH = pathlib.Path("work/window-state.json")` が
#     ⚠⚠ **cwd 相対**なので、pytest の cwd（= repo 直下）に書いていました。
#
# ## ★直し方（⚠ DQ2 の製品コードは触りません）
#
#   ⚠⚠ DQ2 全体の portable 化へは広げません（★依頼者の指示 / 2026-10-01）。
#   → ★検査の間だけ `DEFAULT_PATH` を隔離先へ向けます。
#     ⚠ これで DQ2 の窓を作る検査**ぜんぶ**（★実測 4 本）が一度に逃げます。
#
#   ⚠ 1 本ずつ直す形にしなかった理由: ★この計画は「口ごとに直して足し忘れる」を
#     何度も踏んでいます（`RX-0141` の 25 か所）。**親を差し替える**ほうが強いです。

def _isolate_dq2_window_state() -> str:
    """★DQ2 の窓の記録を隔離先へ向ける（⚠ 戻せたら道を返す / 駄目なら空）。

    ⚠ `retroux.ui.window_state` は PySide6 を import しないので、
      ★ここで読み込んでも重くありません（実測 / import は `os` と `pathlib` だけ）。
    """
    try:
        from retroux.ui import window_state as _ws
    except Exception:                                   # noqa: BLE001
        return ""                                       # ⚠ 無い環境では何もしない
    base = os.environ.get("RETROUX_WRITE_ROOT")
    if not base:                                        # pragma: no cover
        return ""
    got = pathlib.Path(base) / "work" / "window-state.json"
    got.parent.mkdir(parents=True, exist_ok=True)
    _ws.DEFAULT_PATH = got
    return str(got)


# --- ★★ ⚠⚠ 本物の DB へ**繋がせない**（RX3-0480 / 2026-10-01）★★ -----------
#
# ## ⚠⚠ 「再現できない」ではなく「測っていなかった」
#
#   ★2026-10-01 に `work/retroux.sqlite3-wal` / `-shm` が出て、⚠ 1 度しか再現せず
#   「SQLite が開いた跡」として片づけました。→ ⚠⚠ **それは原因の特定ではありません**。
#   ★`sqlite3.connect` を全件走行のあいだ記録したら、**2 本**が名指しで出ました:
#
#   ```text
#   tests/test_map_passability.py::test_実際に歩いた先を通れないと言っていない   1 回
#       ⚠ `sqlite3.connect(DB)`（★select だけだが**読み書きで開いている**）
#   tests/test_icon_buttons_have_tooltips.py::test_the_main_window_icon_buttons…  6 回
#       ⚠ DQ2 の本窓を作るので `Database` が既定の道（`work/retroux.sqlite3`）へ繋ぐ
#   ```
#
#   ⚠⚠ **読むだけでも `-wal` / `-shm` が出来ます**（★WAL の DB を読み書きで開くため）。
#   ★`-wal` を消すと、⚠ 本体へ反映前の変更が**失われます**。だから「開かせない」が要ります。
#
# ## ★直し方（⚠ DQ2 の製品コードは触りません）
#
#   ★`sqlite3.connect` を包み、⚠ 本物の `work/` 配下へ向いた接続を
#   **隔離先の写し**へ付け替えます（★無ければその場で写す / 読めれば検査は同じ答えを出す）。
#   ⚠ 1 本ずつ直さないのは、★「口ごとに直して足し忘れる」を繰り返しているためです。
#
#   ⚠⚠ **黙って付け替えません。** ★付け替えた先は走行の最後に名前つきで出します
#     （`pytest_terminal_summary`）。

#: ★付け替えた接続（道 → 回数）。⚠ worker ごとに別プロセスなので、★親へ集めます
_db_redirects: dict = {}
#: ★★ ⚠⚠ 写しの置き場は **worker ごとに固定**（走行ごとに増やさない）★★
#
#   ⚠⚠ 最初は `RETROUX_TEST_SANDBOX`（= `<worker>-<pid>`）の下に写していました。
#     ★pid が毎回変わるので、⚠ **走行ごとに 42 MB × worker 数が積み上がります**
#     （★実測: 1 回で 521 MB → 685 MB。置き土産は 24 時間残る設定）。
#   → ★pid を含まない固定の場所にして**使い回します**。⚠ 上限は 8 × 42 MB です。
#   ⚠ 元の DB が変わったら写し直します（★大きさと更新時刻を控えておく）。
DB_COPY_DIR_NAME = "_db_copies"
_sqlite_orig = None


def pytest_testnodedown(node, error) -> None:
    """★worker が終わったら、付け替えの記録を親へ集める（⚠ xdist / RX3-0480）。

    ⚠⚠ これが無いと、親の `pytest_terminal_summary` は**自分の分（= 0 件）**しか
      見ないので、★「本物の DB には繋いでいない」という嘘が出ます（2026-10-01 に出した）。
    """
    got = (getattr(node, "workeroutput", None) or {}).get("db_redirects") or {}
    for path, n in got.items():
        _db_redirects[path] = _db_redirects.get(path, 0) + n


def _refresh_db_copy(src: pathlib.Path, want: pathlib.Path) -> None:
    """★元が変わっていたら写し直す（⚠ 同じなら使い回す / 42 MB を毎回は写さない）。

    ⚠⚠ 「写しが在るから使う」だけだと、★元の DB を入れ替えても**古い写しを読み続け**、
      検査は古い観測で緑になります（★`RX3-0232` と同じ形: 作ったもので検算しない）。
    """
    import shutil
    import tempfile

    got = src.stat()
    stamp = want.with_suffix(want.suffix + ".stamp")
    want_stamp = "%d:%d" % (got.st_size, got.st_mtime_ns)
    if want.exists():
        try:
            if stamp.read_text(encoding="utf-8") == want_stamp:
                return
        except OSError:
            pass
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=str(want.parent),
                                      suffix=".part")
    tmp.close()
    shutil.copyfile(src, tmp.name)
    for suffix in ("-wal", "-shm", "-journal"):          # ⚠ 前の走行の跡を持ち越さない
        try:
            pathlib.Path(str(want) + suffix).unlink()
        except OSError:
            pass
    os.replace(tmp.name, want)
    stamp.write_text(want_stamp, encoding="utf-8")


def _isolate_real_sqlite() -> bool:
    """★本物の `work/` 配下への SQLite 接続を、隔離先の写しへ付け替える。

    ⚠ 戻り値は「包めたか」。★二重に包みません。
    """
    global _sqlite_orig
    import sqlite3

    if _sqlite_orig is not None:
        return False
    if not (os.environ.get(SANDBOX_ENV) or os.environ.get("RETROUX_WRITE_ROOT")):
        return False                                    # pragma: no cover
    real_work = (ROOT / "work").resolve()
    worker = os.environ.get("PYTEST_XDIST_WORKER") or "main"
    sandbox_work = _sandbox_home() / DB_COPY_DIR_NAME / worker
    # ⚠⚠ **付け替えを 2 度かけません。** ★隔離先は `work/tests/lua-sandbox/` の下、
    #   つまり**本物の `work/` の中**にあるので、⚠ 写しの道で開き直すと
    #   もう一度付け替わり、★中身が空の別のファイルを読みます（2026-10-01 に実測）。
    sandbox_home = _sandbox_home().resolve()
    _sqlite_orig = sqlite3.connect

    def _resolve(database):
        """★本物の `work/` 直下を指していれば、写しの道を返す（⚠ そうでなければ None）。"""
        text = str(database)
        uri = text.startswith("file:")
        if uri:
            text = text[5:].split("?")[0]
        if not text or text == ":memory:":
            return None
        got = pathlib.Path(text)
        if not got.is_absolute():
            got = pathlib.Path(os.getcwd()) / got
        try:
            got = got.resolve()
        except OSError:                                 # pragma: no cover
            return None
        if got.is_relative_to(sandbox_home):
            return None                                 # ★もう隔離先（⚠ 2 度かけない）
        try:
            rel = got.relative_to(real_work)
        except ValueError:
            return None
        return sandbox_work / rel

    def _connect(database, *a, **kw):
        want = _resolve(database)
        if want is None:
            return _sqlite_orig(database, *a, **kw)
        want.parent.mkdir(parents=True, exist_ok=True)
        src = real_work / want.relative_to(sandbox_work)
        if src.is_file():
            _refresh_db_copy(src, want)
        _db_redirects[str(want)] = _db_redirects.get(str(want), 0) + 1
        # ⚠ `uri=True` で来た接続は、★道だけ差し替えて同じ形で返す
        if str(database).startswith("file:"):
            tail = str(database)[5:]
            query = ("?" + tail.split("?", 1)[1]) if "?" in tail else ""
            return _sqlite_orig("file:%s%s" % (want.as_posix(), query), *a, **kw)
        return _sqlite_orig(str(want), *a, **kw)

    sqlite3.connect = _connect
    return True


# --- ★★ ⚠ 書かれたら**気づく**ための見張り（RX3-0480）★★ -----------------
#
# ⚠⚠ 上の差し替えは「いま分かっている口」しか塞ぎません。
#   ★だから「走ったあとに本物の `work/` が変わっていないか」を**数えます**。
#   ⚠ 黙って skip を増やさないため、★変わっていたら**走行そのものを赤にします**。
#
# ⚠ 見るのは `work/` の**直下のファイル**だけです（★フォルダの中は潜らない）。
#   `work/tests/lua-sandbox/` `work/release/` などは検査と道具の作業場なので対象外です。

#: ⚠⚠ **何も外しません。**
#
#   ★最初は `_` で始まる名前（私の作業用の足跡）を外していましたが、
#   ⚠⚠ **それだと `work/_desktop.png` が見張りから漏れます**
#     （★まさに漏れていた 1 つ）。「歯止めの武装条件に壊れが混ざる」形です。
#   → ★見張りは**1 回の pytest の前後**しか比べないので、
#     ⚠ 私が pytest の外で置いた足跡は**そもそも動きません**（除く必要がない）。
WORK_GUARD_SKIP: tuple = ()

#: ★大きいものも中身まで見る（⚠⚠ 2026-10-01 に 4 MB から上げました / RX3-0480）
#
#   ⚠⚠ **4 MB だと `work/retroux.sqlite3`（42 MB）は大きさだけの比較**でした。
#     ★SQLite のページは固定長なので、⚠ WAL を本体へ反映しても**大きさは変わらない**
#     ことがあります → ★見張りは「無事」と言い続けます（⚠ 歯止めの盲点）。
#   ★`work/` 直下の 4 MB 超は 5 件・合計 84 MB（実測）。⚠ 指紋を取るのは
#     走行の前後の 2 回だけで、★340 秒の走行に対して 1 秒ほどです（実測）。
WORK_GUARD_MAX_BYTES = 256 * 1024 * 1024

_work_guard_before: dict = {}


def _work_snapshot() -> dict:
    """★`work/` の直下のファイルを (大きさ, 中身の指紋) で撮る。"""
    out: dict = {}
    work = ROOT / "work"
    if not work.is_dir():
        return out
    for got in work.iterdir():
        if got.is_dir() or got.name.startswith(WORK_GUARD_SKIP):
            continue
        try:
            size = got.stat().st_size
            if size > WORK_GUARD_MAX_BYTES:
                out[got.name] = "size:%d" % size
                continue
            import hashlib

            out[got.name] = "%d:%s" % (
                size, hashlib.sha256(got.read_bytes()).hexdigest()[:16])
        except OSError:
            continue
    return out


def pytest_sessionstart(session) -> None:
    """★親の `config` を覚えておく（RX-0130）。"""
    _config_hook(session.config)
    # ⚠ xdist の worker では撮りません（★親だけが前後を比べます）
    if not hasattr(session.config, "workerinput"):
        _work_guard_before.update(_work_snapshot())
    _isolate_dq2_window_state()
    _isolate_real_sqlite()


def pytest_addoption(parser) -> None:
    parser.addoption(
        SLOW_FLAG, action="store_true", default=False,
        help="⚠ 重い検査（★金型との突き合わせなど）も走らせる")


def pytest_collection_modifyitems(config, items) -> None:
    """⚠ `--runslow` が無ければ `slow` を飛ばす。★飛ばした数を出す。"""
    if config.getoption(SLOW_FLAG):
        return
    skip = pytest.mark.skip(
        reason="⚠ 重い検査です。★走らせるには %s" % SLOW_FLAG)
    count = 0
    for item in items:
        if SLOW_MARK in item.keywords:
            item.add_marker(skip)
            count += 1
    if count:
        config.stash[_SLOW_SKIPPED] = count


_SLOW_SKIPPED = pytest.StashKey[int]()


# --- ★経過時間を出す（RX-0130 / 2026-09-03）--------------------------------
#
#   ⚠ `pytest` は**終わってから**しか時間を出しません。
#     ★3 分半のあいだ点が進むだけで、⚠ 「あと何分か」も
#     「止まったのか動いているのか」も分かりませんでした。
#
#   ⚠⚠ 一度踏んでいます（★`Out-String` で 4 分 35 秒の無反応 / `RX-0111`）。
#     そのときは `-q` をやめて点を出しましたが、★時間は出ていませんでした。
#
#   ★10% ごとに 1 行だけ出します。⚠ 8 worker では行の順番が入り混じるので、
#     1 行ずつ出すのは**かえって読みにくい**（案A を採らなかった理由）。

#: ★何 % ごとに出すか
PROGRESS_STEP = 10

#: ⚠ これより短く終わりそうな run では出さない（★秒）
#:   ⚠⚠ 2 秒で終わる run に 10 行出ると、かえって読みにくい。
PROGRESS_MIN_SECONDS = 20

_progress = {"total": 0, "done": 0, "start": 0.0, "next": PROGRESS_STEP,
             "reporter": None, "config": None, "shown": False}


def _is_worker(config) -> bool:
    """⚠ xdist の worker では出さない（★同じ行が 8 本出る）。"""
    return hasattr(config, "workerinput")


def _config_hook(config) -> None:
    """★親の `config` を覚える（⚠ worker では何もしない）。"""
    if _is_worker(config):
        return
    _progress["config"] = config


def _start(got) -> bool:
    """★件数と開始時刻を、最初の report のときに拾う。

    ⚠⚠ xdist では `pytest_report_collectionfinish` が**親で発火しません**
      （★「8 workers [4563 items]」を出しているのは xdist 自身）。
      → ★端末側が持っている件数を、走り出してから拾います。
    """
    config = got.get("config")
    if config is None:
        return False
    reporter = config.pluginmanager.getplugin("terminalreporter")
    if reporter is None:
        return False
    total = getattr(reporter, "_numcollected", 0) or 0
    if not total:
        session = getattr(reporter, "_session", None)
        total = getattr(session, "testscollected", 0) or 0
    if not total:
        return False
    got["total"] = total
    got["start"] = time.monotonic()
    got["reporter"] = reporter
    return True


def pytest_runtest_logreport(report) -> None:
    """★10% ごとに「経過 / 残り およそ」を出す。

    ⚠ `teardown` だけを数えます（★1 件につき 1 回）。

    ⚠⚠ 併せて、飛んだ理由も集めます（★`SKIP_MUST_NOT` / D-35）。
      ★`setup` で飛ぶもの・`call` で飛ぶものの両方が来るので、★先に拾います。
    """
    # ⚠⚠ `xfail` も `report.skipped` で来ます（★理由の欄に assert 本文が入る）。
    #   ★`wasxfail` が付いているものは skip ではありません（2026-09-29 に実測）。
    if getattr(report, "skipped", False) and not hasattr(report, "wasxfail"):
        key = (report.nodeid, _skip_reason(report))
        _skipped_reasons[key] = _skipped_reasons.get(key, 0) + 1
    if report.when != "teardown":
        return
    got = _progress
    if not got["total"] and not _start(got):
        return
    if got["reporter"] is None:
        return
    got["done"] += 1
    pct = got["done"] * 100 // got["total"]
    if pct < got["next"]:
        return
    got["next"] = (pct // PROGRESS_STEP + 1) * PROGRESS_STEP
    used = time.monotonic() - got["start"]
    left = used / max(got["done"], 1) * (got["total"] - got["done"])
    # ⚠ 短い run では出さない（★一度出したら最後まで出す）
    if not got["shown"]:
        if used + left < PROGRESS_MIN_SECONDS:
            return
        got["shown"] = True
    got["reporter"].write_line(
        "  ★%3d%%  %.0f 秒経過 / 残り およそ %.0f 秒（%d / %d 件）"
        % (pct, used, left, got["done"], got["total"]))


# --- ⚠⚠ skip は「件数」ではなく「理由」で見る（D-35 / RX3-0475）----------------
#
#   ★2026-09-29 に実際に起きたこと（`RX3-0474`）:
#
#     ⚠ 全件の skip が走行ごとに 47 ⇄ 51 で揺れた。⚠⚠ **合計は同じ**なので、
#       「7379 passed」だけ見ていると**緑のまま**。中身は、ネタバレの歯止め
#       （`test_ROMの20件を素で出さない`）が ROM を読めずに飛んでいた。
#
#   → ★だから件数は合否に使いません。⚠ 見るのは「**その理由で飛んでよいか**」。
#
#   ## ★2 つに分けています
#
#     ① `SKIP_MUST_NOT`  ⚠⚠ **起きてはいけない理由**（★理由 ＋ WI 番号 ＋ 条件）
#                        → 1 件でも出たら**この走行を赤にします**
#     ② 理由の一覧表示    ★飛んだ理由を件数つきで最後に出す（⚠ 数えるためではない）
#
#   ⚠ 許可リスト側（「飛んでよい理由」の全列挙）にはしていません。
#     ★まっさらな環境では素材が無い skip が増えるので、⚠ 全列挙は
#     環境ごとに赤くなり、**歯止めを外す圧力**になります（RX-0138 と同じ形）。

#: ★この理由で飛んだら欠陥、という組（`理由の一部`, `WI`, `なぜ`, `いつ見るか`）
#:
#:   ⚠ 4 つめは「この環境でこの規則を当てにしてよいか」を返す関数です。
#:     ★ROM を置いていない人の走行を赤にしないため（⚠ 鳴りすぎも壊れ方）。
SKIP_MUST_NOT: tuple = ()


def _dq3_rom_is_readable() -> bool:
    """★DQ3 の ROM が**いま実際に読める**か（⚠ 置いてあるかではない）。

    ⚠⚠ **`rom_names` を経由しないこと。** ★あの memo は `RX3-0474` で汚れる
      当のものです。⚠ 経由すると「汚れているから条件も False」になり、
      **歯止めが鳴りません**（★2026-09-29 に実際に空振りさせました）。
    """
    try:
        from dq3 import paths as P3
        from dq3rom import profile as P
        from dq3rom import rura

        got = P3.rom()
        return got is not None and bool(rura.read_points(P.load_and_identify(got)))
    except Exception:                                  # noqa: BLE001 - ★読めない扱い
        return False


SKIP_MUST_NOT = (
    ("ROM が読めません", "RX3-0474",
     "★ROM が読めているのに飛ぶのは欠陥です（⚠ 2026-09-29 は共有 memo の汚れで"
     " ネタバレの歯止め 4 件が黙って飛び、件数だけが 47 ⇄ 51 で揺れました）",
     _dq3_rom_is_readable),
)

#: ★飛んだ理由（⚠ 親プロセスに集めます。xdist の worker の report も親に来る）
_skipped_reasons: dict = {}


def _skip_reason(report) -> str:
    """★`(path, lineno, "Skipped: 理由")` から理由だけ取り出す。"""
    got = getattr(report, "longrepr", None)
    text = got[2] if isinstance(got, tuple) and len(got) == 3 else str(got or "")
    return text.split("Skipped: ", 1)[-1].strip()


def _skip_violations() -> list:
    """⚠⚠ 起きてはいけない理由で飛んだものを並べる（★条件が成り立つときだけ）。"""
    out = []
    for want, wi, why, applies in SKIP_MUST_NOT:
        hit = {k: v for k, v in _skipped_reasons.items() if want in k[1]}
        if not hit or not applies():
            continue
        for (nodeid, reason), count in sorted(hit.items()):
            out.append((nodeid, reason, wi, why, count))
    return out


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """⚠⚠ **黙って減らさない**（★`CLAUDE.md` の実装の基本ルール）。"""
    count = config.stash.get(_SLOW_SKIPPED, 0)
    if count:
        terminalreporter.write_line(
            "⚠ 重い検査を %d 件飛ばしました（★全部走らせるには %s）"
            % (count, SLOW_FLAG))

    # ★飛んだ理由を出す（⚠ 件数は「内訳」として出すだけ。合否には使わない）
    if _skipped_reasons:
        by_reason: dict = {}
        for (_nodeid, reason), n in _skipped_reasons.items():
            by_reason[reason] = by_reason.get(reason, 0) + n
        terminalreporter.write_line(
            "★飛ばした理由 %d 種（⚠ 件数ではなく理由で見てください / D-35）"
            % len(by_reason))
        for reason, n in sorted(by_reason.items(), key=lambda x: (-x[1], x[0])):
            terminalreporter.write_line("    %3d 件  %s" % (n, reason[:100]))

    for nodeid, reason, wi, why, n in _skip_violations():
        terminalreporter.write_line(
            "⚠⚠ 飛んではいけない理由で飛びました（%s / %d 件）: %s\n"
            "      理由: %s\n      %s" % (wi, n, nodeid, reason, why))

    # ⚠⚠ 隔離を**黙ってやりません**（★RX3-0480 / 付け替えた先を名前で出す）
    if _db_redirects:
        terminalreporter.write_line(
            "★本物の DB への接続を隔離先の写しへ付け替えました（%d 種 / RX3-0480）"
            % len(_db_redirects))
        for path, n in sorted(_db_redirects.items()):
            terminalreporter.write_line("    %d 回  %s" % (n, path))


def work_guard_changes() -> list[str]:
    """⚠⚠ 走行の前後で、★本物の `work/` の直下が変わっていないか。

    戻り値は変わったものの説明（★空なら無事）。
    """
    if not _work_guard_before:
        return []
    after = _work_snapshot()
    out = []
    for name in sorted(set(after) - set(_work_guard_before)):
        out.append("+ work/%s（★新しく出来た）" % name)
    for name in sorted(set(_work_guard_before) - set(after)):
        out.append("- work/%s（⚠⚠ 消えた）" % name)
    for name in sorted(set(after) & set(_work_guard_before)):
        if after[name] != _work_guard_before[name]:
            out.append("~ work/%s（⚠ 中身が変わった: %s → %s）"
                       % (name, _work_guard_before[name], after[name]))
    return out


def pytest_sessionfinish(session, exitstatus) -> None:
    """⚠⚠ 起きてはいけない理由の skip が 1 件でもあれば、★この走行を赤にする。

    ⚠ skip は既定では緑です。★だから「飛んだ」ことに気づけません
      （`RX3-0474` は 10 日ぶん気づけませんでした）。

    ★★ ⚠⚠ **本物の `work/` を書き換えたら赤にします**（RX3-0480 / 2026-10-01）★★

      ⚠ 2026-10-01 の実測で、全件が依頼者の `work/window-state.json` を
        **538 → 284 bytes に痩せさせていました**（★DQ2 の窓の配置）。
      ⚠⚠ 検査が緑なのに依頼者のデータが減るのは、★いちばん気づけない壊れ方です。
    """
    # ⚠⚠ worker は**別プロセス**なので、★親へ渡さないと報告が消えます
    #   （★2026-10-01: 同じ形で「本物の DB への接続 0 件」という嘘を 1 度出しました）
    out = getattr(session.config, "workeroutput", None)
    if out is not None:
        out["db_redirects"] = dict(_db_redirects)
    if _skip_violations():
        session.exitstatus = 1
    changed = work_guard_changes()
    if changed:
        # ⚠ `write_line` は使えない（★terminalreporter がここには無い）
        print("\n⚠⚠ 検査が本物の work/ を書き換えました（★%d 件）" % len(changed))
        for line in changed:
            print("    " + line)
        print("★書き先を隔離してください（⚠ `RETROUX_WRITE_ROOT` / `tmp_path`）。")
        print("⚠⚠ 中身は**戻していません**（★依頼者のものかもしれないため）。")
        session.exitstatus = 1



def load_memory_map_with_enemies() -> dict:
    """YAML + ROM 由来の5表。無ければ pytest.skip。"""
    import yaml
    from retroux.core import enemy_tables

    mm = yaml.safe_load((ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml")
                        .read_text(encoding="utf-8"))
    enemy_tables.attach(mm, ROOT / "work" / "rom" / "DQ2_J.nes",
                        ROOT / "work" / "generated" / enemy_tables.CACHE_NAME)
    if "monsters" not in mm:
        pytest.skip("敵の表が無い（ROM もキャッシュも無い環境）")
    return mm


@pytest.fixture(scope="session")
def memory_map_with_enemies() -> dict:
    return load_memory_map_with_enemies()


# --- ⚠⚠ 検査が本物のセーブステート保護を止めないようにする -------------------
#
#   ★2026-08-29 に実際に起きたこと:
#
#     20:29:44  依頼者がショートカットから起動 → 控えが立つ
#     20:30:41  ⚠⚠ 控えが**止まった**（running: false）
#     20:31:24  work/savestate_backup.stop が書かれていた
#
#   ⚠ 犯人は**走っていた pytest**。画面（`retroux/ui/main_window.py:1041`）の
#     `closeEvent` が、後始末で**本物の** `work/savestate_backup.stop` を書く。
#     ★`tests/test_main_window_close.py` の冒頭にも
#     「closeEvent 全体は teardown で実 work/ を触る（.stop 書き込み等）」とある。
#
#   ⚠⚠ **検査を走らせるたびに、遊んでいる人の控えが黙って止まる。**
#     ★守るために作った仕組みを、検査が壊していた。
#
#   → ★`backup_lock` の場所だけを一時フォルダへ逃がす。
#     ⚠ 名前は変えない（`savestate_backup.lock` を見る検査があるため）。


@pytest.fixture(scope="session", autouse=True)
def _本物の戦術ファイルを書かない(tmp_path_factory):
    """⚠⚠ **検査が本物の `work/generated/tactics.lua` を書いていました。**

    ## ★どうやって見つけたか（RX-0114 Phase 2 / 2026-08-30）

      8 worker で走らせたら、⚠ 毎回**違う検査**が 1 件だけ落ちました。

        1 回目  test_ok_closes_the_window_after_it_really_applied
        2 回目  test_ok_saves_the_changes_before_applying

      ★出ていた文言:

        ⚠ エミュレータへ渡せませんでした（閲覧専用か、書けない状態です）。

      `lua_bridge.write` は `tactics.lua.tmp` という**決め打ちの名前**で
      書いてから置き換えます。⚠ 2 つの worker が同時に書くと、
      片方の `.tmp` をもう片方が消し、`os.replace` が失敗します。

    ## ⚠⚠ 並列だから起きたのではありません

      ★**そもそも本物を書いていたこと**が問題です。
      ⚠ 1 worker では「たまたま 1 人しかいなかった」だけでした。

      ★`DEFAULT_PATH` を差し替えていた検査は **1 件だけ**で、
      残りは素通りしていました。
    """
    from retroux.core.tactics import lua_bridge

    sandbox = tmp_path_factory.mktemp("tactics-lua")
    original = lua_bridge.DEFAULT_PATH
    lua_bridge.DEFAULT_PATH = sandbox / "tactics.lua"
    try:
        yield sandbox
    finally:
        lua_bridge.DEFAULT_PATH = original


@pytest.fixture(scope="session", autouse=True)
def _本物の控えを止めない(tmp_path_factory):
    """⚠ 検査中は `backup_lock` を一時フォルダへ向ける。"""
    from retroux.core.config.user_config import UserConfig

    sandbox = tmp_path_factory.mktemp("backup-lock")
    original = UserConfig.path

    def path(self, name: str):
        if name == "backup_lock":
            # ★名前はそのまま（`.stop` も `.status.json` も隣に出る）
            return sandbox / "savestate_backup.lock"
        return original(self, name)

    UserConfig.path = path
    try:
        yield sandbox
    finally:
        UserConfig.path = original


@pytest.fixture(scope="session", autouse=True)
def _本物の窓の位置を読み書きしない(tmp_path_factory):
    """⚠ 検査で作った DQ3 の画面が、本物の `work/dq3-window-state.json` を読み書きしない（RX3-0200）。

    ★閉じると位置を書く（`save_window_positions`）。⚠ 検査が閉じると、遊んでいる人の配置を上書きする。
    """
    try:
        from dq3.ui import main_window
    except Exception:                                   # noqa: BLE001 ★Qt の無い環境
        yield None
        return
    original = main_window.WINDOW_STATE_PATH
    main_window.WINDOW_STATE_PATH = tmp_path_factory.mktemp("dq3-window-state") / "dq3-window-state.json"
    try:
        yield main_window.WINDOW_STATE_PATH
    finally:
        main_window.WINDOW_STATE_PATH = original


@pytest.fixture(scope="session", autouse=True)
def _本物の生成物を書かない(tmp_path_factory):
    """⚠⚠ **検査が、Lua の読む本物の `work/generated/dq3_enemy_book.lua` を空で上書きしていました**（RX3-0215）。

    ## ★どうやって見つけたか（2026-09-12）

      依頼者「save5 初見ではない認識だが、オートターボがきかない」。★`auto_v0.log` は 18:21 以降の
      全戦闘が「倒したことのある敵か: いいえ」。★その時の生成物は `defeated = {}`（122 バイト）で、
      ★`tests/test_dq3_enemies_seen.py` の逃げた戦闘の検査が書く中身と同じだった（⚠ 全件検査の最中）。

    ## ★直し方

      ★書き先を決める口（`overlay_path` 3 つ / 戦闘 AI の `generate.OUT_DIR`）を一時フォルダへ向ける。
      ⚠ 画面を作る検査（`main_window` の起動）も、まんたん・自動戦闘・戦闘 AI の生成物を本物へ書いていた。
    """
    try:
        from dq3.battle_ai import generate as G
        from dq3.phase0 import battle_auto_overlay as BA
        from dq3.phase0 import enemy_book_overlay as EO
        from dq3.phase0 import mantan_settings as MS
    except Exception:                                   # noqa: BLE001 ★読めない環境
        yield None
        return
    from dq3 import paths as P3

    sandbox = tmp_path_factory.mktemp("dq3-generated")
    real = P3.repo("work", "generated").resolve()
    saved = [(mod, mod.overlay_path) for mod in (EO, BA, MS)]

    def redirect(original):
        def overlay_path(out_dir=None):
            got = original(out_dir)
            # ★本物の repo の work/generated に落ちる時だけ逃がす
            #   （⚠ 検査が自分で RETROUX_WRITE_ROOT や out_dir を渡した時は、その場所を守る）
            if out_dir is None and got.resolve().parent == real:
                return original(sandbox)
            return got
        overlay_path.__wrapped__ = original
        return overlay_path

    for mod, original in saved:
        mod.overlay_path = redirect(original)
    original_out = G.OUT_DIR
    G.OUT_DIR = sandbox
    try:
        yield sandbox
    finally:
        for mod, original in saved:
            mod.overlay_path = original
        G.OUT_DIR = original_out


def _window_pid(hwnd) -> int:
    """★窓の持ち主のプロセス番号（⚠ Win32 でなければ 0）。"""
    import sys

    if sys.platform != "win32" or not hwnd:
        return 0
    import ctypes
    import ctypes.wintypes as wt

    pid = wt.DWORD()
    ctypes.WinDLL("user32").GetWindowThreadProcessId(wt.HWND(int(hwnd)), ctypes.byref(pid))
    return int(pid.value)


@pytest.fixture(scope="session", autouse=True)
def _よその窓に触らない():
    """⚠⚠ **検査が、遊んでいる人の FCEUX を閉じていました**（RX-0138 / 2026-09-12）。

    ## ★どうやって見つけたか

      依頼者「いま save0 で何回か FCEUX が落ちた」。★2 回とも全件検査の最中で、
      ★Lua の後始末（`DEV end`）が走っていた（⚠ 強制終了ではなく、**閉じてくれと頼まれた**形）。
      ★囮の窓（題名「FCEUX 2.6.6: DECOY」）を置いて全件を回すと、⚠ **WM_CLOSE が 97 回**届いた。

    ## ★直し方

      ⚠ 窓を閉じる・動かす・前へ出す・速度を送る・音を消す、は全部「題名が FCEUX の**最初の窓**」に効く。
      → ★窓を探す口（`window_align.find_windows` / `emu_speed.find_fceux`）を、
        ★**この検査のプロセスが持つ窓だけ**に絞る（★検査が自分で作った窓はこれまでどおり見える）。
      ⚠ どの検査が送ったかを 1 件ずつ直すより、★口で止めるほうが漏れない（⚠ 検査は増える）。
    """
    import os

    from dq3.ui import emu_speed
    from retroux.core import window_align

    mine = os.getpid()
    original_find = window_align.find_windows
    original_fceux = emu_speed.find_fceux

    def own_windows(title, match="contains"):
        return [w for w in original_find(title, match=match) if _window_pid(w.handle) == mine]

    def own_fceux():
        hwnd = original_fceux()
        return hwnd if hwnd and _window_pid(hwnd) == mine else 0

    own_windows.__wrapped__ = original_find
    own_fceux.__wrapped__ = original_fceux
    window_align.find_windows = own_windows
    emu_speed.find_fceux = own_fceux
    try:
        yield
    finally:
        window_align.find_windows = original_find
        emu_speed.find_fceux = original_fceux


def prepare_dq3_probe(slot: str = "DQ3_J.fc2") -> pathlib.Path:
    """★DQ3 の Lua 足場が読む材料を、**その走行の隔離先に**置く。

    ## ⚠⚠ 順番に頼っていました（RX-0114 / 2026-08-30）

      ```text
      pytest tests/test_dq3_auto_v0.py tests/test_dq3_dev.py   ★33 passed
      pytest tests/test_dq3_dev.py tests/test_dq3_auto_v0.py   ⚠ 8 errors
      ```

      ⚠ `test_dq3_auto_v0.py` だけがこれを置いており、
        ★`test_dq3_dev.py` はそれに乗っかっていました。

      ⚠⚠ 8 並列だと、どちらが先かは**運**です。しかも隔離先は
        worker ごとに分かれたので、★**別の worker のぶんは見えません**。

    ★使う側が自分で呼びます（⚠ 呼び忘れると skip ではなく落ちます）。
    """
    from retroux.core.bgmap import savestate as ss

    from dq3.phase0.generate_lua import build, write_lua

    state_path = ROOT / "tools" / "fceux" / "fcs" / slot
    write_lua(build())                                   # ⚠ 生成し忘れ防止
    out = test_sandbox() / "work" / "runtime" / "dq3-probe"
    out.mkdir(parents=True, exist_ok=True)
    (out / "auto_v0.log").write_text("", encoding="utf-8")
    state = ss.load(state_path)
    # ★画面と RAM は**同じセーブステート**から取る。
    #   ⚠ 別々にすると、名前が食い違って「誰の手番か」が決まらない。
    ram = state.chunks["RAM"]
    (out / "ram.txt").write_text(
        "\n".join("%04X %02X" % (0x0700 + i, ram[0x0700 + i])
                   for i in range(0x100)) + "\n", encoding="utf-8")
    nt = state.chunks["NTAR"][:960]
    (out / "nametable.txt").write_text(
        "\n".join(" ".join("%02X" % b for b in nt[y * 32:(y + 1) * 32])
                   for y in range(30)) + "\n", encoding="utf-8")
    return out


def pytest_report_header(config):
    """⚠⚠ セーブを撮り直すと検査が赤くなる。★その理由を**見出しに出す**（RX-0135）。

    ★依頼者が普通に遊ぶと `tools/fceux/fcs/DQ3_J.fc*` は上書きされます。
    ⚠ 2026-08-31 と 2026-09-07 の 2 回、★「回帰かセーブか」で悩みました。
    → ⚠ 指紋（`tests/data/savestate-fingerprints.json`）と比べて、**先に**言います。
    """
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from scripts.update_savestate_fingerprints import changed
    except Exception:                                    # noqa: BLE001 ★出せないだけ
        return None
    try:
        sys.path.insert(0, str(ROOT / "tests"))
        from savestate_dir import PINNED, is_pinned
    except Exception:                                    # noqa: BLE001
        is_pinned = None
    if is_pinned is not None and is_pinned():
        # ★写しを使っているので、⚠ 依頼者が遊んでも検査は動きません（RX-0135 A）
        return ["★検査は固定した写しのセーブを使っています: %s" % PINNED,
                "   ⚠ 撮り直すときは:"
                " PYTHONUTF8=1 python scripts/pin_savestates.py"]
    try:
        got = changed()
    except Exception:                                    # noqa: BLE001
        return None
    if not got:
        return None
    return [
        "⚠⚠ セーブステートが撮り直されています: " + ", ".join(got),
        "   ★赤い検査は、回帰ではなくこれが原因かもしれません（RX-0135）。",
        "   ⚠ 新しいセーブを正とするなら:"
        " PYTHONUTF8=1 python scripts/update_savestate_fingerprints.py",
    ]
