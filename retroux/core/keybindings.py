"""キーバインドの読み込み・マージ・検証（2026-08-01 の指示書 §12・§14）。

★★ **3層**（指示書 §2）★★

    retroux/config/default_keybindings.yaml   既定（同梱・編集させない）
      ↓ 書いてある項目だけ上書き
    config/keybindings.yaml                   利用者の設定
      ↓
    実行時のキー割り当て

## ⚠⚠ **設定が壊れていても RetroUX は起動できること**（指示書 §14.4）

  キーが1つ間違っているだけでゲームが遊べなくなるのは筋が悪い。
  読めないときは**既定値へ落として、理由を持って画面に出す**。

## キー表記の正規化（指示書 §12.3）

  `ctrl+r` も `Shift+Ctrl+R` も、内部では `Ctrl+Shift+R` にそろえる。
  ⚠ そろえないと「重複しているのに気づけない」。
  修飾キーの順番は **Ctrl → Alt → Shift** に固定する。
"""

from __future__ import annotations

import dataclasses
import pathlib

from .actions import ACTION_BY_NAME, CONTEXTS, action_names

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "retroux" / "config" / "default_keybindings.yaml"
USER_PATH = PROJECT_ROOT / "config" / "keybindings.yaml"

#: この版が読める形。★上げるときは移行のしかたも一緒に決める。
SCHEMA_VERSION = 1

#: 修飾キーの並び順。⚠ **固定する**（順番が違うと別のキーに見える）
MODIFIER_ORDER = ("Ctrl", "Alt", "Shift")
_MODIFIER_ALIASES = {
    "ctrl": "Ctrl", "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
}

#: 修飾キー以外で使える名前。★FCEUX の `input.get()` が返す綴りに合わせる。
_NAMED_KEYS = {
    "escape": "Escape", "esc": "Escape",
    "space": "Space", "tab": "Tab", "enter": "Enter", "return": "Enter",
    "backspace": "Backspace", "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
}
for _n in range(1, 13):
    _NAMED_KEYS[f"f{_n}"] = f"F{_n}"


@dataclasses.dataclass
class Issue:
    """検証で見つかったこと。★**どこが**悪いかまで持つ。"""

    level: str          # "error" / "warning"
    where: str          # 例: toggle_auto.keyboard[0]
    message: str

    def __str__(self) -> str:
        head = "エラー" if self.level == "error" else "警告"
        return f"{head}：{self.where}\n{self.message}"


def normalize_key(text: str) -> tuple[str | None, str | None]:
    """キー表記をそろえる。戻り値: `(正規化した表記, 悪い理由)`。

    ★片方は必ず None。**理由を返す**のは、設定画面で直し方を出すため。

        ctrl+r        -> Ctrl+R
        Shift+Ctrl+R  -> Ctrl+Shift+R
        f9            -> F9
        Ctr+A         -> None, 「Ctr」は修飾キーではありません
    """
    raw = str(text or "").strip()
    if not raw:
        return None, "キーが空です"

    parts = [p.strip() for p in raw.split("+")]
    if any(not p for p in parts):
        return None, f"「{raw}」の書き方が正しくありません（+ の前後が空です）"

    mods: set = set()
    main: str | None = None
    #: 打ち間違いを直した場合の「こう書いてください」（指示書 §13.4 の例）。
    #  ★★ **部品ではなく全体の表記を出す。** ★★
    #    「『Ctrl』を使用してください」だと、利用者は結局どう書けばよいか
    #    自分で組み立てることになる。⚠ そのまま貼れる形で出す。
    typo: str | None = None

    for part in parts:
        low = part.lower()
        if low in _MODIFIER_ALIASES:
            mods.add(_MODIFIER_ALIASES[low])
            continue
        near = {"ctr": "Ctrl", "ctl": "Ctrl", "cntrl": "Ctrl",
                "shft": "Shift", "sft": "Shift", "altgr": "Alt"}.get(low)
        if near is not None:
            mods.add(near)
            typo = typo or part
            continue
        if main is not None:
            return None, f"「{raw}」にキーが2つ以上あります"
        if low in _NAMED_KEYS:
            main = _NAMED_KEYS[low]
        elif len(part) == 1 and (part.isalpha() or part.isdigit()):
            main = part.upper()
        else:
            return None, f"「{part}」は知らないキーです"

    if main is None:
        # ⚠ 修飾キーだけの指定（指示書 §13.4）
        return None, f"「{raw}」は修飾キーだけです。組み合わせるキーが要ります"

    ordered = [m for m in MODIFIER_ORDER if m in mods]
    fixed = "+".join(ordered + [main])
    if typo is not None:
        return None, (f"キー表記「{raw}」は不正です。"
                      f"「{fixed}」を使用してください。")
    return fixed, None


