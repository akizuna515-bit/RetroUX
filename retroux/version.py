"""RetroUX のバージョン（2026-07-30 / リリース調整 仕様書 14章）。

★★ **一元管理する。** ★★
  タイトル・About・診断情報・ログの起動行が別々に持つと、
  問い合わせを受けたときに**どれが本当か分からなくなる**。

★出どころは `pyproject.toml` の1か所。
  ⚠ ここに数字を書き写さない（写すと必ずずれる）。
    パッケージとして入っていない環境（リポジトリを直接動かす）でも
    読めるように、`pyproject.toml` を直接読む道も用意してある。
"""

from __future__ import annotations

import json
import pathlib
import re

#: 読めなかったときに出す文字列。★**数字を偽らない**
UNKNOWN = "0.0.0+unknown"

#: ★配布物に焼く断面の記録（RX3-0464 / 2026-09-29）。
#
#   ⚠⚠ 配布 Runtime には `pyproject.toml` が**入りません**（開発の設定なので）。
#     ★そのままだと `get_version()` が `UNKNOWN` を返します。
#   ★だから export のときに `build-info.json` を作って同梱します。
#
#   ```json
#   {"product": "retroux-dq3", "version": "1.1.0",
#    "source_commit": "0123456789abcdef", "exported_at": "2026-09-29T.."}
#   ```
#
#   ⚠ 開発 repo では**作りません**（`.gitignore` 済み）。★正本は pyproject のまま。
BUILD_INFO_NAME = "build-info.json"

#: ★断面が分からないときの札（⚠ 数字を偽らないのと同じ考え）
UNKNOWN_BUILD = "dev"

_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _from_metadata() -> str | None:
    """インストール済みパッケージから読む（普通はこちら）。"""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("retroux")
    except Exception:                                  # noqa: BLE001
        # PackageNotFoundError 以外（importlib が無い等）もまとめて拾う
        return None


def _from_pyproject() -> str | None:
    """`pyproject.toml` から読む（リポジトリを直接動かしているとき）。

    ⚠ `tomllib` を使わず正規表現で読む理由: `[tool.*]` の中にも
      `version = "..."` が現れうるので、**先頭の1件**だけを採りたい。
      `[project]` を厳密に解釈するほどの利得が無い。
    """
    here = pathlib.Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        path = parent / "pyproject.toml"
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        found = _PATTERN.search(text)
        return found.group(1) if found else None
    return None


def _roots():
    """★`build-info.json` を探す場所（⚠ 近いほうから）。"""
    here = pathlib.Path(__file__).resolve()
    return (here.parent, *here.parents)


def build_info() -> dict:
    """★同梱された断面の記録（⚠ 無ければ空の dict / 例外は投げない）。

    ⚠ 壊れた JSON でも落ちません（★版が出ないより、起動するほうが害が小さい）。
    """
    for parent in _roots():
        path = parent / BUILD_INFO_NAME
        if not path.is_file():
            continue
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}
    return {}


def _from_build_info() -> str | None:
    """★`build-info.json` から読む（⚠ 配布 Runtime の受け皿）。"""
    got = build_info().get("version")
    return str(got) if got else None


def _commit_from_git() -> str | None:
    """★`.git` から HEAD の commit を読む（⚠ `git` を起こさない）。

    ⚠⚠ `subprocess` で `git rev-parse` を呼ぶと、★起動が遅くなり、
      `git` が無い環境で余計な失敗が出ます。→ ★ファイルを直接読みます。
    ★worktree（`.git` がファイル）も読みます（2026-10-03 / RX3-0500）。
      ⚠ 以前は `None` で、worktree から作った配布 ZIP の断面が空になりました。
    """
    for parent in _roots():
        dirs = _git_dirs(parent)
        if dirs is None:
            continue
        own, common = dirs
        try:
            head = (own / "HEAD").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not head.startswith("ref: "):
            return head or None                 # ★detached HEAD は生の hash
        return _read_ref(head[5:].strip(), own, common)
    return None


def _git_dirs(parent: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path] | None:
    """★（HEAD のある場所, 共有の refs のある場所）。⚠ 見つからなければ `None`。

    ```text
    通常の repo   .git/ がフォルダ            → (.git, .git)
    worktree      .git が `gitdir: <場所>`    → (<場所>, <場所>/commondir の先)
    ```
    """
    git = parent / ".git"
    if git.is_dir():
        return git, git
    if not git.is_file():
        return None
    try:
        line = git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not line.startswith("gitdir: "):
        return None
    own = pathlib.Path(line[len("gitdir: "):].strip())
    if not own.is_absolute():
        own = parent / own
    try:
        common = own / (own / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        common = own
    return own, common


def _read_ref(ref: str, own: pathlib.Path, common: pathlib.Path) -> str | None:
    """★ref の commit（★worktree 固有 → 共有 → packed-refs の順）。"""
    for base in (own, common):
        try:
            got = (base / ref).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if got:
            return got
    try:
        packed = (common / "packed-refs").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in packed.splitlines():
        sha, _, name = line.partition(" ")
        if name.strip() == ref and not line.startswith(("#", "^")):
            return sha or None
    return None


def source_commit() -> str | None:
    """★この断面の commit（⚠ 分からなければ `None`）。

    ```text
    1 build-info.json の source_commit   ★配布 Runtime（Git が無くても分かる）
    2 .git/HEAD から辿る                 ★開発 repo
    3 None
    ```
    """
    got = build_info().get("source_commit")
    if got:
        return str(got)
    return _commit_from_git()


def build_id(length: int = 7) -> str:
    """★ログや画面に出す短い断面（⚠ 分からなければ `dev`）。"""
    got = source_commit()
    return got[:length] if got else UNKNOWN_BUILD


def get_version() -> str:
    """バージョン文字列。読めなければ `UNKNOWN`。

    ★★ pyproject.toml を**先に**読む（RX-0087 / 2026-08-20）★★
      以前はメタデータ優先だったが、この使い方（リポジトリを clone して
      editable で動かす）では **`git pull` してもメタデータは古いまま**で、
      画面に前のバージョンが出続けた（実例: pyproject 1.0.1 なのに表示 1.0.0）。
      ⚠ 出どころは pyproject の1か所、が本方針。メタデータは
      pyproject が見つからない環境（wheel 配布など）の受け皿にする。

    ★★ `build-info.json` は pyproject の**後**（RX3-0464 / 2026-09-29）★★
      ⚠⚠ 順番を逆にすると、⚠ 開発 repo に残った古い `build-info.json` が
        pyproject の編集を**黙って上書き**します（★正本は pyproject のまま）。
      ★配布 Runtime には pyproject が入らないので、そこでは build-info が使われます。
    """
    return _from_pyproject() or _from_build_info() or _from_metadata() or UNKNOWN


#: 画面に出す形（例 `RetroUX 0.1.0`）
def title(prefix: str = "RetroUX") -> str:
    return f"{prefix} {get_version()}"


def stamp(prefix: str = "RetroUX") -> str:
    """★版と断面を 1 行で（例 `RetroUX DQ3 1.1.0 / build 45c3acf`）。

    ⚠ 起動ログに出す形です（★「どの断面の話か」を後から決められるように）。
    """
    return f"{title(prefix)} / build {build_id()}"


VERSION = get_version()
