"""書き先の 1 か所（RX3-0128 / 2026-09-08）— ★`work/` の下に書くものは、全部ここを通す。

```text
読む場所（ROM・生成物・input）      いつも repo の下           ★変わらない
書く場所（プレイデータ・記録・IPC） RETROUX_WRITE_ROOT があればそこ
```

## ⚠⚠ なぜ要るか

★実機テストが**人が遊んでいる本物**を書き換えていました（2026-09-08 実測）。

```text
tools/fceux/fcs/DQ3_J.fc*     ⚠ テストのセーブで上書き（★実際に fc5 を潰した）
work/dq3-knowledge/           ⚠ location-book の visit_order が巻き戻る
work/dq3-ui-settings.json     ⚠ 人が選んだ作戦・役割がテストの値になる
```

★Lua 側は前から `RETROUX_WRITE_ROOT` を見ています（`dev.lua`）。
⚠ Python 側だけが repo 直下に書いていたので、ここで**同じ環境変数**に合わせます。

## ★使い方

```python
from dq3 import paths
KNOWLEDGE = paths.lazy_work("dq3-knowledge")   # ★module の定数は**これ**を使う
got = paths.work("dq3-knowledge")              # ⚠ その場で使い切るならこちら
```

> ⚠⚠ **2026-09-21 訂正（RX3-0342）**: ここには「環境変数は **import より前**に立ててください」
> と書いてありましたが、★**守られませんでした**。⚠ `scripts/*_run.py` は `dq3.*` を
> module の頭で import し、`open_sandbox()` を `main()` で呼ぶので、⚠⚠ **順番が逆**です。
> → ★実際に**依頼者の `work/dq3-knowledge/` が書き換わりました**。
>
> ★いまは `lazy_work()` が**使うたびに**引き直すので、⚠ 順番に依存しません。
> ⚠ 「約束を守る」ではなく「★守らなくても壊れない」形にしました。
"""
from __future__ import annotations

import os
import pathlib

#: ★repo の場所（⚠ ここは読む専用。書き先ではない）
ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★書き先を差し替える環境変数（⚠ Lua と**同じ名前**にする）
ENV = "RETROUX_WRITE_ROOT"

#: ★隔離して動いている印（⚠ セーブスロットの扱いが変わる / `ai_state.lua`）
SANDBOX_ENV = "RETROUX_SANDBOX"


def write_root() -> pathlib.Path:
    """★いまの書き先の親。⚠ 立っていなければ repo。"""
    got = os.environ.get(ENV)
    return pathlib.Path(got) if got else ROOT


def work(*parts) -> pathlib.Path:
    """★`<書き先>/work/...`。"""
    return write_root().joinpath("work", *parts)


def program_root() -> pathlib.Path:
    """★Program が持っている領域（RX3-0466 / 2026-09-29）。

    ```text
    program_root()  = Release が交換する側   ⚠ **ここへ書かない**
    write_root()    = 利用者のデータ         ★更新で残る
    ```

    ⚠ いまは `ROOT` と同じものを返します。★名前を先に用意する理由は、
      「読む場所」と「書く場所」を**呼ぶ側の字面で見分けられる**ようにするためです。
      ⚠⚠ `Path(__file__).parents[...]` から**書き先**を作るのを増やさないこと。
    """
    return ROOT


def generated_dir() -> pathlib.Path:
    """★生成した Lua の置き場（RX3-0466 / 2026-09-29）。

    ⚠⚠ **program 側に書いてはいけません。** ★生成物は更新で消える側（GENERATED）で、
      program は Release が丸ごと差し替えます。⚠ 以前は `ROOT/work/generated` に
      書いていて、★配布物では書けない場所を指していました。

    ⚠ `write_root/generated` ではなく **`write_root/work/generated`** です。
      ★`work/` が既に「書き先の下の runtime data の根」で、他の 20 種類も全部そこです。
      ⚠ 開発環境では `write_root == ROOT` なので、**道は 1 文字も変わりません**。
    """
    return work("generated")


