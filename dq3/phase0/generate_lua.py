"""Phase 0 の設定を Lua が読める形に落とす（RX3-0015 / 2026-08-25）。

★DQ2 の `retroux/core/config/generate_lua.py` と同じ作りにする（**import して使うだけ**）。

## ⚠ なぜ「語」ではなく「タイル列」を渡すのか

Lua 側に文字コード表を持たせて毎フレーム復号すると重い。
★判定に要るのは「その並びが画面にあるか」だけなので、
**あらかじめタイル番号の列に変換して**渡す。

    「たたかう」 →  1A 1A 10 0D      （★ネームテーブルの生バイト）

⚠ 変換の元は `dq3rom/profiles/` の文字コード表 1 か所だけ。
★Lua 側に同じ表を写さない（写すと片方だけ古くなる）。
"""

from __future__ import annotations

import json
import os
import pathlib

import yaml

from dq3 import ownership as _own
from dq3 import paths as P3
from dq3rom.screen import PATTERN_BASE, unvoice
from retroux.core.config.generate_lua import source_fingerprint, to_lua

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★★ 設定の正本（⚠⚠ **キー割り当ては利用者がここを直接書き換えます**）★★
#
#   ★**user 側にあればそれを読みます**（案 A / `RX3-0472` / 2026-10-01）:
#
#     <write_root>/work/user-data/config/dq3_phase0.yaml   ★在ればこちら
#     <program_root>/config/dq3_phase0.yaml                ★無ければ見本
#
#   ⚠ ファイルの冒頭に「GUI はありません。ここを直接書き換えてください」と
#     書いてあるので、★3 つの override 対象の中で**いちばん触られます**。
#   ⚠⚠ 配布 ZIP はこの見本を毎回入れ替えるので、★書き換えを残したい人は
#     user 側へ置いてください（⚠ 初回に自動で写しません）。
CONFIG = _own.lazy_resolve("config/dq3_phase0.yaml")
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
#: ★生成物の置き場（⚠ **write_root 側** / RX3-0466 / 2026-09-29）。
#
#   ⚠⚠ 以前は `ROOT / "work" / "generated"` でした。★program 側に書いていたので、
#     配布 Runtime では**書けない場所**を指していました。
#   ★`lazy_generated()` なので、⚠ 使う瞬間に `RETROUX_WRITE_ROOT` を引き直します
#     （既定引数に固めない / RX3-0215）。
OUT_DIR = P3.lazy_generated()
MODULE = "dq3_phase0"
NEWLINE = chr(10)


class GenerateError(ValueError):
    """⚠ 生成できなかった。★黙って空を書かない。"""


def tile_bytes(word: str, charset_table: dict[int, str]) -> list[int]:
    """語 → ネームテーブルの生バイト列。

    ⚠ 1 文字でも表に無ければ**例外**にする。★半分だけ一致する列を作らない。
    ⚠ 濁点は**上の行の別マス**なので、ここでは基底の文字だけを並べる。
    """
    reverse = {ch: code for code, ch in charset_table.items()}
    out = []
    for ch in word:
        # ⚠ 濁点つきは 1 マスに収まらない（★濁点は上の行の別マス）。
        #   ここでは**基底の文字**だけを並べる。判定はその行だけで足りる。
        base, _mark = unvoice(ch)
        code = reverse.get(base)
        if code is None and "ァ" <= ch <= "ヶ":
            # ★★ 字形の無いカタカナは、ゲームも**ひらがなの字**で出す（RX3-0193 / 2026-09-12）。
            #   ★会話の記録: 「アりアハン」「レーべ」「ロマりア」（⚠ 文字表に『リ』『ヘ』のカタカナが無い）。
            #   ⚠ 以前はここで例外になり、ベホイミ・ベホマ・キアリーを画面の字にできなかった
            #     （まんたんは生成で止まり、戦闘 AI は黙って空の並びにしていた）。
            base, _mark = unvoice(chr(ord(ch) - 0x60))
            code = reverse.get(base)
        if code is None:
            raise GenerateError(f"文字コード表に『{base}』がありません（{word}）")
        out.append(code - PATTERN_BASE)
    return out


