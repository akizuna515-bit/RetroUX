"""撮った戦闘画面から敵の絵だけを切り出す（2026-07-27）。

★★ 座標は**実測で決めた**（推測していない）★★

  `research/probes/archived/analyze_art.py` / `research/probes/archived/analyze_art2.py` で3枚の実写を測った結果:

    画面      256x224（FCEUX がオーバースキャンを落とした後の大きさ）
    背景      **純黒 (0,0,0)**
    パーティ枠 y 8..70 / x 33..174   ← 3枚で**完全に同じ画素**
    敵         y 80..127 のどこか     ← 下端が **127 に揃う**
    メッセージ枠 y 137..              ← 出ているときだけ

  | 画像 | 敵の行 | 敵の列 | メッセージ枠 |
  | --- | --- | --- | --- |
  | 0C キングコブラ | 96..127 | 114..143 | 137..151 |
  | 0F よろいムカデ | 104..127 | 16..231（★複数体） | 137..214 |
  | 12 リビングデッド | 80..126 | 33..174 | なし |

  -> **敵の帯は y 71..136**（パーティ枠の下、メッセージ枠の上）。
     この帯の中で黒でない画素の外接矩形を取れば敵の絵になる。

⚠ **「下から続く黒でない行をメッセージ枠と見なす」やり方は外した。**
  メッセージ枠が出ていない画像（12.png）では**敵そのものを枠と誤認**して
  帯が空になった。固定の帯を使うほうが正しい
  （メッセージ枠の位置は DQ2 では動かない）。

⚠ 複数体が並んでいる絵は図鑑に向かない。**撮る側で1体の戦闘に限る**
  （`config.yaml` の `monster_art.single_individual_only`）。
  ここでは切り出すだけで、体数の判断はしない。
"""

from __future__ import annotations

from dataclasses import dataclass

# 敵が描かれる帯（実測 / 上の表を参照）。**この外は切り出しに使わない。**
BAND_TOP = 71
BAND_BOTTOM = 136

# 背景。DQ2 の戦闘画面は純黒
BACKGROUND = (0, 0, 0)

# 切り出しの周りに残す余白（画素）。0 だとぴったり過ぎて窮屈に見える
MARGIN = 2

# 体と体の境目と見なす黒い列の幅（画素）。
# ★FC のタイルは8pxなので1タイルぶんを目安にする。
#   ⚠ これ未満の隙間は**同じ体の一部**として繋げる（脚の間などがある）。
#     実測で合わなければ work/analyze_art3.py で確かめてから変える。
MIN_GAP = 8

# 期待する画面の大きさ。★違ったら切り出さない（前提が崩れている）
EXPECT_W, EXPECT_H = 256, 224


@dataclass
class TrimResult:
    """切り出しの結果。`ok` が False なら理由が `reason` に入る。"""

    ok: bool
    reason: str = ""
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0


def column_blobs(pixels, width: int, top: int, bottom: int,
                 background=BACKGROUND, min_gap: int = MIN_GAP
                 ) -> list[tuple[int, int]]:
    """帯の中を「黒でない列のかたまり」に分ける（左から順）。

    ★★ **同じ種が複数体並んでいても1体だけ切り出せる** ★★

      よろいムカデ3体のキャプチャは x 16..231（幅216px）だった。
      外接矩形で切ると3体の集合写真になる。
      ⚠ しかし**体の間には黒い列がある**ので、そこで分ければ1体になる。

    ★`min_gap` 未満の隙間は**同じ体の一部**として繋げる。
      敵の絵の中にも黒い列はあり得る（脚の間など）。
      FC のタイルは8px なので、1タイルぶんを境目の目安にする。
      ⚠ この値は**実測で決める**もの。合わなければ切り分けが崩れるので、
        `work/analyze_art3.py` で確かめてから変える。
    """
    filled = [any(pixels[y][x] != background for y in range(top, bottom + 1))
              for x in range(width)]

    blobs: list[list[int]] = []
    for x, on in enumerate(filled):
        if on:
            if blobs and x - blobs[-1][1] - 1 < min_gap:
                blobs[-1][1] = x          # 隙間が狭いので同じかたまり
            else:
                blobs.append([x, x])
    return [(a, b) for a, b in blobs]


