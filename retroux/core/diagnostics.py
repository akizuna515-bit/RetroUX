"""問い合わせ対応のための診断情報（2026-07-30 / リリース調整 仕様書 13章）。

★★ **公開後に「動きません」と言われたとき、これ1つで状況が分かる。** ★★

  仕様書 13章が挙げている項目:
      RetroUXバージョン / Pythonバージョン / FCEUXバージョン / OS /
      設定スキーマバージョン / ROMハッシュ / 起動モード / 直近警告

## ⚠⚠ 入れてはいけないもの（仕様書 13章）

  > 診断情報には、ROM本体や個人パス等を不用意に含めない。

| 入れない | なぜ |
| --- | --- |
| ROM そのもの | 配布できないもの |
| 利用者の名前を含むパス | `C:\\Users\\本名\\...` が公開の場に貼られる |
| セーブデータ | 個人の遊び方の記録 |

★パスは**プロジェクトからの相対**にする（`work\\retroux.log`）。
  絶対パスは利用者名を含みうるので、置き換える。

★ROM は**ハッシュだけ**（同じROMかを確かめるのに十分で、中身は分からない）。
"""

from __future__ import annotations

import pathlib
import platform
import re
import sys

#: 直近の警告を何件まで載せるか。★多すぎると貼るのが面倒になって使われない
MAX_WARNINGS = 10


def _relative(path, root) -> str:
    """プロジェクトからの相対パスにする。★外なら**名前だけ**にする。

    ⚠ 絶対パスをそのまま出さない（`C:\\Users\\本名\\...` が漏れる）。
    """
    try:
        p = pathlib.Path(path)
        return str(p.relative_to(root))
    except (ValueError, TypeError):
        try:
            # ★外にあるものは名前だけ（場所は伏せる）
            return f"…/{pathlib.Path(path).name}"
        except (TypeError, ValueError):
            return "(不明)"


def _version_from_window() -> "str | None":
    """動いている FCEUX の**窓の題名**から版を読む。

    ★★ **FCEUX の exe には版情報が入っていない**（2026-07-30 に実測）。 ★★
      `FileVersion` は空、各パートは 0。だからファイルからは読めない。

    ★ところが窓の題名には入っている: `FCEUX 2.6.6: DQ2_J`
      ⚠ 動いていないときは読めないので、そのときは None を返す。
    """
    try:
        from .window_align import find_windows

        for info in find_windows("FCEUX", match="prefix"):
            # ★`FCEUX 2.6.6: DQ2_J` から数字の並びだけを取る
            found = re.search(r"FCEUX\s+([0-9]+(?:\.[0-9]+)+)", info.title)
            if found:
                return found.group(1)
    except Exception:                                  # noqa: BLE001
        return None
    return None


def format_file_version(ms: int, ls: int) -> "str | None":
    """Win32 の版情報（2つの 32bit）を `a.b.c.d` にする。

    ★★ **すべて 0 のときは「版」として返さない**（`None`）。 ★★
      ⚠ FCEUX 2.6.6 は実際にここが 0 だった（版情報リソースが無い）。
        `0.0.0.0` を出すと、**入っているのに読めた**ように見えてしまう。
        「無い」と「読めた」は区別する。

    ★ここだけ切り出してあるのは、`ctypes` を通さずに試せるようにするため。
    """
    if (ms, ls) == (0, 0):
        return None
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def fceux_version(root) -> str:
    """FCEUX の版。★取れなければ「分からない」と書く（推測しない）。

    ★探す順:
      1. 動いている窓の題名（**これがいちばん確実**）
      2. ファイルの版情報（⚠ FCEUX 2.6.6 では**空だった**）
      3. 分からない
    """
    from_window = _version_from_window()
    if from_window:
        return from_window

    exe = pathlib.Path(root) / "tools" / "fceux" / "fceux64.exe"
    if not exe.exists():
        exe = pathlib.Path(root) / "tools" / "fceux" / "fceux.exe"
    if not exe.exists():
        return "見つかりません"
    try:
        # ⚠ `--help` で起動すると窓が開くことがあるので、**実行しない**。
        #   ファイルの版情報だけを読む（Windows のみ）。
        import ctypes
        import ctypes.wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(exe), None)
        if not size:
            # ⚠ FCEUX 2.6.6 はここに来る（版情報リソースが**無い**）。
            #   ★「不明」だけだと読み損じたのか元から無いのか分からないので、
            #     **無いこと**と**読める条件**を書く。
            return f"版情報なし（{exe.name} / FCEUX 起動中なら題名から読めます）"
        buf = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(str(exe), 0, size, buf)
        length = ctypes.c_uint()
        block = ctypes.c_void_p()
        if not ctypes.windll.version.VerQueryValueW(
                buf, "\\", ctypes.byref(block), ctypes.byref(length)):
            return f"不明（{exe.name}）"
        info = ctypes.cast(
            block, ctypes.POINTER(ctypes.c_uint * 4)).contents
        made = format_file_version(info[2], info[3])
        if made is None:
            return f"版情報なし（{exe.name} / FCEUX 起動中なら題名から読めます）"
        return made
    except Exception:                                  # noqa: BLE001
        return f"不明（{exe.name} はあります）"