def _read_yaml(path: pathlib.Path) -> tuple[dict | None, str | None]:
    """YAML を読む。戻り値: `(中身, 失敗の理由)`。"""
    import yaml

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None                   # ★無いのは異常ではない
    except OSError as exc:
        return None, f"{path.name} を読めません: {exc}"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"{path.name} の書き方が正しくありません: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"{path.name} の中身が辞書ではありません"
    return data, None


def validate(data, *, source: str = "設定") -> list[Issue]:
    """中身を検査する（指示書 §13.4）。★**保存する前に**呼ぶ。

    ⚠ 1つ目で止めない。**まとめて**返す。
      1件ずつ直させると、直しては怒られるを繰り返すことになる。
    """
    issues: list[Issue] = []
    if not isinstance(data, dict):
        return [Issue("error", source, "中身が辞書ではありません")]

    version = data.get("schema_version")
    if version is None:
        issues.append(Issue("error", "schema_version",
                            "schema_version がありません"))
    elif version != SCHEMA_VERSION:
        issues.append(Issue(
            "error", "schema_version",
            f"この版が読めるのは {SCHEMA_VERSION} です（{version!r} でした）"))

    bindings = data.get("bindings")
    if bindings is None:
        issues.append(Issue("error", "bindings", "bindings がありません"))
        return issues
    if not isinstance(bindings, dict):
        issues.append(Issue("error", "bindings", "bindings が辞書ではありません"))
        return issues

    # ★★ 全体でのキーの重複を見る（指示書 §14.2）★★
    #   ⚠ 第一弾は context の切り替えが無いので**全体で禁止**。
    #     許すと「押しても片方しか動かない」が静かに起きる。
    seen: dict = {}

    for name, spec in bindings.items():
        if name not in ACTION_BY_NAME:
            issues.append(Issue(
                "error", str(name),
                f"知らないアクションです。使えるのは: {', '.join(action_names())}"))
            continue
        if not isinstance(spec, dict):
            issues.append(Issue("error", str(name), "中身が辞書ではありません"))
            continue

        context = spec.get("context", ACTION_BY_NAME[name].context)
        if context not in CONTEXTS:
            issues.append(Issue(
                "error", f"{name}.context",
                f"知らない context です（使えるのは: {', '.join(CONTEXTS)}）"))

        keys = spec.get("keyboard", [])
        if keys is None:
            keys = []
        if not isinstance(keys, list):
            issues.append(Issue(
                "error", f"{name}.keyboard",
                "keyboard はリストで書いてください（例: [A]）"))
            continue

        normalized: list[str] = []
        for i, key in enumerate(keys):
            where = f"{name}.keyboard[{i}]"
            fixed, why = normalize_key(key)
            if fixed is None:
                issues.append(Issue("error", where, str(why)))
                continue
            if fixed in normalized:
                issues.append(Issue(
                    "error", where,
                    f"同じアクションの中で「{fixed}」が重複しています"))
                continue
            normalized.append(fixed)
            other = seen.get(fixed)
            if other is not None:
                issues.append(Issue(
                    "error", where,
                    f"「{fixed}」が {other} と重複しています"
                    "（同じキーに2つの操作を割り当てられません）"))
            else:
                seen[fixed] = name

        # ★この版で動かないアクションにキーを配ってしまわないよう知らせる
        if normalized and not ACTION_BY_NAME[name].implemented:
            issues.append(Issue(
                "warning", name,
                f"『{ACTION_BY_NAME[name].label}』はこの版では動きません"
                "（キーを設定しても何も起きません）"))
    return issues


