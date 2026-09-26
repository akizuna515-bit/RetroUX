"""ROM 由来の名前辞書への入口（RX3-0069 / 2026-09-03）。

★★ 名前は**ユーザーの ROM から実行時に**起こす。配布物には持たない ★★

```text
dq3rom/names.py      構造（bank / file / 幅 / 符号）と復号器
work/generated/       ★復号した名前の cache（⚠ Git の外 / ROM と decoder の版で鍵）
ここ                  製品側の入口。⚠ ROM が無くても**落ちない**
```

## ⚠ 画面読み（`enemies_seen` / `item_names`）との関係

★当面は**2 系統**です（指示書 §9）。

```text
画面で読めた名前   → 今までどおり覚える（★実機の証拠）
ROM の名前         → ⚠ 画面で読めていないときの**代わり**と、突き合わせの相手
一致              → 信頼が上がる（数える）
不一致            → ⚠⚠ 上書きしない。両方と番号を残す（`mismatches`）
```
"""
from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_ROM = _ROOT / "work" / "rom" / "DQ3_J.nes"

_cache: dict | None = None
_tried = False
last_error: str | None = None


def _load(rom_path=None) -> dict | None:
    """★1 度だけ読む。⚠ ROM が無い / 版が違うときは None（★黙らず `last_error` に残す）。"""
    global _cache, _tried, last_error
    if _tried and rom_path is None:
        return _cache
    _tried = True
    target = pathlib.Path(rom_path) if rom_path else DEFAULT_ROM
    if not target.exists():
        last_error = "ROM がありません: %s" % target
        _cache = None
        return None
    try:
        from dq3rom import names as N

        _cache = N.load_cached(target)
        last_error = None
    except Exception as exc:                       # noqa: BLE001 - ★理由を残して None
        last_error = "名前辞書を作れません: %s" % exc
        _cache = None
    return _cache


def available(rom_path=None) -> bool:
    return _load(rom_path) is not None


def _get(kind: str, entity_id, rom_path=None) -> str | None:
    data = _load(rom_path)
    if data is None or entity_id is None:
        return None
    return (data.get("names") or {}).get(kind, {}).get(str(int(entity_id)))


def monster(entity_id, rom_path=None) -> str | None:
    """★敵 id → 名前。⚠ 無ければ None。"""
    return _get("monster", entity_id, rom_path)


def item(entity_id, rom_path=None) -> str | None:
    """★品 id（★bit7 = 装備中 は落として渡す）→ 名前。"""
    if entity_id is None:
        return None
    return _get("item", int(entity_id) & 0x7F, rom_path)


def spell(entity_id, rom_path=None) -> str | None:
    return _get("spell", entity_id, rom_path)


_points: list | None = None
_points_tried = False


def place_maps(rom_path=None) -> list:
    """★ルーラの行き先の map 番号（⚠ 画面に並ぶ順）。★引けなければ空。"""
    global _points, _points_tried
    if _points_tried and rom_path is None:
        return list(_points or [])
    _points_tried = True
    target = pathlib.Path(rom_path) if rom_path else DEFAULT_ROM
    try:
        from dq3rom import profile as P
        from dq3rom import rura

        _points = rura.read_points(P.load_and_identify(target))
    except Exception:                              # noqa: BLE001 - ★無ければ黙って空
        _points = None
    return list(_points or [])


def place(index, rom_path=None) -> str | None:
    """★ルーラの並びの何番目か → 名前。"""
    return _get("place", index, rom_path)


def place_for_map(map_id, rom_path=None) -> str | None:
    """★map 番号 → 地名（⚠ ルーラの行き先 20 件だけ。★無ければ None）。

    ⚠⚠ ネタバレになるので、**行った場所にだけ**使うこと（★`LocationBook.enter`）。
    """
    if map_id is None:
        return None
    points = place_maps(rom_path)
    try:
        index = points.index(int(map_id))
    except ValueError:
        return None
    return place(index, rom_path)


def name(kind: str, entity_id, rom_path=None) -> str | None:
    """★共通の入口: (kind, id) → 名前。⚠ kind は monster / item / spell。"""
    if kind == "item":
        return item(entity_id, rom_path)
    if kind not in ("monster", "spell"):
        raise ValueError("kind は monster / item / spell: %r" % (kind,))
    return _get(kind, entity_id, rom_path)


def reset() -> None:
    """⚠ 検査用（★別の ROM / cache を読み直す）。"""
    global _cache, _tried, last_error, _points, _points_tried
    _cache, _tried, last_error = None, False, None
    _points, _points_tried = None, False
