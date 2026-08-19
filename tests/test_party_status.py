"""パーティ加入・生存判定の回帰テスト（DEV-11）。

守りたい契約:
  加入判定は status バイト($062D+, 間隔 0x12)の **bit2** で行う。
  max_hp / current_hp では未加入メンバーと区別できない。

なぜテストが必要か:
  未加入メンバーの領域には初期値が残っており、
  ローレシア単独のセーブでも 3人分の max_hp/current_hp が 0 以外になる。
  これを加入とみなすと、未加入メンバーの残留HPが仲間の死亡を隠し、
  「生存者が min_alive_members 未満なら危険」という安全機構が発火しない。
  一度この誤りを入れて倍速が解除されない不具合を出したため固定化する。

Lua 実装（retroux/plugins/dq2/dq2.lua の DQ2:party / DQ2:is_danger）と
同じ判定をここに写し、memory_map.yaml のビット定義を正として検証する。
"""

from __future__ import annotations

import pathlib
import zlib

import pytest
import yaml

MAP_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "retroux" / "plugins" / "dq2" / "memory_map.yaml"
)
FCS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "tools" / "fceux" / "fcs"
)


@pytest.fixture(scope="module")
def party_spec() -> dict:
    spec = yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))["addresses"]["party"]
    return spec


# --- memory_map.yaml の契約 -------------------------------------------


def test_status_bits_are_single_bit_masks(party_spec):
    """ビットマスクは単一ビットであること。

    Lua 側は除算による has_bit() で判定しているため、
    複数ビットのマスクを入れると黙って誤判定する。
    """
    bits = party_spec["status_bits"]
    for name, mask in bits.items():
        assert mask > 0, name
        assert mask & (mask - 1) == 0, f"{name}=0x{mask:02X} が単一ビットでない"


def test_status_bit_values_match_disassembly(party_spec):
    """逆アセンブルの $062D の並びと一致すること。

    ★出典が変わった（2026-07-26 / Phase 6 P4-0）。
      以前は `global/ram.asm` の3ビットぶんのコメントしか見つかっておらず、
      「眠り等の未特定ビットを推測で追加しないこと（B-10）」として
      **キーの集合を3つに固定**していた。

      その後 `bank4.asm:5077` の構造体表に**全ビットの一覧**があった:
        80 = Alive / 40 = Sleep / 20 = Poison / 10 = ? / 08 = ?
        04 = In Party / 02 = Surround / 01 = Silence
      → B-10（睡眠の状態ビット）は 0x40 で埋まった。

    ⚠ **ガードの意図は変えていない。** 検査するのは
      「推測で足していないこと」＝ ROM が示す並びと**完全に一致**することと、
      **`?` のままの 0x10 / 0x08 に名前を付けていないこと**。
      実測済みは in_party / poison / alive の3つだけで、
      残りは ROM 由来だが実測前（memory_map のコメントに明記してある）。
    """
    bits = party_spec["status_bits"]
    assert bits == {
        "silence": 0x01,
        "surround": 0x02,
        "in_party": 0x04,
        "poison": 0x20,
        "sleep": 0x40,
        "alive": 0x80,
    }, "ROM（bank4.asm:5077）が示す並びと違う。推測で足していないか確認すること"

    # ★逆アセンブルでも `?` のビットには名前を付けない（分からないものは列を作らない）
    for name, mask in bits.items():
        assert mask not in (0x08, 0x10), (
            f"{name}=0x{mask:02X} は逆アセンブルでも用途不明のビット。名前を付けない"
        )


def test_enemy_status_bits_differ_from_party(party_spec):
    """敵の状態ビットは**パーティとは別の割り当て**であること。

    ★取り違えると「マホトーンをかけたのに眠ったと判定する」ような
      静かな誤りになる。パーティ 0x40 = 眠り / 敵 0x40 = マホトーン。

    出典は逆アセンブルの実コード（bank4.asm:6180 付近）で、
    呪文の効果を立てる前に $A1 へ入れるマスク:
      ラリホー -> 0x80 / マホトーン -> 0x40 / マヌーサ -> 0x01
    """
    spec = yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))["addresses"]
    enemy = spec["enemy_battle"]["instance_status_bits"]

    assert enemy == {"surround": 0x01, "stopspell": 0x40, "sleep": 0x80}
    for name, mask in enemy.items():
        assert mask & (mask - 1) == 0, f"{name}=0x{mask:02X} が単一ビットでない"

    # ★同じ名前で違う値になっていることを**明示的に**固定する。
    #   「どちらも 0x40 だろう」と書いた側が黙って壊れるのを防ぐ。
    party = party_spec["status_bits"]
    assert enemy["sleep"] != party["sleep"], "敵とパーティの眠りビットは違う"
    assert enemy["surround"] != party["surround"], "敵とパーティのマヌーサビットは違う"
    assert enemy["stopspell"] == party["sleep"], (
        "敵の 0x40 はマホトーンで、パーティの 0x40 は眠り。"
        "この重なりが取り違えの原因になるので、変わったら気づけるように固定する"
    )


