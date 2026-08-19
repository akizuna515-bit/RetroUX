"""戦術プロフィールの検証（2026-07-30 / 仕様書 12.3・12.4・12.5・13章）。

★★ **勝手に直さない。おかしいと言う。** ★★

  仕様書 12.4:
    > 範囲外の場合、**自動補正せずエラーとする**。

  仕様書 12.5:
    > 将来バージョンの設定を古い RetroUX で読み込んだ場合、
    > **勝手に無視しない。**

  理由: プロフィールは「利用者が設計した戦術」なので、
  勝手に 100 へ丸めた値で戦うと**設定した戦術と違う戦い方**になる。
  しかも本人は気づけない。

## 3つの重さを分ける

| 種類 | 意味 | インポートできるか |
| --- | --- | --- |
| `error` | 形が壊れている・値が範囲外 | ✗ できない |
| `unknown` | 知らない項目（新しい版で作った？） | △ 利用者が明示的に許せば |
| `warning` | 形は正しいが、いまは効かない | ○ できる（理由を出す） |

⚠ `unknown` を `warning` にしてはいけない。
  「知らない項目があるが読み込んだ」を黙って通すと、
  **新しい版の戦術が古い版で別物として動く**。
"""

from __future__ import annotations

import dataclasses

from . import models
from .profile import ID_PATTERN

#: YAML の最大サイズ（仕様書 13章）。★戦術の設定に 256KB は要らない
MAX_BYTES = 256 * 1024
#: YAML の最大の深さ（仕様書 13章）。★異常な入れ子で読み込み側を潰させない
MAX_DEPTH = 8


class Severity(str):
    ERROR = "error"
    UNKNOWN = "unknown"
    WARNING = "warning"


@dataclasses.dataclass(frozen=True)
class Issue:
    """見つけたこと1件。★**どこの話か**を必ず持つ（直せるように）。"""

    severity: str
    where: str
    message: str

    def __str__(self) -> str:
        mark = {"error": "✗", "unknown": "？", "warning": "⚠"}.get(
            self.severity, "・")
        return f"{mark} {self.where}: {self.message}"


@dataclasses.dataclass
class Result:
    """検証の結果。**全部まとめて**返す（1つ目で止めない）。"""

    issues: list = dataclasses.field(default_factory=list)

    def add(self, severity: str, where: str, message: str) -> None:
        self.issues.append(Issue(severity, where, message))

    def of(self, severity: str) -> list:
        return [i for i in self.issues if i.severity == severity]

    @property
    def errors(self) -> list:
        return self.of(Severity.ERROR)

    @property
    def unknowns(self) -> list:
        return self.of(Severity.UNKNOWN)

    @property
    def warnings(self) -> list:
        return self.of(Severity.WARNING)

    @property
    def ok(self) -> bool:
        """★`error` が無ければ「読める」。`unknown` は呼ぶ側の判断。"""
        return not self.errors

    def can_import(self, allow_unknown: bool = False) -> bool:
        """インポートしてよいか。

        ⚠ `allow_unknown` の既定は **False**（仕様書 12.5「勝手に無視しない」）。
        """
        if self.errors:
            return False
        return allow_unknown or not self.unknowns

    def lines(self) -> list:
        return [str(i) for i in self.issues]


def depth_of(value, level: int = 1) -> int:
    """入れ子の深さ。★上限を超えたら**そこで数えるのをやめる**。

    ⚠ 数え切ろうとすると、異常な入力で再帰が深くなる（守りたいものと同じ穴）。
    """
    if level > MAX_DEPTH:
        return level
    if isinstance(value, dict):
        return max((depth_of(v, level + 1) for v in value.values()),
                   default=level)
    if isinstance(value, (list, tuple)):
        return max((depth_of(v, level + 1) for v in value), default=level)
    return level