#: ★1 人 1 バイトで並ぶ能力値（⚠ 画面と RAM で**並びが違う**ので名前で持つ）
STAT_KEYS = ("level", "strength", "agility", "wisdom", "luck", "stamina")

#: ★2 バイト刻みで並ぶ、装備から計算される値
DERIVED_KEYS = ("attack", "defence")


def _party(profile: dict) -> dict:
    """パーティの番地。⚠ profile に無ければ**空**を返す（★推測しない）。"""
    src = ((profile.get("runtime") or {}).get("party") or {})
    if not src:
        return {}
    keys = ("hp_current", "hp_max", "mp_current", "mp_max", "name")
    out = {k: int(str(src[k]), 16) for k in keys if k in src}
    # ★2026-08-29 に確定（依頼者の「つよさ」画面 2 枚と 12 項目が一致）
    for k in STAT_KEYS + DERIVED_KEYS + ("exp", "next_exp"):
        if k in src:
            out[k] = int(str(src[k]), 16)
    out["slots"] = int(src.get("slots", 4))
    out["entry_size"] = int(src.get("entry_size", 2))
    out["name_size"] = int(src.get("name_size", 4))
    out["stat_size"] = int(src.get("stat_size", 1))
    out["derived_stride"] = int(src.get("derived_stride", 2))
    out["exp_size"] = int(src.get("exp_size", 3))
    out["exp_stride"] = int(src.get("exp_stride", 3))
    # ★所持品（RX3-0076 / 2026-09-05）。⚠ profile に無ければ渡さない（★推測しない）
    if "items" in src:
        out["items"] = int(str(src["items"]), 16)
        out["item_slots"] = int(src.get("item_slots", 8))
    # ★職業と性別（RX3-0083 / 2026-09-06）。⚠ 下位 3 bit が職業 / bit3 が性別
    if "class_gender" in src:
        out["class_gender"] = int(str(src["class_gender"]), 16)
    # ★覚えている呪文の bit と状態（RX3-0125 / 2026-09-08）。⚠ 無ければ渡さない
    if "spells" in src:
        out["spells"] = int(str(src["spells"]), 16)
        out["spell_stride"] = int(src.get("spell_stride", 8))
    if "status" in src:
        out["status"] = int(str(src["status"]), 16)
        out["status_size"] = int(src.get("status_size", 2))
        # ★★ どのビットが何か（RX3-0135 / 2026-09-09）。
        #   ⚠⚠ **`confirmed` のものだけ**を渡します。★`inferred` を渡すと、
        #     日本版で裏の取れていない読み方で「麻痺だから外す」と判断してしまいます。
        #   → ★`auto_v0.lua` 側は「渡ってこない旗 = 分からない（nil）」として扱います。
        got = {}
        for name, row in (src.get("status_flags") or {}).items():
            if str((row or {}).get("confidence", "")) != "confirmed":
                continue
            got[name] = {"byte": int(row.get("byte", 0)), "bit": int(row.get("bit", 7))}
        if got:
            out["status_flags"] = got
    # ★次のレベルに要る**累計**（⚠ カートリッジ側の RAM。★残りは引き算で出す）
    out["next_exp_stride"] = int(src.get("next_exp_stride", 3))
    return out


#: ★居場所まわりの番地（⚠ 世界地図とローカルで座標が違う）
LOCATION_KEYS = ("kind", "world_x", "world_y", "local_x", "local_y",
                 "map_no", "map_width", "map_height", "oob_tile",
                 "map_buffer",
                 #: ★勇者の向き（⚠ 会話の相手を決めるのに使う / RX3-0133）
                 "facing")


def _location(profile: dict) -> dict:
    """いまどこに居るか。⚠ profile に無ければ**空**（★推測しない）。"""
    src = ((profile.get("runtime") or {}).get("location") or {})
    return {k: int(str(src[k]), 16) for k in LOCATION_KEYS if k in src}