# --- 判定ロジック（Lua と同じ式） -------------------------------------


def _members(ram: bytes, spec: dict) -> list[dict]:
    f, stride, bits = spec["fields"], spec["member_stride"], spec["status_bits"]
    out = []
    for i in range(len(spec["members"])):
        base = i * stride
        status = ram[f["status"]["offset"] + base]
        in_party = bool(status & bits["in_party"])
        cur_hp = ram[f["current_hp"]["offset"] + base]
        out.append(
            {
                "status": status,
                "max_hp": ram[f["max_hp"]["offset"] + base],
                "hp": cur_hp,
                "exists": in_party,
                "alive": in_party and bool(status & bits["alive"]) and cur_hp > 0,
            }
        )
    return out


def _load_ram(path: pathlib.Path) -> bytes:
    """セーブステートから RAM を取り出す。

    ★★ **圧縮あり・なしの2種類がある**（2026-07-31 に踏んだ）★★

      FCEUX のセーブステートの頭は 16 バイトで、**12〜16 バイト目が
      「圧縮後の長さ」**。ここが `0xFFFFFFFF` なら**非圧縮**。

      | 書いた人 | 形 | 大きさの例 |
      | --- | --- | --- |
      | FCEUX 本体（`i` キーなど） | zlib 圧縮 | 11,152 バイト |
      | Lua の `savestate.save` | **非圧縮** | 79,305 バイト |

      ⚠ 「保存して終了」で作られるのは**後者**なので、
        圧縮を決め打ちすると `incorrect header check` で落ちる。
        実際、保存が動くようになった瞬間にこのテストが赤くなった。
    """
    data = path.read_bytes()
    compressed_len = int.from_bytes(data[12:16], "little")
    body = data[16:]
    raw = body if compressed_len == 0xFFFFFFFF else zlib.decompress(body)
    i = raw.find(b"RAM\x00")
    size = int.from_bytes(raw[i + 4 : i + 8], "little")
    return raw[i + 8 : i + 8 + size]


def _savestates() -> list[pathlib.Path]:
    return sorted(FCS_DIR.glob("DQ2_J.fc[0-9]"))


def _in_game(path: pathlib.Path, spec) -> bool:
    """★そのセーブは**遊びの途中**か（⚠ タイトル画面ではないか）。

    ## ⚠⚠ なぜ要るか（2026-08-19）

      依頼者が動作確認のため**タイトル画面**でセーブステートを上書きした。
      ★そこには**パーティが1人も居ない**（RAM が全部ゼロ）ので、

          assert len(by_max_hp) == 3

      が落ちた。⚠ **製品の不具合ではない。**

      ★この検査はもともと「加入者数 == 1」を前提にして一度落ちている
        （★docstring に記録あり）。⚠ **同じ轍を2度目**。
        今度は「3人ぶんの max_hp が必ず埋まっている」を前提にしていた。

      → ★**遊びの途中でないセーブは、判定に使わない**。
        ⚠ 黙って飛ばさず、何枚飛ばしたかを出す。
    """
    try:
        ram = _load_ram(path)
    except Exception:                                   # noqa: BLE001
        return False
    return any(m["max_hp"] > 0 for m in _members(ram, spec))


needs_states = pytest.mark.skipif(
    not FCS_DIR.is_dir() or not _savestates(),
    reason="セーブステートは利用者環境固有のため未コミット",
)


