r"""版を上げるときに、★**利用者のデータだけ**を新しいフォルダへ写す（RX3-0472 / 2026-10-01）。

```text
RetroUX-DQ3-1.1.0\   ← 旧版（⚠⚠ **1 バイトも触りません**）
RetroUX-DQ3-1.2.0\   ← 新しい ZIP を**空のフォルダ**へ展開したもの
                       ★ここへ user data を写す（⚠ derived は写さない）
```

## ⚠⚠ なぜ「新しいフォルダ」なのか（★方式 B / 依頼者 2026-10-01）

⚠ ZIP の上書き展開は「**消えたファイルを消しません**」。v1.1 にあった
`dq3/knowledge/old_thing.py` が v1.2 で消えても、★上書きしたフォルダには
残り、⚠ import されれば動きます。⚠⚠ これは「ゴミが残る」ではなく
**どの版が動いているか分からなくなる**話です。

→ ★新しいフォルダへ展開すれば、⚠ 製品が「利用者のフォルダからファイルを消す」
  役を負わずに、⚠⚠ 旧ファイルの残留が**構造的に起きません**。

## ★この道具の 3 つの約束

```text
① copy only     ⚠⚠ 旧版を**削除・移動・書き換えしません**
② 上書きしない   ⚠ 新版側に同じものが在れば**飛ばして報告**します
③ 途中で止まっても分かる
                ★写す前に印（`work/.migration-incomplete`）を置き、
                ⚠ 1 件ごとに記録へ書き、★終わったら印を消します
```

⚠ 写すものの一覧は**持っていません**。★`dq3/ownership.py` の `USER_DATA`
だけを見ます（⚠⚠ ここに写すと、片方だけ古くなります）。

## 使い方

```bash
# ★何が写るかだけ見る（⚠ 1 バイトも書きません）
python -m dq3.migrate --from "C:/Games/RetroUX-DQ3-1.1.0" --dry-run

# ★実際に写す（⚠ 移行先は既定でいま動いているフォルダ）
python -m dq3.migrate --from "C:/Games/RetroUX-DQ3-1.1.0"
```
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import shutil

from dq3 import ownership as OWN
from dq3 import paths as P3

#: ★「RetroUX DQ3 のフォルダらしい」と言える目印（⚠ 1 つでも欠けたら名指しで言う）
ROOT_MARKERS: tuple[tuple[str, str], ...] = (
    ("dq3/paths.py", "★製品コード"),
    ("DQ3.cmd", "★起動の入口"),
    ("build-info.json", "★版と断面"),
)

#: ★記録の置き場（⚠ derived / `work/dq3-log/` は既に分類済み）
JOURNAL_REL = ("dq3-log", "migration.log")

#: ★★ 引き継ぎを「どうしたか」の覚え（⚠ derived / 引き継がない）★★
#
#   ⚠⚠ これが無いと、★断った人に**毎回**誘いを出すことになります。
#   ⚠ derived なので、新しい版へは引き継がれません（★新しい版では改めて聞きます）。
DECISION_NAME = ".migration-decision.json"

#: ★覚えに入る種類
DONE_MIGRATED = "migrated"
DONE_DECLINED = "declined"

#: ★★ 結果の判定（⚠⚠ 一部でも飛ばしたら「完了」と言わない）★★
OUT_OK = "完了"
OUT_PARTIAL = "一部完了"
OUT_FAILED = "失敗"

# ----------------------------------------------------------------------
# ★★ ⚠⚠ launcher へ返す終了コードの契約（RX3-0481 / 2026-10-02）★★
# ----------------------------------------------------------------------
#
# ⚠⚠ **なぜ要るか。** `start-dq3.ps1` は設定チェックより**先に**引き継ぎの誘いを
#   出すようになりました（★依頼者 2026-10-02 の案 A）。⚠ そこで
#   「どうなったか」を launcher が知らないと、
#   ★失敗したのに FCEUX と画面を起こしてしまいます。
#
# ★契約は**この 1 か所だけ**です（⚠ `.ps1` に数字の意味を書き写しません）。
#   `tests/test_dq3_migrate_launcher.py` が `.ps1` と突き合わせて固定します。
#
# ```text
#  0  ★誘う必要がない（もう決めている / 遊んだ証拠がある）→ そのまま続行
# 10  ★引き継ぎ完了                        → 設定を読み直して続行
# 11  ★引き継がず開始                      → そのまま続行（⚠ 雛形の案内へ進む）
# 12  ⚠ × / 取り消し                       → 今回の起動は終了（★次回も聞く）
# 13  ⚠ 一部完了                           → 結果を見せて終了
# 14  ⚠ 失敗                               → 結果を見せて終了
# ★それ以外（1 / 2 / …）                    → ⚠⚠ 引き継ぎ画面の起動エラー。**黙って続行しない**
# ```
#
# ⚠ 0 と 10 と 11 を分けるのは、★「設定を読み直す必要があるか」と
#   「次回も聞くか」が違うためです（⚠ 1 つにまとめると判断できません）。
EXIT_NOT_NEEDED = 0
EXIT_MIGRATED = 10
EXIT_DECLINED = 11
EXIT_CANCELLED = 12
EXIT_PARTIAL = 13
EXIT_FAILED = 14

#: ★「このまま起動を続けてよい」終了コード（⚠ これ以外は launcher が止まります）
EXIT_CONTINUE = (EXIT_NOT_NEEDED, EXIT_MIGRATED, EXIT_DECLINED)

#: ★結果（`Result.outcome`）→ 終了コード
EXIT_BY_OUTCOME = {OUT_OK: EXIT_MIGRATED,
                   OUT_PARTIAL: EXIT_PARTIAL,
                   OUT_FAILED: EXIT_FAILED}


@dataclasses.dataclass(frozen=True)
class Item:
    """★写す単位 1 つ（⚠ `rel` は root からの相対）。"""

    rel: str
    label: str
    files: int
    size: int


@dataclasses.dataclass(frozen=True)
class Source:
    """★移行元を見た結果（⚠ `ok` が False なら写しません）。"""

    root: pathlib.Path
    ok: bool
    problems: tuple[str, ...]
    product: str = ""
    version: str = ""
    commit: str = ""
    items: tuple[Item, ...] = ()

    @property
    def files(self) -> int:
        return sum(i.files for i in self.items)

    @property
    def size(self) -> int:
        return sum(i.size for i in self.items)

    def describe(self) -> str:
        """★利用者に見せる 1 行（例 `RetroUX DQ3 1.1.0`）。"""
        if not self.version:
            return "⚠ 版が分かりません"
        return ("%s %s" % (self.product or "RetroUX DQ3", self.version)).strip()


@dataclasses.dataclass(frozen=True)
class Result:
    """★写した結果。

    ⚠⚠ `ok` だけを見ないでください。★`outcome` が
      `完了` / `一部完了` / `失敗` を分けます（依頼者 2026-10-01 §3）。
    """

    ok: bool
    copied: int
    size: int
    skipped: tuple[str, ...]
    failed: tuple[str, ...]
    journal: pathlib.Path | None
    dry_run: bool = False

    @property
    def outcome(self) -> str:
        """★`完了` / `一部完了` / `失敗`。

        ⚠⚠ **飛ばしたものが 1 つでもあれば「完了」と言いません。**
          ★飛ばした＝新版に同じものが在って、引き継げなかったということです。
        """
        if self.failed:
            return OUT_FAILED
        return OUT_PARTIAL if self.skipped else OUT_OK

    def next_step(self) -> str:
        """★利用者が次に取る操作（⚠ 結果ごとに 1 つだけ言う）。"""
        if self.failed:
            return ("★もう一度同じコマンドを実行してください"
                    "（⚠ 写せたぶんは飛ばします / ⚠⚠ 旧版はそのまま残っています）")
        if self.skipped:
            return ("⚠ 引き継げなかったものは、新版に**同じものが既にあった**ためです"
                    "（★上書きしていません）。⚠⚠ 旧版のほうを使いたいときは、"
                    "★新しいフォルダへもう一度展開して、最初に引き継いでください")
        return "★このまま遊べます（⚠ 旧版のフォルダは確認がすむまで残しておいてください）"


# ----------------------------------------------------------------------
# ★移行元を見る（⚠ 書く前に全部見る）
# ----------------------------------------------------------------------

def _resolved(path) -> pathlib.Path:
    return pathlib.Path(path).expanduser().resolve()


def _is_inside(inner: pathlib.Path, outer: pathlib.Path) -> bool:
    return inner == outer or outer in inner.parents


def _build_info(root: pathlib.Path) -> dict:
    try:
        got = json.loads((root / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def probe(src, dst=None) -> Source:
    """★移行元を確かめる。⚠ 足りないものは**名指しで**返します。

    ⚠⚠ 「らしくない」で終わらせません。★何が無いから駄目なのかを出します
      （依頼者 2026-10-01「何が不足しているか利用者に分かる形で表示」）。
    """
    problems: list[str] = []
    src_root = _resolved(src)
    dst_root = _resolved(dst) if dst is not None else _resolved(P3.write_root())

    if not src_root.exists():
        return Source(src_root, False,
                      ("⚠ そのフォルダがありません: %s" % src_root,))
    if not src_root.is_dir():
        return Source(src_root, False,
                      ("⚠ フォルダではありません: %s" % src_root,))

    # ⚠⚠ いま動いているフォルダ自身を移行元にしない（★自分から自分へ写す）
    if src_root == dst_root:
        problems.append("⚠⚠ 移行元が、いま動いているフォルダ自身です"
                        "（★新しく展開したフォルダから実行してください）")
    elif _is_inside(dst_root, src_root):
        problems.append("⚠⚠ 移行先が移行元の中にあります（★別のフォルダへ展開してください）")
    elif _is_inside(src_root, dst_root):
        problems.append("⚠⚠ 移行元が移行先の中にあります（★別のフォルダを指してください）")

    missing = [("%s（%s）" % (rel, why)) for rel, why in ROOT_MARKERS
               if not (src_root / rel).exists()]
    if missing:
        problems.append("⚠ RetroUX DQ3 のフォルダに見えません。"
                        "★見つからなかったもの: " + " / ".join(missing))

    info = _build_info(src_root)
    if not info.get("version"):
        problems.append("⚠ `build-info.json` から版を読めませんでした"
                        "（★引き継ぎ自体は版が分からなくても行えます）")

    items = tuple(plan(src_root))
    if not items:
        problems.append("⚠ 引き継ぐデータが 1 つもありません"
                        "（★このフォルダではまだ遊んでいないようです）")

    # ★致命的なのは「同じフォルダ」「入れ子」「目印が無い」「中身が無い」
    fatal = [p for p in problems if p.startswith("⚠⚠") or "見えません" in p
             or "1 つもありません" in p]
    return Source(src_root, not fatal, tuple(problems),
                  product=str(info.get("product") or ""),
                  version=str(info.get("version") or ""),
                  commit=str(info.get("source_commit") or ""),
                  items=items)


#: ★`user_config.yaml` の `paths:` のうち、⚠ 利用者が**外**を指しうる欄
#
#   ⚠⚠ ここだけを見ます。★`db` / `log` / `state` などは既定が相対で、
#     `program_root` 基準に解決されるので版をまたいでも崩れません（2026-10-01 実測）。
OUTSIDE_KEYS = ("dq3_rom", "fceux", "rom")


def stale_references(src, dst=None) -> list[tuple[str, str, str]]:
    """⚠⚠ 引き継いだ設定に **旧版フォルダの中**を指す絶対パスが残らないか。

    戻り値は `(欄の名前, 指している道, 言うこと)`。

    ## ⚠ なぜ要るか（2026-10-01 実測 / ケース D）

    ★`dq3/paths.py::_resolve()` は「人が指した場所はそのまま返す」ので、
    ⚠ `dq3_rom: <旧版>/work/rom/DQ3_J.nes` のような設定は、
    ⚠⚠ **旧版フォルダを消した瞬間に効かなくなります**（★終了コードは 0 のまま）。

    ⚠⚠ **黙って書き換えません**（依頼者 2026-10-01 §4）。
      ★引き継ぐ前に言って、⚠ 利用者に選び直してもらいます。
    """
    src_root = _resolved(src)
    dst_root = _resolved(dst) if dst is not None else _resolved(P3.write_root())
    cfg = src_root / P3.USER_CONFIG_NAME
    if not cfg.is_file():
        return []
    try:
        import yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:                                    # noqa: BLE001
        return []                                        # ⚠ 読めないことは別の層が言う
    got = (data.get("paths") or {}) if isinstance(data, dict) else {}
    out: list[tuple[str, str, str]] = []
    for key in OUTSIDE_KEYS:
        raw = str(got.get(key) or "").strip()
        if not raw:
            continue
        where = pathlib.Path(raw)
        if not where.is_absolute():
            continue                                     # ★相対は新版の root 基準（崩れない）
        try:
            inside = _is_inside(where.resolve(), src_root)
        except OSError:                                  # pragma: no cover
            continue
        if inside and not _is_inside(where.resolve(), dst_root):
            out.append((key, raw,
                        "⚠⚠ 旧版フォルダの中を指しています。"
                        "★旧版を消すと使えなくなるので、"
                        "⚠ 新版で場所を選び直してください"))
    return out


def conflicts(src, dst=None) -> list[tuple[str, str]]:
    """⚠⚠ **写す前に**「引き継げないもの」を出す（★(相対パス, わけ) の一覧）。

    ⚠ 依頼者 2026-10-01 §2:「★既存データを無断で上書き・混合しない。
      ⚠⚠ **引き継げないものと理由を実行前に知らせる**」。

    ★`run()` が飛ばすことになるものと**同じ判定**です
      （⚠ 画面に出す一覧を別に組み立てません）。
    """
    src_root = _resolved(src)
    dst_root = _resolved(dst) if dst is not None else _resolved(P3.write_root())
    out: list[tuple[str, str]] = []
    for item in plan(src_root):
        base = src_root / item.rel
        for _abs_src, rel_in in _files_under(base):
            target = (dst_root / item.rel / rel_in) if base.is_dir() \
                else (dst_root / item.rel)
            if target.exists():
                out.append((target.relative_to(dst_root).as_posix(),
                            "★新版に同じものが既にあります（⚠ 上書きしません）"))
    return out


# ----------------------------------------------------------------------
# ★★ ⚠ 誘いを出すか / 覚えておく ★★
# ----------------------------------------------------------------------

def decision_path(root=None) -> pathlib.Path:
    root = pathlib.Path(root) if root is not None else P3.write_root()
    return root / "work" / DECISION_NAME


def decision(root=None) -> dict | None:
    """★引き継ぎをどうしたかの覚え（⚠ まだ決めていなければ None）。"""
    try:
        got = json.loads(decision_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def record_decision(kind: str, *, source=None, root=None,
                    outcome: str = "") -> pathlib.Path:
    """★「引き継いだ」「引き継がなかった」を覚える（⚠ 書けなくても止めない）。"""
    out = decision_path(root)
    body = json.dumps({
        "kind": kind,
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": str(source) if source else "",
        "outcome": outcome,
    }, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as fh:
            fh.write(body + "\n")
    except OSError:                                      # pragma: no cover
        pass                                             # ⚠ 覚えられなくても進む
    return out


def should_offer(root=None) -> bool:
    """★初回起動で「旧版から引き継ぎますか」を**出すか**。

    ```text
    ★出す    まだ決めていない ＋ 遊んだ証拠が 1 件も無い
    ⚠ 出さない 一度決めた / もう遊んでいる（★勝手に混ぜない）
    ```

    ⚠⚠ 「遊んだ証拠」に `work/rom/` と `work/dq3-window-state.json` は**入りません**
      （★どちらもまっさらな新版でも在りうる / `ownership.user_evidence_paths()`）。
    ⚠ 出さなくなっても、★あとから呼べる道（画面のボタン / `python -m dq3.migrate`）は
      残ります（依頼者 2026-10-01 §1）。
    """
    if decision(root) is not None:
        return False
    return not OWN.user_evidence_paths(
        pathlib.Path(root) if root is not None else None)


def plan(src) -> list[Item]:
    """★写すもの（⚠ `ownership.USER_DATA` に在って、移行元に**実体がある**ものだけ）。"""
    src_root = pathlib.Path(src)
    out: list[Item] = []
    for got in OWN.user_data_paths(src_root):
        rel = got.relative_to(src_root).as_posix()
        entry = OWN.entry_for(rel)
        files, size = OWN.tree_size(got)
        out.append(Item(rel, (entry.label if entry else "") or rel, files, size))
    return out


# ----------------------------------------------------------------------
# ★写す（⚠⚠ copy only / 旧版は触らない）
# ----------------------------------------------------------------------

def _files_under(target: pathlib.Path):
    """★そのパスの下のファイルを (絶対, そこからの相対) で返す。"""
    if target.is_file():
        yield target, pathlib.PurePosixPath(target.name)
        return
    for p in sorted(target.rglob("*")):
        if p.is_file():
            yield p, pathlib.PurePosixPath(p.relative_to(target).as_posix())


def incomplete_marker(dst_root) -> pathlib.Path:
    return pathlib.Path(dst_root) / "work" / OWN.INCOMPLETE_NAME


def journal_path(dst_root) -> pathlib.Path:
    return pathlib.Path(dst_root).joinpath("work", *JOURNAL_REL)


def _write_marker(dst_root: pathlib.Path, src_root: pathlib.Path,
                  items) -> pathlib.Path:
    """⚠⚠ **写す前に**印を置く（★途中で止まっても「途中だ」と分かるように）。"""
    out = incomplete_marker(dst_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": str(src_root),
        "items": [i.rel for i in items],
    }, ensure_ascii=False, indent=2, sort_keys=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(body + "\n")
    return out


def pending(dst_root=None) -> dict | None:
    """⚠⚠ 前の引き継ぎが**途中で終わっていないか**（★終わっていれば None）。"""
    root = pathlib.Path(dst_root) if dst_root is not None else P3.write_root()
    got = incomplete_marker(root)
    if not got.is_file():
        return None
    try:
        data = json.loads(got.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": [], "source": "⚠ 読めませんでした"}
    return data if isinstance(data, dict) else {"items": []}


def run(src, dst=None, *, dry_run: bool = False,
        overwrite: bool = False) -> Result:
    """★user data を写す。⚠⚠ **移行元は 1 バイトも変えません**。

    ```text
    ★写す        移行元に在って、移行先に**無い**もの
    ⚠ 飛ばす     移行先に既に在るもの（★中身が違っても消しません）
    ⚠⚠ 触らない  移行元（削除・移動・書き換えを 1 つもしません）
    ```

    ⚠ `overwrite=True` は**用意だけ**してあります。★画面からは渡しません
      （⚠⚠ 「利用者のデータを上書きする」判断を製品が持たないため）。
    """
    src_root = _resolved(src)
    dst_root = _resolved(dst) if dst is not None else _resolved(P3.write_root())
    items = plan(src_root)

    copied = 0
    size = 0
    skipped: list[str] = []
    failed: list[str] = []

    if dry_run:
        return Result(True, sum(i.files for i in items),
                      sum(i.size for i in items), (), (), None, dry_run=True)

    marker = _write_marker(dst_root, src_root, items)
    journal = journal_path(dst_root)
    journal.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")

    # ⚠ 記録は **1 件ごとに flush** します（★途中で落ちても、どこまで写せたかが残る）
    with open(journal, "a", encoding="utf-8", newline="") as log:
        log.write("%s ★引き継ぎ開始 %s → %s（%d 項目）\n"
                  % (stamp, src_root, dst_root, len(items)))
        log.flush()
        for item in items:
            base = src_root / item.rel
            for abs_src, rel_in in _files_under(base):
                out = dst_root / item.rel
                out = out / rel_in if base.is_dir() else out
                try:
                    if out.exists() and not overwrite:
                        skipped.append(out.relative_to(dst_root).as_posix())
                        continue
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(abs_src, out)
                    copied += 1
                    size += out.stat().st_size
                except OSError as exc:
                    failed.append("%s: %s" % (item.rel, exc))
                    log.write("  ⚠ 失敗 %s: %s\n" % (abs_src, exc))
                    log.flush()
            log.write("  ★%s（写した %d 件 / 飛ばした %d 件）\n"
                      % (item.rel, copied, len(skipped)))
            log.flush()
        verdict = "★完了" if not failed else "⚠ 一部失敗"
        log.write("%s %s 写した %d 件 / %d bytes / 飛ばした %d 件 / 失敗 %d 件\n"
                  % (datetime.datetime.now().isoformat(timespec="seconds"),
                     verdict, copied, size, len(skipped), len(failed)))

    # ⚠⚠ 印を消すのは**最後**（★1 件でも失敗したら残します）
    if not failed:
        try:
            marker.unlink()
        except OSError:                                  # pragma: no cover
            pass
    got = Result(not failed, copied, size, tuple(skipped), tuple(failed),
                 journal)
    # ★「引き継いだ」ことを覚える（⚠ 失敗したときは覚えない = もう一度誘う）
    if not failed:
        record_decision(DONE_MIGRATED, source=src_root, root=dst_root,
                        outcome=got.outcome)
    return got


# ----------------------------------------------------------------------
# ★言葉にする（⚠ 画面と CLI が同じ文を使う）
# ----------------------------------------------------------------------

def summary(src: Source, blocked=(), stale=()) -> str:
    """★確認の画面に出す本文（⚠ CLI も画面も**これ 1 本**を出します）。

    `blocked` は `conflicts()`、`stale` は `stale_references()` の結果。
    ⚠⚠ どちらも渡すと「★引き継げないもの」「⚠ 選び直しが要るもの」を
    **実行する前に**本文へ出します（依頼者 2026-10-01 §2・§4）。
    """
    lines = []
    if src.ok:
        lines.append("%s が見つかりました。" % src.describe())
    else:
        lines.append("⚠ このフォルダからは引き継げません。")
    for why in src.problems:
        lines.append("  " + why)
    if src.items:
        lines.append("")
        lines.append("引き継ぐもの:")
        for item in src.items:
            lines.append("  ・%s（%d 件 / %s bytes）"
                         % (item.label, item.files, format(item.size, ",")))
        lines.append("")
        lines.append("引き継がないもの:")
        lines.append("  ・プログラム / Python Runtime（★新しい版のものを使います）")
        lines.append("  ・生成データ（★新しい版で作り直します）")
    blocked = list(blocked)
    if blocked:
        lines.append("")
        lines.append("⚠⚠ 引き継げないもの（★新版に同じものが既にあります / %d 件）:"
                     % len(blocked))
        for rel, _why in blocked[:10]:
            lines.append("  ・" + rel)
        if len(blocked) > 10:
            lines.append("  ・…ほか %d 件" % (len(blocked) - 10))
        lines.append("  ⚠ 上書きしません。★旧版のほうを使いたいときは、")
        lines.append("    新しいフォルダへもう一度展開して、**最初に**引き継いでください。")
    stale = list(stale)
    if stale:
        lines.append("")
        lines.append("⚠⚠ 引き継いだあとに**選び直しが要る**設定（%d 件）:" % len(stale))
        for key, raw, why in stale:
            lines.append("  ・%s: %s" % (key, raw))
            lines.append("    " + why)
        lines.append("  ★管理画面か `user_config.yaml` で場所を指し直してください")
        lines.append("    （⚠ RetroUX が勝手に書き換えることはしません）。")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="旧版の RetroUX DQ3 フォルダから利用者データだけを写す")
    ap.add_argument("--from", dest="src", required=True,
                    help="旧版の RetroUX DQ3 のルートフォルダ")
    ap.add_argument("--to", dest="dst", default=None,
                    help="★既定はいま動いているフォルダ")
    ap.add_argument("--dry-run", action="store_true",
                    help="★何が写るかだけ見る（⚠ 1 バイトも書かない）")
    args = ap.parse_args(argv)

    src = probe(args.src, args.dst)
    blocked = conflicts(args.src, args.dst) if src.ok else []
    stale = stale_references(args.src, args.dst) if src.ok else []
    print(summary(src, blocked, stale))
    if not src.ok:
        return 2
    if args.dry_run:
        print("\n★--dry-run のため、1 バイトも書いていません"
              "（%d 件 / %s bytes が対象）"
              % (src.files, format(src.size, ",")))
        return 0

    got = run(args.src, args.dst)
    # ⚠⚠ 「完了」と「一部完了」と「失敗」を**同じ顔で出さない**（依頼者 §3）
    print("\n== 引き継ぎ: %s ==" % got.outcome)
    print("コピーできた      : %d 件 / %s bytes"
          % (got.copied, format(got.size, ",")))
    print("引き継げなかった  : %d 件%s"
          % (len(got.skipped),
             "（★新版に同じものが既にあった / ⚠ 上書きしていません）"
             if got.skipped else ""))
    for rel in got.skipped[:10]:
        print("    ・" + rel)
    if len(got.skipped) > 10:
        print("    ・…ほか %d 件" % (len(got.skipped) - 10))
    print("失敗              : %d 件" % len(got.failed))
    for why in got.failed[:10]:
        print("    ・" + why)
    if stale:
        print("選び直しが要る設定: %d 件（★上の一覧 / ⚠ 書き換えていません）" % len(stale))
    print("次にすること      : %s" % got.next_step())
    print("詳しい記録        : %s" % got.journal)
    if got.failed:
        print("⚠⚠ 旧版のフォルダはそのまま残っています（★1 バイトも変えていません）")
        return 1
    return 0


__all__ = ["ROOT_MARKERS", "JOURNAL_REL", "DECISION_NAME",
           "DONE_MIGRATED", "DONE_DECLINED",
           "OUT_OK", "OUT_PARTIAL", "OUT_FAILED",
           "EXIT_NOT_NEEDED", "EXIT_MIGRATED", "EXIT_DECLINED",
           "EXIT_CANCELLED", "EXIT_PARTIAL", "EXIT_FAILED",
           "EXIT_CONTINUE", "EXIT_BY_OUTCOME",
           "Item", "Source", "Result",
           "OUTSIDE_KEYS",
           "probe", "plan", "run", "summary", "pending", "conflicts",
           "stale_references",
           "decision", "decision_path", "record_decision", "should_offer",
           "incomplete_marker", "journal_path", "main"]


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
