"""大目的の読み書き（2026-08-05 / 戦闘AI再設計 Phase 3）。

★`config/mantan.yaml` と同じ流儀です（`core/mantan/repository.py`）。

## ⚠⚠ 書きかけのファイルを残さない

  同じ名前へ直接書くと、途中で落ちたときに**壊れた設定が残り**、
  次の起動で読めなくなります。
  ★隣に書いてから `os.replace` で置き換えます（同じディスク上なら不可分）。

## ⚠ 読めなくても落ちない

  設定が読めないことと、ゲームが遊べないことは別です。
  ★読めなければ既定（ダンジョン攻略）で動き、**理由を返します**。
"""

from __future__ import annotations

import os
import pathlib
import tempfile

import yaml

from .settings import USER_PATH, Mission, MissionSettings, Risk

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _path(path=None) -> pathlib.Path:
    if path is not None:
        return pathlib.Path(path)
    return PROJECT_ROOT / USER_PATH


def from_dict(data, base: MissionSettings | None = None):
    """辞書から設定を作る。戻り値は `(設定, 気づいたことの一覧)`。

    ⚠ 例外を投げません。**呼ぶ側が起動できなくなるのを避けるため**。
    """
    base = base or MissionSettings()
    problems: list[str] = []
    if data is None:
        return base, problems
    if not isinstance(data, dict):
        return base, ["設定の中身が読めませんでした。既定値で動きます"]

    version = data.get("schema_version")
    if version is not None and version != 1:
        problems.append(
            f"知らない schema_version {version!r} です。"
            "この版が読める形として扱います")

    # ⚠⚠ **知らない値を黙って通さない。** 打ち間違いが別の目的になると、
    #   ★「ボスにしたのに AUTO が入る」のような事故になります。
    mission = Mission.parse(data.get("mission"), None)
    if data.get("mission") is not None and mission is None:
        problems.append(
            f"知らない目的 {data.get('mission')!r} です。"
            f"『{base.mission.value}』のまま続けます"
            f"（使えるのは {' / '.join(m.value for m in Mission)}）")
        mission = base.mission

    risk = Risk.parse(data.get("risk"), None)
    if data.get("risk") is not None and risk is None:
        problems.append(
            f"知らない不確実戦術の許容度 {data.get('risk')!r} です。"
            f"『{base.risk.value}』のまま続けます")
        risk = base.risk

    return MissionSettings(mission=mission or base.mission,
                           risk=risk or base.risk), problems


def load(path=None):
    """設定を読む。戻り値は `(設定, 気づいたことの一覧)`。"""
    target = _path(path)
    if not target.exists():
        # ★無いのは異常ではありません（まだ触っていないだけ）
        return MissionSettings(), []
    try:
        data = yaml.safe_load(target.read_bytes().decode("utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return MissionSettings(), [f"設定を読めません（{target}）: {exc}"]
    return from_dict(data)


def save(settings: MissionSettings, path=None):
    """設定を書く。戻り値は `(書けたか, 理由)`。

    ⚠ 書けなくても**画面の選択は残します**（呼ぶ側の判断 / 指示書 §15）。
    """
    target = _path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"置き場を作れません（{target.parent}）: {exc}"

    text = yaml.safe_dump(settings.to_yaml_dict(), allow_unicode=True,
                          sort_keys=False)
    try:
        # ★隣に書いてから置き換える（途中で落ちても元が残る）
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(target.parent),
            prefix=".mission-", suffix=".tmp", delete=False)
        with handle:
            handle.write(text)
        os.replace(handle.name, target)
    except OSError as exc:
        return False, f"設定を書けません（{target}）: {exc}"
    return True, ""
