"""YAML 設定を FCEUX の Lua が読める形式へ変換する。

FCEUX 内蔵の Lua 5.1 には YAML パーサがないため、マスタである YAML を
Python 側で読み、Lua のテーブルリテラルとして書き出す（DEV-9）。

マスタは常に YAML 側。生成物は work/generated/ に置き、Git 管理しない。

使い方:
    python -m retroux.core.config.generate_lua
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Lua 5.1 の予約語（2026-08-02 に追加）。
#:
#: ⚠⚠ **`k.isidentifier()` は Python の判定で、Lua の予約語を知らない。**
#:   設定に `local:` と書いたら `local = "..."` が生成され、
#:   `unexpected symbol near 'local'` で config.lua ぜんぶが読めなくなった
#:   （テスト14件が赤くなって気づいた）。
#: ★予約語は `["local"] = ...` の形にする。**設定を書く人を守る。**
LUA_KEYWORDS = frozenset({
    "and", "break", "do", "else", "elseif", "end", "false", "for",
    "function", "if", "in", "local", "nil", "not", "or", "repeat",
    "return", "then", "true", "until", "while",
})
PLUGIN_DIR = PROJECT_ROOT / "retroux" / "plugins" / "dq2"
OUT_DIR = PROJECT_ROOT / "work" / "generated"


def to_lua(value: Any, indent: int = 0) -> str:
    """Python の値を Lua のリテラル表記へ変換する。

    Lua のテーブルは 1-based のため、リストは自然に 1-based の配列になる。
    dict のキーが int の場合は `[key]=` 形式にする（モンスターID表など）。
    """
    pad = "  " * indent
    inner_pad = "  " * (indent + 1)

    if isinstance(value, bool):
        # bool は int のサブクラスなので必ず先に判定する
        return "true" if value else "false"
    if value is None:
        return "nil"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, list):
        if not value:
            return "{}"
        items = [f"{inner_pad}{to_lua(v, indent + 1)}," for v in value]
        return "{\n" + "\n".join(items) + f"\n{pad}}}"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = []
        for k, v in value.items():
            rendered = to_lua(v, indent + 1)
            if isinstance(k, int):
                items.append(f"{inner_pad}[{k}] = {rendered},")
            elif (isinstance(k, str) and k.isidentifier()
                  and k not in LUA_KEYWORDS):
                items.append(f"{inner_pad}{k} = {rendered},")
            else:
                items.append(f"{inner_pad}[{to_lua(k)}] = {rendered},")
        return "{\n" + "\n".join(items) + f"\n{pad}}}"

    raise TypeError(f"Lua へ変換できない型です: {type(value).__name__} ({value!r})")


#: ★このプログラムが読める設定スキーマの版（Phase 10 / 2026-08-07）。
#
#  ⚠⚠ **知らない版を黙って読まない。** 将来 DQ3 などを足すとき、
#    古い形の設定をそのまま読むと「効いているつもりで効かない」という、
#    ★いちばん気づきにくい壊れ方になります。
SUPPORTED_SCHEMA = 1


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"トップレベルがマッピングではありません: {path}")

    # ★★ 版を確かめる。⚠ 無いのは古い設定（★止めずに知らせる）。
    version = data.get("schema_version")
    if version is None:
        print(f"⚠ schema_version がありません: {path.name}"
              f"（★{SUPPORTED_SCHEMA} として読みます）")
    elif version != SUPPORTED_SCHEMA:
        # ⚠⚠ **ここは止めます。** 形が違うものを読むと、
        #   ★設定したつもりの項目が黙って捨てられます。
        raise ValueError(
            f"⚠⚠ 読めない設定スキーマです: {path.name} は版 {version!r}、"
            f"このプログラムが読めるのは版 {SUPPORTED_SCHEMA} です。"
            " / ★設定を新しい形へ直すか、プログラムを更新してください。")
    return data


def source_fingerprint(path: Path) -> str:
    """生成元 YAML の指紋。生成物が古いことを Lua 側から検出するために使う。

    ★なぜ必要か（2026-07-26 に実際に起きた事故）:
      依頼者が config.yaml の mode を throttled に変えて試したが
      「変わらない」という結果になった。原因は**生成し直していなかった**こと。
      YAML はマスタだが Lua が読むのは work/generated/*.lua なので、
      生成しない限り**設定を変えても黙って無視される**。

      「生成し忘れ」は必ず起きる。起きたときに**気づけるようにする**のが対策。
      Lua には stat が無く更新時刻を読めないので、
      ここで指紋を埋め込み、Lua 側で YAML を読み直して突き合わせる。

    バイト数と加算チェックサムの組。暗号強度は要らない（改竄対策ではない）。
    編集すればほぼ確実にどちらかが変わる。
    """
    raw = path.read_bytes()
    return f"{len(raw)}:{sum(raw) & 0xFFFFFFFF:08x}"


def write_lua_module(name: str, data: dict, out_dir: Path, src: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.lua"
    body = to_lua(data)
    fp = source_fingerprint(src)
    out_path.write_text(
        "-- 自動生成ファイル。直接編集しないこと。\n"
        f"-- 生成元: retroux/plugins/dq2/{name}.yaml\n"
        f"-- 生成: retroux/core/config/generate_lua.py\n"
        "--\n"
        "-- ★生成元の指紋。Lua 側がこれと実物を突き合わせ、\n"
        "--   生成し忘れ（設定を変えたのに反映されていない状態）を検出する。\n"
        f'local SOURCE_FINGERPRINT = "{fp}"\n'
        f"local DATA = {body}\n"
        "DATA.__source_fingerprint = SOURCE_FINGERPRINT\n"
        "return DATA\n",
        encoding="utf-8",
    )
    return out_path


def _merge_mantan(data: dict) -> dict:
    """まんたんの利用者設定を重ねる（2026-08-02 / 指示書 §13）。

    ★★ **Lua に YAML を読ませない。** ★★
      `config/mantan.yaml` を Lua が直接解析する仕組みは作りません
      （指示書 §13）。Python で読み・検証・同梱設定とマージしてから、
      いつもの `work/generated/config.lua` へ流します。

          config/mantan.yaml
              ↓ Python で読込・検証・マージ
          work/generated/config.lua
              ↓
          FCEUX / Lua

    ⚠ 既存の `mode` / `modes` / `methods` は**消しません**（指示書 §14）。
      新しい値を `mantan` の下に**足すだけ**です。

    ⚠ 設定が壊れていても、ここで止めません。`mantan.load()` が既定値へ
      落として理由を返すので、それをそのまま画面に出せる形で持ちます。
    """
    from ..mantan import load as load_mantan

    settings, problems, _used = load_mantan()
    section = dict(data.get("mantan") or {})
    section.update(settings.to_lua_dict())
    # ★読み込みで気づいたことも Lua へ渡す。**黙って捨てない**
    section["settings_problems"] = list(problems)
    out = dict(data)
    out["mantan"] = section
    for p in problems:
        print(f"⚠ まんたん設定: {p}", file=sys.stderr)
    return out


#: ★利用者が上書きしてよい項目（Phase 10A / 2026-08-07）。
#
#  ⚠⚠ **試すたびに `config.yaml` の原本を書き換えるのは危険です。**
#    ★`config.yaml` は「ゲームの知識」、`user_config.yaml` は
#      「利用者・環境ごとの選択」。engine はどちらかといえば後者です。
#
#  ⚠ さらに `start-retroux.ps1` は**起動のたびに再生成**するので、
#    ★`work/generated/config.lua` を手で書き換えても必ず消えます
#    （2026-08-07 に実際にこれで実機確認が空振りしました）。
#
#  形式: `user_config.yaml` に
#
#      battle:
#        engine: layered      # ★既定は config.yaml の値（legacy）
#
USER_OVERRIDES = {
    # (user_config の道) -> (config.yaml の道)
    ("battle", "engine"): ("auto_input", "engine"),
    # ★出す量の段階（2026-08-13 / 製品版ログ整理 §19）。
    #   ⚠ Lua 側もこれを見る（`bridge.lua` の `Bridge.resolve_log_min`）。
    #     ここを通さないと **Lua だけ常に全部出る**（実測 33,578 行）。
    ("logging", "mode"): ("logging", "mode"),
    # ★研究用の採取（§22）。⚠ 既定は切。通常運用では走らせない。
    ("research", "capture"): ("research", "capture"),
}


def _apply_user_overrides(data: dict) -> dict:
    """`user_config.yaml` の上書きを反映する。

    ⚠ 読めなくても**止めません**（★設定が無いのは普通のこと）。
    ★上書きしたときは必ず知らせます（⚠ 黙って変えない）。
    """
    path = PROJECT_ROOT / "user_config.yaml"
    if not path.exists():
        return data
    try:
        with path.open(encoding="utf-8") as fh:
            user = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        print(f"⚠ user_config.yaml を読めません（★上書きしません）: {exc}")
        return data
    if not isinstance(user, dict):
        return data

    for src_path, dst_path in USER_OVERRIDES.items():
        node = user
        for key in src_path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if node is None:
            continue
        target = data
        for key in dst_path[:-1]:
            target = target.setdefault(key, {})
        before = target.get(dst_path[-1])
        target[dst_path[-1]] = node
        # ★★ **黙って変えない。** ⚠ 何が効いているか分からなくなります。
        print(f"★user_config.yaml で上書き: "
              f"{'.'.join(dst_path)} = {node!r}（元は {before!r}）")
    return data


def main() -> int:
    try:
        written = []
        for name in ("memory_map", "config"):
            src = PLUGIN_DIR / f"{name}.yaml"
            data = load_yaml(src)
            if name == "config":
                data = _merge_mantan(data)
                data = _apply_user_overrides(data)
            written.append(write_lua_module(name, data, OUT_DIR, src))
        # ★キーバインドも Lua へ渡す（2026-08-01 の指示書 §15.1）。
        #   ⚠ Lua に `if key == "A"` を散らさないため。
        #     設定が壊れていても `load()` が既定値へ落とすので、ここは止まらない。
        from ..keybindings import write_lua as write_keybindings

        written.append(write_keybindings(OUT_DIR))
    except (FileNotFoundError, ValueError, TypeError, yaml.YAMLError) as exc:
        print(f"変換に失敗しました: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(f"生成: {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