def _log_tail(path, count: int) -> "list | None":
    """ログの末尾 `count` 行を読む。★読めなければ None（省かず理由を出せる）。"""
    try:
        p = pathlib.Path(path)
        # ⚠ 大きいログを丸ごと読まない。末尾だけ拾う（cp932 誤読を避け UTF-8）。
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return None
    return [ln.rstrip("\n") for ln in lines[-count:]]


def collect(*, root=None, user_cfg=None, rom_hash=None, read_only=None,
            warnings=None, schema_version=None, tactics=None,
            log_tail=0) -> dict:
    """診断情報を集める。★**分からないものは「不明」と書く**（省かない）。

    ⚠ 省くと、読んだ人が「無い」と「取れなかった」を区別できない。
    """
    from ..version import VERSION

    here = pathlib.Path(root or pathlib.Path(__file__).resolve().parents[2])
    made: dict = {
        "RetroUX": VERSION,
        "Python": f"{sys.version_info.major}.{sys.version_info.minor}."
                  f"{sys.version_info.micro}",
        # ★どの exe で動いているか＝公開用（pythonw）か開発用（python）か
        "実行ファイル": pathlib.Path(sys.executable).name,
        "OS": f"{platform.system()} {platform.release()} ({platform.version()})",
        "FCEUX": fceux_version(here),
        "起動モード": ("閲覧専用" if read_only else "記録あり")
                      if read_only is not None else "不明",
    }
    if schema_version is not None:
        made["設定スキーマ"] = str(schema_version)
    if rom_hash:
        # ★ハッシュだけ。★頭12文字で十分（同じROMかを確かめる用途）
        made["ROMハッシュ"] = str(rom_hash)[:12]
    else:
        made["ROMハッシュ"] = "不明"
    if tactics:
        made["戦術プロフィール"] = str(tactics)
    if user_cfg is not None:
        # ⚠⚠ **渡すものを間違えていないかを先に見る**（2026-07-30 に踏んだ）。
        #   `user_cfg.gui`（`GuiConfig`）を渡すと `path()` が無いので
        #   AttributeError になり、下の `except` が「不明」に化けさせていた。
        #   ★結果、**プログラムの間違いが「分からなかった」ように見えた**。
        #     しかも DB と ROMファイルの行は**丸ごと消えた**（1行目で例外なので）。
        if not hasattr(user_cfg, "path"):
            made["設定"] = (f"⚠ 渡された設定に path() がありません"
                            f"（{type(user_cfg).__name__}）。"
                            "UserConfig 全体を渡してください")
        else:
            # ★1項目ずつ囲む。1つ失敗しても**残りは出す**
            #   （まとめて囲むと、最初の失敗で後ろが全部消える）
            for label, key in (("ログ", "log"), ("DB", "db")):
                try:
                    made[label] = _relative(user_cfg.path(key), here)
                except Exception as exc:               # noqa: BLE001
                    made[label] = f"不明（{exc}）"
            # ⚠ ROM のパスは出さない（利用者名を含みうる）。あるかだけ書く
            try:
                rom = pathlib.Path(user_cfg.path("rom"))
                made["ROMファイル"] = "あり" if rom.exists() else "見つかりません"
            except Exception as exc:                   # noqa: BLE001
                made["ROMファイル"] = f"不明（{exc}）"
    if warnings:
        made["直近の警告"] = list(warnings)[-MAX_WARNINGS:]
    # ★ログの直近数行（2026-08-11 / 依頼者の要望）。問い合わせで最初に効く。
    #   ⚠ user_cfg からログの場所を引く。取れなければ理由を書く（省かない）。
    if log_tail and log_tail > 0:
        if user_cfg is not None and hasattr(user_cfg, "path"):
            try:
                tail = _log_tail(user_cfg.path("log"), int(log_tail))
            except Exception as exc:                       # noqa: BLE001
                tail = None
                made[f"ログの直近{int(log_tail)}行"] = f"不明（{exc}）"
            if tail is not None:
                made[f"ログの直近{int(log_tail)}行"] = tail
            elif f"ログの直近{int(log_tail)}行" not in made:
                made[f"ログの直近{int(log_tail)}行"] = "不明（ログを読めません）"
        else:
            made[f"ログの直近{int(log_tail)}行"] = "不明（ログの場所が分かりません）"
    return made


def as_text(info: dict) -> str:
    """貼り付けやすい形にする。★そのまま問い合わせに貼れること。"""
    lines = ["RetroUX 診断情報", "```"]
    for key, value in info.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("```")
    return "\n".join(lines)
