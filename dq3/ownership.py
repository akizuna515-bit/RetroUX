"""所有境界の一覧（RX3-0472 / 2026-10-01）— ★**誰のものか**を 1 か所で決める。

```text
shipped   配布 ZIP が持っている        ⚠ 新しい版で丸ごと入れ替わる
user      利用者のもの                 ⚠⚠ 配布物に**入れない** / 版を上げても引き継ぐ
derived   作り直せるもの               ★引き継がない（⚠ 新しい版で作り直す）
dev       開発機と検査だけのもの       ⚠ 配布物にも引き継ぎにも出てこない
dq2       DQ2 のもの                   ⚠⚠ DQ3 は触らない（★引き継がない・消さない / RX3-0506）
```

## ⚠⚠ なぜ 1 か所なのか

★この計画は「**見張る対象を足し忘れて素通り**」を何度も踏んでいます
（`RX3-0164` の ZIP から `dq3/` が丸ごと欠けた件、`RX3-0217` の記録の口が
2 本あった件）。⚠ 一覧が 2 つあると、**片方だけ古くなったことに気づけません**。

→ ★だから引き継ぎの道具・README・検査・build は、**この module だけ**を見ます。
  ⚠⚠ コピーする一覧をどこかへ写さないこと（★写した瞬間に歯止めが死にます）。

## ★足し忘れの歯止め

`tests/test_dq3_ownership.py` が、⚠ 製品コードが `paths.work(...)` へ渡している
**リテラルの第 1 区画を全部集めて**、★どれかの分類に入っていることを見ます。
⚠ 新しい機能が `work/なにか` へ書き始めた瞬間に**赤くなります**
（★`code_write_segments()` がその採取をします）。

## ★使い方

```python
from dq3 import ownership as OWN

OWN.classify("work/dq3-knowledge")        # → "user"
OWN.user_data_paths(root)                 # ★引き継ぐ実体（⚠ 在るものだけ）
OWN.resolve("data/dq3/hero-memo.yaml")    # ★user 側にあればそちら（案 A）
OWN.unclassified(root)                    # ⚠ どの分類にも入っていないもの
```

> ⚠ 判断の経緯は `docs/20-decision-log.md` の `D-38` / `D-39`、
> 台帳は `docs/12-work-items-dq3.md` の `RX3-0472` です（★ここには写しません）。
"""
from __future__ import annotations

import dataclasses
import fnmatch
import hashlib
import json
import pathlib
import re

from dq3 import paths as P3

#: ★分類の名前（⚠ 文字列を各所に書かない）
KIND_USER = "user"
KIND_DERIVED = "derived"
KIND_DEV = "dev"
#: ⚠⚠ 別の製品（DQ2）のもの。★DQ3 は**写さず・消さず・作り直しもしない**（RX3-0506）
KIND_DQ2 = "dq2"

#: ★引き継ぐのはこれだけ（⚠ `derived` と `dev` は引き継がない）
MIGRATED_KINDS = (KIND_USER,)


@dataclasses.dataclass(frozen=True)
class Owned:
    """★root からの相対パス 1 つの持ち主（⚠ `rel` は posix / `*` が使えます）。

    ```text
    rel              work/dq3-knowledge   ★フォルダなら中身ごと
    kind             user / derived / dev
    why              ⚠ なぜその分類なのか（★人が読む）
    label            ★引き継ぎ画面に出す言葉（⚠ 空なら出さない）
    evidence_of_use  ★「もう遊んだ / 使った」と言える印か
    ```

    ## ⚠⚠ `evidence_of_use` が要る理由（RX3-0471 / 2026-10-01）

    ★引き継ぎの誘いを出すかは「user data が 1 件も無いか」で決めたい。
    ⚠ ところが **まっさらな新版でも 2 つは普通に在ります**:

    ```text
    work/rom/                   ★案内（PLACE-ROM-HERE.txt）どおり置いた直後
    work/dq3-window-state.json  ⚠⚠ 1 度起動して**閉じた**だけで出来る（実測）
    ```

    ⚠ これを「使用済み」と数えると、★ROM を置いた人には**誘いが 1 度も出ません**。
    → ⚠⚠ だから「在っても遊んだ証拠にはならない」ものに印を付けます。
      ★`evidence_of_use=False` でも **user であることは変わりません**
      （⚠ 引き継ぎの対象で、上書きもしません）。
    """

    rel: str
    kind: str
    why: str
    label: str = ""
    evidence_of_use: bool = True