def find_sprite(pixels, width: int, height: int,
                background=BACKGROUND, min_gap: int = MIN_GAP) -> TrimResult:
    """敵**1体**の外接矩形を返す。`pixels[y][x]` は (r, g, b)。

    ★見つからなければ**切り出さない**（`ok=False`）。
      無理に切ると、真っ黒な画像や枠の切れ端を図鑑に載せることになる。

    ★複数体並んでいたら**左端の1体**を取る（`column_blobs` を参照）。
      どれを取っても同じ絵なので、いちばん端＝隣と重なりにくいものを選ぶ。
    """
    if (width, height) != (EXPECT_W, EXPECT_H):
        # ★画面の大きさが違う＝オーバースキャンの設定などが違う。
        #   実測した座標が当てにならないので手を出さない。
        return TrimResult(False, f"画面の大きさが想定と違う（{width}x{height}）")

    top = max(BAND_TOP, 0)
    bottom = min(BAND_BOTTOM, height - 1)

    blobs = column_blobs(pixels, width, top, bottom, background, min_gap)
    if not blobs:
        return TrimResult(False, "帯の中に敵が見つからない（演出中か画面が違う）")

    left, right = blobs[0]

    # その列の範囲だけで行の範囲を出す（他の体の高さを巻き込まない）
    ys = [y for y in range(top, bottom + 1)
          if any(pixels[y][x] != background for x in range(left, right + 1))]
    up, down = min(ys), max(ys)

    # 余白を足す（帯と画面の外へは出さない）
    left = max(0, left - MARGIN)
    right = min(width - 1, right + MARGIN)
    up = max(top, up - MARGIN)
    down = min(bottom, down + MARGIN)

    return TrimResult(True, f"{len(blobs)}体ぶん検出（左端を採用）" if len(blobs) > 1
                      else "", left, up, right - left + 1, down - up + 1)


def parse_ids(stem: str) -> list[int]:
    """raw のファイル名から敵IDの並びを読む。

    ★★ ファイル名が**画面の並び順**を持つ ★★

      `0C.png`          -> [0x0C]              1種（何体でも）
      `12-06-06.png`    -> [0x12, 0x06, 0x06]  画面の左から この順

      `memory_map` の `enemy_ids`（`$0162`）は
      「**画面上の並び順どおりに**1バイトずつ格納する配列」なので、
      その並びをそのままファイル名にしてある。

    ⚠ 読めない名前は空を返す（**推測で当てない**）。
    """
    out = []
    for part in stem.split("-"):
        part = part.strip()
        if len(part) != 2:
            return []
        try:
            out.append(int(part, 16))
        except ValueError:
            return []
    return out


def trim_new(raw_dir, out_dir) -> list[tuple[str, TrimResult]]:
    """raw から敵の絵を切り出す。**まだ絵が無い敵のぶんだけ**。

    ★**新しいものだけ**触る。GUI の更新（0.5秒ごと）から呼ばれても、
      毎回83枚読み直したりしない。

    ★raw は消さない。切り出しの規則を直したら出力側を消して呼び直せば
      **撮り直さずに**やり直せる（実機の撮影は何度もやり直せない）。
    """
    import pathlib

    raw_dir = pathlib.Path(raw_dir)
    out_dir = pathlib.Path(out_dir)
    if not raw_dir.is_dir():
        return []
    out_dir.mkdir(parents=True, exist_ok=True)

    done = []
    for src in sorted(raw_dir.glob("*.png")):
        ids = parse_ids(src.stem)
        if not ids:
            done.append((src.name, TrimResult(False, "ファイル名から敵IDを読めない")))
            continue
        # ★この raw で埋められる敵が1つも残っていなければ触らない
        if all((out_dir / f"{i:02X}.png").exists() for i in ids):
            continue
        done.append((src.name, split_file(src, out_dir, ids)))
    return done


