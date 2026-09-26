"""まんたんの設定 — ★画面で変えた値を、設定ファイルの上に重ねる（RX3-0160 / 2026-09-11）。

★調査（RX3-0158 / `docs/research/dq3-mantan-settings-poc.md` §14）の推奨案です。

```text
config/dq3_phase0.yaml の mantan:          ★既定（人が書く / 註つき / ⚠ 画面は書き換えない）
  ↓ 画面で変えた項目だけ上書き
work/dq3-ui-settings.json の mantan        ★各自（Git 管理外 / 戦闘 AI と同じ UiSettings）
  ↓ write_overlay()
work/generated/dq3_mantan.lua             ★まんたんが**始めるたびに**読む（⚠ 再起動が要らない）
```

## ★画面に出すのは、次の 6 つだけ（§10 ＋ RX3-0174 の回復のしかた ＋ RX3-0214 の唱えてよい人）

```text
healer    回復役（p1〜p4）          ★v1: 同じくらい良いときに優先する人（⚠ 呪文の表が無いときは この人がホイミ）
                                   ⚠ RX3-0221: 画面からは消した（唱えてよい人と重なる）→ ★設定ファイルの控えだけ
hp_below  回復を始める HP（%）      ★この % 未満の人を治す
min_mp    残す MP                  ★唱えた**後**にこれだけ残す（★v1 / 2026-09-12 依頼者の判断 / 既定 0）
turbo     まんたんの間だけ速くする
heal_order 回復のしかた             ★呪文を優先 / 道具を優先 / 道具を使わない（2026-09-11 依頼者）
casters   唱えてよい人（p1〜p4）    ★チェックした人だけ唱える（既定 全員）。★勇者は ほかに唱えられる人が居ない時だけ（RX3-0214）
```

⚠ 呪文・押す間隔・待ち・上限は**出しません**（★実測で決めた値 / 一覧の 1 番目しか選べない）。

## ⚠⚠ 設定が壊れていても開けること（★DQ2 の `retroux/core/mantan` と同じ考え）

★読めない値は**既定へ落として、理由を `problems` に残します**（⚠ 黙って捨てない）。
"""
from __future__ import annotations

import dataclasses
import pathlib

from .. import paths as P3

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "dq3_phase0.yaml"
#: ★UiSettings の置き場（⚠ 戦闘 AI と同じファイル / 別の節）
SECTION = "mantan"
KEY = "v1"
#: ★まんたんが読む重ね書き（⚠ 書き先は隔離先を意識する / 戦闘 AI の生成物と同じ）
OVERLAY_NAME = "dq3_mantan.lua"

HEALERS = ("p1", "p2", "p3", "p4")
HP_MIN, HP_MAX, HP_STEP = 50, 100, 5
MP_MIN, MP_MAX = 0, 20
FIELDS = ("healer", "hp_below", "min_mp", "turbo", "heal_order", "casters")
#: ★回復のしかた（RX3-0174 / ⚠ Lua の mantan_items.lua と同じ語）
HEAL_ORDERS = ("spell_first", "item_first", "spell_only")
HEAL_ORDER_UI = {"spell_first": "呪文を優先", "item_first": "道具を優先", "spell_only": "道具を使わない"}

#: ★画面の言葉（⚠ 表示名と内部値を 1 か所で結ぶ / DQ2 と同じ）
LABELS = {
    "healer": "回復役",
    "hp_below": "回復を始める HP",
    "min_mp": "残す MP",
    "turbo": "まんたんの間だけ速くする",
    "heal_order": "回復のしかた",
    "casters": "唱えてよい人",
}


@dataclasses.dataclass(frozen=True)
class MantanSettings:
    """★まんたんのつまみ。⚠ 既定は **YAML と同じ値**（★入れた日に動きを変えない）。"""

    healer: str = "p3"
    hp_below: int = 90
    #: ★唱えた**後**に残す MP（★まんたん v1 / 2026-09-12 依頼者の判断 / 既定 0）
    min_mp: int = 0
    turbo: bool = True
    #: ★回復のしかた（RX3-0174）。★既定は「呪文を優先 → 唱えられなければ やくそう」
    heal_order: str = "spell_first"
    #: ★唱えてよい人（RX3-0214 / 2026-09-12 依頼者「対象のキャラを対象にするか否かを決めるチェックボックス」）。★既定は全員
    casters: tuple = HEALERS