@dataclasses.dataclass(frozen=True)
class Override:
    """★shipped で配るのに、⚠ **人が書き換える**ファイル（案 A の対象）。"""

    rel: str
    why: str
    label: str = ""


# ----------------------------------------------------------------------
# ★★ user — ⚠⚠ 配布 ZIP に入れてはいけない / 版を上げても引き継ぐ ★★
#
#   ⚠ ここに足し忘れると、★方式 B で**引き継がれずに消えます**
#     （⚠⚠ `savestate-backup` と `dq3-knowledge` は**戻りません**）。
# ----------------------------------------------------------------------

USER_DATA: tuple[Owned, ...] = (
    Owned("user_config.yaml", KIND_USER,
          "★ROM と FCEUX の場所（⚠ 利用者しか知らない）",
          label="設定（ROM / FCEUX の場所）"),
    Owned("work/user-data", KIND_USER,
          "★shipped を書き換えたいときの置き場（⚠ 案 A の user 側）",
          label="カスタマイズ（キー割り当て・勇者メモの原本など）"),
    Owned("work/dq3-knowledge", KIND_USER,
          "⚠⚠ 踏破・図鑑・会話・メモの蓄積（★遊んだぶんだけ増える）",
          label="勇者メモ / 図鑑 / 会話 / 踏破の記録"),
    Owned("work/savestate-backup", KIND_USER,
          "⚠⚠ セーブステートの控え（★消えたら戻りません）",
          label="セーブステートの控え"),
    Owned("work/playdata-archive", KIND_USER,
          "⚠⚠ 初期化する前に退避したプレイデータ（★`playdata.py` が写す先）",
          label="初期化前に退避したプレイデータ"),
    Owned("work/rom", KIND_USER,
          "★既定の ROM 置き場（⚠ 外に置いている人には無い）",
          label="ROM（★この中に置いている場合）",
          # ⚠ `PLACE-ROM-HERE.txt` のとおり置いた直後に在る（★遊んだ証拠ではない）
          evidence_of_use=False),
    Owned("work/dq3-ui-settings.json", KIND_USER,
          "★作戦・役割・まんたんの設定（⚠ 画面で選んだもの）",
          label="作戦 / 役割 / まんたんの設定"),
    Owned("work/dq3-window-state.json", KIND_USER,
          "★窓の位置と大きさ",
          label="画面の配置",
          # ⚠⚠ 1 度起動して**閉じた**だけで出来る（2026-10-01 実測 / ★遊んだ証拠ではない）
          evidence_of_use=False),
)

# ----------------------------------------------------------------------
# ★★ derived — ⚠ 作り直せる（★引き継がない / 消してよい）★★
#
#   ⚠⚠ 「重いから引き継ぐ」は成り立ちません。★モンスターの絵 139 枚の作り直しは
#     **0.50 秒**でした（2026-09-30 実測 / `RX3-0472`）。
# ----------------------------------------------------------------------

