"""ROM ごとの差を JSON に追い出す（指示書 4.1）。

★ハッシュが合わなくても**即終了しない**（指示書 2.1）。
  警告を出し、ヘッダ情報は解析し、`--force` のときだけ先へ進む。
  出力メタデータには必ず実測ハッシュを書く。

★プロファイルに書く `symbols` は**実測で埋める**もので、
  手で書いた値を信じない。`dq2rom inspect --update-profile` が
  探索結果を書き戻す。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

from .ines import Rom

PROFILE_DIR = pathlib.Path(__file__).resolve().parent / "profiles"


class ProfileError(ValueError):
    pass


@dataclasses.dataclass
class Profile:
    game_id: str
    data: dict
    path: pathlib.Path | None = None

    # --- 読み書き -------------------------------------------------------

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Profile":
        p = pathlib.Path(path)
        if not p.exists():
            raise ProfileError(f"プロファイルがありません: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        game_id = data.get("game_id")
        if not game_id:
            raise ProfileError(f"game_id がありません: {p}")
        return cls(game_id=game_id, data=data, path=p)

    @classmethod
    def builtin(cls, game_id: str = "dq2_fc_jp") -> "Profile":
        return cls.load(PROFILE_DIR / f"{game_id}.json")

    def save(self, path: str | pathlib.Path | None = None) -> pathlib.Path:
        p = pathlib.Path(path) if path else self.path
        if p is None:
            raise ProfileError("保存先が分かりません")
        p.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        self.path = p
        return p

    # --- 照合 -----------------------------------------------------------

    def hash_mismatches(self, rom: Rom) -> list[str]:
        """合わなかったハッシュの説明を返す（空なら一致）。"""
        expected = self.data.get("hashes") or {}
        actual = {"sha1": rom.sha1, "md5": rom.md5, "crc32": rom.crc32}
        out = []
        for key, want in expected.items():
            if not want:
                continue
            got = actual.get(key)
            if got is None:
                continue
            if want.lower() != got.lower():
                out.append(f"{key}: 期待 {want} / 実測 {got}")
        return out

    def layout_mismatches(self, rom: Rom) -> list[str]:
        """★ハッシュが違っても、構成が同じなら解析できる見込みがある。

        指示書 2.1 の「ハッシュが一致しない場合も即時終了せず、
        iNESヘッダー、PRGサイズ、Mapper番号を解析」に対応する。
        """
        out = []
        want_mapper = self.data.get("mapper")
        if want_mapper is not None and want_mapper != rom.mapper:
            out.append(f"mapper: 期待 {want_mapper} / 実測 {rom.mapper}")
        layout = self.data.get("rom_layout") or {}
        want_banks = layout.get("prg_banks")
        if want_banks is not None and want_banks != rom.prg_banks:
            out.append(f"prg_banks: 期待 {want_banks} / 実測 {rom.prg_banks}")
        want_chr = layout.get("chr_banks")
        if want_chr is not None and want_chr != rom.chr_banks:
            out.append(f"chr_banks: 期待 {want_chr} / 実測 {rom.chr_banks}")
        return out

    # --- 書き戻し -------------------------------------------------------

    def set_symbol(self, name: str, value: dict | None) -> None:
        self.data.setdefault("symbols", {})[name] = value

    def set_confidence(self, name: str, value: str) -> None:
        self.data.setdefault("confidence", {})[name] = value