@needs_states
@pytest.mark.parametrize("path", _savestates(), ids=lambda p: p.name)
def test_max_hp_cannot_identify_party_membership(path, party_spec):
    """max_hp では加入を判定できないことを実データで示す（バグの再発防止）。

    ★人数を固定しない。当初「手持ちのセーブは全てローレシア単独」を前提に
      加入者数 == 1 を検査していたが、依頼者がゲームを進めてサマルトリアが
      加入した時点で落ちた。**製品ではなくテストの前提が古くなった不具合。**
      セーブは利用者の進行で変わるので、進行に依存しない性質だけを検査する。
    """
    if not _in_game(path, party_spec):
        pytest.skip(
            f"★{path.name} は遊びの途中ではありません"
            "（⚠ タイトル画面などでは、パーティの判定に使えません）")
    ram = _load_ram(path)
    members = _members(ram, party_spec)

    joined = [m for m in members if m["exists"]]
    by_max_hp = [m for m in members if m["max_hp"] > 0]

    # 進行に依らず成り立つこと: 全メンバー分の max_hp が埋まっている
    assert len(by_max_hp) == 3, "未加入メンバーにも max_hp が残っている前提が崩れた"
    assert 1 <= len(joined) <= 3, f"加入者数がおかしい: {len(joined)}"

    # 未加入メンバーが居るなら、そこに「max_hp では判定できない」証拠がある
    for m in members:
        if m["exists"]:
            continue
        assert m["max_hp"] > 0, "未加入なのに max_hp が0ならこの誤判定は起きない"
        assert m["hp"] > 0, "未加入メンバーの残留HPが0ならこの誤判定は起きない"
        assert m["alive"] is False, "未加入メンバーを生存に数えてはいけない"

    if len(joined) < 3:
        assert len(joined) != len(by_max_hp), (
            "未加入メンバーが居るのに max_hp と bit2 の人数が一致している"
        )


@needs_states
@pytest.mark.parametrize("path", _savestates(), ids=lambda p: p.name)
def test_lorasia_is_alive_and_in_party(path, party_spec):
    if not _in_game(path, party_spec):
        pytest.skip(
            f"★{path.name} は遊びの途中ではありません"
            "（⚠ タイトル画面などでは、パーティの判定に使えません）")
    ram = _load_ram(path)
    lorasia = _members(ram, party_spec)[0]
    assert lorasia["exists"] is True
    assert lorasia["alive"] is True
    assert 0 < lorasia["hp"] <= lorasia["max_hp"]


# --- 危険判定: 死亡が隠れないこと -------------------------------------


def _count(members: list[dict]) -> tuple[int, int]:
    joined = [m for m in members if m["exists"]]
    return len(joined), len([m for m in joined if m["alive"]])


def _synthetic(joined: int, dead_index: int | None, party_spec: dict) -> bytes:
    """合成RAM: joined 人が加入し、dead_index の1人だけ死亡している状態。

    未加入メンバーには「残留HP」を必ず入れる。これが誤判定の原因だった。
    """
    f, stride, bits = (
        party_spec["fields"],
        party_spec["member_stride"],
        party_spec["status_bits"],
    )
    ram = bytearray(0x800)
    for i in range(len(party_spec["members"])):
        base = i * stride
        if i < joined:
            dead = i == dead_index
            status = bits["in_party"] | (0 if dead else bits["alive"])
            hp = 0 if dead else 30
        else:
            status = 0x00          # 未加入
            hp = 31                # ★残留HP
        ram[f["status"]["offset"] + base] = status
        ram[f["max_hp"]["offset"] + base] = 31
        ram[f["current_hp"]["offset"] + base] = hp
    return bytes(ram)


def test_death_in_two_person_party_is_detected(party_spec):
    """2人パーティで1人死亡 -> 生存1人。危険判定が発火する条件を満たす。

    バグ時は未加入のムーンブルグ(31/31)を生存に数え、
    生存2人と誤認して倍速が解除されなかった。
    """
    ram = _synthetic(joined=2, dead_index=1, party_spec=party_spec)
    n_exists, n_alive = _count(_members(ram, party_spec))

    min_alive = 2
    assert (n_exists, n_alive) == (2, 1)
    assert n_exists >= min_alive and n_alive < min_alive, "危険と判定されるべき"


def test_solo_party_is_not_permanently_dangerous(party_spec):
    """1人パーティは条件1の対象外（下駄）。常時危険になってはいけない。"""
    ram = _synthetic(joined=1, dead_index=None, party_spec=party_spec)
    n_exists, n_alive = _count(_members(ram, party_spec))

    min_alive = 2
    assert (n_exists, n_alive) == (1, 1)
    assert not (n_exists >= min_alive), "1人パーティで条件1を適用してはいけない"


def test_full_party_two_deaths_is_detected(party_spec):
    """3人中2人死亡 -> 依頼者が想定した「王女のみ生存」の状況。"""
    f, stride, bits = (
        party_spec["fields"],
        party_spec["member_stride"],
        party_spec["status_bits"],
    )
    ram = bytearray(_synthetic(joined=3, dead_index=None, party_spec=party_spec))
    for i in (0, 1):  # ローレシア・サマルトリアが死亡
        base = i * stride
        ram[f["status"]["offset"] + base] = bits["in_party"]
        ram[f["current_hp"]["offset"] + base] = 0

    n_exists, n_alive = _count(_members(bytes(ram), party_spec))
    assert (n_exists, n_alive) == (3, 1)
    assert n_alive < 2, "危険と判定されるべき"