DERIVED: tuple[Owned, ...] = (
    Owned("work/generated", KIND_DERIVED,
          "★設定 Lua（⚠ 起動のたびに作る）"),
    # ★RX3-0496: 作り直せる派生物の区分（⚠ 中身は dq3-monster-art/・dq3-world-model/）
    #   dq3-monster-art = ROM から起こした絵（⚠ 139 枚 / 0.42 秒で作り直せる / 2026-10-01 実測）
    Owned("work/cache", KIND_DERIVED,
          "★作り直せる派生物（⚠ ROM から起こした絵・世界のモデル）"),
    # ★RX3-0493: 起動のたびに書くものの区分（⚠ 中身は `paths.runtime(...)` を通る）
    #   dq3-log/（製品の記録）・dq3-nav/（経路の格子）・dq3-command.json・dq3-gamepad.txt・state.json（IPC）
    #   dq3-probe/（実測の記録 / ⚠ 画面が読むが、無くても動く）
    Owned("work/runtime", KIND_DERIVED,
          "★起動のたびに書くもの（⚠ IPC・製品の記録・経路の格子・実測の記録 / 作り直せる）"),
    Owned("work/retroux.log*", KIND_DERIVED,
          "★記録（⚠ `RotatingFileHandler` が世代を作る）"),
    Owned("work/state.json", KIND_DERIVED,
          "⚠ IPC（★DQ2 の bridge.lua が書く / ⚠ DQ3 は work/runtime/state.json / RX3-0493）"),
    Owned("work/state_test.json", KIND_DERIVED, "⚠ IPC の見本"),
    Owned("work/command.json", KIND_DERIVED, "⚠ IPC（★DQ2 由来）"),
    Owned("work/*.status.json", KIND_DERIVED, "⚠ 動いている印"),
    Owned("work/*.lock", KIND_DERIVED, "⚠ 動いている印"),
    Owned("work/*.stop", KIND_DERIVED, "⚠ 止める合図"),
    Owned("work/.migration-incomplete", KIND_DERIVED,
          "⚠⚠ 引き継ぎが途中で終わった印（★`dq3.migrate` が置く）"),
    Owned("work/.migration-decision.json", KIND_DERIVED,
          "★引き継ぎをどうしたかの覚え（⚠ derived = 新しい版では改めて聞く）"),
)

# ----------------------------------------------------------------------
# ★★ dev — ⚠ 開発 repo と検査だけ（★配布物にも引き継ぎにも出てこない）★★
#
#   ⚠⚠ **ここを「分からないものの捨て場」にしないこと。**
#     ★足すのは「配布 Runtime では**作られない**」と言い切れるものだけです。
#     ⚠ 迷ったら `derived` にしてください（★引き継がないので害が小さい）。
# ----------------------------------------------------------------------

DEV_ONLY: tuple[Owned, ...] = (
    # ★RX3-0495: 検査の材料・隔離先・証跡は work/tests/ の下
    #   fixtures/・savestates/・sandbox/・lua-sandbox/・evidence/・dq3-evidence/・art_test/
    Owned("work/tests", KIND_DEV, "★検査の材料・隔離先・実機確認の証跡"),
    # ★RX3-0494 / 0495: 調査の素材と道具（ffmpeg は research/tools/）
    Owned("work/research", KIND_DEV, "★調査の素材・道具の出力・開発機に落とした道具"),
    Owned("work/release", KIND_DEV, "★配布物を作る作業場（⚠ `build_runtime.py`）"),
    Owned("work/dq3-location-todo.csv", KIND_DEV,
          "★人が表へ貼る下書き（⚠ `scripts/dq3_location_todo.py`）"),
    Owned("work/art-*", KIND_DEV, "★記事用の切り出し（⚠ `scripts/dq3_shots.py`）"),
)

# ----------------------------------------------------------------------
# ★★ dq2 — ⚠⚠ DQ2 のもの（★DQ3 は触らない）★★
#
#   ⚠ 以前は `retroux.sqlite3*` / `events*.jsonl` を `derived`（作り直せる）に
#     入れていました（RX3-0506）。★DQ2 の DB は遊んだ地図・戦闘・図鑑・人のメモを持つ
#     **作り直せない**データです。⚠ DQ3 から見ても「消してよいもの」ではありません。
#   ★DQ3 の引き継ぎは写しません（⚠ DQ2 は `migrate-dq2.cmd` が写す）。
# ----------------------------------------------------------------------

DQ2_OWNED: tuple[Owned, ...] = (
    Owned("work/retroux.sqlite3*", KIND_DQ2,
          "⚠⚠ DQ2 の記録 DB（遊んだ地図・戦闘・図鑑・人のメモ / 作り直せない）"),
    Owned("work/events.jsonl", KIND_DQ2,
          "⚠ DQ2 の出来事の記録（★取り込み前のぶんは DB と組）"),
    Owned("work/events-*.jsonl", KIND_DQ2, "⚠ DQ2 の出来事の記録（世代）"),
    Owned("work/encountered.txt", KIND_DQ2,
          "⚠ DQ2 の会った敵の控え（★DB と組）"),
    Owned("work/caution.txt", KIND_DQ2, "⚠ DQ2 の警戒の控え（★DB と組）"),
)