class LazyPath(os.PathLike):
    """★**使うたびに**書き先を引き直す置き場（RX3-0342 / 2026-09-21）。

    ## ⚠⚠ なぜ要るか

    ★`DEFAULT_PATH = paths.work(...)` は **import のときに**決まります。
    ⚠ 隔離の環境変数は `open_sandbox()` が立てるので **import より後**です。

    ```text
    ⚠ 以前  runner が dq3.* を import → 定数が本番で固まる → open_sandbox → ⚠⚠ 本番へ書く
    ★いま  定数は「道の作り方」を覚えるだけ → 使う瞬間に RETROUX_WRITE_ROOT を引く
    ```

    ★2026-09-21 に、これで**依頼者の `work/dq3-knowledge/` が書き換わりました**。
    ⚠ pytest は `conftest.py` が先に立てるので無事でしたが、
    ⚠⚠ **`scripts/*_run.py` の単体起動がすり抜けていました**。

    ## ★使い方

    ```python
    DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "chests.json")   # ★呼ぶ側は変えない
    DEFAULT_PATH.read_text(...)      # ⚠ ここで引き直す
    pathlib.Path(DEFAULT_PATH)       # ★os.fspath 経由で今の道になる
    ```

    ⚠ `pathlib.Path` の属性・メソッドはそのまま使えます（★`__getattr__` が本物へ渡す）。
    ⚠⚠ ただし **`isinstance(x, pathlib.Path)` は False** です（★必要なら `pathlib.Path(x)`）。
    """

    __slots__ = ("_parts",)

    def __init__(self, *parts) -> None:
        self._parts = parts

    def _now(self) -> pathlib.Path:
        return work(*self._parts)

    # --- ★os / open / shutil から使えるように ---
    def __fspath__(self) -> str:
        return str(self._now())

    # --- ★pathlib の顔をそのまま見せる ---
    def __getattr__(self, name):
        return getattr(self._now(), name)

    def __truediv__(self, other):
        return self._now() / other

    def __rtruediv__(self, other):
        return other / self._now()

    def __eq__(self, other) -> bool:
        if isinstance(other, LazyPath):
            return self._now() == other._now()
        if isinstance(other, (pathlib.Path, str)):
            return self._now() == pathlib.Path(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._now())

    def __str__(self) -> str:
        return str(self._now())

    def __repr__(self) -> str:
        return "LazyPath(%s)" % str(self._now())


def lazy_work(*parts) -> LazyPath:
    """★`work(...)` と同じ道を、⚠ **使うたびに**引き直す形で返す。"""
    return LazyPath(*parts)


def lazy_generated(*parts) -> LazyPath:
    """★`generated_dir()` と同じ道を、⚠ **使うたびに**引き直す形で返す。

    ⚠⚠ module の定数にはこちらを使ってください。★`generated_dir()` を
      既定引数に書くと、⚠ **def のときに**道が固まります（RX3-0215 で踏んだ形）。
    """
    return LazyPath("generated", *parts)


def repo(*parts) -> pathlib.Path:
    """★repo の中（⚠ ROM・生成物・input など**読むもの**）。"""
    return ROOT.joinpath(*parts)


# ----------------------------------------------------------------------
# ★利用者が決める場所（ROM / FCEUX）— RX3-0467 / RX3-0468 / 2026-09-29
#
#   ⚠⚠ **固定配置を必須にしない。** 配布 Runtime は任意のフォルダに置かれ、
#     ★ROM も FCEUX も RetroUX の外にあるのが普通です。
#
#   ★解決の順番は 1 か所（下の `_resolve`）。⚠ 同じ式を各モジュールに書かない
#     （2026-09-29 の実測で、ROM の既定値が **8 か所**に散っていました）。
# ----------------------------------------------------------------------

