"""戦術プロフィールの YAML 入出力（2026-07-30 / 仕様書 11章・12章・13章）。

★★ **なぜテキストで出せるようにするのか（仕様書 1章）** ★★

  > 攻略情報を単なる文章ではなく、
  > **実際に戦闘AIが実行できる戦術データ**として扱えるようにする。

だから「読めて・手で直せて・貼って渡せる」ことが要件。YAML を選ぶ理由もそれ。

## ⚠⚠ 安全要件（仕様書 13章）— 外部から来たテキストを読む

| 守ること | どう守るか |
| --- | --- |
| 実行コードを評価しない | `yaml.safe_load` のみ。`load` は使わない |
| 任意の Python オブジェクトを作らせない | 同上（`safe_load` は基本型だけ） |
| ファイルパスを中から読み込まない | プロフィールにパス項目を作らない |
| 外部コマンドを実行しない | そんな項目を作らない |
| 巨大な入力を拒否する | `MAX_BYTES`（256KB） |
| 異常な深さを拒否する | `MAX_DEPTH`（8） |
| 失敗で既存を壊さない | 一時ファイル -> 読み直し -> 置き換え |

⚠ `id` は**ファイル名になる**。`../` を作らせないよう `ID_PATTERN` で縛る
  （検証は `profile_validator` 側）。ここでは検証済みの `id` しか使わない。
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

from . import models
from .profile import TacticsProfile
from .profile_validator import (
    MAX_BYTES, Issue, Result, Severity, validate_raw,
)

#: 貼り付けテキストの上限（ファイルと同じ）
MAX_TEXT_CHARS = MAX_BYTES


def _dump(data: dict) -> str:
    import yaml

    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)


# --- 出す -------------------------------------------------------------

def profile_to_yaml(prof: TacticsProfile) -> str:
    """プロフィールを YAML の文字列にする（貼り付け用・ファイル用の共通）。

    ★先頭に**人が読める説明**を付ける。もらった人が
      「これは何で、どう使うのか」を分かるようにする。
    """
    head = (
        "# RetroUX 戦術プロフィール\n"
        f"# {prof.name}"
        + (f"（{prof.description}）" if prof.description else "")
        + "\n"
        "#\n"
        "# ★このファイルは手で編集できます。RetroUX の\n"
        "#   「戦術プロフィール」画面から読み込めます。\n"
        "#\n"
        "# ⚠ 値の範囲を外れると**自動で直さずエラー**にします\n"
        "#   （設定したものと違う戦術で戦わせないため）。\n"
        "#     HP割合 0〜100 ／ 最低残存MP 0以上 ／ 敵数 1以上\n"
        "#\n"
        "# ⚠ 効くのは "
        + "・".join(f"フェーズ{n}" for n in models.IMPLEMENTED_PHASES)
        + " の項目だけです。\n"
        "#   それ以外は保存されますが、まだ AI へ渡していません。\n"
    )
    return head + "\n" + _dump(prof.to_dict())


def write_profile_file(path, prof: TacticsProfile) -> bool:
    """ファイルへ書く。★**元のファイルを壊さない**（仕様書 13章）。

        一時ファイルへ書く -> 読み直して確かめる -> 置き換える

    ⚠ 「書いた」と「書けた」は別。読み直して同じ内容が返ることを確かめる。
    """
    target = pathlib.Path(path)
    temp = target.with_suffix(target.suffix + ".tmp")
    body = profile_to_yaml(prof)
    try:
        temp.write_text(body, encoding="utf-8")
        # ★読み直して確かめる（途中で切れていたら気づける）
        if temp.read_text(encoding="utf-8") != body:
            temp.unlink(missing_ok=True)
            return False
        os.replace(temp, target)
        return True
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def profile_summary(prof: TacticsProfile) -> str:
    """人が読む要約（仕様書 11.4）。★**再インポート対象ではない**。"""
    return "\n".join(prof.summary_lines())


# --- 読む -------------------------------------------------------------

@dataclasses.dataclass
class ImportPreview:
    """インポートの下見（仕様書 12.7）。★保存の前に必ず見せる。"""

    profile: object
    result: Result
    #: 既にある同じ `id` / 同じ名前のプロフィール（衝突 / 仕様書 12.6）
    conflict_id: str | None = None
    conflict_name: str | None = None

    @property
    def ok(self) -> bool:
        return self.profile is not None and self.result.ok

    def can_import(self, allow_unknown: bool = False) -> bool:
        return self.profile is not None and self.result.can_import(allow_unknown)

    def lines(self) -> list:
        """画面に出す下見（仕様書 12.7）。"""
        made = []
        if self.profile is None:
            made.append("読み込めませんでした。")
        else:
            made.append(f"プロフィール：{self.profile.name}")
            made.append(f"スキーマ：{self.profile.schema_version}")
            for cid in models.CHARACTER_IDS:
                if cid not in self.profile.characters:
                    continue
                role = models.Role.parse(self.profile.get(cid, "root", "role"))
                label = models.ROLE_LABELS.get(role, "？")
                made.append(f"{models.CHARACTER_LABELS.get(cid, cid)}：{label}")
        if self.conflict_id:
            made.append("")
            made.append(f"⚠ 同じID『{self.conflict_id}』のプロフィールが既にあります")
        if self.conflict_name:
            made.append(f"⚠ 同じ名前『{self.conflict_name}』のプロフィールが既にあります")
        if self.result.issues:
            made.append("")
            made.append("見つかったこと：")
            made.extend(self.result.lines())
        return made


def parse_yaml_text(text) -> tuple:
    """YAML の文字列を読む。戻り: `(生の値, Result)`。

    ⚠⚠ **`yaml.safe_load` だけを使う**（仕様書 13章）。
      `yaml.load` は任意の Python オブジェクトを作れるので、
      もらったテキストを読む用途では使えない。
    """
    result = Result()
    if text is None:
        result.add(Severity.ERROR, "全体", "何も入っていません")
        return None, result
    body = str(text)
    if not body.strip():
        result.add(Severity.ERROR, "全体", "空です")
        return None, result
    # ★文字数とバイト数の両方を見る（日本語は1文字3バイト）
    if len(body) > MAX_TEXT_CHARS or len(body.encode("utf-8")) > MAX_BYTES:
        result.add(Severity.ERROR, "全体",
                   f"大きすぎます（上限 {MAX_BYTES // 1024}KB）")
        return None, result
    try:
        import yaml

        raw = yaml.safe_load(body)
    except Exception as exc:                          # noqa: BLE001
        # ⚠ yaml の例外はいろいろ（Scanner/Parser/Composer…）。まとめて拾う
        result.add(Severity.ERROR, "全体", f"YAML として読めません: {exc}")
        return None, result
    return raw, result


def read_profile_text(text, *, repository=None,
                      preset: bool = False) -> ImportPreview:
    """貼り付けテキストからプロフィールを作る（保存はしない）。

    ★**下見を返すだけ**。保存するかは利用者が決める（仕様書 12.3 の 9・10）。
    """
    raw, result = parse_yaml_text(text)
    if raw is None:
        return ImportPreview(None, result)

    checked = validate_raw(raw)
    result.issues.extend(checked.issues)
    if checked.errors:
        # ★形が壊れているものからプロフィールを作らない
        #   （中途半端なものを画面に出すと「読めた」と思われる）
        return ImportPreview(None, result)

    prof = TacticsProfile.from_dict(raw, preset=preset)
    # ⚠ 3人ぶん揃っていなければ**既定で埋める**。
    #   ここは補正ではなく「足りないものを既定にする」なので、
    #   何を足したかを警告として残す。
    for cid in models.CHARACTER_IDS:
        if cid not in prof.characters:
            prof.characters[cid] = models.default_character(
                character_id=cid)
            result.add(Severity.WARNING, f"characters.{cid}",
                       "入っていなかったので既定値にしました")

    conflict_id = conflict_name = None
    if repository is not None:
        existing = repository.list_profiles()
        if any(p.id == prof.id for p in existing):
            conflict_id = prof.id
        if any(p.name == prof.name for p in existing):
            conflict_name = prof.name
    prof.warnings = [str(i) for i in result.issues]
    return ImportPreview(prof, result, conflict_id, conflict_name)


def read_profile_file(path) -> tuple:
    """ファイルから読む。戻り: `(プロフィール or None, [Issue])`。

    ★一覧を作るときに使うので、**1つ壊れていても他を読めるように**
      例外を投げない。
    """
    p = pathlib.Path(path)
    try:
        size = p.stat().st_size
    except OSError as exc:
        return None, [Issue(Severity.ERROR, p.name, f"開けません: {exc}")]
    if size > MAX_BYTES:
        return None, [Issue(Severity.ERROR, p.name,
                            f"大きすぎます（{size} バイト）")]
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [Issue(Severity.ERROR, p.name, f"読めません: {exc}")]

    preview = read_profile_text(text)
    if preview.profile is None:
        return None, preview.result.issues
    preview.profile.path = p
    return preview.profile, preview.result.issues


# --- 衝突の解決（仕様書 12.6）----------------------------------------

#: 衝突したときの選択肢。★既定は**別名保存**（上書きで消さない）
CONFLICT_RENAME = "rename"
CONFLICT_OVERWRITE = "overwrite"
CONFLICT_CANCEL = "cancel"


def resolve_conflict(prof: TacticsProfile, repository,
                     how: str = CONFLICT_RENAME) -> TacticsProfile | None:
    """衝突を解決したプロフィールを返す。`cancel` なら None。

    ⚠ 既定は `rename`（仕様書 12.6）。**上書きを既定にしない**。
      もらったプロフィールで自分の戦術が消えるのは取り返しがつかない。
    """
    if how == CONFLICT_CANCEL:
        return None
    existing = {p.id: p for p in repository.list_profiles()}
    if how == CONFLICT_OVERWRITE:
        found = existing.get(prof.id)
        if found is not None and found.preset:
            # ⚠ 見本は上書きできない（消せないものと同じ理由）。別名にする
            how = CONFLICT_RENAME
        else:
            return prof
    if prof.id in existing or any(p.name == prof.name
                                  for p in existing.values()):
        prof.name = repository.unique_name(f"{prof.name}（インポート）")
        prof.id = repository.unique_id(prof.id)
    return prof