ALL_ENTRIES: tuple[Owned, ...] = USER_DATA + DERIVED + DEV_ONLY + DQ2_OWNED

#: ⚠⚠ DQ3 と DQ2 が**同じフォルダを共用**している置き場（★中身を名前で分ける / RX3-0507）
#:   work/savestate-backup/  DQ2_J.* と DQ3_J.* の控えが同居する
#:   work/rom/               DQ2_J.nes と DQ3_J.nes が同居しうる
#:   work/playdata-archive/  DQ2 は <日時> 、DQ3 は dq3-<日時> と seen-*.json
SHARED_WITH_DQ2 = ("work/savestate-backup", "work/rom", "work/playdata-archive")

#: ★DQ2 のものと分かる名前の頭（⚠ `retroux/core/dq2_ownership.py` の DQ3 側と対）
DQ2_NAME_PREFIXES = ("dq2_", "dq2-")

#: ★DQ2 の playdata-archive の名前（`retroux/tools/playdata.py` の `_stamp()` = `yyyymmdd-HHMM[-label][-n]`）
#:   ⚠ DQ3 は `dq3-<日時>` なので**重ならない**。★迷うもの（名前が読めない）は DQ3 側 = **写す**
#:   （⚠ 「分からないものを落とす」より「余分に写す」ほうが害が小さい）
DQ2_ARCHIVE_RE = re.compile(r"^\d{8}-\d{4}(?:-.*)?$")

# ----------------------------------------------------------------------
# ★★ user override（案 A）— ⚠ shipped で配るのに、人が書き換えるもの ★★
#
#   ★読む順:  <write_root>/work/user-data/<同じ相対パス>    ★あればこちら
#             <program_root>/<元の場所>                      ★無ければ見本
#
#   ⚠⚠ **初回に自動で写しません**（依頼者 2026-09-30 の判断 / 案 A）。
#     ★触っていない人には、⚠ 新しい版の見本の更新が**そのまま届きます**。
# ----------------------------------------------------------------------

USER_OVERRIDE: tuple[Override, ...] = (
    Override("config/dq3_phase0.yaml",
             "⚠⚠ キー割り当て（★GUI が無く、ここを直接書き換える案内が入っている）",
             label="キー割り当て・自動化の既定"),
    Override("data/dq3/hero-memo.yaml",
             "★勇者メモの原本（⚠ 人が書き足す）",
             label="勇者メモの原本"),
    Override("data/dq3/location-names.csv",
             "★地名の表（⚠ 3 列を人が書く）",
             label="地名の表"),
)

#: ★override の「写した時点の見本」を覚えておくところ（⚠ user-data の中 = 一緒に引き継がれる）
BASELINE_NAME = ".shipped-baseline.json"

#: ⚠⚠ 引き継ぎが途中で終わった印（★次の起動で気づけるように）
INCOMPLETE_NAME = ".migration-incomplete"


# ----------------------------------------------------------------------
# ★分類する
# ----------------------------------------------------------------------

def _norm(rel) -> str:
    """★posix の相対パスに揃える（⚠ 先頭の `./` と末尾の `/` を落とす）。"""
    got = str(rel).replace("\\", "/").strip("/")
    return got[2:] if got.startswith("./") else got


def _matches(rel: str, pattern: str) -> bool:
    """★`pattern` 自身か、⚠ その**下**に入っているか。

    ```text
    work/dq3-knowledge         ← work/dq3-knowledge         ★一致
    work/dq3-knowledge/a.json  ← work/dq3-knowledge         ★一致（中身）
    work/dq3-knowledge2        ← work/dq3-knowledge         ⚠ 一致しない
    ```
    """
    rel = _norm(rel)
    pattern = _norm(pattern)
    if fnmatch.fnmatchcase(rel, pattern):
        return True
    return fnmatch.fnmatchcase(rel, pattern + "/*")


