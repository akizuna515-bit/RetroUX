"""敵のデータ表を利用者の ROM から起こして `memory_map` に足す（RX-0090 / 2026-08-21）。

## 何をするか

`memory_map.yaml` には **敵の表が入っていない**（名前・ステータス・行動・
ドロップ・経験値表）。それらは利用者の ROM に入っているデータなので、
起動のたびにここで ROM から読み、`memory_map` の辞書に**同じキー名で**足す:

    monsters / monster_stats / monster_behavior / action_rates / exp_to_level

読む側（`gui.py`・`record.py`・`generate_lua.py`）は以前と同じキーを見るだけ。

## キャッシュ（`work/generated/enemy_tables.json`）

ROM の PRG sha256 を添えて JSON に置く。次回以降は ROM を読み直さない。
- ROM があり sha が違えば読み直す（ROM を差し替えた）。
- ⚠ **ROM が無くてもキャッシュがあればそれを使う**（以前この環境で読めた値）。
- ROM もキャッシュも無ければ **何も足さない**。図鑑は「データがありません」、
  Lua 側は `未知(0x..)` と耐性不明（効くと決めない）の劣化動作になる
  （★それぞれ以前から用意されていた道。0 を入れてごまかさない）。

## ⚠ 起動を止めない

読めなくても例外を外へ出さない。理由を 1 行出して進む（絵の展開と同じ方針。
`retroux/tools/monster_art_setup.py`）。ROM が別物のときは `dq2rom.enemies.verify`
が値の辻褄で止め、**嘘の表を足さない**。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from dq2rom import enemies, ines

from . import rom as rom_mod
from . import text as text_mod

log = logging.getLogger("retroux.enemy_tables")

ENEMY_KEYS = ("monsters", "monster_stats", "monster_behavior", "action_rates", "exp_to_level")
CACHE_NAME = "enemy_tables.json"
CACHE_SCHEMA = 1


def decode_names(name_bytes: dict[int, bytes], charset: text_mod.Charset) -> dict[int, str]:
    """ID → 名前。読めない文字が混ざった名前は**入れない**（`未知(0x..)` 表示に落ちる）。"""
    out: dict[int, str] = {}
    for mid, raw in name_bytes.items():
        if mid == 0:
            continue                        # ID 0 は空エントリ
        s, unknown = charset.decode(raw)
        s = s.replace("␣", " ").strip()
        if s and not unknown:
            out[mid] = s
    return out


def extract(rom_path: Path, memory_map: dict) -> tuple[dict, str]:
    """ROM から5表を読む。戻り値 (表, PRG sha256)。問題があれば ValueError。"""
    rom = ines.load(rom_path)
    tables = enemies.read_all(rom.prg)
    problems = enemies.verify(rom.prg, tables)
    if problems:
        raise ValueError("ROM の敵データの辻褄が合いません: " + " / ".join(problems))
    charset = text_mod.from_memory_map(memory_map)
    if not charset.usable:
        raise ValueError("memory_map.yaml に text:（文字コード表）がありません")
    names = decode_names(tables.pop("monster_name_bytes"), charset)
    if len(names) < enemies.MONSTER_COUNT:
        raise ValueError(f"名前を読めたのが {len(names)}/{enemies.MONSTER_COUNT} 体")
    tables["monsters"] = names
    sha = rom_mod.identify(rom_path).prg_sha256
    return tables, sha


# --- キャッシュ -----------------------------------------------------------------

def _to_json(tables: dict) -> dict:
    # JSON のキーは文字列になる。読む側で int に戻す（exp_to_level は 2 段）。
    return {k: tables[k] for k in ENEMY_KEYS}


def _from_json(data: dict) -> dict:
    out: dict = {}
    for k in ENEMY_KEYS:
        if k not in data:
            raise ValueError(f"キャッシュに {k} が無い")
        if k == "exp_to_level":
            out[k] = {h: {int(lv): int(v) for lv, v in rows.items()} for h, rows in data[k].items()}
        else:
            out[k] = {int(i): v for i, v in data[k].items()}
    return out


def read_cache(path: Path) -> tuple[dict, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != CACHE_SCHEMA:
            return None
        return _from_json(data["tables"]), str(data["prg_sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_cache(path: Path, tables: dict, sha: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": CACHE_SCHEMA, "prg_sha256": sha,
            "note": "RetroUX が利用者の ROM から読んだ敵データ。消せば次回の起動で作り直す。",
            "tables": _to_json(tables)}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")


# --- 入口 ---------------------------------------------------------------------

def resolve(rom_path: Path | None, memory_map: dict, cache_path: Path) -> tuple[dict | None, str]:
    """表を決める（★純ロジックに近い層。I/O の失敗はここで飲んで理由を返す）。

    戻り値 (表 or None, 1行の説明)。
    """
    cached = read_cache(cache_path)
    rom_ok = rom_path is not None and Path(rom_path).is_file()
    if rom_ok:
        try:
            sha = rom_mod.identify(rom_path).prg_sha256
        except (OSError, ValueError) as exc:
            sha = None
            rom_err = str(exc)
        if sha is not None:
            if cached is not None and cached[1] == sha:
                return cached[0], "敵データ: キャッシュを使用"
            try:
                tables, sha = extract(Path(rom_path), memory_map)
            except (OSError, ValueError) as exc:
                rom_err = str(exc)
            else:
                try:
                    write_cache(cache_path, tables, sha)
                except OSError as exc:
                    log.warning("敵データのキャッシュを書けません: %s", exc)
                return tables, f"敵データ: ROM から読みました（{len(tables['monsters'])} 体）"
        if cached is not None:
            return cached[0], f"敵データ: ROM を読めないため前回のキャッシュを使用（{rom_err}）"
        return None, f"敵データ: ROM を読めません（{rom_err}）。図鑑と耐性は不明のまま動きます"
    if cached is not None:
        return cached[0], "敵データ: ROM が無いため前回のキャッシュを使用"
    return None, "敵データ: ROM が無いため読めません。★ROM を置けば次回の起動で読みます"


def attach(memory_map: dict, rom_path: Path | None, cache_path: Path) -> dict:
    """`memory_map` に5表を足して返す（無理なら足さず、理由をログに1行）。"""
    tables, why = resolve(rom_path, memory_map, cache_path)
    log.info(why)
    if tables is not None:
        for k in ENEMY_KEYS:
            memory_map[k] = tables[k]
    return memory_map