#: ★利用者の設定ファイルの名前（⚠ 中身の解釈は `retroux.core.config.user_config` 1 本）
USER_CONFIG_NAME = "user_config.yaml"

#: ★後方互換の置き場（⚠ `RX3-0467` より前は**ここ固定**だった）
LEGACY_ROM_NAME = "DQ3_J.nes"


def user_config_path() -> pathlib.Path | None:
    """★設定ファイルの場所（⚠ 書き先を先に見る / 無ければ None）。

    ```text
    <write_root>/user_config.yaml    ★PRESERVE 側（配布ではこちら）
    <program_root>/user_config.yaml  ⚠ 開発 repo の従来の場所（★控え）
    ```
    """
    for base in (write_root(), program_root()):
        got = base / USER_CONFIG_NAME
        if got.is_file():
            return got
    return None


#: ★読んだ設定の控え（⚠ 鍵は「場所・更新時刻・大きさ」。書き換えたら読み直す）
_CONFIG_CACHE: dict[tuple, object] = {}


#: ⚠⚠ 設定ファイルが**あるのに読めなかった**理由（★無ければ None / RX3-0476）
#
#   ★「設定ファイルが無い」は普通のことなので、ここには入れません。
#   ⚠ 入るのは「置いてあるのに読めなかった」ときだけです。
_config_error: str | None = None


def config_error() -> str | None:
    """⚠⚠ 設定を**読めなかった**理由（★読めた / 置いていないときは None）。

    ★呼ぶ側は、これが返ってきたら**黙って既定値で進めないでください**
      （⚠ 2026-09-30: 設定が効いていないことに気づけませんでした / `RX3-0476`）。
    """
    return _config_error


def _paths_config():
    """★`user_config.yaml` の `paths` 節（⚠ 読めなければ None）。

    ⚠ 毎回 YAML を読むと、ROM を引くたびにディスクを触ります。
      ★更新時刻と大きさで控えます（⚠ 人が編集したら鍵が変わるので読み直します）。

    ⚠⚠ **読めなかったことを黙って既定値に変えません**（`RX3-0476`）。
      ★理由は `_config_error` に残し、`config_error()` で取れます。
    """
    global _config_error

    target = user_config_path()
    if target is None:
        return None                                     # ★置いていないのは普通
    try:
        stat = target.stat()
        key = (str(target), stat.st_mtime_ns, stat.st_size)
    except OSError as exc:
        _config_error = "%s を読めませんでした: %s" % (target, exc)
        return None
    if key not in _CONFIG_CACHE:
        try:
            # ⚠⚠ ここの import は PyYAML を要ります（★PyYAML の無い Python で落ちる）。
            #   ⚠ 以前はこれが関数の**外**にあり、`_setting()` の
            #     `except Exception` が **ModuleNotFoundError まで飲み込んで**
            #     いました（★設定を丸ごと無視して控えの場所を答えた）。
            from retroux.core.config import user_config as UC

            config, _warnings = UC.load(target)
        except Exception as exc:                        # noqa: BLE001
            _config_error = ("%s を読めませんでした: %s: %s"
                             % (target, type(exc).__name__, exc))
            return None
        _CONFIG_CACHE.clear()                           # ★古い鍵を溜めない
        _CONFIG_CACHE[key] = config.paths
    _config_error = None                                # ★読めたので理由は消す
    return _CONFIG_CACHE[key]


def _setting(name: str) -> str:
    """★`user_config.yaml` の `paths.<name>` を**生の文字列**で返す（無ければ空）。

    ⚠ `user_config.path()` は相対パスを repo 基準の絶対パスにしてしまうので、
      ★「空かどうか」を見たいここでは使いません。
    ⚠ 読めなくても落ちません（★既定の場所で動くほうが害が小さい）。
      ⚠⚠ ただし**黙りません** — 理由は `config_error()` に残ります。
    """
    got = _paths_config()
    if got is None:
        return ""
    return str(getattr(got, name, "") or "")