def _no_magic(profile: dict) -> dict:
    """★★ 呪文がかき消される場所（RX3-0320 / 2026-09-20）。

    ⚠⚠ 依頼者「save9 呪文をかきけすダンジョンでは、呪文をつかわないようにしたい」。

    ★番号をここに**書き写しません**。⚠ `dq3rom/no_magic.py` が **ROM の判定の命令列**から
      読み出します（★1 か所に無ければ空 = 今までどおり動く）。

    ```text
    {"kind_mask": 1, "maps": {56: true, 195: true, ...}}
    ```
    ⚠ Lua で `maps[map_no]` と引けるように、★集合の形で渡します。
    """
    try:
        from dq3rom import no_magic as NMG
        from dq3.knowledge import terrain as T

        prg = T.TerrainSource()._identify().rom.prg
        got = NMG.read_rule(prg)
    except Exception:                                        # noqa: BLE001 - ★生成を止めない
        return {}
    if not got:
        return {}
    return {"kind_mask": int(got["kind_mask"]),
            "maps": {int(m): True for m in got["maps"]}}


def _battle_state(profile: dict) -> dict:
    """★戦闘の状態を読む番地（⚠ profile の `runtime.in_battle` / `dq3/battle_state.py` と同じ読み方）。"""
    from dq3 import battle_state as BS

    return BS.spec_from_profile(profile).as_lua()


#: ★窓の色で Lua が使う欄（★番地と、人へ返す 2 色 / RX3-0225）
WINDOW_COLOR_KEYS = ("address", "dead", "low_hp")


def _window_color(profile: dict) -> dict:
    """★窓の色（`$06E0` / RX3-0225）。⚠ profile に無ければ**空**（★Lua は battle_speed.lua の既定を使う）。

    ★ゲームが HP と状態から決めた色（`$27` オレンジ = 死者あり / `$2A` 緑 = HP 1/4 未満）で
      Auto を人へ返す。⚠ 決まりそのものは `tests/test_dq3_window_color.py` がセーブで見張る。
    """
    src = ((profile.get("runtime") or {}).get("window_color") or {})
    if "address" not in src:
        return {}
    return {k: int(str(src[k]), 16) for k in WINDOW_COLOR_KEYS if k in src}


def _battle_enemies(profile: dict) -> dict:
    """戦闘中の敵の番地。⚠ profile に無ければ**空**（★推測しない）。"""
    src = ((profile.get("runtime") or {}).get("battle_enemies") or {})
    if not src or "ids" not in src:
        return {}
    out = {
        "ids": int(str(src["ids"]), 16),
        "counts": int(str(src["counts"]), 16),
        "groups": int(src.get("groups", 4)),
        "empty": int(str(src.get("empty", "0xFF")), 16),
    }
    # ★個体ごとの HP と生存（RX3-0033 で確定 / ★戦闘 AI の内部判断だけに使う / RX3-0126）
    for key in ("hp_current", "status", "mp", "agility", "defense"):
        if key in src:
            out[key] = int(str(src[key]), 16)
    # ★RX3-0268: used_bit / group_shift = 群は状態の 1 バイト目の bit3-2（使用中は bit7）
    for key in ("hp_size", "hp_slots", "status_size", "alive_bit", "alive_byte", "defense_size",
                "used_bit", "group_shift"):
        if key in src:
            got = src[key]
            out[key] = int(str(got), 16) if isinstance(got, str) else int(got)
    # ★★ 敵の状態（RX3-0268）。⚠ **`confirmed` のものだけ**（★味方の status_flags と同じ作法）。
    #   ★渡らない旗は Lua 側で「分からない（nil）」になる（⚠ コードだけの 混乱・マホカンタ は渡さない）
    flags = {}
    for name, row in (src.get("status_flags") or {}).items():
        if str((row or {}).get("confidence", "")) != "confirmed":
            continue
        flags[name] = {"byte": int(row.get("byte", 0)), "bit": int(row.get("bit", 7))}
    if flags:
        out["status_flags"] = flags
    return out