def entry_for(rel) -> Owned | None:
    """★その相対パスの持ち主（⚠ どれにも当たらなければ None）。"""
    for entry in ALL_ENTRIES:
        if _matches(rel, entry.rel):
            return entry
    return None


def is_dq2_owned(rel) -> bool:
    """⚠⚠ DQ2 のものか（★DQ3 の引き継ぎは**写さない** / RX3-0506・0507）。

    ```text
    work/retroux.sqlite3                 ★DQ2 の DB（`DQ2_OWNED`）
    work/savestate-backup/DQ2_J.fc0/...  ★共用の置き場の中で DQ2 の名前
    work/rom/DQ2_J.nes                   ★同上
    work/playdata-archive/20261003-1200  ★DQ2 の退避（日時だけの名前）
    work/savestate-backup/DQ3_J.fc1...   ⚠ DQ3 のもの（False）
    ```

    ⚠ 判定できないものは **False（= DQ3 のもの扱い）** です。
      ★誤って DQ3 のデータを落とすより、DQ2 のものを余分に写すほうが害が小さい。
    """
    got = _norm(rel)
    if classify(got) == KIND_DQ2:
        return True
    for container in SHARED_WITH_DQ2:
        if got == container or not got.startswith(container + "/"):
            continue
        child = got[len(container) + 1:].split("/", 1)[0]
        if container == "work/playdata-archive":
            return bool(DQ2_ARCHIVE_RE.match(child))
        return child.casefold().startswith(DQ2_NAME_PREFIXES)
    return False


def classify(rel) -> str | None:
    """★`"user"` / `"derived"` / `"dev"`、⚠ どれにも入っていなければ `None`。"""
    got = entry_for(rel)
    return got.kind if got is not None else None


def entries_of(kind: str) -> tuple[Owned, ...]:
    """★その分類の一覧。"""
    return tuple(e for e in ALL_ENTRIES if e.kind == kind)


def labels_of(kind: str) -> tuple[str, ...]:
    """★利用者に見せる言葉だけ（⚠ `label` の無いものは出さない）。"""
    return tuple(e.label for e in entries_of(kind) if e.label)


# ----------------------------------------------------------------------
# ★実体を数える（⚠ 在るものだけ）
# ----------------------------------------------------------------------

def _root(root=None) -> pathlib.Path:
    return pathlib.Path(root) if root is not None else P3.write_root()


def paths_of(kind: str, root=None) -> list[pathlib.Path]:
    """★その root に**実際にある**もの（⚠ 無いものは返さない）。

    ⚠ `rel` に `*` が入っていれば glob で広げます
      （★`work/retroux.log*` が `retroux.log.1` まで拾う）。
    """
    base = _root(root)
    out: list[pathlib.Path] = []
    for entry in entries_of(kind):
        if "*" in entry.rel:
            out += sorted(base.glob(entry.rel))
        else:
            got = base / entry.rel
            if got.exists():
                out.append(got)
    return out


def user_data_paths(root=None) -> list[pathlib.Path]:
    """★引き継ぐ実体（⚠ `MIGRATED_KINDS` のものだけ）。"""
    out: list[pathlib.Path] = []
    for kind in MIGRATED_KINDS:
        out += paths_of(kind, root)
    return out


def derived_paths(root=None) -> list[pathlib.Path]:
    """★作り直せる実体（⚠ 引き継がない）。"""
    return paths_of(KIND_DERIVED, root)


def user_evidence_paths(root=None) -> list[pathlib.Path]:
    """★「もう遊んだ / 使った」と言える user data だけ（⚠ `evidence_of_use`）。

    ⚠⚠ `work/rom/` と `work/dq3-window-state.json` は**入りません**。
      ★どちらも、まっさらな新版でも普通に在ります（上の `Owned` の註）。
    """
    base = _root(root)
    out: list[pathlib.Path] = []
    for entry in entries_of(KIND_USER):
        if not entry.evidence_of_use:
            continue
        if "*" in entry.rel:
            out += sorted(base.glob(entry.rel))
            continue
        got = base / entry.rel
        if got.is_file():
            out.append(got)
        elif got.is_dir() and any(got.iterdir()):
            out.append(got)                             # ⚠ 空のフォルダは証拠にしない
    return out