def _resolve(setting: str, *legacy: pathlib.Path) -> pathlib.Path | None:
    """★設定 → 後方互換 → None。⚠ **無いものは None**（勝手に作らない）。"""
    if setting:
        got = pathlib.Path(setting)
        if not got.is_absolute():
            got = program_root() / got
        return got                                      # ★人が指した場所はそのまま返す
    for candidate in legacy:
        if candidate.exists():
            return candidate
    return None


def rom(name: str = LEGACY_ROM_NAME) -> pathlib.Path | None:
    """★DQ3 の ROM。⚠ 見つからなければ `None`（★落とさない / 案内は呼ぶ側）。

    ```text
    1 user_config.yaml の paths.dq3_rom   ★任意の場所（コピー不要）
    2 <write_root>/work/rom/DQ3_J.nes     ★後方互換（配布では userdata 側）
    3 <program_root>/work/rom/DQ3_J.nes   ⚠ 開発 repo と隔離走行のため（★控え）
    4 None
    ```

    ⚠⚠ 3 を残す理由: 検査は `RETROUX_WRITE_ROOT` を一時フォルダに向けるので、
      ★2 だけにすると**本物の ROM を見失います**（`D-33` と同じ話）。
    ⚠ hash の照合は `dq3rom/profile.py` の仕事です（★ここではしない）。
    """
    return _resolve(_setting("dq3_rom"),
                    work("rom", name), program_root() / "work" / "rom" / name)


def rom_or_legacy(name: str = LEGACY_ROM_NAME) -> pathlib.Path:
    """★`rom()` と同じだが、⚠ 無いときは**従来の場所**を返す。

    ⚠⚠ 「無ければ None」を扱えない古い呼び出し（★`DEFAULT_ROM` のような
      module の定数）のための入口です。★新しいコードは `rom()` を使ってください。
    """
    got = rom(name)
    return got if got is not None else (program_root() / "work" / "rom" / name)


class LazyResolved(os.PathLike):
    """★**使うたびに**解決し直す置き場（⚠ `LazyPath` の兄弟）。

    ⚠⚠ module の定数（`DEFAULT_ROM` など）に `rom()` の**結果**を入れると、
      ★import のときに固まります。⚠ 設定を書き換えても効かず、
      検査が `RETROUX_WRITE_ROOT` を差し替えても追いつきません（RX3-0215 と同じ形）。

    ⚠ `isinstance(x, pathlib.Path)` は False です（★必要なら `pathlib.Path(x)`）。
    """

    __slots__ = ("_resolve", "_args")

    def __init__(self, resolve, *args) -> None:
        self._resolve = resolve
        self._args = args

    def _now(self) -> pathlib.Path:
        return self._resolve(*self._args)

    def __fspath__(self) -> str:
        return str(self._now())

    def __getattr__(self, name):
        return getattr(self._now(), name)

    def __truediv__(self, other):
        return self._now() / other

    def __rtruediv__(self, other):
        return other / self._now()

    def __eq__(self, other) -> bool:
        if isinstance(other, LazyResolved):
            return self._now() == other._now()
        if isinstance(other, (pathlib.Path, str)):
            return self._now() == pathlib.Path(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._now())

    def __str__(self) -> str:
        return str(self._now())

    def __repr__(self) -> str:
        return "LazyResolved(%s)" % str(self._now())


def lazy_rom(name: str = LEGACY_ROM_NAME) -> LazyResolved:
    """★module の定数にする DQ3 の ROM（⚠ 使う瞬間に解決し直す）。"""
    return LazyResolved(rom_or_legacy, name)