@dataclasses.dataclass
class Keybindings:
    """実行時のキー割り当て。"""

    #: {アクション名: [正規化したキー]}
    keys: dict = dataclasses.field(default_factory=dict)
    #: {アクション名: context}
    contexts: dict = dataclasses.field(default_factory=dict)
    #: ⚠ 読み込みで気づいたこと。**捨てずに持って画面に出す**
    problems: list = dataclasses.field(default_factory=list)
    #: 利用者の設定を使えたか（False なら既定値で動いている）
    used_user_file: bool = False

    def action_for(self, key: str) -> str | None:
        """押されたキーからアクション名を引く。★正規化してから引く。"""
        fixed, _ = normalize_key(key)
        if fixed is None:
            return None
        for name, keys in self.keys.items():
            if fixed in keys:
                return name
        return None

    def keys_for(self, action: str) -> list:
        return list(self.keys.get(action, ()))

    def as_dict(self) -> dict:
        """YAML に出す形。★アクションの並びは定義順（差分が読みやすい）。"""
        return {
            "schema_version": SCHEMA_VERSION,
            "bindings": {
                name: {
                    "context": self.contexts.get(
                        name, ACTION_BY_NAME[name].context),
                    "keyboard": list(self.keys.get(name, ())),
                    "restore_emulator_focus":
                        ACTION_BY_NAME[name].restore_emulator_focus,
                }
                for name in action_names()
            },
        }


def _build(data: dict) -> Keybindings:
    """検証済みの辞書から実行時の形を作る。"""
    made = Keybindings()
    bindings = data.get("bindings") or {}
    for name in action_names():
        spec = bindings.get(name) or {}
        made.contexts[name] = spec.get("context", ACTION_BY_NAME[name].context)
        keys = spec.get("keyboard") or []
        fixed_keys = []
        for key in keys:
            fixed, why = normalize_key(key)
            if fixed is not None:
                fixed_keys.append(fixed)
        made.keys[name] = fixed_keys
    return made


def load(default_path=None, user_path=None) -> Keybindings:
    """既定＋利用者の設定を読み、実行時の形にする。

    ★★ **利用者の設定が壊れていても起動する**（指示書 §14.4）★★
      その場合は既定値で動き、理由を `problems` に持つ。

    ⚠ マージは**アクション単位**（指示書 §12.2）。
      利用者が `toggle_auto` だけ書いたら、他は既定のまま。
      キーの配列ごと差し替えるので、「既定の A も残る」ことはない。
    """
    default_file = pathlib.Path(default_path or DEFAULT_PATH)
    user_file = pathlib.Path(user_path or USER_PATH)

    base, why = _read_yaml(default_file)
    if base is None:
        # ⚠⚠ 同梱の既定が読めないのは**こちらの落ち度**。
        #   それでも起動は止めない（キー無しで遊べる）。
        made = Keybindings()
        for name in action_names():
            made.keys[name] = []
            made.contexts[name] = ACTION_BY_NAME[name].context
        made.problems.append(
            why or f"既定のキーバインド（{default_file.name}）がありません")
        return made

    problems: list = []
    base_issues = [i for i in validate(base, source=default_file.name)
                   if i.level == "error"]
    if base_issues:
        problems.append(f"同梱の既定キーバインドに問題があります: "
                        + "／".join(i.message for i in base_issues[:2]))

    merged = {"schema_version": base.get("schema_version", SCHEMA_VERSION),
              "bindings": dict(base.get("bindings") or {})}

    user, why = _read_yaml(user_file)
    used_user = False
    if why is not None:
        problems.append(f"{why}（既定値で動きます）")
    elif user is not None:
        issues = validate(user, source=user_file.name)
        errors = [i for i in issues if i.level == "error"]
        if errors:
            # ★★ **部分的に採らない。** ★★
            #   1つでもエラーがあれば利用者の設定は使わない。
            #   ⚠ 半分だけ効いた状態は「なぜこのキーが動かないか」が
            #     いちばん分かりにくい壊れ方。
            problems.append(
                f"{user_file.name} に問題があるため既定値で動きます: "
                + "／".join(f"{i.where} {i.message}" for i in errors[:3]))
        else:
            for name, spec in (user.get("bindings") or {}).items():
                if isinstance(spec, dict):
                    merged["bindings"][name] = {
                        **(merged["bindings"].get(name) or {}), **spec}
            used_user = True
            problems.extend(str(i) for i in issues if i.level == "warning")

    made = _build(merged)
    made.problems = problems
    made.used_user_file = used_user
    return made


