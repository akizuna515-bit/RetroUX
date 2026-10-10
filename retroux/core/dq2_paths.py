"""DQ2 の場所の決め方を 1 か所に（RX-0146 / D-42 / 依頼者の判断 J1・J6・J7）。

★DQ2 が使う「どこ」を、ここから決めます。⚠ DQ3 の `dq3/paths.py` は参考にしただけで import しません。

```text
program_root   プログラムの直下（★このファイルの 2 つ上）
write_root     書き先の根（★`RETROUX_WRITE_ROOT`、無ければ program_root / Portable ZIP では ZIP の直下）
rom            DQ2 の ROM（★設定 `paths.rom`。相対なら program_root から）
fceux_exe      DQ2 が起動する FCEUX（★設定 `paths.fceux`。空なら tools/fceux/fceux64.exe → fceux.exe）
fceux_dir      FCEUX の exe が居るフォルダ（⚠ FCEUX は fceux.cfg と fcs/ を exe の隣にしか置かない / RX-0108）
fcs_dir        セーブステートの本物（★DQ2 の控えが見張る所）
fceux_cfg      fceux.cfg（★映像倍率を書く所）
```

★設定は DQ2 専用の `dq2_user_config.yaml` から読みます（RX-0147）。
⚠ 旧 `user_config.yaml` の `paths.fceux` は DQ3 用なので、DQ2 では使いません（★読み手が空にする）。

## ★Phase 1 では場所を**変えない**

既定（設定が空）のときの場所は、これまでと同じです（★`tools/fceux/fceux64.exe` / `work/rom/DQ2_J.nes`）。
★変わるのは「設定に書いた場所が、FCEUX の起動に効くようになる」ことだけです
（⚠ 以前は `paths.rom` が FCEUX の起動に効かず、公開 README の説明と食い違っていた）。

起動スクリプト（PowerShell）からは `python -m retroux.core.dq2_paths --launch-json` で受け取ります
（★JSON は ASCII で出す = 日本語や空白を含む場所でも、コンソールの文字コードに左右されない）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: ★同梱の既定の FCEUX（⚠ 無ければ fceux.exe も見る）
FCEUX_NAMES = ("fceux64.exe", "fceux.exe")


def program_root() -> Path:
    return PROJECT_ROOT


def write_root() -> Path:
    env = os.environ.get("RETROUX_WRITE_ROOT")
    return Path(env) if env else PROJECT_ROOT


def work(*parts: str) -> Path:
    return write_root().joinpath("work", *parts)


#: ★DQ2 の利用者設定（画面から保存するもの）の置き場（RX-0156 / 依頼 §9）
#:   ⚠ program_root の `config/` は Portable では「プログラムの中」なので書かない
SETTINGS_DIR = "dq2-settings"
#: ⚠ 旧の置き場（★読むだけ・書き戻さない）
LEGACY_SETTINGS_DIR = "config"
#: ★ここへ移した設定（keybindings / まんたん / 大目的）
SETTING_NAMES = ("keybindings.yaml", "mantan.yaml", "mission.yaml")


def settings_dir() -> Path:
    return work(SETTINGS_DIR)


def setting(name: str) -> Path:
    """★利用者設定の書き先（`<write_root>/work/dq2-settings/<name>`）。"""
    return settings_dir() / name


def legacy_setting(name: str) -> Path:
    """⚠ 旧の置き場（`<program_root>/config/<name>`）。★読むだけ。"""
    return PROJECT_ROOT / LEGACY_SETTINGS_DIR / name


def _for_log(path: Path) -> str:
    """★ログには絶対パスを出さない（RX-0043）。program_root / write_root からの相対で書く。"""
    for base in (PROJECT_ROOT, write_root()):
        try:
            return Path(path).relative_to(base).as_posix()
        except ValueError:
            continue
    return Path(path).name


def setting_to_read(new: Path, legacy: Path) -> Path:
    """★読む場所: 新しい方があればそれ、無くて旧があれば旧、どちらも無ければ新しい方。

    ⚠ 旧を読んでも、保存は必ず新しい方へ（★旧は書き戻さない / 依頼 §9）。
    ★旧を読んだときはログに 1 行（★同じファイルは 1 回だけ / RX-0156 の Logging impact）。
    """
    if new.exists() or not legacy.exists():
        return new
    if legacy not in _LEGACY_REPORTED:
        _LEGACY_REPORTED.add(legacy)
        import logging

        logging.getLogger("retroux.settings").info(
            "旧の置き場の設定を読みました: %s（★保存は %s へ。旧は書き換えません）",
            _for_log(legacy), _for_log(new))
    return legacy


#: ★旧の置き場を読んだと書いたもの（★毎回は出さない）
_LEGACY_REPORTED: set[Path] = set()


#: ★DQ2 の events.jsonl（write_root からの相対）。⚠ Lua は `retroux/plugins/dq2/config.yaml` の
#:   `logging.events_path` を write_root に足して書く → 2 つが同じ値であることを検査で見る（RX-0162）
EVENTS_REL = "work/events.jsonl"


def events() -> Path:
    """★DQ2 の events.jsonl の正本（`<write_root>/work/events.jsonl` / RX-0162）。

    ★Lua の書き先（bridge.lua: `write_root .. "/" .. logging.events_path`）と、Python の取り込み・世代交代・
      分析ツールの読み先を、ここ 1 か所から決める。
    ⚠ 設定 `paths.events` は使わない（★Lua はその値を読まないので、変えると Python だけ別のファイルを見ていた）。
    """
    return write_root() / EVENTS_REL


def legacy_events(old_root: Path | None = None) -> Path:
    """⚠ 旧配置の events.jsonl（`<program_root>/work/events.jsonl`）。★Migration の元として読むだけ。"""
    return (old_root if old_root is not None else PROJECT_ROOT) / EVENTS_REL


def window_state() -> Path:
    """★窓の位置と大きさ（`work/window-state.json`）。⚠ DQ3 は自分の置き場を渡す。"""
    return work("window-state.json")


def program_work(*parts: str) -> Path:
    """★`<program_root>/work/...`（RX-0156）。

    ⚠ **program_root 側**に置くもの: Lua（bridge.lua）が `self.root` から読む生成物と、
      `gui.py` が `PROJECT_ROOT / 相対` で読む派生データ（地図・絵・作戦）。
      write_root にすると片側だけ別の場所を見る（★Portable では両者が同じ場所 / J7）。
    ★CWD には依らない（⚠ 以前は `Path("work/...")` で、起動した場所次第だった）。
    """
    return PROJECT_ROOT.joinpath("work", *parts)


def generated(*parts: str) -> Path:
    """★Lua へ渡す生成物（`work/generated/`）。⚠ program_root 側（`program_work` の説明）。"""
    return program_work("generated", *parts)


def _cfg(cfg=None):
    if cfg is not None:
        return cfg
    from .config import dq2_user_config

    return dq2_user_config.load()[0]


def _absolute(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p


def rom(cfg=None) -> Path:
    """DQ2 の ROM（★設定 `paths.rom`）。"""
    return _absolute(_cfg(cfg).paths.rom)


def fceux_exe(cfg=None) -> Path:
    """DQ2 が起動する FCEUX の exe。

    ★設定 `paths.fceux` があればそれ（★名前は問わない / 相対なら program_root から）。
    ★無ければ `tools/fceux/fceux64.exe` → `fceux.exe`（⚠ どちらも無ければ fceux64.exe を返す = 起動側が「見つかりません」と出す）。
    """
    given = getattr(_cfg(cfg).paths, "fceux", "")
    if given:
        return _absolute(given)
    base = PROJECT_ROOT / "tools" / "fceux"
    for name in FCEUX_NAMES:
        if (base / name).exists():
            return base / name
    return base / FCEUX_NAMES[0]


def fceux_dir(cfg=None) -> Path:
    return fceux_exe(cfg).parent


def fcs_dir(cfg=None) -> Path:
    """★セーブステートの本物の置き場（FCEUX は exe の隣の fcs/ に書く）。"""
    return fceux_dir(cfg) / "fcs"


def fceux_cfg(cfg=None) -> Path:
    """★fceux.cfg（⚠ exe の隣にしか置けない / RX-0108 で実測）。"""
    return fceux_dir(cfg) / "fceux.cfg"


#: ★場所の設定で、制御文字が混ざると壊れる項目（RX-0168）
PATH_KEYS = ("rom", "fceux")
_CONTROL_NAMES = {"\f": "\\f（改ページ）", "\t": "\\t（タブ）", "\n": "\\n（改行）", "\r": "\\r",
                  "\b": "\\b（後退）", "\a": "\\a", "\v": "\\v", "\x00": "\\0"}


def path_problems(cfg=None) -> list[str]:
    """⚠ 場所の設定に制御文字が混ざっていないか（RX-0168）。

    ⚠⚠ YAML の `"…"` の中では `\\f` `\\t` `\\n` などが**特殊文字に化ける**
      （2026-10-05 実測: `"C:/Emu/…/\\fceux64.exe"` が `…/<改ページ>ceux64.exe` になり、起動が黙って止まった）。
    """
    cfg = _cfg(cfg)
    out = []
    for key in PATH_KEYS:
        value = str(getattr(cfg.paths, key, "") or "")
        bad = sorted({ch for ch in value if ord(ch) < 32})
        if bad:
            names = "・".join(_CONTROL_NAMES.get(ch, f"\\x{ord(ch):02x}") for ch in bad)
            out.append(f"設定 paths.{key} に、場所として使えない文字が入っています（{names}）: {value!r}。"
                       f"\\ を / に書き換えてください（例 C:/Emu/fceux/fceux64.exe）。"
                       f"⚠ \"…\" で囲むと \\f や \\t が特殊文字として読まれます")
    return out


def launch_info(cfg=None) -> dict:
    """★起動スクリプトへ渡す場所の組（★1 度だけ設定を読み、同じ設定から全部決める）。

    ★`problems` が空でなければ、起動スクリプトは FCEUX を起こさずに理由を出して止まる（RX-0168）。
    """
    cfg = _cfg(cfg)
    return {
        "rom": str(rom(cfg)),
        "fceux": str(fceux_exe(cfg)),
        "fceux_cfg": str(fceux_cfg(cfg)),
        "fcs": str(fcs_dir(cfg)),
        "problems": path_problems(cfg),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="DQ2 の場所（ROM・FCEUX・fcs・fceux.cfg）を出す")
    ap.add_argument("--launch-json", action="store_true",
                    help="起動スクリプト用に JSON（ASCII）で出す")
    args = ap.parse_args(argv)
    info = launch_info()
    if args.launch_json:
        print(json.dumps(info, ensure_ascii=True))
    else:
        for key, value in info.items():
            print(f"{key:10s} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