def tree_size(target) -> tuple[int, int]:
    """(ファイル数, バイト数)。⚠ ファイル 1 つなら (1, 大きさ)。"""
    target = pathlib.Path(target)
    if target.is_file():
        return 1, target.stat().st_size
    count = 0
    total = 0
    for p in target.rglob("*"):
        if p.is_file():
            count += 1
            total += p.stat().st_size
    return count, total


# ----------------------------------------------------------------------
# ★★ ⚠⚠ 足し忘れの歯止め ★★
# ----------------------------------------------------------------------

def unclassified(root=None) -> list[str]:
    """⚠⚠ `work/` の中で、★どの分類にも入っていない**最上位**の名前。

    ★見るのは `work/` の直下と `user_config.yaml` だけです。
    ⚠ 分類はすべて最上位の名前で決まるので、**下まで潜る必要がありません**。

    ⚠⚠ 空でなければ、★引き継ぎの一覧に**足し忘れた**か、
      ⚠ 開発機の置き土産です（→ `DEV_ONLY` か `DERIVED` へ足す）。
    """
    base = _root(root)
    out: list[str] = []
    work = base / "work"
    if work.is_dir():
        for child in sorted(work.iterdir()):
            rel = "work/" + child.name
            if classify(rel) is None:
                out.append(rel)
    return out


#: ★製品コードが `work/` の下へ書くときに通る呼び方（⚠ リテラルの第 1 区画を採る）
_WRITE_CALL_RE = re.compile(
    r"""(?:lazy_work|\bwork)\(\s*(['"])([^'"]+)\1"""
)

#: ⚠ 古い書き方（★`ROOT / "work" / "…"`）。⚠⚠ 残っていたら採る
_WRITE_SLASH_RE = re.compile(
    r"""["']work["']\s*/\s*(['"])([^'"]+)\1"""
)

#: ★★ 採取の対象 = ⚠ **配布 Runtime の中で動くもの**だけ ★★
#
#   ⚠⚠ `scripts/*.py` は**入れません**。★配布 manifest が入れているのは
#     `scripts/start-dq3.ps1` と `launcher-common.ps1` の 2 本だけで、
#     ⚠ `.py` の道具は 1 つも配られません（★利用者の `work/` を作りようがない）。
#   ★歯止めを「開発の道具にも」広げると、⚠ 新しい調査スクリプトを足すたびに
#     `DEV_ONLY` へ 1 行足す作業になり、⚠⚠ **考えずに足す場所**になります
#     （★それは分類の意味を殺します）。
#   ⚠ 実測（2026-10-01）: 分類漏れ 12 件は**すべて `scripts/`** でした
#     （`dq3/**` と `savestate_backup.py` は 0 件）。
CODE_SCAN_GLOBS = ("dq3/**/*.py", "retroux/tools/savestate_backup.py")

#: ⚠ 採取しないもの（★この module 自身と、引き継ぎの道具）
CODE_SCAN_SKIP = ("dq3/ownership.py", "dq3/migrate.py")


def code_write_segments(root=None) -> dict[str, list[str]]:
    """★製品コードが `work/` の下へ書いている**第 1 区画**を集める。

    戻り値は `{区画名: [見つけた場所, ...]}`。

    ⚠⚠ これが分類の一覧と食い違ったら、★**検査が赤くなります**
      （`tests/test_dq3_ownership.py`）。⚠ 新しい機能が `work/なにか` へ
      書き始めたら、**引き継ぐのか捨てるのかを決めてから**進めます。

    ⚠ 組み立てた名前（`work("art-" + fixture)`）は採れません。
      ★そのぶんは `unclassified()` が実体で見ます（**2 つで挟みます**）。
    """
    base = pathlib.Path(root) if root is not None else P3.ROOT
    found: dict[str, list[str]] = {}
    for pattern in CODE_SCAN_GLOBS:
        for path in sorted(base.glob(pattern)):
            rel = _norm(path.relative_to(base))
            if rel in CODE_SCAN_SKIP:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):       # pragma: no cover
                continue
            for i, line in enumerate(text.splitlines(), 1):
                for rx in (_WRITE_CALL_RE, _WRITE_SLASH_RE):
                    for hit in rx.finditer(line):
                        seg = hit.group(2)
                        if "/" in seg or "\\" in seg:
                            continue                    # ⚠ 第 1 区画だけを見る
                        found.setdefault(seg, []).append("%s:%d" % (rel, i))
    return found


