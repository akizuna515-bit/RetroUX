"""画面の見え方（FCEUX の映像フィルタ）を起動前に当てる（RX-0140 / 2026-09-18）。

依頼者 2026-09-18:

    レトロ感だと pal3x だね。これにしよう。
    これの設定は ini ファイルから？それとも管理画面から？
    → ★管理画面から選ぶ / ⚠ `winspecial` の行だけ書き換えてよい

```text
選ぶ      管理画面「画面の見え方」      → work/dq3-ui-settings.json（emulator.video_filter）
当てる    scripts/start-dq3.ps1 が起動前に → tools/fceux/fceux.cfg の winspecial 行だけ
効く      ⚠ **次に FCEUX を起こしたときから**（★実行中は変えられない / RX-0108）
```

## ⚠⚠ なぜ `-cfg` ではなく同梱の cfg を書き換えるのか

★2026-09-18 に実測しました（RX-0108）。⚠ `-cfg <写し>` でフィルタを渡しても**効きません**
（フィルタ 0〜9 で撮った 10 枚が**バイト単位で同じ絵**でした）。
FCEUX は **exe の隣の `fceux.cfg`** を見ます（`dq3/testing/sandbox.py` の註と同じ話）。

⚠ このファイルは FCEUX 自身が終了時に書き戻す**可変ファイル**です。
★それでも触るのは `winspecial` の行**だけ**にします（⚠ 依頼者の許可もその 1 行）。

## ★選べるもの（⚠ 管理画面に出すのは 2 つだけ）

★10 種すべて撮って見比べた結果（`work/article/filters/` / RX-0108）:

```text
走査線      PAL 3x       ★これを採用（依頼者「レトロ感だと pal3x」）
にじみ      NTSC 2x      ⚠ 窓が横に広がる（903x672）→ 右画面の配置に影響するので出さない
丸み        hq2x / hq3x  ⚠ 好みが分かれるので出さない（★要ると言われたら足す）
Prescale    2x/3x/4x     ⚠⚠ `<none>` と**見分けが付かない**（★出す意味が無い）
```
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★同梱 FCEUX の固定フィルタ（⚠ `src/drivers/win/video.cpp` の並びそのもの / RX-0108）
FILTERS: dict[str, int] = {
    "<none>": 0, "hq2x": 1, "Scale2x": 2, "NTSC 2x": 3, "hq3x": 4,
    "Scale3x": 5, "Prescale2x": 6, "Prescale3x": 7, "Prescale4x": 8, "PAL 3x": 9,
}

#: ★管理画面に出す選択肢 `(設定に書く名前, 画面に出す文字, ヒント)`
#:
#:   ⚠ 増やすときは「実際に見分けが付くか」を撮って確かめてから（★RX-0108 の 20 枚）。
#:   ★2026-09-18 依頼者「動きは OK。スキャンラインは他も選べるようにして」→ **7 種**に広げた。
#:   ⚠⚠ `Prescale2x/3x/4x` は**出しません**（★撮り比べて `<none>` と**見分けが付かなかった**）。
#:     ⚠ 隠しているのではなく、★設定ファイルに名前を書けば当たります（下の `chosen`）。
#:   ⚠ 画面に出す文字は**短く**（★管理画面の右の列の幅が広がると左右の釣り合いが崩れる / RX3-0258）。
CHOICES: tuple[tuple[str, str, str], ...] = (
    ("<none>", "そのまま", "★素のドット（⚠ 拡大は最近傍）"),
    ("PAL 3x", "走査線", "★ブラウン管のような横線（PAL 3x）"),
    ("NTSC 2x", "にじみ", "★テレビのような色のにじみ（NTSC 2x）"
                          + chr(10) + "⚠⚠ 窓が**横に広がります**（903×672 / ★右画面の配置がずれます）"),
    ("hq2x", "丸み 強", "★輪郭を滑らかにする（hq2x / ⚠ ドットの角が消えます）"),
    ("Scale2x", "丸み 弱", "★角を少しだけ落とす（Scale2x）"),
    ("hq3x", "丸み 強・3 倍", "★hq3x（⚠ 窓の大きさは変わりません / hq2x と見分けにくい）"),
    ("Scale3x", "丸み 弱・3 倍", "★Scale3x（⚠ Scale2x と見分けにくい）"),
)

#: ⚠ 一覧に出さないが、設定ファイルに書けば当たるもの（★理由つき）
HIDDEN_REASON = {
    "Prescale2x": "⚠ `<none>` と見分けが付かない（★整数倍の前拡大だけ / RX-0108 で撮り比べ）",
    "Prescale3x": "⚠ 同上",
    "Prescale4x": "⚠ 同上",
}

#: ★既定（⚠ 設定が無ければ今までどおり素の画面）
DEFAULT = "<none>"

#: ★`work/dq3-ui-settings.json` の置き場所（⚠ 管理画面と起動スクリプトで同じものを見る）
SECTION, KEY = "emulator", "video_filter"

#: ★同梱 FCEUX の設定（⚠ 書き換えるのはこの行だけ）
CFG = ROOT / "tools" / "fceux" / "fceux.cfg"
CFG_KEY = "winspecial"


class VideoFilterError(ValueError):
    """⚠ 知らない名前。★黙って `<none>` に落とさない（「設定したのに効かない」を静かに起こさない）。"""


def number_of(name: str) -> int:
    """★名前 → `winspecial` の番号。⚠ 知らない名前は例外。"""
    if name in FILTERS:
        return FILTERS[name]
    raise VideoFilterError(
        "⚠ 知らないフィルタ名です: %r（★%s）" % (name, " / ".join(FILTERS)))


def label_of(name: str) -> str:
    """★画面に出す文字（⚠ 一覧に無い名前はそのまま返す）。"""
    return {n: label for n, label, _tip in CHOICES}.get(name, name)


def tip_of(name: str) -> str:
    """★その選択肢のヒント（⚠ 無ければ空）。"""
    return {n: tip for n, _label, tip in CHOICES}.get(name, "")


def chosen(settings) -> str:
    """★設定から選ばれている名前（⚠ 空・知らない値なら既定）。"""
    got = settings.get(SECTION, KEY, DEFAULT) if settings is not None else DEFAULT
    return got if got in FILTERS else DEFAULT


def apply_to_cfg(name: str, cfg_path: pathlib.Path | None = None) -> bool:
    """★`winspecial` の行だけ差し替える。戻り値は「書き換えたか」。

    ⚠⚠ **ほかの行は 1 バイトも変えません**（★`base64:` の行や改行を壊さないため、
      文字列ではなく**バイト列**のまま置き換えます）。
    ⚠ `winspecial` の行が無ければ何もしません（★行を足すと FCEUX の並びを崩しうる）。
    """
    number = number_of(name)
    path = pathlib.Path(cfg_path) if cfg_path else CFG
    raw = path.read_bytes()
    pattern = re.compile(rb"^" + CFG_KEY.encode() + rb"[ \t]+-?\d+", re.M)
    found = pattern.search(raw)
    if found is None:
        return False
    new = pattern.sub(("%s %d" % (CFG_KEY, number)).encode(), raw, count=1)
    if new == raw:
        return False
    path.write_bytes(new)
    return True


def main(argv=None) -> int:
    """★起動スクリプトから呼ぶ（⚠ 失敗しても起動は止めない = 見え方だけの話）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    from .ui.ui_settings import UiSettings

    name = argv[0] if argv else chosen(UiSettings())
    try:
        changed = apply_to_cfg(name)
    except (VideoFilterError, OSError) as err:
        print("⚠ 画面の見え方を当てられませんでした: %s" % err)
        return 1
    print("★画面の見え方: %s（%s %d）%s"
          % (label_of(name), CFG_KEY, number_of(name),
             "" if changed else " ⚠ 変更なし"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