def _gold(profile: dict) -> dict:
    """所持金の番地。⚠ 未確認なら**空**（★推測で出さない）。"""
    src = ((profile.get("runtime") or {}).get("gold") or {})
    if not src or "address" not in src:
        return {}
    return {"address": int(str(src["address"]), 16),
            "size": int(src.get("size", 2))}


def _rura(profile: dict) -> dict:
    """★ルーラで戻れる町の記録（`$0750` / RX3-0113）。⚠ 未確認なら**空**。

    ⚠⚠ **これは「ゲーム自身が持つ、行ったことのある町」です。**
      ★こちらの `visited_locations` と突き合わせて、取りこぼしに気づくために使います。
      ⚠ 中身（どの町か）を画面へ素で出してはいけません（★ROM の 20 件は全世界の地名）。
    """
    src = ((profile.get("runtime") or {}).get("rura") or {})
    if not src or "returnable" not in src:
        return {}
    if str(src.get("confidence", "")) != "confirmed":
        return {}                          # ⚠ 裏の取れていない番地は渡さない
    return {"address": int(str(src["returnable"]), 16),
            "stride": int(src.get("stride", 3)),
            "players": int(src.get("players", 4)),
            "bits": int(src.get("bits", 20))}


#: Phase 0 で押せるコマンド。⚠ ここに無いものは**押さずに止まる**
KNOWN_COMMANDS = ("attack", "defend", "spell")


def _commands(raw: dict, charset_table: dict[int, str]) -> dict:
    """設定のコマンドを Lua が使える形に正す。

    ★短く書ける形（`p1: attack`）と、細かく書く形の両方を受ける。
    ⚠ 知らないコマンドや、呪文名が表に無い文字を含む場合は**例外**にする。
      （★黙って attack に落とすと、利用者は気づけない）
    """
    out = {}
    for slot, spec in (raw or {}).items():
        if isinstance(spec, str):
            spec = {"primary": spec}
        if not isinstance(spec, dict):
            raise GenerateError(f"{slot} の書き方が分かりません: {spec!r}")
        item = {
            "primary": str(spec.get("primary", "attack")),
            "fallback": str(spec.get("fallback", "attack")),
            "min_mp": int(spec.get("min_mp", 0)),
            # ★HP がこの割合（%）を切ったら fallback へ。0 なら見ない
            "hp_below": int(spec.get("hp_below", 0)),
        }
        for key in ("primary", "fallback"):
            if item[key] not in KNOWN_COMMANDS:
                raise GenerateError(
                    f"{slot} の {key} が使えません: {item[key]}"
                    f"（使えるのは {'/'.join(KNOWN_COMMANDS)}）")
        if "spell" in item["primary"] or "spell" in item["fallback"]:
            name = spec.get("spell")
            if not name:
                raise GenerateError(f"{slot}: spell を使うなら `spell:` に呪文名が要ります")
            item["spell_tiles"] = tile_bytes(str(name), charset_table)
            # ★呪文の ID（⚠ 賢者の系統を決めるのに要る / RX3-0293）。
            #   ⚠ ROM が無い環境では引けない → ★そのときは系統の窓で押さずに止まる
            got = _spell_id(str(name))
            if got is not None:
                item["spell_id"] = got
        out[slot] = item
    return out


#: ★呪文の番号を探す範囲（⚠ DQ3 の呪文は 64 個ほど / ★余裕を見て 0x80）
SPELL_ID_MAX = 0x80


def _spell_id(name: str):
    """★呪文の名前 → 番号（★ROM の名前表 / ⚠ 引けなければ None）。"""
    try:
        from dq3.knowledge import rom_names as RN

        for sid in range(SPELL_ID_MAX):
            if RN.spell(sid) == name:
                return sid
    except Exception:                                            # noqa: BLE001 - ★生成を止めない
        pass
    return None