# ----------------------------------------------------------------------
# ★★ user override（案 A）★★
# ----------------------------------------------------------------------

def override_dir(root=None) -> pathlib.Path:
    """★user 側の置き場（`<write_root>/work/user-data`）。"""
    base = pathlib.Path(root) / "work" if root is not None else P3.work()
    return base / "user-data"


def override_path(rel, root=None) -> pathlib.Path:
    """★その shipped ファイルに対応する **user 側の道**（⚠ 在るとは限らない）。"""
    return override_dir(root) / _norm(rel)


def is_override_target(rel) -> bool:
    """★`USER_OVERRIDE` に入っているか。"""
    got = _norm(rel)
    return any(_norm(o.rel) == got for o in USER_OVERRIDE)


def shipped_path(rel) -> pathlib.Path:
    """★見本（program 側）の道。"""
    return P3.program_root() / _norm(rel)


def resolve(rel, root=None) -> pathlib.Path:
    """★**案 A** — user 側にファイルが在ればそれ、⚠ 無ければ見本。

    ⚠⚠ 初回起動時に**自動で写しません**（依頼者 2026-09-30）。
      ★触っていない人には、新しい版の見本がそのまま届きます。

    ```text
    <write_root>/work/user-data/config/dq3_phase0.yaml   ★在ればこちら
    <program_root>/config/dq3_phase0.yaml                ★無ければ見本
    ```
    """
    user = override_path(rel, root)
    if user.is_file():
        return user
    return shipped_path(rel)


def lazy_resolve(rel) -> P3.LazyResolved:
    """★module の定数にする `resolve()`（⚠ 使う瞬間に引き直す / RX3-0215）。"""
    return P3.LazyResolved(resolve, rel)


def active_overrides(root=None) -> list[str]:
    """★いま user 側が使われている `USER_OVERRIDE` の相対パス。"""
    return [_norm(o.rel) for o in USER_OVERRIDE
            if override_path(o.rel, root).is_file()]


# ----------------------------------------------------------------------
# ★★ 見本が新しくなったことを**知らせるだけ**（⚠ 自動 merge はしない）★★
#
#   ⚠⚠ 依頼者 2026-09-30:「自動 merge / 自動上書きはしない。
#     ★『カスタマイズ版を使用しています。標準版が更新されています』相当を知らせる」
#
#   ★見分け方: user 側を**初めて見たとき**の見本の SHA-256 を覚えておき、
#     ⚠ 見本が変わったら知らせます。
#     → ★覚えは `work/user-data/.shipped-baseline.json` に置きます。
#       ⚠ user-data の中なので**引き継ぎで一緒に移り**、
#         ★新しい版では見本が変わっている＝**引き継いだ直後に知らせが出ます**（狙いどおり）。
# ----------------------------------------------------------------------

def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def baseline_path(root=None) -> pathlib.Path:
    return override_dir(root) / BASELINE_NAME