#: Lua が**自分で実行する**アクション。
#
# ★ここに無いものは Lua が「押された」と伝えるだけで、実行は画面側。
#   例: 地図を開く（窓を作るのは Qt の仕事）。
LUA_HANDLED = ("toggle_auto", "toggle_turbo", "emergency_manual")


def to_lua(bindings: "Keybindings") -> str:
    """Lua が読む形にする（`work/generated/keybindings.lua`）。

    ★★ **キーを拾えるのは Lua だけ**（2026-08-01 に実機で判明）★★

      遊んでいる間フォーカスは FCEUX にあるので、⚠ **画面側は
      キーを1つも見られない**。当初は「地図を開くのは画面の担当」として
      Lua へ渡していなかったが、その結果 `G` が**構造的に死んでいた**
      （押しても何も起きない。実機で指摘された）。

      → **全部のアクションを Lua へ渡す。** Lua は
        ・自分でできるもの（`LUA_HANDLED`）はその場で実行
        ・できないものは「押された」と書くだけ（画面が拾って実行する）

    ⚠ 修飾キー付き（`Ctrl+K` 等）は**渡さない**。FCEUX の `input.get()` は
      修飾キーを別項目で返すため、単独キーと同じようには扱えない。
      渡すと「設定したのに効かない」になるので、こちらで落とす。
      ★そちらは画面にフォーカスがあるときに使う（設定・編集の操作なので困らない）。
    """
    lines = [
        "-- 自動生成ファイル。直接編集しないこと。",
        "-- 生成元: retroux/config/default_keybindings.yaml"
        " + config/keybindings.yaml",
        "-- 生成: retroux/core/config/generate_lua.py",
        "--",
        "-- ★アクション名 -> キーの並び。Lua はキーの意味を知らない。",
        "--",
        "-- ★`handled` は Lua が自分で実行するもの。",
        "--   それ以外は「押された」と state.json へ書くだけで、実行は画面側。",
        "return {",
        "  keys = {",
    ]
    for name in action_names():
        keys = [k for k in bindings.keys_for(name) if "+" not in k]
        if not keys:
            continue
        body = ", ".join('"%s"' % k for k in keys)
        lines.append(f"    {name} = {{{body}}},")
    lines.append("  },")
    lines.append("  handled = {")
    for name in LUA_HANDLED:
        lines.append(f"    {name} = true,")
    lines.append("  },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_lua(out_dir, bindings: "Keybindings" = None):
    """`keybindings.lua` を書き出す。戻り値は書いた場所。"""
    made = bindings if bindings is not None else load()
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "keybindings.lua"
    path.write_text(to_lua(made), encoding="utf-8")
    return path


def default_text() -> str:
    """既定の設定ファイルの中身（設定画面の「既定値に戻す」用）。"""
    try:
        return DEFAULT_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
