"""地図に**出す中身を組み立てる**（2026-08-01 に `map_window.py` から分離 / §8.3）。

★★ **ここは widget を触らない。** ★★
  返すのは文字列と値だけ。並べるのは `window.py` の仕事です。

  ⚠ 触ってしまうと、「この文言で合っているか」を確かめるのに
    画面を建てる必要が出ます。いまは組み立てだけを直接呼べます。

## ⚠ 分離で1つだけ形を変えました

`_floor_text` は**文字列を作りながら、同時にラベルの色も当てて**いました。

```python
self._floor_note.setStyleSheet(warn if estimate.has_conflict else plain)
return f"階層: ..."
```

★`FloorText(text, warn)` を返す形にしました。**色を決めるのは画面**です。
⚠ 見え方は変わりません（食い違いのときだけ橙、は同じ）。

---

## 何をどこから取っているか

| もの | 出どころ | 確からしさ |
| --- | --- | --- |
| マップの大きさ・境界タイル | **ROM のヘッダ表**（`dq2rom maps export`） | 北米版と109/109一致 |
| いまのマップID・座標 | 実機の RAM（`$31` / `$16` / `$17`） | セーブステート10件で実測 |
| 見たマス | 遊んでいる間に貯めた記録（SQLite） | 観測＋画面の広さ |
| **地形（壁・扉・階段）** | ★**ROM のマップデータ**（`bgmap/`） | 実コードの写し |
| 世界地図の地形と色 | ★**ROM**（`bgmap/world_art.py`） | 実測と食い違い 0（2026-08-11） |

★2026-08-09 に街・ダンジョン、2026-08-11 に世界地図が ROM から描けるように
なりました（この表の「無い / 未解読」は**その前の記述**です）。

⚠⚠ **それでも、描くのは「見たマス」だけ**です（指示書 §2.2）。
  ROM から全部読めますが、行っていない所は開けません。
  ★ROM が用意するのは**絵**であって、**どこを見せるか**ではありません。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib


def load_map_meta(path) -> dict[int, dict]:
    """`dq2rom maps export` が出した `maps.json` を読む。

    ★無くても動く。無ければ大きさが分からないので、
      **歩いた範囲に合わせた枠**で描く（推測の大きさを出さない）。
    """
    if path is None:
        return {}
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for m in raw.get("maps") or []:
        try:
            out[int(m["map_id"])] = m
        except (KeyError, TypeError, ValueError):
            continue
    return out


@dataclasses.dataclass(frozen=True)
class FloorText:
    """階層の説明と、**目立たせるかどうか**。

    ⚠ 色そのものは持たない。色は画面の都合であって、中身の話ではない。
    """

    text: str
    warn: bool = False


@dataclasses.dataclass(frozen=True)
class MapDetail:
    """1つのマップについて、画面に出すもの一式。"""

    map_id: int
    map_ptr: int
    tiles: list
    width: int | None
    height: int | None
    kind: str
    label: str
    data_pointer: str
    search_term: str
    tile_ids: dict = dataclasses.field(default_factory=dict)
    """`{(x, y): タイルID}`。★絵で描くのに使う（2026-08-01 / 課題 #65）。"""
    metatiles: list = dataclasses.field(default_factory=list)
    """`[(x, y, 鍵, 回数, 確度)]`。★背景キャラクタで描く（2026-08-02）。

    ⚠ 空なら描画側が現行表示へ落ちる（**勝手に黒で埋めない**）。
    """
    source: str = "observed"
    """★地形の出どころ。`"rom"` なら ROM のマップデータ（2026-08-09）。"""
    note: str = ""
    """⚠ ROM を使えなかった理由。★黙って落ちない。"""
    outside_rom: int = 0
    """⚠ ROM の枠の外にあった記録の数。★黙って捨てない。

    ★記録側は `map.view_radius` ぶんの**見えている窓ごと**書くので、
      マップの端では枠からはみ出します。異常ではありません。
    """