# ----------------------------------------------------------------------
# ★FCEUX（RX3-0468 / 2026-09-29）
#
#   ⚠⚠ `tools/fceux/` は **3 つの意味**を兼ねています:
#     exe / 設定（`fceux.cfg`）/ ★**セーブステートの本物**（`fcs/`）。
#   ★FCEUX は `-cfg` で渡しても **exe の隣**の cfg しか見ません（RX-0108 で実測）。
#   → ★だから「exe の場所」1 つから派生させます。⚠ 各機能が別々に組み立てない。
# ----------------------------------------------------------------------

#: ★同梱の既定（⚠ 無ければ `fceux.exe` も見る）
LEGACY_FCEUX_NAMES = ("fceux64.exe", "fceux.exe")


def fceux() -> pathlib.Path | None:
    """★FCEUX の exe。⚠ 見つからなければ `None`（★落とさない / 案内は呼ぶ側）。

    ```text
    1 user_config.yaml の paths.fceux    ★任意の場所（例 C:/Emulators/FCEUX/fceux64.exe / ⚠ 名前は問わない）
    2 <write_root>/tools/fceux/fceux64.exe  → fceux.exe   ★後方互換
    3 <program_root>/tools/fceux/fceux64.exe → fceux.exe   ⚠ 開発 repo（★控え）
    4 None
    ```

    ⚠ 動かしたときは**設定を変えるだけ**で戻ります（★再インストールは要りません）。
    """
    legacy: list[pathlib.Path] = []
    for base in (write_root(), program_root()):
        legacy += [base / "tools" / "fceux" / n for n in LEGACY_FCEUX_NAMES]
    return _resolve(_setting("fceux"), *legacy)


def fceux_dir() -> pathlib.Path | None:
    """★FCEUX の exe が居るフォルダ（⚠ cfg と fcs はこの中）。"""
    exe = fceux()
    return exe.parent if exe is not None else None


def _beside(*parts: str) -> pathlib.Path | None:
    """★exe の隣を指す（⚠ 場所が分からなければ None）。"""
    base = fceux_dir()
    return base.joinpath(*parts) if base is not None else None


def fceux_cfg() -> pathlib.Path | None:
    """★`fceux.cfg`。⚠⚠ **exe の隣にしか置けません**（RX-0108 で実測）。

    ⚠ RetroUX 側で別のフォルダへ移す設計にはしません（★FCEUX の挙動に合わせる）。
    """
    return _beside("fceux.cfg")


def fceux_fcs() -> pathlib.Path | None:
    """★セーブステートの**本物**の置き場（`fcs/`）。

    ⚠⚠ ここを見失うと、**世代バックアップが静かに空振りします**
      （★消えたセーブは戻りません）。→ 呼ぶ側は `fcs_warning()` を出してください。
    """
    return _beside("fcs")


def fceux_palettes() -> pathlib.Path | None:
    """★`palettes/`（⚠ FCEUX の配布物に入っているもの）。"""
    return _beside("palettes")


def fcs_warning() -> str | None:
    """★セーブステートの元が取れないときの**言葉**（⚠ 取れていれば None）。

    ⚠⚠ 「成功したように見えるがバックアップしていない」を禁止するための入口です
      （依頼者 2026-09-29 §7）。★呼ぶ側はこれを**必ず記録か画面に出す**こと。
    """
    exe = fceux()
    if exe is None:
        return ("⚠ FCEUX の場所が分かりません。セーブステートの控えを取れません"
                "（★user_config.yaml の paths.fceux を設定してください）")
    if not exe.exists():
        return f"⚠ FCEUX がありません: {exe}（★控えを取れません）"
    fcs = fceux_fcs()
    if fcs is None or not fcs.is_dir():
        return (f"⚠ セーブステートの置き場がありません: {fcs}"
                "（★FCEUX を 1 度起動すると作られます）")
    if not any(fcs.iterdir()):
        return (f"⚠ セーブステートがまだ 1 つもありません: {fcs}"
                "（★控えは取れますが、中身は空です）")
    return None