def read_baseline(root=None) -> dict:
    """★覚えている見本の hash（⚠ 読めなければ空 / 落とさない）。"""
    try:
        got = json.loads(baseline_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def write_baseline(data: dict, root=None) -> pathlib.Path:
    """★覚えを書く（⚠ 改行を反転させない / `newline=""`）。"""
    out = baseline_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(body + "\n")
    return out


def master_update_notices(root=None) -> list[str]:
    """⚠⚠ 「カスタマイズ版を使っていて、★見本が更新されている」ものの知らせ。

    ★戻すのは**言葉だけ**です（⚠ 何も merge しません / 何も上書きしません）。
    ⚠ 覚えの無いものは**その場で覚えて、知らせません**
      （★「いつから使っているか」が分からないものを騒がない）。
    """
    baseline = read_baseline(root)
    notices: list[str] = []
    changed = False
    for spec in USER_OVERRIDE:
        rel = _norm(spec.rel)
        if not override_path(rel, root).is_file():
            continue                                    # ★見本を使っている
        master = shipped_path(rel)
        if not master.is_file():
            continue                                    # ⚠ 見本が無い版（★騒がない）
        now = _sha256(master)
        was = (baseline.get(rel) or {}).get("shipped_sha256")
        if was is None:
            baseline[rel] = {"shipped_sha256": now}
            changed = True
            continue                                    # ★初めて見た（知らせない）
        if was != now:
            notices.append(
                "★カスタマイズ版を使用しています（%s）。"
                "⚠ 標準版が更新されています（★取り込みは手作業です）。" % rel)
    if changed:
        try:
            write_baseline(baseline, root)
        except OSError:                                 # pragma: no cover
            pass                                        # ⚠ 書けなくても起動は止めない
    return notices


def main(argv=None) -> int:
    """★所有境界を人が見るための口（⚠ 何も書きません）。

    ```text
    python -m dq3.ownership --list                ★一覧を出す
    python -m dq3.ownership --audit <root>        ⚠⚠ 分類外の実体を探す（★配布木に当てる）
    ```

    ⚠ `--audit` は**配布 Runtime の木**に当ててください。
      ★開発 repo の `work/` には調査の置き土産が大量にあり（2026-10-01 実測で 163 件）、
      ⚠⚠ そこで赤にすると「分からないものを `DEV_ONLY` に放り込む」圧力になります。
    """
    import argparse

    ap = argparse.ArgumentParser(description="所有境界（shipped / user / derived）")
    ap.add_argument("--list", action="store_true", help="★一覧を出す")
    ap.add_argument("--audit", default=None,
                    help="⚠ その木の work/ に分類外のものが無いか見る")
    args = ap.parse_args(argv)

    if args.list:
        for kind, title in ((KIND_USER, "★user（引き継ぐ / ⚠ 配布物に入れない）"),
                            (KIND_DQ2, "⚠⚠ dq2（DQ2 のもの / DQ3 は触らない・写さない）"),
                            (KIND_DERIVED, "★derived（引き継がない / 作り直せる）"),
                            (KIND_DEV, "⚠ dev（配布も引き継ぎもしない）")):
            print(title)
            for entry in entries_of(kind):
                print("  %-34s %s" % (entry.rel, entry.why))
        print("★user override（案 A / ⚠ user 側にあればそちらを読む）")
        for spec in USER_OVERRIDE:
            print("  %-34s %s" % (spec.rel, spec.why))
    if args.audit:
        got = unclassified(args.audit)
        if not got:
            print("★分類外はありません: %s" % args.audit)
            return 0
        print("⚠⚠ どの分類にも入っていないものが %d 件あります" % len(got))
        for rel in got:
            print("  " + rel)
        print("★`dq3/ownership.py` で引き継ぐのか捨てるのかを決めてください。")
        return 1
    if not args.list:
        ap.error("--list か --audit のどちらかを指定してください")
    return 0


__all__ = [
    "KIND_USER", "KIND_DERIVED", "KIND_DEV", "KIND_DQ2", "MIGRATED_KINDS",
    "Owned", "Override",
    "USER_DATA", "DERIVED", "DEV_ONLY", "DQ2_OWNED", "ALL_ENTRIES", "USER_OVERRIDE",
    "SHARED_WITH_DQ2", "is_dq2_owned",
    "BASELINE_NAME", "INCOMPLETE_NAME",
    "entry_for", "classify", "entries_of", "labels_of",
    "paths_of", "user_data_paths", "derived_paths", "user_evidence_paths",
    "tree_size",
    "unclassified", "code_write_segments",
    "override_dir", "override_path", "is_override_target", "shipped_path",
    "resolve", "lazy_resolve", "active_overrides",
    "baseline_path", "read_baseline", "write_baseline",
    "master_update_notices", "main",
]


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
