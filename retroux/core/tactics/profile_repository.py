"""戦術プロフィールの保存（2026-07-30 / 仕様書 10.1・17.2）。

★★ **1プロフィール1ファイル**（仕様書 10.1）★★

    work/tactics/profiles/boss_full_power.yaml
    work/tactics/profiles/mp_saving.yaml
    work/tactics/active.txt        ← いま選んでいるもの

★1ファイルにまとめない理由: Git の差分が読める・手で1つだけ配れる・
  1つ壊れても他が読める（仕様書 10.2）。

## ⚠⚠ 保存で元のファイルを壊さない（仕様書 13章）

  手で書いた戦術は戻らない。だから:

    一時ファイルへ書く -> 読み直して確かめる -> 置き換える

  途中で落ちても、元のファイルはそのまま残る。

## 見本（プリセット）の扱い（仕様書 4.5）

同梱の3つ（レベル上げ／ダンジョン探索／呪文を使わない）は `preset: true` で、**消せない・上書きできない**。
⚠「手動中心」は 2026-08-19 に廃止（RX-0067）。「4つ」は古い（2026-08-21 訂正 / RX-0010）。
編集したいときは複製する（画面がそう促す）。

⚠ 見本をファイルとして置かない。置くと利用者が消したときに復活せず、
  「同梱のはずのものが無い」状態になる。**コードから作る。**
"""

from __future__ import annotations

import copy
import pathlib

from . import models
from .profile import ID_PATTERN, TacticsProfile, now_iso, slug

#: 既定の置き場（仕様書 10.1）
DEFAULT_DIR = pathlib.Path("work/tactics/profiles")
#: 選んでいるプロフィールを覚えるファイル
ACTIVE_NAME = "active.txt"


def _preset_definitions() -> list:
    """同梱の見本（仕様書 4.5）。★**コードから作る**（上のコメント参照）。

    ⚠ 「危険時手動復帰：ON」は3つすべて共通（仕様書のとおり）。
      既定値が ON なので、ここでは書かない（書くと2か所になる）。
    """
    return [
        # ★★ 2026-08-11: 作戦名を戦略に合わせる（依頼者）★★
        #   レベル上げ＝この作戦（バッチリ戦う）／ダンジョン探索＝いのちをだいじに。
        #   ⚠ id は変えない（balanced/life_first。マッピング・保存の互換のため）。
        ("balanced", "レベル上げ",
         "戦闘効率を優先。ローレシアが攻め、ムーンブルクが回復に寄る", {
             "lorasia": models.Role.ATTACK,
             "samaltria": models.Role.BALANCED,
             "moonbrooke": models.Role.HEALER,
         }, {}),
        # ★★ **見本は3つだけ**（2026-07-31 / 依頼者の判断）★★
        #   以前は「MP節約」「ボス全力」も同梱していたが、
        #   ⚠ **細かい見本を増やしても選ぶのが面倒になるだけ**だった。
        #     数値は画面のマトリクスで直せるので、見本は
        #     「ふつう / 呪文を使わない / 全部手動」の3つで足りる。
        # ★★「いのちをだいじに」（2026-08-04 / 指示書 §8）★★
        #
        #   > ローレシアを主攻撃役として維持し、
        #   > サマルトリアとムーンブルクが回復を担当する。
        #
        # ★見本を3つに絞った 2026-07-31 の判断とぶつかりますが、これは
        #   **数値の組み合わせ違いではなく、役割分担そのものが違う**作戦です。
        #   ⚠ マトリクスで作れなくはないものの、6項目を3人ぶん手で
        #     揃える必要があり、依頼者が「作戦」として選びたいものです（§3）。
        ("life_first", "ダンジョン探索",
         "継戦を優先。ローレシアを守って戦い、サマル・ムーンが回復に回り、"
         "自己回復では ちからのたて を最優先する", {
             "lorasia": models.Role.ATTACK,
             "samaltria": models.Role.HEALER,
             "moonbrooke": models.Role.HEALER,
         }, {
             cid: {
                 # ★守る相手はローレシア（§10 の `protect_target`）
                 ("healing", "protect_target"): models.ProtectTarget.LORASIA,
                 ("healing", "protect_hp_threshold"): 50,
                 ("healing", "emergency_self_hp_threshold"): 25,
                 # ★§10 の `self_heal_threshold: 0.50` はこれ（既存項目を再利用）
                 ("healing", "self_hp_threshold"): 50,
                 ("healing", "self_enabled"): True,
                 ("healing", "ally_enabled"): True,
                 ("healing", "avoid_duplicate_healing"): True,
                 # ⚠ 2026-08-10: consider_expected_healing は削除（CONFIG_ONLY）
                 # ★ちからのたてを使うために、減らない道具を許す（§9.1）
                 ("items", "reusable"): True,
             }
             # ⚠ ローレシアには入れない（回復呪文を使えない＝守られる側）。
             #   `not_applicable` が拾うので、書いても落とされます。
             for cid in ("samaltria", "moonbrooke")
         }),
        ("no_spells", "呪文を使わない",
         "MPを一切使わない。通常攻撃と道具だけで戦う"
         "（★回復は自分でしてください）", {
             "lorasia": models.Role.ATTACK,
             "samaltria": models.Role.CONSERVE_MP,
             "moonbrooke": models.Role.CONSERVE_MP,
         }, {
             cid: {("healing", "self_enabled"): False,
                   ("healing", "ally_enabled"): False}
             for cid in models.CHARACTER_IDS
         }),
        # ⚠ 2026-08-19: 見本「手動中心」(manual) を廃止（RX-0067 / 依頼者「いらない」）。
        #   ★戦略を3つ（レベル上げ/ダンジョン探索/亀の子）に絞った経緯とも整合。
        #   ⚠ 役割「手動」(Role.MANUAL) 自体は残る（AI操作OFF は AUTO ボタンで足りる）。
    ]