#: ★既定のキー（⚠ `Q` は FCEUX の「ムービー読み取り専用切替」で使えない）
#: ⚠⚠ `toggle_walk` は最初 `W` にしていましたが、**FCEUX が使っていました**
#:   （★依頼者 2026-08-31「W だとスナップショットセーブが走る」）。
#:   ⚠ FCEUX の割り当ては Lua から問い合わせられないので、★ぶつかったら
#:     ここを変えてください（`config/dq3_phase0.yaml` の `keys` でも変えられます）。
KEYS_DEFAULT = {"toggle_auto": "A", "toggle_turbo": "T", "mantan": "M",
                "toggle_walk": "K"}


def _keys(raw: dict) -> dict:
    """キー割り当て。★書かなかったものは既定を使う。

    ⚠⚠ **キーボードのキー**であって、ゲームの A ボタンではない。
    ★NES の A ボタンは `F`（2026-08-01 実機確認）。
    """
    out = dict(KEYS_DEFAULT)
    for k, v in (raw or {}).items():
        if v:
            out[k] = str(v)
    used = {}
    for k, v in out.items():
        if v in used:
            raise GenerateError(
                f"キーが重複しています: {v}（{used[v]} と {k}）")
        used[v] = k
    if "Q" in used:
        raise GenerateError(
            "⚠ Q は FCEUX の「ムービーの読み取り専用切替」に予約済みです")
    return out


def _auto_battle(raw: dict, charset_table: dict[int, str]) -> dict:
    out = dict(raw)
    out["commands"] = _commands(raw.get("commands"), charset_table)
    # ★レベルアップを**記録に残す**ためだけの語（⚠ 制御には使わない）
    #   ⚠ 名前のまま Lua へ渡すと画面と比べられないので、タイル列にする。
    text = out.get("level_up_text")
    if text:
        out["level_up_tiles"] = tile_bytes(str(text), charset_table)
    return out

def _story_flag_addresses() -> list[int]:
    """★物語の旗が居る番地（⚠ `data/dq3/story-flags.csv` が正本 / RX3-0297）。

    ⚠ 表が読めなければ**既定の 2 つ**（★`dev.lua` が前から読んでいたもの）。
      ★黙って 0 件にすると、⚠ 旗を 1 つも見なくなります。
    """
    fallback = [0x60B7, 0x60B8]
    try:
        from dq3.knowledge import story as ST

        got = sorted({int(f.address) for f in ST.load_flags()})
    except Exception:                                        # noqa: BLE001 - ★生成を止めない
        return fallback
    return got or fallback


#: ★系統の名前（⚠ profile に無いときの控え / `dq3rom/spell_flags.py` のブロックと同じ並び）
SPELL_FAMILIES = ("mage", "pilgrim")


def _spell_families(battle: dict, charset_table: dict[int, str]) -> dict:
    """★賢者の「系統を選ぶ窓」の語 → タイル列（RX3-0293）。

    ⚠ 語が読めなければ**入れない**（★Lua は系統の窓を見分けられず、押さずに止まる）。
    """
    raw = battle.get("spell_families") or {}
    out: dict[str, list[int]] = {}
    for key in SPELL_FAMILIES:
        name = raw.get(key)
        if not name:
            continue
        try:
            out[key] = tile_bytes(str(name), charset_table)
        except GenerateError:
            continue                    # ★字形の無い文字 → 押さずに止まるほうが安全
    return out


def _field(profile: dict, charset_table: dict[int, str]) -> dict:
    """フィールドのメニュー。★窓の位置と語のタイル列。

    ⚠ profile が正本。★ここでは Lua が使う形に直すだけ。
    """
    src = profile.get("field") or {}
    keywords = src.get("menu_keywords") or {}
    windows = {k: v for k, v in (src.get("windows") or {}).items()
               if not k.startswith("_")}
    return {
        "menu_tiles": {k: tile_bytes(v, charset_table)
                       for k, v in keywords.items()},
        "windows": windows,
    }