def main(argv: list[str] | None = None) -> int:
    """★場所を 1 行で答える（⚠ PowerShell から呼ぶための口 / RX3-0467・0468）。

    ```text
    python -m dq3.paths --rom      → ROM の絶対パス（⚠ 無ければ空行 ＋ 終了コード 1）
    python -m dq3.paths --fceux    → FCEUX の exe
    python -m dq3.paths --fcs      → セーブステートの置き場
    python -m dq3.paths --write-root / --program-root / --generated
    ```

    ⚠ 見つからないときに**でたらめな道を返しません**（★空 ＋ 終了コード 1）。
    """
    import argparse

    parser = argparse.ArgumentParser(description="DQ3 の場所を 1 行で出す")
    parser.add_argument("--rom", action="store_true")
    parser.add_argument("--fceux", action="store_true")
    parser.add_argument("--fcs", action="store_true")
    parser.add_argument("--write-root", action="store_true")
    parser.add_argument("--program-root", action="store_true")
    parser.add_argument("--generated", action="store_true")
    args = parser.parse_args(argv)

    got: pathlib.Path | None
    if args.rom:
        got = rom()
    elif args.fceux:
        got = fceux()
    elif args.fcs:
        got = fceux_fcs()
    elif args.write_root:
        got = write_root()
    elif args.program_root:
        got = program_root()
    elif args.generated:
        got = generated_dir()
    else:
        parser.error("どれか 1 つを指定してください")
        return 2

    # ⚠⚠ 設定が**あるのに読めなかった**なら、★答えずに理由を出す（`RX3-0476`）。
    #   ★ここで道を 1 行返すと、「設定が効いている」と読めてしまいます。
    problem = config_error()
    if problem:
        import sys

        print("⚠⚠ 設定を読めませんでした: %s" % problem, file=sys.stderr)
        print("⚠ そのため %s の指定は**効いていません**（★控えの場所を答えません）。"
              % USER_CONFIG_NAME, file=sys.stderr)
        print("★同梱の Python で実行してください:", file=sys.stderr)
        print(r"    .venv\Scripts\python.exe -m dq3.paths " + " ".join(argv or sys.argv[1:]),
              file=sys.stderr)
        return 3

    if got is None:
        print("")
        return 1
    print(str(got))
    return 0


def as_repo(path) -> pathlib.Path:
    """★逃がした書き先を、**repo 側の同じ場所**に読み替える（RX-0141 / 2026-09-18）。

    ⚠⚠ 検査中は `RETROUX_WRITE_ROOT` が一時フォルダを指します（`conftest.py`）。
      ★そのとき「この置き場は Git の外か」を見たい検査は、⚠ 一時フォルダを見ても意味が無く、
      **repo 側の同じ道**を見る必要があります。

    ```text
    <一時>/work/dq3-knowledge/topic-state.json  →  <repo>/work/dq3-knowledge/topic-state.json
    <repo>/work/rom/DQ3_J.nes                   →  そのまま（★書き先の下でなければ触らない）
    ```
    """
    got = pathlib.Path(path).resolve()
    base = (write_root() / "work").resolve()
    if base == got:
        return ROOT / "work"
    if base in got.parents:
        return ROOT.joinpath("work", got.relative_to(base))
    return got


def in_sandbox() -> bool:
    """★隔離された場所で動いているか。"""
    return os.environ.get(SANDBOX_ENV) == "1" or write_root() != ROOT


__all__ = ["ROOT", "ENV", "SANDBOX_ENV", "LazyPath", "LazyResolved",
           "write_root", "work", "lazy_work",
           "program_root", "generated_dir", "lazy_generated",
           "USER_CONFIG_NAME", "LEGACY_ROM_NAME", "LEGACY_FCEUX_NAMES",
           "user_config_path", "rom", "rom_or_legacy", "lazy_rom",
           "fceux", "fceux_dir", "fceux_cfg", "fceux_fcs", "fceux_palettes",
           "fcs_warning", "main",
           "repo", "as_repo", "in_sandbox"]


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