class MapPresenter:
    """`view_model` から読んで、画面に出す形へ直す。

    ★`view_model` としか話さない。SQL も Qt も知らない。
    """

    #: 出どころの説明。★どれくらい信じてよいかを言葉で書く
    FLOOR_SOURCE = {
        "manual": "あなたが指定した値です（いちばん強い）",
        # ⚠ 2026-08-19: ROM 由来（確か）の根拠文言は**出さない**（依頼者）。
        #   ★出どころ・時点はデバッグ向けなので docs（map-decoder-evidence.md）へ。
        #   ⚠ 画面に出す文字列に `**` や `` ` `` を書かないこと（2026-08-09）。
        "binding": "",
        "inferred": "⚠ 上下移動から推定した値です（確かではありません）",
    }

    def __init__(self, view_model) -> None:
        self.vm = view_model

    def settings(self):
        """地図の描き方の設定（2026-08-12 / 監査 P0-A）。

        ⚠⚠ **渡っていなければ、いまの挙動のままにします。**
          ★`MapRenderSettings()` の既定は `rom_master` なので、
            設定を用意していない環境（古い ViewModel・テスト）でも
            地図の絵は消えません。
        ⚠ ここで「安全側だから observed」に落とすと、**直したつもりで
          地図が真っ黒に戻ります**。安全側の向きを間違えないこと。
        """
        got = getattr(self.vm, "map_render", None)
        if got is None:
            from ...core.bgmap.settings import MapRenderSettings

            got = MapRenderSettings()
        return got

    # --- 一覧 ---------------------------------------------------------

    def map_rows(self) -> tuple[list[tuple[int, int]], list[str]]:
        """行ったマップの `(キー一覧, 表示文字列一覧)`。"""
        visited = list(self.vm.visited_maps())
        keys = [(mid, ptr) for mid, ptr, _n in visited]
        counts = {(mid, ptr): n for mid, ptr, n in visited}
        rows = []
        for mid, ptr in keys:
            # ★大きさは `map_size` に聞く（ワールドマップは設定から補われる）
            w, h = self.vm.map_size(mid)
            size = f"{w}x{h}" if w and h else "?"
            kind = self.vm.map_type(mid) or ""
            mark = "" if self.vm.map_matches_pointer(mid, ptr) else "  ⚠食い違い"
            # ★地名が引けたら名前で出す。引けなければ ID だけ（推測しない）
            rows.append(f"{self.vm.map_label(mid, ptr)}  {size}  {kind}"
                        f"  見た {counts[(mid, ptr)]} マス{mark}")
        return keys, rows

    def summary_text(self, count: int) -> str:
        return f"行ったマップ {count} 件"

    # --- 世界地図（★ROM の絵で描く / 2026-08-11）------------------------

    def _world_assets(self, prg, live, map_id: int):
        """世界地図の材料。★一度だけ作って使い回す。⚠ 作れなければ理由。

        ⚠⚠ **描くたびに作り直さないこと。** `WorldArt` は 256×256 の
          ランレングス展開と壁向き補正で 0.3 秒かかります。
          ★`_draw()` は歩くたびに呼ばれるので、そこで作ると必ず引っかかります。
        """
        made = getattr(self, "_world_cache", None)
        if made is not None:
            return made, ""
        from ...core.bgmap import world_art as wa

        maptiles = live.source.for_map(map_id)
        if maptiles is None:
            why = live.source.why_not(map_id) or "⚠ 世界地図の絵の材料がありません"
            return None, f"⚠ {why}"
        art = wa.WorldArt(prg)
        colors = {i: wa.hex_color(c) for i, c in
                  wa.terrain_colors(prg, maptiles, live.nes_palette).items()}
        # ★16×16 の絵も用意しておく（★索引ごとに1枚。32 枚だけ）。
        #   ⚠ いまの倍率（×4）では並べられませんが、倍率を上げたときに
        #     `metatile_renderer` がそのまま使えます。
        keys = {}
        for index, (tiles, group) in art.entries.items():
            keys[index] = live.key_for(map_id, tiles, group)
        made = (art, colors, keys)
        self._world_cache = made
        return made, ""

    def world_layer(self, prg, live, map_id: int, map_ptr: int,
                    observed) -> dict:
        """世界地図を **ROM の地形と色**で組む（2026-08-11 / 依頼者の決定）。

        > 世界地図は「見た範囲だけ／色は ROM から」

        ★★ **黒塗りの根治** ★★
          ⚠ これまでは1マス1点、**画面の画素**を色にしていました。暗転や
            フェードの一瞬を拾ったマスは、そのまま黒く残ります（応急処置は
            `bridge.lua` の `_screen_looks_blank()`）。
          ★色を ROM から作れば、画面を見ないので原理的に黒く塗れません。

        ⚠⚠ **開示は増えません。** 返すのは `observed`（見たマス）だけです。
          ROM から全部読めますが、行っていない所は返しません（§2.2）。
        """
        from ...core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

        # ⚠ 切替の一瞬に別のマップのポインタで記録されたぶんは使わない
        #   （`view_model.map_matches_pointer` と同じ考え方）
        off = MAP_HEADER + map_id * MAP_HEADER_SIZE
        want = prg[off + 3] | (prg[off + 4] << 8)
        if map_ptr and want != map_ptr:
            return {"note": f"⚠ 世界地図のポインタは ${want:04X} のはずが "
                            f"${map_ptr:04X} でした（★切替の一瞬かも）"}

        made, why = self._world_assets(prg, live, map_id)
        if made is None:
            return {"note": why}
        art, colors, keys = made

        tiles, cells, outside, unreadable = [], [], 0, 0
        for x, y, visits, _color in observed:
            if not art.inside(x, y):
                outside += 1            # ⚠ 黙って捨てない。数えて画面に出す
                continue
            index = art.index[y][x]
            if index is None:
                # ⚠ 復号できなかったマス（★いまは 0 件。埋めない）
                unreadable += 1
                continue
            tiles.append((x, y, visits, colors[index]))
            key = keys.get(index)
            if key is not None:
                cells.append((x, y, key, 1, "confirmed"))
        if not tiles:
            return {"note": "⚠ 世界地図で歩いた記録がまだありません",
                    "outside": outside}
        return {
            "tiles": tiles,
            "metatiles": cells,
            # ★色は ROM から入れてある。⚠ 観測の色（黒塗りの元）は使わない
            "colored": True,
            "width": art.size,
            "height": art.size,
            "outside": outside,
            "note": (f"⚠ 復号できないマス {unreadable}" if unreadable else ""),
        }

    # --- 1つのマップ ---------------------------------------------------

    def rom_layer(self, map_id: int, map_ptr: int, observed) -> dict | None:
        """ROM のマップデータで1枚ぶん組む。⚠ 組めなければ理由を返す。

        ★★ なぜ要るのか（2026-08-09 / 依頼者の報告「城が真っ黒」）★★

          これまで地形は**画面のネームテーブルから読んだタイルID**で
          作っていました。⚠ 城の中ではその読みが空白タイル `F9` のまま
          動かず、**471 マス中 280 マスすべてが同じ絵**になっていました。
          ★同じ城を ROM のマップデータで見ると 19 種類の地形があります。

        ⚠⚠ **開示は増やしません。** 歩いた論理セルだけを返します（§2.2）。
          ROM から読めるからといって、行っていない所を開けません。

        ⚠ ポインタ食い違いでは組めません。★そのときは理由だけを
          返し、呼ぶ側はこれまでどおり観測の地図を使います。

        ★★ 世界地図は `world_layer()` へ回します（2026-08-11）★★
          ⚠ 復号の道が別（行ポインタ＋ランレングス＋壁向き補正）なので、
            `MapMaster` には**混ぜません**（`map_master.py` の SUPPORTED_KINDS）。
        """
        # ★★ 設定を通す（2026-08-12 / 監査 P0-A）★★
        #
        #   ⚠⚠ ここは設定を**1度も見ていませんでした**。`config.yaml` の
        #     `map.rom_master` を読む口（`core/bgmap/settings.py`）はあるのに、
        #     呼んでいたのはテストだけでした（`docs/audit/source-to-doc.md`）。
        #   ★`renderer: observed` にすれば、これまでの地図に戻せます。
        #   ⚠ 設定が渡っていない場合は**いまの挙動のまま**（ROM で描く）。
        #     ここで既定へ落として絵を消すと、直したつもりで劣化します。
        render = self.settings()
        if not render.uses_rom_master:
            return {"note": "★設定により現行表示にしています"
                            "（map.rom_master.renderer = observed）"}

        live = getattr(self.vm, "live_metatiles", None)
        if live is None:
            # ⚠ 絵の材料を作る係が居ない（ROM かパレットが無い環境）
            return None
        try:
            from ...core.bgmap import adapter, reader
            from ...core.bgmap.world_art import WORLD_MAP_ID

            prg = live.source.prg
        except Exception as exc:                        # noqa: BLE001
            # ⚠ 地図が出ないだけに留める。★本体は止めない
            return {"note": f"⚠ ROM を読めません: {exc}"}

        if map_id == WORLD_MAP_ID:
            return self.world_layer(prg, live, map_id, map_ptr, observed)

        resolution = adapter.resolve_map_master(prg, map_id, map_ptr)
        if not resolution:
            return {"note": resolution.detail}
        master = resolution.master
        span = reader.span_of(master)

        # ★★ 画面マス → 論理セル（2026-08-09 に実測で確かめた）★★
        #   ⚠ 記録側は `map.view_radius` ぶんの**見えている窓ごと**書くので、
        #     マップの端では枠からはみ出します。★異常ではないので数えるだけ。
        #   ★歩いた辺（MapEdge）12 マスが全て枠内の床・宝箱・階段に乗ることを
        #     確かめてあります（ずれていれば壁に散ります）。
        explored, outside = set(), 0
        for x, y, _visits, _color in observed:
            cx, cy = x // span, y // span
            if 0 <= cx < master.width and 0 <= cy < master.height:
                explored.add((cx, cy))
            else:
                outside += 1
        if not explored and not render.reveals_everything:
            return {"note": "⚠ このマップで歩いた記録がまだありません",
                    "outside": outside}

        # ★★ どこまで見せるか（2026-08-12 / 監査 P0-A で配線）★★
        #   ⚠⚠ 既定は**歩いたマスだけ**（指示書 §2.2）。ROM から読めても
        #     行っていない所は開けません。
        #   ★`reveal_mode: all` は**検証用**です（地図デコーダの答え合わせ）。
        #     ⚠ 探索を潰すので、遊ぶときに使うものではありません。
        layers = adapter.compose_static_layers(master)
        tiles = (layers if render.reveals_everything
                 else adapter.apply_exploration_mask(layers, explored))
        cells, missing = [], 0
        for t in tiles:
            # ★鍵を引くついでに、足りない PNG はここで作られる
            key = live.key_for(map_id, t.tile_ids, t.attribute)
            if key is None:
                missing += 1        # ⚠ 描けなかったぶんは黙って消さない
                continue
            cells.append((t.x, t.y, key, 1, "confirmed"))
        return {
            "metatiles": cells,
            # ★色は持たせない（ROM の絵で描くので、観測の色は主張させない）。
            #   ⚠ それでも枠の大きさと現在地の判定に要るので座標は渡す。
            "tiles": [(t.x, t.y, 1, None) for t in tiles],
            "width": master.screen_width,
            "height": master.screen_height,
            "outside": outside,
            "note": (f"⚠ 絵を作れなかったマス {missing}" if missing else ""),
        }

    def detail(self, map_id: int, map_ptr: int) -> MapDetail:
        """描くのに要るものをまとめて取る。"""
        meta = self.vm.map_meta.get(map_id) or {}
        # ★★ 大きさは `map_size`。ワールドマップのヘッダは $FF（=256）なので
        #   設定から補われる（実測 256×256）。記録側と同じ出口を使う。
        width, height = self.vm.map_size(map_id)
        resolved = self.vm.location_of_map(map_id)
        terms = resolved.search_terms() if resolved is not None else []
        observed = self.vm.visited_tiles(map_id, map_ptr)
        rom = self.rom_layer(map_id, map_ptr, observed)
        # ★`colored` は世界地図（2026-08-11）。1マス 4 画素では絵を並べられ
        #   ないので、**色だけ**が ROM 由来です。⚠ 絵が無くても ROM を使う
        if rom is not None and (rom.get("metatiles") or rom.get("colored")):
            # ★★ ROM のマップデータで描く（2026-08-09）★★
            #   ⚠ 見せるのは**歩いた論理セルだけ**（指示書 §2.2）。
            #     ROM にある地形を勝手に開きません。
            # ⚠⚠ **`note` を落とさない**（2026-08-14 / RX-0048）★★
            #   ここは `note=` を渡していなかったので、
            #   `rom_layer` が返す「⚠ 絵を作れなかったマス N」が
            #   **利用者にも記録にも届いていなかった**。
            #   ★絵が欠けていても「そういう地図」に見えてしまう。
            from ...core.logging_setup import get_logger

            get_logger("map").debug(
                "ROM の地図: map %02X ptr=0x%04X / 絵 %d マス"
                " / ⚠ 枠外 %d マス / %s",
                map_id, map_ptr, len(rom["metatiles"]), rom["outside"],
                rom.get("note") or "欠けなし")
            return MapDetail(
                map_id=map_id, map_ptr=map_ptr,
                tiles=rom["tiles"], width=rom["width"], height=rom["height"],
                note=rom.get("note", ""),
                kind=self.vm.map_type(map_id) or "?",
                label=self.vm.map_label(map_id, map_ptr),
                data_pointer=meta.get("data_pointer") or f"0x{map_ptr:04X}",
                search_term=terms[0] if terms else "",
                tile_ids={}, metatiles=rom["metatiles"],
                source="rom", outside_rom=rom["outside"])
        return MapDetail(
            map_id=map_id,
            map_ptr=map_ptr,
            tiles=observed,
            width=width,
            height=height,
            note=(rom or {}).get("note", ""),
            kind=self.vm.map_type(map_id) or "?",
            label=self.vm.map_label(map_id, map_ptr),
            data_pointer=meta.get("data_pointer") or f"0x{map_ptr:04X}",
            # ★一番当たりやすい語を出す。全部並べても長くて選べない
            search_term=terms[0] if terms else "",
            tile_ids=(self.vm.visited_tile_ids(map_id, map_ptr)
                      if hasattr(self.vm, "visited_tile_ids") else {}),
            # ★背景キャラクタ方式（2026-08-02）。⚠ 無ければ空のまま
            metatiles=(self.vm.visited_metatiles(map_id, map_ptr)
                       if hasattr(self.vm, "visited_metatiles") else []))

    def title_text(self, detail: MapDetail, zoom: int, outside: int,
                   beyond_rom=None) -> str:
        """見出し。★倍率と枠外の数は**描いてみないと分からない**ので受け取る。

        `beyond_rom` は「ROM が言う大きさより、実際はどれだけ広いか」。
        ⚠⚠ **黙って広げない**（2026-08-02 / 依頼者の報告）。
          ROM の値より広い所を歩いているのは事実なので、そう書く。
          ★ROM の正しい読み方が分かったら、この表示は出なくなる。
        """
        size = (f"{detail.width}×{detail.height} マス"
                if detail.width and detail.height else "大きさ不明")
        # ★枠の外の記録があれば**書く**（記録がずれている合図）。黙って捨てない
        note = f"　⚠ 枠の外 {outside} マス" if outside else ""
        if beyond_rom:
            dw, dh = beyond_rom
            note += (f"　⚠ ROM の値より広い（+{dw}×+{dh} マス。"
                     "ROM の読み方が未解明）")
        # ★★ 地形の出どころを**必ず書く**（2026-08-09）★★
        #   ⚠ 見た目が同じでも、ROM の地形と画面から拾った地形は別物です。
        #     どちらを見ているか分からないまま「地図が違う」と悩まないように。
        if detail.source == "rom":
            note = "　★ROM の地形" + note
            if detail.outside_rom:
                # ★はみ出しは記録側の窓の都合。異常ではないと分かるように書く
                note += (f"　（記録 {detail.outside_rom} マスは枠の外＝"
                         "見えていた窓のはみ出し）")
        if detail.note:
            note += f"　{detail.note}"
        return (f"{detail.label}（{detail.kind}）　{size}　"
                f"データ位置 {detail.data_pointer}　"
                f"見た {len(detail.tiles)} マス　拡大 ×{zoom}{note}")

    # --- 人が入れたもの -------------------------------------------------

    def marks_text(self, map_id: int, map_ptr: int) -> str:
        """メモと目印の要約。★**観測と混ぜない**ので別の欄に出す。"""
        notes = self.vm.notes(map_id, map_ptr)
        marks = self.vm.landmarks(map_id, map_ptr)
        if not notes and not marks:
            return "まだありません（Ctrl+M で、いま立っているマスに書けます）"
        parts = []
        if marks:
            from ...core.navigation.models import LANDMARK_LABELS, LandmarkKind

            counted: dict[str, int] = {}
            for row in marks:
                kind = LandmarkKind.parse(row.get("kind"))
                # ⚠ 読めない種類も**数に入れて出す**（黙って隠さない）
                name = (LANDMARK_LABELS[kind] if kind is not None
                        else f"⚠不明({row.get('kind')})")
                counted[name] = counted.get(name, 0) + 1
            parts.append("目印 " + " / ".join(
                f"{k}×{v}" if v > 1 else k for k, v in counted.items()))
        if notes:
            first = str(notes[0].get("body") or "").splitlines()[:1]
            head = first[0] if first else ""
            if len(head) > 30:
                head = head[:30] + "…"
            more = f"（ほか {len(notes) - 1} 件）" if len(notes) > 1 else ""
            parts.append(f"メモ {len(notes)} 件: 「{head}」{more}")
        return "　/　".join(parts)

    # --- つながり -------------------------------------------------------

    @staticmethod
    def kind_name(kind) -> str:
        """遷移の種類の日本語。★表は `models.py` の1箇所だけ（写さない）。

        ⚠ 読めない種類は**そのまま出す**（黙って「種類未判定」にすると、
          綴り違いに気づけない）。
        """
        from ...core.navigation.models import TRANSITION_LABELS, TransitionType

        parsed = TransitionType.parse(kind)
        if parsed is None:
            return f"⚠不明({kind})"
        return TRANSITION_LABELS[parsed]

    def links_text(self, map_id: int, map_ptr: int) -> str:
        """このマップから**行けた先**（★観測した先だけ）。

        ⚠ 2026-08-19: 見出しを「つながり」から「行けた先」へ（意味が伝わる語）。
          ★遷移の**種類が未判定**のときは種類を出さない（「種類未判定 →」は
          意味が無く煩雑 / 依頼者）。種類が分かっているときだけ添える。
        """
        from ...core.navigation.models import TransitionType

        found = self.vm.connections(map_id, map_ptr)
        if not found:
            return ("行けた先: まだ記録がありません"
                    "（★実際に通った所だけ出します）")
        parts = []
        for label, from_xy, kind in found[:6]:
            pos = f"（{from_xy[0]}, {from_xy[1]}）"
            # ★UNKNOWN（未判定）だけ種類を省く。★綴り違い（読めない種類）は
            #   `kind_name` が「⚠不明(...)」を出す＝気づける（黙って丸めない）。
            if TransitionType.parse(kind) == TransitionType.UNKNOWN:
                parts.append(f"{pos}→ {label}")
            else:
                parts.append(f"{pos}{self.kind_name(kind)} → {label}")
        more = f"　ほか {len(found) - 6} 件" if len(found) > 6 else ""
        return "行けた先: " + "　/　".join(parts) + more

    # --- 名前と階層の出どころ -------------------------------------------

    def name_source_text(self, map_id: int) -> str:
        """名前の出どころ。★確かでないものは**確かでないと書く**。"""
        resolved = self.vm.location_of_map(map_id)
        if resolved is None:
            return ("地名の辞書がありません（設定 locations.data_dir）。"
                    "マップは ID で出しています。")
        if not resolved.registered:
            return (f"⚠ このマップ（ID ${map_id:02X}）は地名の辞書にありません。"
                    "名前を推測して出さない方針です。")
        floor = resolved.floor_label
        floor_text = ("階層は分かっていません" if not floor
                      else f"階層 {floor} は **ROM 由来**なので確かです")
        if resolved.source == "rom":
            return f"名前は ROM の会話辞書から取りました（確か）。{floor_text}。"
        if resolved.source == "knowledge":
            # ⚠ QLabel は素のテキストを描くので、`**` や `` ` `` は
            #   **そのまま星印・記号として出ます**（2026-08-09 に画面で発覚）。
            #   ★強調は記号ではなく言葉で伝えます。
            return ("⚠ 日本語名は ROM から取っていません（ROM の辞書には"
                    "5語しか無いため）。間違っていたら "
                    "retroux/plugins/dq2/data/locations.yaml を直せます"
                    f"（表示だけ変わります）。{floor_text}。")
        return (f"⚠ 日本語名がありません。英名 `{resolved.location.name_en}` を"
                f"出しています。{floor_text}。")

    def room_text(self, map_id: int, map_ptr: int, here) -> str:
        """「いまの部屋」の1行（RX-0053 / 2026-08-21）。⚠ 出せないときは空文字。

        ★DQ2 のダンジョンは「入った区画（部屋）だけ見える」。その区画表は
          ROM にあり、展開規則は `core/bgmap/region_map.py`（2026-08-03 に確定）。
          ⚠ 2026-08-15 の時点で**UI から一度も呼ばれていなかった**（死んだコード）。
          依頼者「迷路で同じ部屋をぐるぐる、が分かるのは狙いに合う」→ 案 a で画面へ。

        ★RAM（`$1D`）は読まない。現在地の**論理セル**（物理 x,y ÷ span）で
          区画表を引く。⚠ 区画表が無いマップ・世界地図・現在地不明は空。
        ⚠ 区画番号は 3 ビットで**離れた部屋に使い回される**ので、
          「何マスの部屋か」は `rooms()`（つながったかたまり）で数える。
        """
        if here is None:
            return ""
        live = getattr(self.vm, "live_metatiles", None)
        if live is None:
            return ""
        try:
            from ...core.bgmap import adapter, reader, region_map
            from ...core.bgmap.world_art import WORLD_MAP_ID
            prg = live.source.prg
        except Exception:                               # noqa: BLE001
            return ""
        if map_id == WORLD_MAP_ID:
            return ""
        resolution = adapter.resolve_map_master(prg, map_id, map_ptr)
        if not resolution:
            return ""
        master = resolution.master
        try:
            regions = region_map.load(prg, master.map_id)
        except Exception:                               # noqa: BLE001
            return ""
        if not regions.has_data:
            return ""
        span = reader.span_of(master)
        cx, cy = int(here[0]) // span, int(here[1]) // span
        rid = regions.region_at(cx, cy)
        if rid is None:
            return ""
        if rid == region_map.CORRIDOR:
            return "🚪 いまの部屋: 通路"
        size = next((len(cells) for r, cells in regions.rooms()
                     if r == rid and (cx, cy) in cells), None)
        tail = f"（{size} マス）" if size else ""
        return f"🚪 いまの部屋: {rid} 番{tail}"

    def floor_text(self, map_id: int, map_ptr: int) -> FloorText:
        """階層とその出どころ。★食い違いは `warn=True` で返す。

        ⚠ **色は当てない**（分離前はここで `setStyleSheet` していた）。
          目立たせるかどうかだけを返し、色は画面が決める。
        """
        estimate = self.vm.floor_of_map(map_id, map_ptr)
        if estimate is None:
            return FloorText("")
        if not estimate.known:
            return FloorText("階層: 不明（材料がありません）。"
                             "★分かっているなら指定できます。")
        note = self.FLOOR_SOURCE.get(estimate.source, "")
        # ★根拠が無い（binding など）ときは末尾の空白を付けない
        text = f"階層: {estimate.display}　{note}" if note else f"階層: {estimate.display}"
        if estimate.has_conflict:
            # ⚠ どちらが正しいかは**こちらでは決めない**。人に決めてもらう
            text += ("　→ どちらが正しいか指定してください"
                     "（指定した値がいちばん強くなります）")
        elif estimate.reason and estimate.source == "inferred":
            text += f"　根拠: {estimate.reason}"
        return FloorText(text, warn=estimate.has_conflict)

    # --- 説明 -----------------------------------------------------------

    @staticmethod
    def shortcut_help() -> str:
        """キーの割り当て。★よく使う2つだけ（2026-08-19 / 依頼者）。

        ⚠ Ctrl+P（写真）・Ctrl+矢印（遷移の種類）は**出さない**（上級操作で、
          常時の案内としては煩雑）。機能は残っている。
        """
        return "キー: Ctrl+M=メモ　Ctrl+Shift+M=名前と階層"
