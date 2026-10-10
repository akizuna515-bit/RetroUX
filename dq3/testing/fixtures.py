"""実機テストの入力を**意味のある名前**で管理する（RX3-0129 / 2026-09-08）。

```text
⚠ これまで   「セーブ 4 で試した」   → ★fc4 が何の場面かは、別の資料を思い出すしかない
                                       ⚠ 中身が変わると、同じテスト名で別の条件になる
★これから   「battle_ai_injured_party を使った（sha256=…）」
```

## ★形

```text
work/tests/fixtures/dq3/
  fixtures.json                     ★台帳（id / 由来 / sha256 / 期待する状態）
  states/<id>.fcs                   ★セーブステートの実体（⚠ WRITE 禁止）
```

⚠⚠ **fixture は直接 load / save しません。** ★run ごとの隔離先へ写してから使います
（`dq3/testing/sandbox.py` / RX3-0128）。

```text
fixture（不変）→ copy → sandbox（壊してよい）→ FCEUX → 捨てる
```

## ★使う前に必ず確かめる

```text
sha256       ⚠ 1 バイトでも違えば `FixtureChanged`（★「動いたから使う」にしない）
期待する状態 ★戦闘中か / パーティ人数 / 傷ついているか / 敵の数（⚠ セーブから読む。実機は要らない）
```

## ★台帳から 3 つの問いに答える（RX3-0129 拡張 / 2026-09-09）

```text
Q1 このセーブは何のためのデータ？    → show <id>（★description / tags / 場面）
Q2 この fixture はどのテストで使う？  → show <id> の Tests（★fixture → tests）
Q3 このテストには何が要る？          → for-test <test_id>（★tests → fixture）
```

⚠ スロット番号（`fc4`）は**identity ではなく由来**です（`source_slot`）。
★外へ出す名前は `battle_ai_injured_party` の側だけにします。

## 使い方

```bash
PYTHONUTF8=1 python -m dq3.testing.fixtures list
PYTHONUTF8=1 python -m dq3.testing.fixtures show battle_ai_injured_party
PYTHONUTF8=1 python -m dq3.testing.fixtures for-test battle_ai_survival
PYTHONUTF8=1 python -m dq3.testing.fixtures tests          # ★回せるテストの名簿
PYTHONUTF8=1 python -m dq3.testing.fixtures check          # ★台帳そのものの検査
PYTHONUTF8=1 python -m dq3.testing.fixtures register-slot 8 --name town_shop_restock \
    --description "…" --tags town,shop --tests restock_buy_missing_items
```

```python
from dq3.testing import fixtures as FX

fx = FX.get("battle_ai_injured_party")     # ⚠ sha256 と状態をここで検算
slot = FX.install(fx, sandbox)             # ★隔離先へ写す。戻り値は読み込むスロット番号
```
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import sys

from .. import paths

ROOT = paths.ROOT
#: ★固定のテスト入力（⚠ ここは本番と同じく WRITE 禁止。`sandbox.production_files()` が見張る）
DIR = ROOT / "work" / "tests" / "fixtures" / "dq3"
STATES = DIR / "states"
MANIFEST = DIR / "fixtures.json"

#: ★隔離先で fixture を置くスロット（⚠ 隔離先なのでどれでもよい / RX3-0128）
DEFAULT_SLOT = 9

#: ★ROM が無いと出せない欄（⚠ 出せないときは「違う」ではなく「分からない」）
ROM_KEYS = ("shop_available", "shop_roles")

#: ★台帳へ書いてよい場面の欄（⚠ 増やすときはここへ。★打ち間違いを checker が拾う）
CONDITION_KEYS = (
    "in_battle", "party_count", "party_hp", "party_injured", "party_alive",
    "party_poisoned",
    "loc_kind", "map_id", "world_map", "world_pos", "local_pos",
    "window_open", "safe_to_walk", "enemy_groups", "enemy_count", "enemy_kind",
) + ROM_KEYS


class FixtureError(RuntimeError):
    """⚠ fixture が使えない（★理由をそのまま出す）。"""


class FixtureChanged(FixtureError):
    """⚠⚠ fixture の中身が変わった（★同じ名前で別の条件になっている）。"""


# ----------------------------------------------------------------------
# ★セーブステートから「何の場面か」を読む（⚠ 実機は要らない）
# ----------------------------------------------------------------------

def _profile() -> dict:
    return json.loads((ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                      .read_text(encoding="utf-8"))["runtime"]


def conditions_of(path: pathlib.Path) -> dict:
    """★そのセーブステートの場面（⚠ 読めない項目は入れない。★推測しない）。"""
    from retroux.core.bgmap import savestate as ss

    rt = _profile()
    state = ss.load(path)
    ram = state.chunks["RAM"]

    def at(addr) -> int:
        """★`"0x071C"` でも `1820` でも受ける（⚠ 混ぜると 10 進を 16 進で読む事故になる）。"""
        return addr if isinstance(addr, int) else int(str(addr), 16)

    def b(addr) -> int:
        return ram[at(addr)]

    def w16(addr, i=0) -> int:
        base = at(addr) + i
        return ram[base] + ram[base + 1] * 256

    party = rt["party"]
    hp = [w16(party["hp_current"], i * 2) for i in range(4)]
    hp_max = [w16(party["hp_max"], i * 2) for i in range(4)]
    alive = [(h, m) for h, m in zip(hp, hp_max) if m > 0]
    # ★★ 状態（RX3-0135 / 2026-09-09）。⚠ **裏の取れた旗だけ**を数える。
    #   ★`fixtures needed` の「毒の場面」がもう手に入ったかを、機械で言えるように。
    poisoned = 0
    flags = party.get("status_flags") or {}
    row = flags.get("poisoned")
    if row is not None and str(row.get("confidence")) == "confirmed" and "status" in party:
        base, size = at(party["status"]), int(party.get("status_size", 2))
        for i in range(4):
            if hp_max[i] <= 0:
                continue                              # ⚠ 居ない枠のゴミを数えない
            byte = ram[base + i * size + int(row.get("byte", 0))]
            if byte >> int(row.get("bit", 5)) & 1:
                poisoned += 1
    ene = rt["battle_enemies"]
    groups = []
    for i in range(int(ene.get("groups", 4))):
        eid = b(at(ene["ids"]) + i)
        if eid != at(ene.get("empty", "0xFF")):
            groups.append({"id": eid, "n": b(at(ene["counts"]) + i)})
    # ★★ 戦闘中は DQ3 自身の式（RX3-0166 / `$32 == $FD かつ $60B7 & $20`）。
    #   ⚠ 旧い `$62 == 255` は戦闘中フラグではなかった（RX3-0165）。★WRAM も読む
    from dq3 import battle_state as BS

    battle = BS.of_memory(ram, state.chunks.get("WRAM", b""), BS.spec_from_profile({"runtime": rt}))
    in_battle = battle["in_battle"]
    kind = b(rt["location"]["kind"])
    #: ★世界地図か（⚠ `kind` 0 / 2 が世界。★そこでは `map_no` は前の値が残る）
    world = kind in (0, 2)
    out = {
        "in_battle": in_battle,
        "party_count": len(alive),
        "party_hp": ["%d/%d" % (h, m) for h, m in alive],
        "party_injured": any(h * 2 < m for h, m in alive),
        "party_poisoned": poisoned,
        "party_alive": len(alive) > 0 and all(h > 0 for h, _m in alive),
        "loc_kind": kind,
        "map_id": b(rt["location"]["map_no"]),
        "world_map": world,
    }
    if world:
        out["world_pos"] = [b(rt["location"]["world_x"]), b(rt["location"]["world_y"])]
    else:
        out["local_pos"] = [b(rt["location"]["local_x"]), b(rt["location"]["local_y"])]
    # ★★ 窓が開いていないか（RX3-0131 / 2026-09-08）。
    #   ⚠⚠ **これが `boxed_in` の正体でした。** ★メニューが開いたままのセーブを読むと、
    #     方向キーは全部メニューに吸われ、walker は「4 方向とも壁」と学習します。
    out["window_open"] = _has_window(state)
    #: ★歩かせてよい場面か（⚠ 戦闘中でない / 窓が出ていない / 全員生きている）
    out["safe_to_walk"] = (not in_battle) and (not out["window_open"]) and out["party_alive"]
    # ★★ この地図に店があるか（RX3-0129 拡張 / 2026-09-09）。
    #   ⚠ ROM が読めない環境では**入れません**（★`verify` はこの欄を飛ばす / `ROM_KEYS`）。
    if not world:
        roles = _shop_roles(out["map_id"])
        if roles is not None:
            out["shop_available"] = bool(roles)
            if roles:
                out["shop_roles"] = roles
    if in_battle:
        out["enemy_groups"] = groups
        out["enemy_count"] = sum(g["n"] for g in groups)
        names = []
        for g in groups:
            try:
                from ..knowledge import rom_names as RN

                got = RN.monster(g["id"])
            except Exception:                              # noqa: BLE001 - ★名前は無くてもよい
                got = None
            if got:
                names.append(got)
        if names:
            out["enemy_kind"] = names
    return out


def _shop_roles(map_id: int):
    """★その地図にある店の種類（⚠ ROM が読めなければ `None` = 「分からない」）。

    ⚠⚠ 「無い」と「分からない」を同じ値にしないこと。★分からないなら台帳へ書きません。
    """
    try:
        from ..knowledge import item_info as II

        got = II.shops_by_map()
    except Exception:                                      # noqa: BLE001 - ★ROM 無しでも動く
        return None
    return sorted({s.role for s in got.get(int(map_id), [])})


def _has_window(state) -> bool:
    """★画面に枠つきの窓が出ているか（⚠ 判定は `dq3rom/window.py` の 1 本に任せる）。"""
    nt = state.chunks.get("NTAR")
    if not nt:
        return False
    try:
        from dq3rom import window as W

        return len(W.find_windows(bytes(nt[:960]))) > 0
    except Exception:                                      # noqa: BLE001 - ★見えないなら無いことにしない
        return False


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------------------
# ★台帳
# ----------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Fixture:
    id: str
    description: str
    purpose: str
    source_slot: int | None
    source_sha256: str | None
    sha256: str
    created_at: str
    expected: dict
    file: str
    #: ★分類（★`battle` `ai` `injured` のような短い語。⚠ 検索の手がかりだけ）
    tags: tuple = ()
    #: ★この入力を使うテスト（★`dq3/testing/e2e_tests.py` の名簿か、`tests/` の関数名）
    tests: tuple = ()
    #: ★スロット以外から採ったときの由来（★世代の控え など / RX3-0402）。
    #:
    #:   ⚠ `source_slot` は「いまのスロット 0」を指してしまい、★**別の中身**を指し続けます。
    #:     → ★写した元のパスをそのまま残します（⚠ 消えても構わない参考値）。
    source_path: str | None = None

    def __post_init__(self):
        # ★JSON からは list で来る（⚠ frozen なので object.__setattr__ で揃える）
        object.__setattr__(self, "tags", tuple(self.tags or ()))
        object.__setattr__(self, "tests", tuple(self.tests or ()))

    @property
    def path(self) -> pathlib.Path:
        return DIR / self.file

    def as_json(self) -> dict:
        got = dataclasses.asdict(self)
        got["tags"] = list(self.tags)
        got["tests"] = list(self.tests)
        return got

    def summary(self) -> str:
        e = self.expected or {}
        bits = ["戦闘" if e.get("in_battle") else "フィールド",
                "map %s" % e.get("map_id"),
                "%s 人" % e.get("party_count")]
        if e.get("party_injured"):
            bits.append("傷あり")
        if e.get("enemy_count"):
            bits.append("敵 %d 体" % e["enemy_count"])
        return " / ".join(str(x) for x in bits)


def load_manifest() -> dict:
    if not MANIFEST.exists():
        return {"game": "dq3", "rom": "DQ3_J", "fixtures": []}
    got = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return got if isinstance(got, dict) else {"fixtures": []}


def save_manifest(data: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def all_fixtures() -> list[Fixture]:
    return [Fixture(**row) for row in load_manifest().get("fixtures", [])]


def get(fixture_id: str, *, check: bool = True) -> Fixture:
    """★名前で引く。⚠ 無ければ理由つきで例外。★`check` で中身も検算する。"""
    for fx in all_fixtures():
        if fx.id == fixture_id:
            if check:
                verify(fx)
            return fx
    known = ", ".join(f.id for f in all_fixtures()) or "（1 件もありません）"
    raise FixtureError("⚠ そんな fixture はありません: %r（★あるのは: %s）"
                       % (fixture_id, known))


def verify(fx: Fixture) -> None:
    """⚠⚠ 使う前に必ず。★sha256 と、セーブから読める状態を確かめる。"""
    if not fx.path.exists():
        raise FixtureError("⚠ fixture の実体がありません: %s" % fx.path)
    got = digest(fx.path)
    if got != fx.sha256:
        raise FixtureChanged(
            "⚠⚠ fixture が変わっています: %s%s  台帳 sha256=%s…%s  実体 sha256=%s…"
            % (fx.id, chr(10), fx.sha256[:16], chr(10), got[:16]))
    now = conditions_of(fx.path)
    for key, want in (fx.expected or {}).items():
        if key in ("party_hp", "enemy_kind", "enemy_groups"):
            continue                                   # ★参考の値（⚠ 名前は ROM 依存）
        if key in ROM_KEYS and key not in now:
            continue                                   # ⚠ ROM が読めない環境（★「違う」ではない）
        if now.get(key) != want:
            raise FixtureChanged(
                "⚠⚠ fixture の場面が違います: %s の %s（台帳 %r / 実体 %r）"
                % (fx.id, key, want, now.get(key)))


def verify_all() -> list[str]:
    """★全部を検算し、⚠ 駄目だったものの理由を返す（空なら無事）。"""
    out = []
    for fx in all_fixtures():
        try:
            verify(fx)
        except FixtureError as err:
            out.append(str(err))
    return out


# ----------------------------------------------------------------------
# ★テストとの対応（★両方向に引ける / 指示書 §4・§5）
# ----------------------------------------------------------------------

def pytest_index(tests_dir: pathlib.Path | None = None) -> dict:
    """★`tests/` にある関数名 → `ファイル::関数名` の一覧（⚠ 打ち間違いを拾うため）。"""
    import ast
    from collections import defaultdict

    got: dict[str, list[str]] = defaultdict(list)
    base = tests_dir or (ROOT / "tests")
    if not base.is_dir():
        return {}
    for path in sorted(base.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_bytes().decode("utf-8"))
        except SyntaxError:                                # ⚠ 壊れた検査でここを止めない
            continue
        rel = path.name
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test_"):
                got[node.name].append("%s::%s" % (rel, node.name))
                got["%s::%s" % (rel, node.name)].append("%s::%s" % (rel, node.name))
    return dict(got)


def resolve_test(test_id: str) -> dict | None:
    """★テスト名の正体（⚠ 名簿にも `tests/` にも無ければ `None` = 打ち間違い）。"""
    from . import e2e_tests as E2E

    got = E2E.get(test_id)
    if got is not None:
        return {"kind": "e2e", "id": test_id, "purpose": got.purpose, "runner": got.runner}
    hits = pytest_index().get(test_id)
    if hits:
        return {"kind": "pytest", "id": test_id, "purpose": "", "runner": hits[0]}
    return None


def tests_of(fixture_id: str) -> list[str]:
    """★fixture → tests（⚠ 無い名前でも落とさない。★空を返す / Case F）。"""
    for fx in all_fixtures():
        if fx.id == fixture_id:
            return list(fx.tests)
    return []


def for_test(test_id: str) -> list[Fixture]:
    """★test → fixtures（⚠ 知らない名前は空。★例外にしない / 指示書 §18 Case F）。"""
    return [fx for fx in all_fixtures() if test_id in fx.tests]


# ----------------------------------------------------------------------
# ★まだ無い fixture（NEED-FIXTURE / 指示書 v1.1 §17）
# ----------------------------------------------------------------------

def needed() -> list[dict]:
    """★人が作ってくれないと手に入らない場面（⚠ 作業を止めずに一覧化する）。

    ⚠⚠ **テストのために本番の RAM を書き換えて作りません**（指示書 v1.1 §3）。
    ★依頼者が遊んでいて「この場面は使えそう」と思ったらセーブし、
    ⚠ スロット番号を教えてもらって `register-slot` で登録します。
    """
    rows = load_manifest().get("needed") or []
    have = {fx.id for fx in all_fixtures()}
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        got = dict(row)
        got["ready"] = row["id"] in have          # ★もう手に入っているか
        out.append(got)
    return out


# ----------------------------------------------------------------------
# ★台帳そのものの検査（指示書 §14 / `scripts/check_fixtures.py`）
# ----------------------------------------------------------------------

def check_registry() -> list[str]:
    """★台帳が壊れていないか。⚠ 返るのは**人が読める理由**の一覧（空なら無事）。"""
    problems: list[str] = []
    data = load_manifest()
    rows = data.get("fixtures", [])
    if not isinstance(rows, list):
        return ["⚠⚠ `fixtures` が一覧になっていません: %r" % type(rows).__name__]

    seen: set[str] = set()
    for row in rows:
        fid = row.get("id")
        if not isinstance(fid, str) or not fid:
            problems.append("⚠⚠ id の無い行があります: %r" % (row,))
            continue
        if fid in seen:
            problems.append("⚠⚠ fixture_id が重複しています: %s" % fid)
        seen.add(fid)
        # ★由来（⚠ あっても無くてもよい。★あるなら数字）
        slot = row.get("source_slot")
        if slot is not None and not isinstance(slot, int):
            problems.append("⚠ %s: source_slot は数字か空: %r" % (fid, slot))
        for key in ("tags", "tests"):
            got = row.get(key, [])
            if not isinstance(got, list) or not all(isinstance(v, str) and v for v in got):
                problems.append("⚠ %s: %s は文字列の一覧: %r" % (fid, key, got))
                continue
            if len(set(got)) != len(got):
                problems.append("⚠ %s: %s に同じものが 2 度: %r" % (fid, key, got))
        exp = row.get("expected")
        if not isinstance(exp, dict):
            problems.append("⚠ %s: expected_conditions が表になっていません: %r" % (fid, exp))
        else:
            for key in exp:
                if key not in CONDITION_KEYS:
                    problems.append("⚠ %s: 知らない場面の欄です: %s（★%s）"
                                    % (fid, key, ", ".join(CONDITION_KEYS)))
        # ⚠⚠ テスト名の打ち間違い（★名簿にも `tests/` にも無い）
        for test_id in row.get("tests", []) or []:
            if isinstance(test_id, str) and resolve_test(test_id) is None:
                problems.append("⚠⚠ %s: そんなテストはありません: %s"
                                "（★`dq3/testing/e2e_tests.py` か `tests/` の関数名）"
                                % (fid, test_id))

    # ★まだ無い fixture の一覧（⚠ 形だけ見る。★無いこと自体は問題ではない）
    for row in data.get("needed") or []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            problems.append("⚠ needed に id の無い行があります: %r" % (row,))
            continue
        if not isinstance(row.get("why"), str) or not row["why"]:
            problems.append("⚠ %s: 何のために要るのかが書いてありません" % row["id"])
        for test_id in row.get("tests") or []:
            if isinstance(test_id, str) and resolve_test(test_id) is None:
                problems.append("⚠⚠ needed %s: そんなテストはありません: %s" % (row["id"], test_id))

    # ★実体と sha256 と場面（⚠ `verify` と同じ判定を 2 度書かない）
    problems += verify_all()

    # ⚠⚠ fixture が「隔離の外から直接 WRITE されるもの」になっていないか
    try:
        from . import sandbox as SB

        guarded = {str(p) for p in SB.production_files()}
        for fx in all_fixtures():
            if fx.path.exists() and str(fx.path) not in guarded:
                problems.append("⚠⚠ %s: 見張りの外にあります（★書き換えても気づけません）: %s"
                                % (fx.id, fx.path))
    except Exception as err:                               # noqa: BLE001
        problems.append("⚠ 見張りを確かめられませんでした: %s" % err)
    return problems


# ----------------------------------------------------------------------
# ★作る（★本番のスロットから 1 回だけ写す）
# ----------------------------------------------------------------------

def capture(fixture_id: str, slot: int | None, *, description: str = "", purpose: str = "",
            tags=(), tests=(), source_dir: pathlib.Path | None = None,
            source: pathlib.Path | None = None) -> Fixture:
    """★本番のスロットを、名前つきの固定入力として写し取る（指示書 §8）。

    ⚠ 本番は**読むだけ**です（★sha256 を控えて由来に残します）。

    ```text
    1 スロットの実体を読む → 2 fixture の置き場へ写す → 3 sha256 → 4 場面を観る
    → 5 台帳へ足す → 6 由来（source_slot）を残す → 7 以後は不変（★見張りの中）
    ```
    """
    # ★`source` を渡せば、スロット以外（★世代の控え など）からも写せます（RX3-0402）。
    #   ⚠ そのときは `source_slot` を空にし、★`source_path` に元の場所を残します。
    if source is not None:
        src = pathlib.Path(source)
    else:
        src_dir = source_dir or (ROOT / "tools" / "fceux" / "fcs")
        src = src_dir / ("DQ3_J.fc%d" % slot)
    if not src.exists():
        raise FixtureError("⚠ 元のセーブがありません: %s" % src)
    STATES.mkdir(parents=True, exist_ok=True)
    dst = STATES / ("%s.fcs" % fixture_id)
    shutil.copyfile(src, dst)
    fx = Fixture(id=fixture_id, description=description, purpose=purpose,
                 source_slot=None if source is not None else slot,
                 source_path=str(pathlib.Path(src)).replace("\\", "/") if source is not None else None,
                 source_sha256=digest(src), sha256=digest(dst),
                 created_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 expected=conditions_of(dst),
                 file=str(dst.relative_to(DIR)).replace("\\", "/"),
                 tags=tuple(tags), tests=tuple(tests))
    data = load_manifest()
    rows = [r for r in data.get("fixtures", []) if r.get("id") != fixture_id]
    rows.append(fx.as_json())
    data["fixtures"] = sorted(rows, key=lambda r: r["id"])
    save_manifest(data)
    return fx


# ----------------------------------------------------------------------
# ★隔離先へ置く（⚠ fixture そのものは触らない / RX3-0128）
# ----------------------------------------------------------------------

def install(fx: Fixture, sandbox, *, slot: int = DEFAULT_SLOT) -> int:
    """★fixture を隔離先の `DQ3_J.fc<slot>` として写す。戻り値は読み込むスロット。

    ⚠⚠ fixture を直接読み込ませない（★実機が上書きしたら固定入力でなくなる）。
    """
    verify(fx)
    target = sandbox.saves / ("DQ3_J.fc%d" % slot)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fx.path, target)
    used = sandbox.root / "fixtures-used.json"
    rows = json.loads(used.read_text(encoding="utf-8")) if used.exists() else []
    rows.append({"id": fx.id, "sha256": fx.sha256, "slot": slot,
                 "tags": list(fx.tags), "tests": list(fx.tests),
                 "expected": fx.expected, "at": dt.datetime.now().isoformat(timespec="seconds")})
    used.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return slot


# ----------------------------------------------------------------------
# ★CLI
# ----------------------------------------------------------------------

def _csv(text: str) -> tuple:
    return tuple(x.strip() for x in (text or "").split(",") if x.strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="実機テストの固定入力（fixture）")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("id")
    show.add_argument("--json", action="store_true", help="★台帳の行をそのまま出す")
    ft = sub.add_parser("for-test", help="★このテストに要る fixture（逆引き）")
    ft.add_argument("test_id")
    sub.add_parser("tests", help="★回せるテストの名簿")
    sub.add_parser("needed", help="★まだ無い fixture（NEED-FIXTURE）")
    sub.add_parser("verify")
    sub.add_parser("check", help="★台帳そのものの検査（重複 / 実体 / hash / 対応）")
    for name in ("capture", "register-slot"):
        cap = sub.add_parser(name)
        if name == "capture":
            cap.add_argument("id")
            cap.add_argument("--slot", type=int, required=True)
        else:
            cap.add_argument("slot", type=int)
            cap.add_argument("--name", required=True, dest="id")
        cap.add_argument("--description", default="")
        cap.add_argument("--purpose", default="")
        cap.add_argument("--tags", default="", help="★`battle,ai,injured` のように")
        cap.add_argument("--tests", default="", help="★`battle_ai_survival,...`")
    args = ap.parse_args(argv)

    if args.cmd in (None, "list"):
        rows = all_fixtures()
        if not rows:
            print("（fixture はまだありません）")
            return 0
        for fx in rows:
            print("%s" % fx.id)
            print("  source: %s / %s" % (
                "slot %d" % fx.source_slot if fx.source_slot is not None else "（不明）",
                fx.summary()))
            print("  tags: %s" % (", ".join(fx.tags) or "（なし）"))
            print("  tests: %d" % len(fx.tests))
        return 0
    if args.cmd == "show":
        fx = get(args.id, check=False)
        if args.json:
            print(json.dumps(fx.as_json(), ensure_ascii=False, indent=1))
        else:
            print("Fixture: %s" % fx.id)
            print("File:    %s（sha256=%s…）" % (fx.file, fx.sha256[:16]))
            print("Source:  %s" % ("slot %d" % fx.source_slot
                                   if fx.source_slot is not None else "（不明）"))
            print("Purpose: %s" % (fx.purpose or fx.description))
            print("State:   %s" % fx.summary())
            print("Tags:    %s" % (", ".join(fx.tags) or "（なし）"))
            print("Tests:")
            if not fx.tests:
                print("  （まだ紐づいていません）")
            for test_id in fx.tests:
                got = resolve_test(test_id)
                if got is None:
                    print("  %-28s ⚠⚠ そんなテストはありません" % test_id)
                else:
                    print("  %-28s %s" % (test_id, got["purpose"] or got["runner"]))
        try:
            verify(fx)
            print("★検算 OK（sha256 と場面が台帳と一致）")
        except FixtureError as err:
            print(str(err))
            return 1
        return 0
    if args.cmd == "for-test":
        rows = for_test(args.test_id)
        if not rows:
            # ⚠ 落とさない（★「無い」は答えのひとつ / 指示書 §18 Case F）
            known = resolve_test(args.test_id)
            if known is None:
                print("（そんなテストはありません: %s）" % args.test_id)
            else:
                print("（%s に紐づく fixture はまだありません）" % args.test_id)
            return 0
        for fx in rows:
            print(fx.id)
        return 0
    if args.cmd == "tests":
        from . import e2e_tests as E2E

        for test_id in E2E.ids():
            got = E2E.TESTS[test_id]
            used = [fx.id for fx in for_test(test_id)]
            print("%-28s %s" % (test_id, got.purpose))
            print("%-28s %s" % ("", got.command(used[0] if used else None)))
        return 0
    if args.cmd == "needed":
        rows = needed()
        if not rows:
            print("（足りない fixture はありません）")
            return 0
        print("NEED-FIXTURE:")
        for row in rows:
            print("- %s%s" % (row["id"], "  ★もう有ります" if row["ready"] else ""))
            print("    なぜ: %s" % row.get("why", ""))
            if row.get("how"):
                print("    作り方: %s" % row["how"])
            if row.get("tests"):
                print("    使うテスト: %s" % ", ".join(row["tests"]))
        left = [r for r in rows if not r["ready"]]
        print()
        print("★%d 件中 %d 件がまだ手に入っていません。" % (len(rows), len(left)))
        print("⚠ 遊んでいて場面を作れたらセーブして、"
              "★`register-slot <番号> --name <id>` で登録できます。")
        return 0
    if args.cmd == "verify":
        bad = verify_all()
        for line in bad:
            print(line)
        print("★%d 件中 %d 件に問題" % (len(all_fixtures()), len(bad)))
        return 1 if bad else 0
    if args.cmd == "check":
        bad = check_registry()
        for line in bad:
            print(line)
        if bad:
            print("⚠ 台帳に %d 件の問題（fixture %d 件）" % (len(bad), len(all_fixtures())))
            return 1
        print("★問題なし（fixture %d 件）" % len(all_fixtures()))
        return 0
    if args.cmd in ("capture", "register-slot"):
        fx = capture(args.id, args.slot, description=args.description, purpose=args.purpose,
                     tags=_csv(args.tags), tests=_csv(args.tests))
        print("★作りました: %s（%s）" % (fx.id, fx.summary()))
        print("  source: slot %d / sha256=%s…" % (fx.source_slot, fx.sha256[:16]))
        print(json.dumps(fx.expected, ensure_ascii=False))
        bad = check_registry()
        for line in bad:
            print(line)
        return 1 if bad else 0
    ap.print_help()
    return 2


__all__ = ["Fixture", "FixtureError", "FixtureChanged", "get", "all_fixtures", "verify",
           "verify_all", "capture", "install", "conditions_of", "digest", "DIR", "STATES",
           "MANIFEST", "DEFAULT_SLOT", "for_test", "tests_of", "resolve_test",
           "pytest_index", "check_registry", "CONDITION_KEYS", "ROM_KEYS"]


if __name__ == "__main__":
    sys.exit(main())