def _mantan(raw: dict, charset_table: dict[int, str]) -> dict:
    """まんたんの設定。★呪文名をタイル列に変換する。

    ⚠ 名前のまま Lua へ渡すと、画面と比べられない。
    """
    out = dict(raw)
    name = out.get("spell")
    if name:
        out["spell_tiles"] = tile_bytes(str(name), charset_table)
    # ★★ 道具（RX3-0174 / 2026-09-11 依頼者「まんたんで薬草・毒消し草を使わない」）。
    #   ★名前はタイル列で、道具番号は ROM の名前表から引く（⚠ 引けなければ既定の 101 / 102）
    herb, antidote = str(out.get("herb") or "やくそう"), str(out.get("antidote") or "どくけしそう")
    out["herb_tiles"] = tile_bytes(herb, charset_table)
    out["antidote_tiles"] = tile_bytes(antidote, charset_table)
    out["use_tiles"] = tile_bytes(str(out.get("use_word") or "つかう"), charset_table)
    out["herb_id"], out["antidote_id"] = _item_id(herb, 101), _item_id(antidote, 102)
    # ★★ まひ（RX3-0252 / 2026-09-13 依頼者「save7 まひを満タンで直したい。まんげつそう or キアリク」）。
    #   ★ROM bank 0 $B27B → $A09F（上位バイトの bit6 を落とす）。⚠ 引けなければ既定の 108
    moon = str(out.get("moon") or "まんげつそう")
    out["moon_tiles"] = tile_bytes(moon, charset_table)
    out["moon_id"] = _item_id(moon, 108)
    # ★★ まんたん v1（RX3-0161 / 0163 / 0162 / 2026-09-12）: 呪文ごとの名前の並び。
    #   ★Lua は選んだ呪文をこの並びで探す（⚠ 字形の無いカタカナも RX3-0193 で変換できる）
    out["spell_tiles_by_id"] = _spell_tiles(charset_table)
    return out


#: ★まんたん v1 が唱える呪文（★ベホマラーは v1.1 / 依頼者の判断）。⚠ 名前は ROM が先、これは控え
#: ★53 キアリク = まひを治す（RX3-0252）
MANTAN_SPELLS = {26: "ホイミ", 27: "ベホイミ", 28: "ベホマ", 52: "キアリー", 53: "キアリク"}


def _spell_tiles(charset_table: dict[int, str]) -> dict[int, list[int]]:
    """★呪文 ID → 画面の並び（⚠ 変換できない呪文は**入れない** = Lua は押さずに止まる）。"""
    out: dict[int, list[int]] = {}
    for sid, fallback in MANTAN_SPELLS.items():
        name = fallback
        try:
            from dq3.knowledge import rom_names as RN

            name = RN.spell(sid) or fallback
        except Exception:                                        # noqa: BLE001 - ★生成を止めない
            pass
        try:
            out[sid] = tile_bytes(str(name), charset_table)
        except GenerateError:
            continue
    return out


def _item_id(name: str, default: int) -> int:
    """★道具の名前 → 番号（★ROM の名前表 / ⚠ ROM が無い環境では既定）。"""
    try:
        from dq3.knowledge import item_info as II

        for item_id in range(128):
            got = II.info(item_id)
            if got is not None and got.name == name:
                return item_id
    except Exception:                                            # noqa: BLE001 - ★生成を止めない
        pass
    return default


