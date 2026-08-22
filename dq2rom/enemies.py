"""敵のデータ表を ROM から読む（RX-0090 / 2026-08-21）。

## なぜ ROM から読むのか

以前は `retroux/plugins/dq2/memory_map.yaml` に敵83体の名前・ステータス・
行動・ドロップ・経験値表を**数値のまま同梱**していた。それらは利用者の
ROM に入っているデータそのもので、公開 Repo に複製を置く必要が無い
（権利面でいちばん大きいグレーだった）。ここでは**読み方だけ**を持ち、
値は実行時に利用者の ROM から起こす。

## 位置と形（すべて日本版 ROM の PRG 内オフセット。ヘッダ 16 バイトを除く）

根拠はすべて 2026-07-26 〜 07-29 の調査で、当時の記録が
`research/probes/archived/extract_monster_stats.py` ほかに残っている。
★ここに移したのは**読み方**だけで、当時の値と一致することは
`tests/test_enemy_tables.py`（ROM がある環境で走る）で確かめてある。

- ステータス表 `STATS_OFFSET` … 15 バイト × 83 体（ID 0x01..0x53）
    +0  最大HP                      +1  上位4bit = 回避率（/64）
    +2  最大ゴールド                +3  EXP 下位8bit
    +4  すばやさ  +5  攻撃力  +6  守備力
    +7  上位2bit = 賢さ / bit3-5 = ラリホー耐性 / bit0-2 = 攻撃呪文耐性
    +8  上位2bit = EXP×256 / bit3-5 = ザラキ耐性 / bit0-2 = マホトーン耐性
    +9  上位2bit = EXP×1024 / bit3-5 = ルカニ耐性 / bit0-2 = マヌーサ耐性
    +10..+13  行動8枠（ニブル）       +14  各枠の +0x10 ビット
  ★北米版逆アセンブル（bank4.asm:5079）の構造体と同じ。
    位置は戦闘開始時HP（最大の 75〜100%）の実測から総当たりで特定した。
- ドロップ表 `DROPS_OFFSET` … 1 バイト × 82 体。0 = 落とさない。
    bit0-5 = 道具ID / bit6-7 = 分母（00→1/8, 01→1/16, 10→1/32, 11→1/128）
  ⚠ ハーゴン（0x51）・シドー（0x52）は値があっても**落とさない**。
- 行動確率のしきい値 `RATES_OFFSET` … 7 バイト × 4（賢さ 0..3）。
    P(枠0) = (表[0]+1)/256、P(枠i) = (表[i]-表[i-1])/256、P(枠7) = (255-表[6])/256
- 経験値表 `EXP_OFFSET` … 2 バイト（little endian）の**増分**。
    ローレシア +0x00 / サマルトリア +0x62 / ムーンブルク +0xBA。0 で終わり。
  ⚠ ムーンブルクの LV30 以降は表に無い +65536 がコードで足される。表どおりに返す。
- 名前表 `NAMES_OFFSET` … 区切り 0xFA 区切りの可変長。ID 0x00 から並ぶ。
    文字コード → 文字 は `memory_map.yaml` の `text:`（`retroux.core.text.Charset`）。
    ⚠ ここでは**バイト列のまま**返す。文字への変換は呼び出し側。

## ⚠ 間違った ROM で読まない

これらの位置は日本版（PRG CRC32 48349B0B）でしか意味を持たない。
`verify()` が「スライムの HP は 6」「名前表の先頭が区切りの直後」など
**値そのものの辻褄**を見て、合わなければ問題を列挙する（黙って使わない）。
"""

from __future__ import annotations

STATS_OFFSET = 0x13791
STATS_STRIDE = 15
MONSTER_COUNT = 83                      # ID 0x01..0x53

DROPS_OFFSET = 0x13EAA
DROPS_COUNT = 82
NEVER_DROPS = (0x51, 0x52)              # ハーゴン・シドー
DROP_DENOMINATOR = {0b00: 8, 0b01: 16, 0b10: 32, 0b11: 128}

RATES_OFFSET = 0x1329B
RATES_ROWS = 4
RATES_COLS = 7

EXP_OFFSET = 0x13C5F
EXP_HERO_OFFSETS = {"lorasia": 0x00, "samaltria": 0x62, "moonbrooke": 0xBA}
EXP_MAX_LEVEL = 50

NAMES_OFFSET = 0x18930                  # ID 0x00 のエントリの先頭
NAME_SEPARATOR = 0xFA
NAME_MAX_LEN = 16                       # ★暴走防止。実際は最長 8 文字程度

RESIST_KEYS = ("spell_damage", "sleep", "stopspell", "defeat", "defense_down", "surround")


def read_stats(prg: bytes) -> dict[int, dict]:
    """ID → ステータス（`memory_map.yaml` の `monster_stats` と同じ形。drop は別）。"""
    out: dict[int, dict] = {}
    for i in range(MONSTER_COUNT):
        b = prg[STATS_OFFSET + i * STATS_STRIDE: STATS_OFFSET + (i + 1) * STATS_STRIDE]
        if len(b) < STATS_STRIDE:
            raise ValueError("ROM が短すぎます（ステータス表が末尾を超える）")
        out[i + 1] = {
            "max_hp": b[0],
            "gold": b[2],
            "exp": b[3] + ((b[8] >> 6) * 256) + ((b[9] >> 6) * 1024),
            "agility": b[4],
            "attack": b[5],
            "defense": b[6],
            "evade": b[1] >> 4,
            "resist": {
                "spell_damage": b[7] & 0x07,
                "sleep": (b[7] >> 3) & 0x07,
                "stopspell": b[8] & 0x07,
                "defeat": (b[8] >> 3) & 0x07,
                "defense_down": (b[9] >> 3) & 0x07,
                "surround": b[9] & 0x07,
            },
        }
    return out