def validate_raw(raw) -> Result:
    """YAML から読んだ生の形を検証する（仕様書 12.3 の順）。"""
    result = Result()

    # 1. 形
    if not isinstance(raw, dict):
        result.add(Severity.ERROR, "全体",
                   "トップレベルがマッピングではありません（YAML の書き方を確認）")
        return result
    if depth_of(raw) > MAX_DEPTH:
        result.add(Severity.ERROR, "全体",
                   f"入れ子が深すぎます（上限 {MAX_DEPTH}）")
        return result

    # 2. schema_version（仕様書 10.3 / **必須**）
    version = raw.get("schema_version")
    if version is None:
        result.add(Severity.ERROR, "schema_version",
                   "ありません（必須項目です）")
    elif isinstance(version, bool) or not isinstance(version, int):
        result.add(Severity.ERROR, "schema_version",
                   f"整数ではありません: {version!r}")
    elif version > models.SCHEMA_VERSION:
        # ⚠ 新しい版で作られたもの。**勝手に読まない**（仕様書 10.3）
        result.add(Severity.ERROR, "schema_version",
                   f"この RetroUX が知らない版です（{version} > "
                   f"{models.SCHEMA_VERSION}）。RetroUX を更新してください")
    elif version < 1:
        result.add(Severity.ERROR, "schema_version", f"版が不正です: {version}")

    # 3. profile の必須項目
    head = raw.get("profile")
    if not isinstance(head, dict):
        result.add(Severity.ERROR, "profile", "ありません（必須項目です）")
    else:
        _check_head(head, result)
        for key in head:
            if key not in ("id", "name", "description", "created_at",
                           "updated_at"):
                result.add(Severity.UNKNOWN, f"profile.{key}",
                           "知らない項目です")

    # 4. characters
    chars = raw.get("characters")
    if not isinstance(chars, dict):
        result.add(Severity.ERROR, "characters", "ありません（必須項目です）")
    else:
        if not chars:
            result.add(Severity.ERROR, "characters",
                       "1人も入っていません（3人ぶん必要です）")
        for cid, body in chars.items():
            _check_character(str(cid), body, result)

    for key in raw:
        if key not in ("schema_version", "profile", "characters"):
            result.add(Severity.UNKNOWN, key, "知らない項目です")
    return result


def _check_head(head: dict, result: Result) -> None:
    profile_id = head.get("id")
    if not profile_id:
        result.add(Severity.ERROR, "profile.id", "ありません（必須項目です）")
    elif not isinstance(profile_id, str):
        result.add(Severity.ERROR, "profile.id", "文字列ではありません")
    elif not ID_PATTERN.match(profile_id):
        # ★ファイル名になるので厳しくする（`../` などを作らせない / 仕様書 13章）
        result.add(Severity.ERROR, "profile.id",
                   f"英小文字・数字・`_` だけにしてください: {profile_id!r}")
    name = head.get("name")
    if name is not None and not isinstance(name, str):
        result.add(Severity.ERROR, "profile.name", "文字列ではありません")
    description = head.get("description")
    if description is not None and not isinstance(description, str):
        result.add(Severity.ERROR, "profile.description", "文字列ではありません")


def _check_character(cid: str, body, result: Result) -> None:
    where = f"characters.{cid}"
    if cid not in models.CHARACTER_IDS:
        # ⚠ 知らないキャラクターは**エラー**（誰の設定か決まらない）
        result.add(Severity.ERROR, where,
                   "知らないキャラクターです（使えるのは "
                   + " / ".join(models.CHARACTER_IDS) + "）")
        return
    if not isinstance(body, dict):
        result.add(Severity.ERROR, where, "マッピングではありません")
        return

    for key, value in body.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                _check_field(where, str(key), str(sub_key), sub_value, result)
        else:
            _check_field(where, "root", str(key), value, result)


def _check_field(where: str, section: str, key: str, value,
                 result: Result) -> None:
    path = f"{where}.{key}" if section == "root" else f"{where}.{section}.{key}"
    field = models.FIELD_BY_PATH.get((section, key))
    if field is None:
        result.add(Severity.UNKNOWN, path, "知らない項目です")
        return

    if field.kind == "bool":
        if not isinstance(value, bool):
            result.add(Severity.ERROR, path,
                       f"true / false ではありません: {value!r}")
    elif field.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            result.add(Severity.ERROR, path, f"整数ではありません: {value!r}")
        else:
            # ⚠ 範囲外は**自動補正せずエラー**（仕様書 12.4）
            if field.minimum is not None and value < field.minimum:
                result.add(Severity.ERROR, path,
                           f"{field.minimum} 以上にしてください: {value}")
            if field.maximum is not None and value > field.maximum:
                result.add(Severity.ERROR, path,
                           f"{field.maximum} 以下にしてください: {value}")
    elif field.kind == "enum":
        parsed = field.enum_cls.parse(value) if field.enum_cls else None
        if parsed is None:
            allowed = " / ".join(m.value for m in field.enum_cls)
            result.add(Severity.ERROR, path,
                       f"知らない値です: {value!r}（使えるのは {allowed}）")

    # ★形は正しいが、いまは効かない項目（仕様書 20章）
    if not field.implemented:
        result.add(Severity.WARNING, path,
                   f"いまは効きません（フェーズ{field.phase}で対応予定）"
                   "。値は保存され、対応したときに効きます")


def validate_profile(prof) -> Result:
    """`TacticsProfile` を検証する（保存の前に使う）。"""
    return validate_raw(prof.to_dict())