def build(config_path: pathlib.Path = CONFIG,
          profile_path: pathlib.Path = PROFILE) -> dict:
    from retroux.core.text import Charset

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    phase0 = cfg.get("dq3_phase0") or {}
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    charset = Charset(profile.get("text"))
    if not charset.usable:
        raise GenerateError("profile に文字コード表がありません")
    battle = profile.get("battle") or {}
    keywords = battle.get("menu_keywords") or {}
    if not keywords:
        raise GenerateError("profile に戦闘メニューの語がありません")

    return {
        "schema_version": 1,
        # ★キー割り当て（⚠ DQ2 に合わせる。`Q` は FCEUX が予約済み）
        "keys": _keys(phase0.get("keys") or {}),
        "auto_battle": _auto_battle(phase0.get("auto_battle") or {},
                                    charset.table),
        "mantan": _mantan(phase0.get("mantan") or {}, charset.table),
        # ★聞き込み・街移動・補充の Turbo（RX3-0170 / `town_speed.lua`）
        "town_turbo": dict(phase0.get("town_turbo") or {}),
        # ★フィールドのメニュー（⚠ 実測。profile が正本）
        "field": _field(profile, charset.table),
        # ★判定に使うタイル列（生バイト）
        "menu_tiles": {k: tile_bytes(v, charset.table) for k, v in keywords.items()},
        # ★★ 賢者の「呪文の系統を選ぶ窓」の語（RX3-0293）。⚠ profile が正本
        #   ★この語が窓に出ていたら系統の窓（⚠ 職業から当てにいかない = 転職した人で外れる）
        "spell_family_tiles": _spell_families(battle, charset.table),
        "cursor_tile": int(str(battle.get("cursor_tile", "0x172")), 16) - PATTERN_BASE,
        # ★パーティの HP/MP（画面と RAM の突き合わせで特定）
        "party": _party(profile),
        "gold": _gold(profile),
        # ★ゲーム自身が持つ「戻れる町」（RX3-0113）。⚠ 突き合わせにだけ使う
        "rura": _rura(profile),
        "location": _location(profile),
        # ★★ 物語の旗の番地（RX3-0297 / 2026-09-19）。⚠ 正本は `data/dq3/story-flags.csv`
        #   ⚠⚠ 以前は `dev.lua` に**番地を直書き**していました。★表に足しても Lua が読まず、
        #     ⚠ 「立っているのに気づかない」が起きます（★この計画で何度も踏んだ「足し忘れ」の型）。
        "story_flags": _story_flag_addresses(),
        # ★★ 呪文がかき消される場所（RX3-0320）。⚠ 番号は ROM の判定から読み出す（★書き写さない）
        "no_magic": _no_magic(profile),
        # ★戦闘の状態を読む番地（RX3-0166 / DQ3 自身の式 `$32 == $FD かつ $60B7 & $20`）。
        #   ⚠⚠ 旧い `in_battle`（`$62` の番地）は渡しません（★戦闘中フラグではなかった / RX3-0165）。
        #   ★Lua の `battle_state.lua` がこれで既定を上書きする（⚠ profile が正本）。
        "battle_state": _battle_state(profile),
        # ★窓の色（RX3-0225）。★オレンジ / 緑になったら Auto を人へ返す（battle_speed.lua / auto_v0.lua）
        "window_color": _window_color(profile),
        "battle_enemies": _battle_enemies(profile),
        "columns": 32,
        "rows": 30,
        # ★★ 窓の枠のタイル（RX3-0016 / 2026-08-30）★★
        #
        #   ⚠⚠ **Lua に直書きしません。** `dq3rom/window.py` が正本です。
        #     ★この計画では「同じ判定を 2 か所に書いて片方だけ直っていた」
        #     を既に踏んでいます（2026-08-29 / 窓の見つけ方）。
        #
        #   ★Lua が使うのは「窓が出ているか」の**安い見分け**だけ。
        #     ⚠ 本当の切り出しは Python 側（`dq3rom.window`）が行います。
        "window": _window_tiles(),
    }


def _window_tiles() -> dict:
    """★枠のタイル（⚠ `dq3rom/window.py` から取る。ここで決めない）。"""
    from dq3rom import window as win

    return {
        "top_left": win.TOP_LEFT,
        "top_right": win.TOP_RIGHT,
        "bottom_left": win.BOTTOM_LEFT,
        "bottom_right": win.BOTTOM_RIGHT,
    }