def read_behavior(prg: bytes) -> dict[int, dict]:
    """ID → { wisdom, actions[8] }（`monster_behavior` と同じ形）。"""
    out: dict[int, dict] = {}
    for i in range(MONSTER_COUNT):
        b = prg[STATS_OFFSET + i * STATS_STRIDE: STATS_OFFSET + (i + 1) * STATS_STRIDE]
        alt = b[14]
        acts = []
        for slot in range(8):
            raw = b[10 + slot // 2]
            nib = (raw >> 4) if slot % 2 == 0 else (raw & 0x0F)
            acts.append(((alt >> slot) & 0x01) * 16 + nib)
        out[i + 1] = {"wisdom": b[7] >> 6, "actions": acts}
    return out


def read_drops(prg: bytes) -> dict[int, dict]:
    """ID → { item, denominator }。落とさない敵は**キーごと無い**（0 を入れない）。"""
    out: dict[int, dict] = {}
    for i in range(DROPS_COUNT):
        mid = i + 1
        raw = prg[DROPS_OFFSET + i]
        if raw == 0 or mid in NEVER_DROPS:
            continue
        out[mid] = {"item": raw & 0x3F, "denominator": DROP_DENOMINATOR[(raw >> 6) & 0x03]}
    return out


def read_action_rates(prg: bytes) -> dict[int, list[float]]:
    """賢さ → 8枠の確率（%）。★表示用に有効数字4桁へ丸める（以前の YAML と同じ）。"""
    out: dict[int, list[float]] = {}
    for row in range(RATES_ROWS):
        t = list(prg[RATES_OFFSET + row * RATES_COLS: RATES_OFFSET + (row + 1) * RATES_COLS])
        probs = [(t[0] + 1) / 256.0]
        probs += [(t[i] - t[i - 1]) / 256.0 for i in range(1, RATES_COLS)]
        probs.append((255 - t[RATES_COLS - 1]) / 256.0)
        out[row] = [float(f"{p * 100:.4g}") for p in probs]
    return out


def read_exp_to_level(prg: bytes) -> dict[str, dict[int, int]]:
    """主人公 → { レベル: そのレベルに到達するのに必要な累計EXP }。"""
    out: dict[str, dict[int, int]] = {}
    for hero, off in EXP_HERO_OFFSETS.items():
        base = EXP_OFFSET + off
        total = 0
        rows: dict[int, int] = {}
        for lv in range(2, EXP_MAX_LEVEL + 1):
            pos = base + (lv - 2) * 2
            inc = int.from_bytes(prg[pos:pos + 2], "little")
            if inc == 0:
                break
            total += inc
            rows[lv] = total
        out[hero] = rows
    return out


def read_name_bytes(prg: bytes) -> dict[int, bytes]:
    """ID → 名前のバイト列（ID 0x00..0x53。文字への変換は呼び出し側）。"""
    out: dict[int, bytes] = {}
    pos = NAMES_OFFSET
    for mid in range(MONSTER_COUNT + 1):
        end = pos
        while end < len(prg) and prg[end] != NAME_SEPARATOR and end - pos < NAME_MAX_LEN:
            end += 1
        out[mid] = bytes(prg[pos:end])
        pos = end + 1
    return out


def read_all(prg: bytes) -> dict:
    """5つの表をまとめて読む（名前はバイト列のまま）。"""
    stats = read_stats(prg)
    for mid, d in read_drops(prg).items():
        stats[mid]["drop"] = d
    return {
        "monster_stats": stats,
        "monster_behavior": read_behavior(prg),
        "action_rates": read_action_rates(prg),
        "exp_to_level": read_exp_to_level(prg),
        "monster_name_bytes": read_name_bytes(prg),
    }


def verify(prg: bytes, tables: dict) -> list[str]:
    """読めた値の辻褄を見る。問題を列挙（空なら OK）。★推測で先へ進まないため。"""
    problems: list[str] = []
    if len(prg) < NAMES_OFFSET + 0x400:
        return [f"PRG が短すぎます（{len(prg)} バイト）"]
    st = tables["monster_stats"]
    if st.get(0x01, {}).get("max_hp") != 6:
        problems.append(f"ID 0x01 の最大HPが 6 でない（{st.get(0x01, {}).get('max_hp')}）")
    if any(v > 7 for s in st.values() for v in s["resist"].values()):
        problems.append("耐性に 8 以上がある（3bit のはず）")
    if prg[NAMES_OFFSET - 1] != NAME_SEPARATOR:
        problems.append("名前表の先頭が区切り（0xFA）の直後でない")
    nb = tables["monster_name_bytes"]
    if any(len(b) == 0 or len(b) >= NAME_MAX_LEN for b in nb.values()):
        problems.append("空または長すぎる名前がある")
    for hero, rows in tables["exp_to_level"].items():
        vals = list(rows.values())
        if len(vals) < 10 or any(b <= a for a, b in zip(vals, vals[1:])):
            problems.append(f"経験値表が増加列でない（{hero}）")
    rates = tables["action_rates"]
    if any(abs(sum(v) - 100.0) > 0.5 for v in rates.values()):
        problems.append("行動確率の合計が 100% でない")
    return problems