#: ★廃止した見本の id。★保存ファイルが残っていても**一覧に出さない**用。
#   ⚠ 2026-08-19: 「手動中心」(manual) を廃止（RX-0067）。既に
#   `work/tactics/profiles/manual.yaml` が置かれていても出さない。
REMOVED_PRESET_IDS = ("manual",)


def build_presets() -> list:
    """見本のプロフィールを作る。"""
    made = []
    for profile_id, name, description, roles, extra in _preset_definitions():
        prof = TacticsProfile.create(profile_id, name, description, preset=True)
        for cid, role in roles.items():
            prof.set(cid, "root", "role", role)
        for cid, values in extra.items():
            for (section, key), value in values.items():
                prof.set(cid, section, key, value)
        made.append(prof)
    return made


class TacticsRepository:
    """プロフィールの一覧・読み・保存・複製・削除・選択（仕様書 17.2）。

    ⚠ 置き場が作れない環境でも**落ちない**（見本だけで動く）。
      戦術の設定が保存できなくても、ゲームは遊べる。
    """

    def __init__(self, directory=None, logger=None) -> None:
        self.dir = pathlib.Path(directory or DEFAULT_DIR)
        self.log = logger
        #: ⚠ 読み込みで気づいた不整合。**捨てずに持って画面に出す**
        self.problems: list = []
        self._presets = {p.id: p for p in build_presets()}

    # --- 置き場 -----------------------------------------------------

    def ensure_dir(self) -> bool:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            return True
        except OSError as exc:
            self._note(f"置き場を作れません（{self.dir}）: {exc}")
            return False

    def _note(self, message: str) -> None:
        if message not in self.problems:
            self.problems.append(message)
        if self.log is not None:
            self.log.warning("戦術プロフィール: %s", message)

    # --- 一覧・読み -------------------------------------------------

    def path_for(self, profile_id: str) -> pathlib.Path:
        """`id` からファイルの場所。⚠ `id` は検証済みのものだけ渡すこと。"""
        if not ID_PATTERN.match(profile_id or ""):
            raise ValueError(f"プロフィールIDが不正です: {profile_id!r}")
        return self.dir / f"{profile_id}.yaml"

    def list_profiles(self) -> list:
        """全部のプロフィール。★**見本が先、保存したものが後**。

        ⚠ 同じ `id` のファイルがあれば**ファイル側を採る**
          （利用者が見本を複製して同じ名前で保存した場合、その人の版が正）。
        """
        from .import_export import read_profile_file

        made = {pid: prof for pid, prof in self._presets.items()}
        if self.dir.exists():
            for path in sorted(self.dir.glob("*.yaml")):
                prof, issues = read_profile_file(path)
                if prof is None:
                    self._note(f"{path.name} を読めません: "
                               + "／".join(i.message for i in issues[:2]))
                    continue
                # ⚠ 2026-08-19: 廃止した見本（manual＝手動中心）の保存ファイルは
                #   出さない（RX-0067 / 依頼者「手動中心はいらない」）。★消しはしない。
                if prof.id in REMOVED_PRESET_IDS:
                    continue
                # ★見本を改名したとき、保存ファイル側の**表示名を追従**させる
                #   （2026-08-11）。⚠ 中身（数値の編集）は保存ファイルを尊重する。
                #   ★install_presets で置いた編集用コピーが旧名のままなのを直す。
                seed = self._presets.get(prof.id)
                if seed is not None:
                    prof.name = seed.name
                    prof.description = seed.description
                made[prof.id] = prof
        return list(made.values())

    def get(self, profile_id: str):
        """1つ読む。無ければ None。"""
        for prof in self.list_profiles():
            if prof.id == profile_id:
                return prof
        return None

    # --- 保存・複製・削除 -------------------------------------------

    def save(self, prof: TacticsProfile) -> bool:
        """保存する。戻り値は**保存できたか**。

        ⚠ 見本は上書きしない（複製してから編集する / 仕様書 4.5）。
        """
        from .import_export import write_profile_file

        if prof.preset:
            self._note(f"見本『{prof.name}』は上書きできません（複製してください）")
            return False
        if not self.ensure_dir():
            return False
        prof.touch()
        try:
            path = self.path_for(prof.id)
        except ValueError as exc:
            self._note(str(exc))
            return False
        if not write_profile_file(path, prof):
            self._note(f"{path.name} へ書けませんでした")
            return False
        prof.path = path
        return True

    def unique_id(self, base: str) -> str:
        """使われていない `id` を作る。★衝突したら連番（仕様書 12.6）。"""
        made = slug(base)
        taken = {p.id for p in self.list_profiles()}
        if made not in taken:
            return made
        for n in range(2, 1000):
            candidate = f"{made}_{n}"
            if candidate not in taken:
                return candidate
        # ★ここまで来たら時刻で作る（無限に探さない）
        return f"{made}_{now_iso().replace(':', '').replace('-', '')[:14]}"

    def unique_name(self, base: str) -> str:
        """使われていない表示名を作る。★画面で見分けられるように。"""
        taken = {p.name for p in self.list_profiles()}
        if base not in taken:
            return base
        for n in range(2, 1000):
            candidate = f"{base}（{n}）"
            if candidate not in taken:
                return candidate
        return f"{base}（{now_iso()}）"

    def create(self, name: str) -> TacticsProfile:
        """新規作成（既定値）。★保存はまだしない（利用者が押すまで）。"""
        unique = self.unique_name(name)
        return TacticsProfile.create(self.unique_id(unique), unique)

    def duplicate(self, prof: TacticsProfile,
                  name: str | None = None) -> TacticsProfile:
        """複製する。★見本からの複製は**編集できる**（`preset` を引き継がない）。"""
        unique = self.unique_name(name or f"{prof.name}のコピー")
        return prof.duplicate(self.unique_id(unique), unique)

    def rename(self, prof: TacticsProfile, name: str) -> bool:
        """名前を変える。★`id`（ファイル名）は変えない。

        ⚠ `id` を変えると別ファイルになり、古いほうが残る。
          「名前を変えたら2つになった」は分かりにくい壊れ方。
        """
        text = (name or "").strip()
        if not text:
            self._note("名前が空です")
            return False
        prof.name = text
        return True

    def delete(self, prof: TacticsProfile) -> bool:
        """消す。⚠ 見本は消せない（仕様書 4.5）。"""
        if prof.preset:
            self._note(f"見本『{prof.name}』は消せません")
            return False
        try:
            path = self.path_for(prof.id)
        except ValueError as exc:
            self._note(str(exc))
            return False
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            self._note(f"{path.name} を消せません: {exc}")
            return False
        # ★消したものが選ばれていたら、選択も外す
        if self.active_id() == prof.id:
            self.set_active(None)
        return True

    # --- 選んでいるもの ---------------------------------------------

    @property
    def active_path(self) -> pathlib.Path:
        return self.dir.parent / ACTIVE_NAME

    def active_id(self) -> str | None:
        """選んでいるプロフィールの `id`。★再起動後も残る（受入条件10）。"""
        try:
            text = self.active_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    def set_active(self, profile_id) -> bool:
        """選ぶ。`None` を渡すと選択を外す。"""
        if not self.ensure_dir():
            return False
        try:
            if profile_id is None:
                self.active_path.write_text("", encoding="utf-8")
            else:
                self.active_path.write_text(str(profile_id), encoding="utf-8")
            return True
        except OSError as exc:
            self._note(f"選んだプロフィールを覚えられません: {exc}")
            return False

    def active(self):
        """選んでいるプロフィール。

        ⚠ 選択が無い／消えている場合は **`balanced`（バッチリ戦う）** へ落とす。
          `None` を返すと呼ぶ側が「AIを止める」のか「既定で動く」のか
          決められない。**既定の見本で動く**とはっきりさせる。
        """
        wanted = self.active_id()
        if wanted:
            found = self.get(wanted)
            if found is not None:
                return found
            self._note(f"選んでいたプロフィール『{wanted}』が見つかりません"
                       "（既定の『バッチリ戦う』を使います）")
        return self._presets.get("balanced") or build_presets()[0]

    # --- 見本 -------------------------------------------------------

    @property
    def presets(self) -> list:
        return [copy.deepcopy(p) for p in self._presets.values()]

    def install_presets(self) -> int:
        """見本をファイルとしても置く（利用者が手で編集したいとき用）。

        ⚠ **既にあるファイルは上書きしない**（手で直したものを壊さない）。
        戻り値は置いた数。
        """
        from .import_export import write_profile_file

        if not self.ensure_dir():
            return 0
        placed = 0
        for prof in build_presets():
            path = self.dir / f"{prof.id}.yaml"
            if path.exists():
                continue
            copied = copy.deepcopy(prof)
            copied.preset = False        # ★ファイルに置いたら編集できる
            if write_profile_file(path, copied):
                placed += 1
        return placed
