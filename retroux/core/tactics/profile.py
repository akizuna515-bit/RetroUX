"""戦術プロフィール1つ分（2026-07-30 / 仕様書 10章）。

★★ **プロフィールは「利用者が設計した戦術」そのもの。** ★★
  だから:

  | 守ること | なぜ |
  | --- | --- |
  | 勝手に値を補正しない | 設定したものと違う戦術で戦うことになる |
  | 分からない項目を捨てない | 新しい版で作った設定を古い版が黙って壊す |
  | 保存に失敗したら**元のファイルを壊さない** | 手で書いた戦術は戻らない |

## 中身

    schema_version: 1
    profile: { id, name, description, created_at, updated_at }
    characters: { lorasia: {...}, samaltria: {...}, moonbrooke: {...} }

⚠ `id` はファイル名にも使うので**英数字と `_` だけ**。
  `name` は日本語でよい（画面に出るのはこちら）。
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import re

from . import models

#: `id` に使える文字。★ファイル名になるので厳しくする
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


def now_iso() -> str:
    """いまの時刻（地域つき）。★UTC ではなく地域つきで書く。

    プロフィールは人が読んで共有するものなので、
    「2026-07-30T09:00:00+09:00」のほうが分かる。
    """
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def slug(text: str, fallback: str = "profile") -> str:
    """名前から `id` を作る。**日本語は英数字にならないので落ちる**。

    ⚠ 落ちたときに空にしない（ファイル名が作れなくなる）。
      `fallback` + 連番は呼ぶ側（Repository）が付ける。
    """
    made = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return made if ID_PATTERN.match(made) else fallback


@dataclasses.dataclass
class TacticsProfile:
    """1つの戦術プロフィール。"""

    id: str
    name: str
    description: str = ""
    schema_version: int = models.SCHEMA_VERSION
    created_at: str = dataclasses.field(default_factory=now_iso)
    updated_at: str = dataclasses.field(default_factory=now_iso)
    #: {キャラクターID: {項目...}}
    characters: dict = dataclasses.field(default_factory=dict)
    #: ⚠ 読み込みで気づいた不整合。**捨てずに持って画面に出す**
    warnings: list = dataclasses.field(default_factory=list)
    #: このプロフィールは同梱の見本か（★消させない / 仕様書 4.5）
    preset: bool = False
    #: 読み込んだファイル（保存先。新規なら None）
    path: object = None

    # --- 作る -------------------------------------------------------

    @classmethod
    def create(cls, profile_id: str, name: str, description: str = "",
               preset: bool = False) -> "TacticsProfile":
        """既定値で作る。★3人ぶん必ず埋める（欠けた形を作らない）。"""
        return cls(
            id=profile_id, name=name, description=description, preset=preset,
            # ★キャラクターIDを渡す＝その人に意味が無い項目を入れない
            #   （ローレシアに「回復開始HP」を持たせない）
            characters={cid: models.default_character(character_id=cid)
                        for cid in models.CHARACTER_IDS})

    def duplicate(self, profile_id: str, name: str) -> "TacticsProfile":
        """複製する。★`preset` は**引き継がない**（複製は編集できる）。"""
        copied = copy.deepcopy(self.characters)
        stamp = now_iso()
        return TacticsProfile(
            id=profile_id, name=name, description=self.description,
            schema_version=self.schema_version,
            created_at=stamp, updated_at=stamp,
            characters=copied, preset=False)

    # --- 読む・書く -------------------------------------------------

    def get(self, character_id: str, section: str, key: str):
        """1項目を読む。**無ければ既定値**。"""
        return models.get_value(self.characters.get(character_id) or {},
                                section, key)

    def set(self, character_id: str, section: str, key: str, value) -> None:
        """1項目を書く。⚠ 知らないキャラクターには書かない。"""
        if character_id not in models.CHARACTER_IDS:
            raise KeyError(f"知らないキャラクターです: {character_id}")
        target = self.characters.setdefault(
            character_id, models.default_character(character_id=character_id))
        models.set_value(target, section, key, value)

    def touch(self) -> None:
        self.updated_at = now_iso()

    # --- 形を変える -------------------------------------------------

    def to_dict(self) -> dict:
        """YAML に出す形。★キーの並びを固定する（差分が読みやすい）。"""
        return {
            "schema_version": int(self.schema_version),
            "profile": {
                "id": self.id,
                "name": self.name,
                "description": self.description,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
            "characters": {cid: _ordered(self.characters.get(cid) or {})
                           for cid in models.CHARACTER_IDS
                           if cid in self.characters},
        }

    @classmethod
    def from_dict(cls, raw: dict, *, preset: bool = False,
                  path=None) -> "TacticsProfile":
        """辞書から作る。**検証はしない**（`profile_validator` の仕事）。

        ⚠ ここで弾かないのは、検証の結果を**まとめて**利用者に見せたいから。
          1つ目で例外を投げると「ほかにも問題があるか」が分からない。
        """
        head = (raw.get("profile") or {}) if isinstance(raw, dict) else {}
        chars = (raw.get("characters") or {}) if isinstance(raw, dict) else {}
        made = cls(
            id=str(head.get("id") or ""),
            name=str(head.get("name") or head.get("id") or ""),
            description=str(head.get("description") or ""),
            schema_version=raw.get("schema_version"),
            created_at=str(head.get("created_at") or now_iso()),
            updated_at=str(head.get("updated_at") or now_iso()),
            characters={cid: copy.deepcopy(v) for cid, v in chars.items()
                        if isinstance(v, dict)},
            preset=preset, path=path)
        return made

    # --- AI へ渡す形 ------------------------------------------------

    def for_ai(self) -> dict:
        """Lua へ渡す形。★**いまのフェーズで実装済みの項目だけ**。

        ⚠⚠ **未実装の項目を渡さない**（仕様書 20章）。
          渡すと Lua 側が「知らないキーだが何かある」状態になり、
          あとで実装したときに**設定していない値で急に効き始める**。

        ★`_phases` を一緒に渡す。Lua 側のログに出して
          「いまどこまで効いているか」を利用者が確かめられるようにする。
        """
        out: dict = {
            "profile_id": self.id,
            "profile_name": self.name,
            "schema_version": int(self.schema_version or 0),
            "_phases": list(models.IMPLEMENTED_PHASES),
            "characters": {},
        }
        for cid in models.CHARACTER_IDS:
            source = self.characters.get(cid)
            if source is None:
                continue
            made: dict = {}
            for field in models.FIELDS:
                if not field.implemented:
                    continue
                # ⚠ その人に意味が無い項目は渡さない（YAML・画面と揃える）。
                #   ★揃えないと、画面では灰色なのに Lua には値が行っていて、
                #     「設定していないのに設定されている」状態になる。
                if models.not_applicable(cid, field.section, field.key):
                    continue
                value = models.get_value(source, field.section, field.key)
                if field.section == "root":
                    made[field.key] = value
                else:
                    made.setdefault(field.section, {})[field.key] = value
            out["characters"][cid] = made
        return out

    # --- 人が読む形 -------------------------------------------------

    def summary_lines(self) -> list:
        """日本語の要約（仕様書 11.4）。**再インポート対象ではない**。

        ★出すのは**設定した値**だけ。既定値と同じ項目まで並べると
          長くなって読まれなくなる（「毎回出る通知は読まれない通知」）。
        """
        lines = [f"プロフィール：{self.name}"]
        if self.description:
            lines.append(f"（{self.description}）")
        for cid in models.CHARACTER_IDS:
            if cid not in self.characters:
                continue
            lines.append("")
            lines.append(models.CHARACTER_LABELS.get(cid, cid))
            for text in self._character_summary(cid):
                lines.append(f"・{text}")
        return lines

    def _character_summary(self, cid: str) -> list:
        made = []
        if not self.get(cid, "root", "enabled"):
            return ["AI操作しない（手動）"]
        made.append("AI操作")
        role = models.Role.parse(self.get(cid, "root", "role"))
        if role is not None:
            made.append(models.ROLE_LABELS[role])
        # ⚠⚠ **「しない」も書く**（2026-07-31）。
        #   以前は有効なときだけ書いていたので、切ってあると**何も出なかった**。
        #   ★「回復しない」は要約でいちばん知りたいことなのに、
        #     沈黙で伝えようとしていた（読む人には区別が付かない）。
        if self.get(cid, "healing", "ally_enabled"):
            made.append(f"仲間HP{self.get(cid, 'healing', 'ally_hp_threshold')}"
                        "%以下で回復")
        else:
            made.append("仲間を回復しない")
        if self.get(cid, "healing", "self_enabled"):
            made.append(f"自分HP{self.get(cid, 'healing', 'self_hp_threshold')}"
                        "%以下で回復")
        else:
            made.append("自分を回復しない")
        made.append(f"最低残存MP{self.get(cid, 'resources', 'reserve_mp')}")
        if self.get(cid, "resources", "ignore_reserve_on_boss"):
            made.append("ボス戦ではMP温存を解除")
        if self.get(cid, "items", "reusable"):
            made.append("非消耗道具を使用")
        # ⚠ 2026-08-10: `items.consumable` は削除（消耗品はまんたん設定が担う）
        if self.get(cid, "safety", "return_to_manual_on_danger"):
            made.append("危険時は手動へ戻す")
        fallback = models.FallbackAction.parse(
            self.get(cid, "safety", "fallback_action"))
        if fallback is not None:
            made.append(f"有効な行動が無ければ{models.FALLBACK_LABELS[fallback]}")
        return made


def _ordered(character: dict) -> dict:
    """キャラクター設定のキーを `FIELDS` の順に並べる。

    ★並びを固定するのは **Git の差分を読めるようにする**ため（仕様書 10.2）。
    ⚠ `FIELDS` に無いキー（新しい版で足された項目）は**落とさず末尾に置く**。
    """
    out: dict = {}
    for field in models.FIELDS:
        if field.section == "root":
            if field.key in character:
                out[field.key] = character[field.key]
        else:
            source = character.get(field.section)
            if isinstance(source, dict) and field.key in source:
                out.setdefault(field.section, {})[field.key] = source[field.key]
    # ⚠ 知らないキーを黙って捨てない（新しい版で作った設定を壊さない）
    for key, value in character.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if (key, sub_key) not in models.FIELD_BY_PATH:
                    out.setdefault(key, {})[sub_key] = sub_value
        elif ("root", key) not in models.FIELD_BY_PATH:
            out[key] = value
    return out