DEFAULTS = MantanSettings()


@dataclasses.dataclass(frozen=True)
class Effective:
    """★いま効いている値と、どこから来たか（⚠ 画面が「どちらが効いているか」を出すため）。"""

    value: MantanSettings
    #: ★項目 → `"screen"`（画面で変えた）/ `"file"`（設定ファイル）/ `"default"`
    source: dict
    #: ★設定ファイルに書いてある値（⚠ 画面の「既定」表示用）
    file: dict
    problems: list


# ----------------------------------------------------------------------
# ★値を確かめる
# ----------------------------------------------------------------------
def check(field: str, value):
    """★その項目として正しい値に直す。⚠ 駄目なら `(None, 理由)`。"""
    if field == "healer":
        got = str(value).strip().lower()
        return (got, None) if got in HEALERS else (None, "回復役は p1〜p4 です: %r" % (value,))
    if field == "casters":
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            return None, "唱えてよい人は p1〜p4 の並びです: %r" % (value,)
        got = [str(v).strip().lower() for v in value]
        if any(v not in HEALERS for v in got):
            return None, "唱えてよい人は p1〜p4 です: %r" % (value,)
        picked = tuple(s for s in HEALERS if s in got)          # ★並びの順（⚠ 重ねても 1 回）
        return (picked, None) if picked else (None, "唱えてよい人を 1 人は選んでください")
    if field == "heal_order":
        got = str(value).strip().lower()
        return (got, None) if got in HEAL_ORDERS else (
            None, "回復のしかたは %s です: %r" % (" / ".join(HEAL_ORDERS), value))
    if field == "turbo":
        if isinstance(value, bool):
            return value, None
        return None, "ターボは true / false です: %r" % (value,)
    if field in ("hp_below", "min_mp"):
        if isinstance(value, bool):
            return None, "%s は数です: %r" % (LABELS[field], value)
        try:
            got = int(value)
        except (TypeError, ValueError):
            return None, "%s は数です: %r" % (LABELS[field], value)
        lo, hi = (HP_MIN, HP_MAX) if field == "hp_below" else (MP_MIN, MP_MAX)
        if not lo <= got <= hi:
            return None, "%s は %d〜%d です: %r" % (LABELS[field], lo, hi, value)
        return got, None
    return None, "知らない項目です: %s" % field


def _checked(raw: dict, where: str) -> tuple[dict, list]:
    out, problems = {}, []
    for field in FIELDS:
        if field not in (raw or {}):
            continue
        got, why = check(field, raw[field])
        if why:
            problems.append("⚠ %s の %s" % (where, why))
        else:
            out[field] = got
    return out, problems


# ----------------------------------------------------------------------
# ★読む
# ----------------------------------------------------------------------
#: ★YAML の読み込みを覚えておく（⚠ 右画面は 0.5 秒ごとに見るので、毎回開かない）
_YAML_CACHE: dict = {}


def _file_mantan(config_path: pathlib.Path) -> tuple[dict, str | None]:
    """★設定ファイルの `mantan:` 丸ごと（⚠ 変わったときだけ読み直す / 更新時刻で見る）。"""
    import yaml

    path = pathlib.Path(config_path)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError as err:
        return {}, "⚠ 設定ファイルを読めません: %s" % err
    got = _YAML_CACHE.get(str(path))
    if got is not None and got[0] == stamp:
        return got[1], got[2]
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw, why = dict((cfg.get("dq3_phase0") or {}).get("mantan") or {}), None
    except (OSError, ValueError, yaml.YAMLError) as err:
        raw, why = {}, "⚠ 設定ファイルを読めません: %s" % err
    _YAML_CACHE[str(path)] = (stamp, raw, why)
    return raw, why


def file_values(config_path: pathlib.Path = CONFIG) -> tuple[dict, list]:
    """★設定ファイル（YAML）の 4 項目。⚠ 読めなければ空と理由。"""
    raw, why = _file_mantan(config_path)
    if why:
        return {}, [why]
    return _checked(raw, "設定ファイル")


def file_spell(config_path: pathlib.Path = CONFIG) -> str:
    """★設定ファイルの呪文（⚠ 画面では変えない / 表示だけ）。"""
    raw, _why = _file_mantan(config_path)
    return str(raw.get("spell") or "ホイミ")