def replace_when_ready(temp, out_path, tries: int = 40, wait: float = 0.05) -> None:
    """★`os.replace` を短く待って繰り返す（RX-0119 / 2026-09-03）。

    ⚠⚠ Windows は「置換先が**別のプロセスに開かれている**」と拒みます。
      ★8 worker で同じ 1 本を書くとき、これが 8 回に 1〜2 回起きていました。

    ```text
    PermissionError: [WinError 5] アクセスが拒否されました。
      work/generated/….lua.31184.tmp -> work/generated/….lua
    ```

    ⚠ 読んでいる側は**すぐ閉じる**ので、★少し待てば必ず通ります。
    """
    import time

    for _ in range(tries):
        try:
            os.replace(temp, out_path)
            return
        except PermissionError:
            time.sleep(wait)
    # ⚠ ここまで来たら一時的なものではない（★握りつぶさず投げる）
    os.replace(temp, out_path)


def same_text(out_path, body: str) -> bool:
    """★すでに同じ中身なら書かない（⚠ 取り合いをそもそも起こさない）。

    ⚠⚠ 8 worker は**同じ内容**を書きます。★書かなければぶつかりません。
    """
    try:
        return out_path.read_text(encoding="utf-8") == body
    except OSError:
        return False


def write_lua(data: dict, out_dir: pathlib.Path | P3.LazyPath = OUT_DIR,
              src: pathlib.Path = CONFIG) -> pathlib.Path:
    """Lua モジュールとして書き出す。

    ⚠ DQ2 の `write_lua_module` は見出しに DQ2 のパスを固定で書くので使わない。
    ★`to_lua` と `source_fingerprint`（どちらも純粋な関数）だけ借りる。

    ⚠ 既定の `OUT_DIR` は `LazyPath` です（★使う瞬間に書き先を引き直す / RX3-0466）。
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{MODULE}.lua"
    # ★★ ⚠⚠ **書きかけを読ませない**（RX-0114 / 2026-08-30）★★
    #
    #   ⚠ 検査を 8 並列で走らせると、複数の worker が**同じ瞬間に**
    #     ここを書きます。素朴に上書きすると、★Lua 側が
    #     **途中まで書かれたファイル**を読み、
    #     「乗っている機能が 1 件（2 のはず）」で落ちます（実際に踏んだ）。
    #
    #   ★自分の pid を付けた仮の名前で書いてから、⚠ **差し替え**ます。
    #     `os.replace` は同じドライブなら不可分です。
    body = ("-- 自動生成ファイル。直接編集しないこと。" + NEWLINE
            + f"-- 生成元: {src.relative_to(ROOT).as_posix()}" + NEWLINE
            + "-- 生成: python -m dq3.phase0.generate_lua" + NEWLINE
            + "--" + NEWLINE
            + "-- ★生成元の指紋。設定を変えたのに生成し忘れた状態を Lua 側で検出する。"
            + NEWLINE
            + f'local SOURCE_FINGERPRINT = "{source_fingerprint(src)}"' + NEWLINE
            + f"local DATA = {to_lua(data)}" + NEWLINE
            + "DATA.__source_fingerprint = SOURCE_FINGERPRINT" + NEWLINE
            + "return DATA" + NEWLINE)
    # ★中身が同じなら書かない（⚠ 8 worker の取り合いをそもそも起こさない / RX-0119）
    if same_text(out_path, body):
        return out_path
    temp = out_dir / f"{MODULE}.lua.{os.getpid()}.tmp"
    temp.write_text(body, encoding="utf-8")
    replace_when_ready(temp, out_path)
    return out_path


def main() -> int:
    data = build()
    path = write_lua(data)
    # ★RX3-0493: Lua は state.json を `work/runtime/` へ書く（⚠ Lua はフォルダを作れない）
    P3.runtime().mkdir(parents=True, exist_ok=True)
    tiles = " ".join(f"{b:02X}" for b in data["menu_tiles"]["attack"])
    print(f"→ {path}")
    print(f"  ★『たたかう』のタイル列: {tiles}")
    print(f"  ★カーソル: 0x{data['cursor_tile']:02X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
