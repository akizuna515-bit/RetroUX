"""設定がまだ無いときの「次の一手」（RX3-0471 / 2026-10-01）。

## ⚠⚠ なぜ要るか

★配布 Runtime には `user_config.yaml` が**入っていません**（利用者のものなので）。
⚠ そのため、ROM / FCEUX を外に置いている人は**必ず**この状態から始めます。

```text
⚠ 直す前の案内   「FCEUX が見つかりません。user_config.yaml に場所を書く」
                 → ★その**ファイルがまだ無い**ことに触れていない
                 → ⚠⚠ 利用者は「どこに作るのか」「名前は何か」から迷う
```

→ ★だから「**雛形から作る**」を 1 手で踏めるようにします。

## ⚠ 作るのは利用者の操作で

⚠⚠ **起動のたびに勝手に作りません。**
★人が「作る」を選んだときだけ作ります（`--create`）。
⚠ 既にあるものは**上書きしません**（★`RX3-0472` の所有境界と同じ考え）。

## 使い方

```bash
python -m dq3.first_run --check     # ★要るかどうかだけ見る（終了コード 0/1）
python -m dq3.first_run --create    # ★雛形から作る（⚠ 既にあれば何もしない）
```
"""
from __future__ import annotations

import pathlib
import shutil

from dq3 import paths as P3

#: ★同梱している雛形の名前（⚠ 本物と 1 文字違い = 衝突しない）
TEMPLATE_NAME = "user_config.example.yaml"


def template_path() -> pathlib.Path:
    """★雛形（program 側 / ⚠ 配布物に入っている）。"""
    return P3.program_root() / TEMPLATE_NAME


def target_path() -> pathlib.Path:
    """★作る先（`<write_root>/user_config.yaml`）。

    ⚠ `paths.user_config_path()` は「在るもの」を探しますが、
      ★ここは「**これから作る場所**」なので write_root 固定です。
    """
    return P3.write_root() / P3.USER_CONFIG_NAME


def needs_config() -> bool:
    """★設定がまだ無いか（⚠ 在れば False / 中身は見ません）。"""
    return P3.user_config_path() is None


def create_from_template(dest=None) -> tuple[bool, str]:
    """★雛形から作る。戻り値は `(作ったか, 言うこと)`。

    ```text
    ★作った      True  / 道と「ここを書き換えてください」
    ⚠ 既にある    False / ⚠⚠ **上書きしません**
    ⚠ 雛形が無い  False / ★配布物が壊れている（名指しで言う）
    ```
    """
    out = pathlib.Path(dest) if dest is not None else target_path()
    if out.exists():
        return False, ("⚠ 設定ファイルは既にあります: %s"
                       "（★上書きしません / 中を書き換えてください）" % out)
    src = template_path()
    if not src.is_file():
        return False, ("⚠⚠ 雛形がありません: %s"
                       "（★配布物が壊れています。ZIP を展開し直してください）" % src)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        # ⚠ `copy2` はバイト列のまま写す（★改行も BOM も変えない / RX-0121）
        shutil.copy2(src, out)
    except OSError as exc:
        return False, ("⚠⚠ 作れませんでした: %s: %s"
                       "（★書き込めない場所に置いていませんか）" % (out, exc))
    return True, ("★作りました: %s\n"
                  "⚠ この中の paths.dq3_rom と paths.fceux を、"
                  "あなたの ROM / FCEUX の場所に書き換えてください。" % out)


def guidance() -> str:
    """★案内の本文（⚠ 設定がまだ無いときに出す / ★launcher も同じ文を使う）。"""
    if not needs_config():
        return ("★設定ファイル: %s\n"
                "⚠ 場所が合っているか、この中の paths を見てください。"
                % P3.user_config_path())
    return ("⚠ 設定ファイル（%s）が、まだありません。\n\n"
            "★次のどちらかをしてください:\n\n"
            "  1. 雛形から作る（⚠ この案内の「作る」を押す / "
            "または `python -m dq3.first_run --create`）\n"
            "       → ★%s ができます。中の paths を書き換えてください。\n\n"
            "  2. ROM と FCEUX を、案内のとおりフォルダに置く\n"
            "       → ★PLACE-ROM-HERE.txt / PLACE-FCEUX-HERE.txt"
            % (P3.USER_CONFIG_NAME, target_path()))


def main(argv=None) -> int:
    """★`--check` は「要るか」を終了コードで返す（0 = 要る / 1 = もうある）。"""
    import argparse

    ap = argparse.ArgumentParser(description="設定がまだ無いときの次の一手")
    ap.add_argument("--check", action="store_true",
                    help="★雛形から作る必要があるか（⚠ 0 = 要る / 1 = もうある）")
    ap.add_argument("--create", action="store_true", help="★雛形から作る")
    ap.add_argument("--where", action="store_true", help="★作る先を 1 行で出す")
    args = ap.parse_args(argv)

    if args.where:
        print(str(target_path()))
        return 0
    if args.check:
        print(guidance())
        return 0 if needs_config() else 1
    if args.create:
        made, why = create_from_template()
        print(why)
        return 0 if made else 1
    ap.error("--check / --create / --where のどれかを指定してください")
    return 2


__all__ = ["TEMPLATE_NAME", "template_path", "target_path", "needs_config",
           "create_from_template", "guidance", "main"]


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
