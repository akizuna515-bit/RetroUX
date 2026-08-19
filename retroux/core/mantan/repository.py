"""まんたん設定の読み書き（2026-08-02 / 指示書 §3・§4・§5.4）。

## 読み込みの順（指示書 §4.1）

    1. config/mantan.yaml                        利用者の設定
    2. retroux/plugins/dq2/config.yaml の mantan  同梱の既定
    3. コード内の安全な既定値（`MantanSettings()`）

⚠ 利用者の設定に一部しか無いときは、残りを 2 と 3 で埋めます。

## 保存（指示書 §5.4）

★★ **書きかけのファイルを残さない。** ★★
  同じ名前へ直接書くと、途中で落ちたときに**壊れた設定が残り**、
  次の起動で読めなくなります。
  ★隣に書いてから `os.replace` で置き換えます（同じディスク上なら不可分）。
"""

from __future__ import annotations

import os
import pathlib
import tempfile

import yaml

from .settings import USER_PATH, MantanSettings
from .validation import from_dict

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
PLUGIN_CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"


def _read_yaml(path: pathlib.Path, problems: list[str]):
    """YAML を読む。⚠ 壊れていても例外を投げない（指示書 §4.2）。"""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(f"{path.name} を読めませんでした（{exc}）。既定値を使います")
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # ★何行目かまで出す。「どこが悪いか」が分からないと直せない
        where = ""
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            where = f"（{mark.line + 1}行目あたり）"
        problems.append(
            f"{path.name} の書き方が壊れています{where}。既定値で動きます")
        return None


def load(user_path=None, plugin_path=None):
    """まんたんの設定を読む。

    戻り値は `(設定, 気づいたことの一覧, 利用者の設定を使えたか)`。
    ⚠ 例外を投げません。**設定が壊れていても起動できること**が要件です。
    """
    user_path = pathlib.Path(user_path) if user_path else USER_PATH
    plugin_path = pathlib.Path(plugin_path) if plugin_path else PLUGIN_CONFIG
    problems: list[str] = []

    # --- 2. 同梱の既定（プラグインの config.yaml の mantan）---------------
    base = MantanSettings()
    plugin_raw = _read_yaml(plugin_path, problems)
    if isinstance(plugin_raw, dict):
        section = plugin_raw.get("mantan")
        if isinstance(section, dict):
            base, plugin_problems = from_dict(section, base)
            # ⚠ 同梱ファイルの不備は**利用者のせいではない**。区別して出す
            problems.extend(f"同梱の設定: {p}" for p in plugin_problems)

    # --- 1. 利用者の設定（書いてある項目だけ上書き）-----------------------
    user_raw = _read_yaml(user_path, problems)
    if user_raw is None:
        return base, problems, False
    settings, user_problems = from_dict(user_raw, base)
    problems.extend(user_problems)
    return settings, problems, True


def save(settings: MantanSettings, user_path=None) -> pathlib.Path:
    """利用者の設定を書く。★書きかけを残さない（指示書 §5.4）。

    ⚠ 例外は**握りつぶしません**。保存できなかったことは呼ぶ側が
      画面に出す必要があります（黙って失敗するのが一番困る）。
    """
    path = pathlib.Path(user_path) if user_path else USER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    body = yaml.safe_dump(settings.to_yaml_dict(), allow_unicode=True,
                          sort_keys=False, default_flow_style=False)
    header = (
        "# まんたんの設定（RetroUX が書きます / 手で直しても構いません）\n"
        "# ★ここに無い項目は retroux/plugins/dq2/config.yaml の既定を使います。\n"
        "# ⚠ 値が壊れていても RetroUX は起動します。既定へ落として画面に出します。\n")

    # ★同じディレクトリへ書く。別のディスクだと `os.replace` が不可分でなくなる
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".mantan-",
                               suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(header)
            fh.write(body)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)   # ★書きかけを残さない
        raise
    return path
