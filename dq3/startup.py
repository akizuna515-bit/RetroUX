"""起動の 1 行目に版と断面を残す（RX3-0464 / 2026-09-29）。

## ⚠⚠ なぜ要るか

★2026-09-29 の実測で、**DQ3 は実行中に版を知る手段が 1 つもありませんでした**。

```text
DQ2   ★題名 "RetroUX 1.1.0 — ドラゴンクエストII"（retroux/ui/main_window.py:315）
      ★起動ログ 1 行目に VERSION（retroux/gui.py:567-570）
DQ3   ⚠⚠ 題名は "RetroUX DQ3" 固定 / ⚠⚠ 起動バナーが無い（logging の初期化も無い）
```

⚠ 版が出ないと、実機で見てもらった報告が**どの断面のものか後から決められません**。

## ★なぜ `events/writer.py` を通さないのか

⚠⚠ あちらは `FM.stamped()` が **None を返すと 1 行も出ません**（★知らない種類の
Event は捨てられる）。⚠ 起動バナーは「出ないと困るもの」なので、
★短絡の陰に置かず、ここで**直に**書きます（`ProductLogSink` と同じ置き場・同じ作法）。

⚠ 改行は LF 固定（★`open(..., "a")` の既定は環境で変わる / RX-0121）。
"""

from __future__ import annotations

import datetime
import pathlib

from dq3 import paths as P3

#: ★出す先（⚠ `dq3/events/writer.py` の `product.log` と同じもの）
LOG_PATH = P3.lazy_runtime("dq3-log", "product.log")

#: ★画面と記録で同じ名前を使う（⚠ 2 か所に書き分けない）
PREFIX = "RetroUX DQ3"


def stamp() -> str:
    """★`RetroUX DQ3 1.1.0 / build edc273a`（⚠ 版が読めなければ `0.0.0+unknown`）。"""
    from retroux import version as V

    return V.stamp(PREFIX)


def title() -> str:
    """★窓の題名（例 `RetroUX DQ3 1.1.0`）。⚠ 断面は題名に出さない（長い）。"""
    from retroux import version as V

    return V.title(PREFIX)


def log_startup(path=None, *, extra: str = "") -> str:
    """★起動を 1 行残す（⚠ 書けなくても起動は止めない）。戻り値はその 1 行。

    ⚠⚠ 画面の無い起動（`pythonw`）では標準出力が捨てられます。
      ★だから**記録にも**書きます（両方）。
    """
    line = "%s %s" % (
        datetime.datetime.now().isoformat(timespec="seconds"), stamp())
    if extra:
        line = "%s（%s）" % (line, extra)
    try:
        target = pathlib.Path(path if path is not None else LOG_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8", newline="") as fh:
            fh.write(line + "\n")
    except OSError:
        pass                                    # ⚠ 記録できなくても起動は続ける
    return line


def notices() -> list[str]:
    """★起動のときに**知らせるだけ**のこと（RX3-0472 / 2026-10-01）。

    ```text
    ① ⚠⚠ 前の引き継ぎが途中で終わっている（`work/.migration-incomplete` が残っている）
    ② ★カスタマイズ版を使っていて、見本（標準版）が更新されている
    ```

    ⚠⚠ **どちらも何も直しません。** ★①は利用者がもう一度引き継ぎを実行すれば済み、
      ②は自動 merge をしない方針です（依頼者 2026-09-30 / `D-38`）。
    ⚠ 読めなくても起動は止めません（★知らせが出ないほうが害が小さい）。
    """
    out: list[str] = []
    try:
        from dq3 import migrate as MG
        from dq3 import ownership as OWN

        stuck = MG.pending()
        if stuck:
            out.append("⚠⚠ 前回の引き継ぎが途中で終わっています"
                       "（★移行元: %s / もう一度実行してください）"
                       % (stuck.get("source") or "⚠ 不明"))
        out += OWN.master_update_notices()
    except Exception:                               # noqa: BLE001
        pass                                        # ⚠ 知らせで起動を止めない
    return out


def log_notices(path=None) -> list[str]:
    """★`notices()` を記録にも残す（⚠ `pythonw` では標準出力が捨てられる）。"""
    got = notices()
    if got:
        try:
            target = pathlib.Path(path if path is not None else LOG_PATH)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8", newline="") as fh:
                for line in got:
                    fh.write("%s %s\n" % (
                        datetime.datetime.now().isoformat(timespec="seconds"),
                        line))
        except OSError:
            pass                                    # ⚠ 記録できなくても起動は続ける
    return got


__all__ = ["LOG_PATH", "PREFIX", "stamp", "title", "log_startup",
           "notices", "log_notices"]