def overrides(settings) -> tuple[dict, list]:
    """★画面で変えた項目だけ。⚠ 読めなければ空と理由。"""
    if settings is None:
        return {}, []
    raw = settings.get(SECTION, KEY, None)
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["⚠ 画面の設定が壊れています（★設定ファイルの値で動きます）"]
    return _checked(raw, "画面の設定")


def effective(settings, config_path: pathlib.Path = CONFIG) -> Effective:
    """★いま効いている値（★画面 > 設定ファイル > 既定）。"""
    file, p1 = file_values(config_path)
    over, p2 = overrides(settings)
    value, source = {}, {}
    for field in FIELDS:
        if field in over:
            value[field], source[field] = over[field], "screen"
        elif field in file:
            value[field], source[field] = file[field], "file"
        else:
            value[field], source[field] = getattr(DEFAULTS, field), "default"
    return Effective(value=MantanSettings(**value), source=source, file=file,
                     problems=p1 + p2)


# ----------------------------------------------------------------------
# ★書く（⚠ YAML には書かない）
# ----------------------------------------------------------------------
def set_value(settings, field: str, value) -> str | None:
    """★1 項目を画面の値にする。⚠ 駄目な値なら書かずに理由を返す。"""
    got, why = check(field, value)
    if why:
        return why
    over, _ = overrides(settings)
    over[field] = got
    settings.set(SECTION, KEY, over)
    return None


def reset(settings, field: str | None = None) -> None:
    """★画面で変えた値を消す（⚠ 設定ファイルの値に戻る）。"""
    over, _ = overrides(settings)
    if field is None:
        over = {}
    else:
        over.pop(field, None)
    settings.set(SECTION, KEY, over)


def overlay_path(out_dir: pathlib.Path | None = None) -> pathlib.Path:
    return pathlib.Path(out_dir or P3.work("generated")) / OVERLAY_NAME


def overlay_lua(settings) -> str:
    """★まんたんへ渡す Lua（⚠ 画面で変えた項目だけ / 無ければ空の表）。"""
    over, _ = overrides(settings)
    parts = []
    for field in FIELDS:
        if field not in over:
            continue
        v = over[field]
        if isinstance(v, bool):
            text = "true" if v else "false"
        elif isinstance(v, int):
            text = str(v)
        elif isinstance(v, (list, tuple)):
            text = "{%s}" % ", ".join('"%s"' % s for s in v)   # ★p1〜p4 だけ（check 済み / RX3-0214）
        else:
            text = '"%s"' % v                      # ★p1〜p4 / 回復のしかたの語だけ（check 済み）
        parts.append("%s = %s" % (field, text))
    return ("-- ★まんたんの画面の設定（RX3-0160）。⚠ 手で書かない（画面が作り直します）\n"
            "return {%s}\n" % ", ".join(parts))


def write_overlay(settings, out_dir: pathlib.Path | None = None) -> pathlib.Path:
    """★まんたんが次に始めるときに読む（⚠ 途中で書き換わらないよう一時ファイル → 置き換え）。"""
    path = overlay_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".lua.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(overlay_lua(settings))
    tmp.replace(path)
    return path


def summary(eff: Effective, names: dict | None = None) -> str:
    """★右画面の 1 行（⚠ 短く / 360px）。"""
    v = eff.value
    # ★唱える人（RX3-0221: 回復役の欄を消したので、右画面も唱えてよい人を出す / ★全員なら「全員」）
    names = names or {}
    who = "全員" if tuple(v.casters) == HEALERS else "・".join(names.get(s) or s for s in v.casters)
    text = "%s・HP %d%% 未満" % (who, v.hp_below)
    # ★回復のしかたは既定（呪文を優先）と違うときだけ（⚠ 360px に収める / RX3-0174）
    if v.heal_order != DEFAULTS.heal_order:
        text += "・" + HEAL_ORDER_UI.get(v.heal_order, v.heal_order)
    return text


__all__ = ["MantanSettings", "Effective", "DEFAULTS", "FIELDS", "LABELS", "HEALERS",
           "HP_MIN", "HP_MAX", "HP_STEP", "MP_MIN", "MP_MAX", "SECTION", "KEY",
           "HEAL_ORDERS", "HEAL_ORDER_UI",
           "check", "file_values", "file_spell", "overrides", "effective", "set_value", "reset",
           "overlay_lua", "overlay_path", "write_overlay", "summary"]