def split_file(src, out_dir, ids: list[int]) -> TrimResult:
    """1枚の画面から、写っている敵を**それぞれの絵**として切り出す。

    ★★ ここが「複数種の戦闘でも図鑑を埋められる」中身 ★★

      画面のかたまりを左から数え、**数が体数と一致したときだけ**
      i 番目のかたまりを `ids[i]` の絵として保存する。

    ⚠⚠ **一致しないときは何もしない。** 敵の絵の中に MIN_GAP 以上の
      黒い列があるとかたまりが増え、対応がずれる。
      ずれたまま保存すると**違う敵の絵を図鑑に載せる**ことになる。
      「分からないときは動かない」（playbook #14 と同じ方針）。

    ★1種だけのときは例外で、**左端のかたまり**を使う。
      同じ絵が並んでいるだけなので、数が合わなくても取り違えようがない。
    """
    import pathlib

    from PySide6.QtGui import QImage

    out_dir = pathlib.Path(out_dir)
    img = QImage(str(src))
    if img.isNull():
        return TrimResult(False, f"読めない: {src}")
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    if (w, h) != (EXPECT_W, EXPECT_H):
        return TrimResult(False, f"画面の大きさが想定と違う（{w}x{h}）")

    pixels = []
    for y in range(h):
        pixels.append([(lambda c: (c.red(), c.green(), c.blue()))(img.pixelColor(x, y))
                       for x in range(w)])

    top, bottom = BAND_TOP, min(BAND_BOTTOM, h - 1)
    blobs = column_blobs(pixels, w, top, bottom)
    if not blobs:
        return TrimResult(False, "帯の中に敵が見つからない（演出中か画面が違う）")

    kinds = sorted(set(ids))
    if len(kinds) == 1:
        # 1種だけ。左端を使う（数が合わなくても取り違えない）
        targets = [(blobs[0], kinds[0])]
    elif len(blobs) == len(ids):
        targets = list(zip(blobs, ids))
    else:
        # ★ずれている。**何もしない**（次に会ったときにまた撮れる）
        return TrimResult(
            False,
            f"かたまり {len(blobs)} 個と体数 {len(ids)} が合わないので切り出さない")

    saved = 0
    last = TrimResult(False, "保存できるものが無かった")
    for (left, right), monster_id in targets:
        dst = out_dir / f"{monster_id:02X}.png"
        if dst.exists():
            continue
        ys = [y for y in range(top, bottom + 1)
              if any(pixels[y][x] != BACKGROUND for x in range(left, right + 1))]
        if not ys:
            continue
        x0 = max(0, left - MARGIN)
        x1 = min(w - 1, right + MARGIN)
        y0 = max(top, min(ys) - MARGIN)
        y1 = min(bottom, max(ys) + MARGIN)
        if not img.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1).save(str(dst)):
            return TrimResult(False, f"書けない: {dst}")
        saved += 1
        last = TrimResult(True, f"{len(blobs)}体から {saved} 種を切り出した",
                          x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    return last if saved else TrimResult(False, "すでに全部そろっている")


def trim_file(src, dst) -> TrimResult:
    """PNG を読んで敵だけを切り出し、別の PNG に書く（Qt を使う）。

    ★元の画像は残す。切り出しの規則を直したときに撮り直さずに済む
      （実機での撮影は何度もやり直せない）。
    """
    from PySide6.QtGui import QImage

    img = QImage(str(src))
    if img.isNull():
        return TrimResult(False, f"読めない: {src}")
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()

    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            c = img.pixelColor(x, y)
            row.append((c.red(), c.green(), c.blue()))
        pixels.append(row)

    got = find_sprite(pixels, w, h)
    if not got.ok:
        return got

    cropped = img.copy(got.left, got.top, got.width, got.height)
    if not cropped.save(str(dst)):
        return TrimResult(False, f"書けない: {dst}")
    return got
