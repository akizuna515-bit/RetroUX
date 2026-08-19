"""根拠（evidence）と信頼度（confidence）をデータにする（指示書 4.2）。

★このプロジェクトには「候補は候補。探索に使っていないデータで裏を取る」という
  決まりがある（`docs/50-playbook.md`）。過去に、確率の署名だけで敵をひも付けて
  1つのIDに2つの名前を割り当てた事故がある。

  そこで「どうやって見つけたか」を**必ず値として持ち歩く**。
  推測を `confirmed` と書けないよう、confidence は下から積み上げる。
"""

from __future__ import annotations

import dataclasses
import enum


class Confidence(str, enum.Enum):
    """指示書 4.2 の4段階。"""

    CONFIRMED = "confirmed"    # 静的解析と実機・エミュレータ表示が一致
    PROBABLE = "probable"      # 複数データで妥当だが実画面照合は未完
    TENTATIVE = "tentative"    # 仮説段階
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {
    Confidence.UNKNOWN: 0,
    Confidence.TENTATIVE: 1,
    Confidence.PROBABLE: 2,
    Confidence.CONFIRMED: 3,
}


def weakest(*values: Confidence) -> Confidence:
    """★合成した結果は**一番弱い根拠**より強くならない。

    「表の位置は confirmed、展開結果は tentative」なら全体は tentative。
    強い方に引きずられて確からしく見せない。
    """
    if not values:
        return Confidence.UNKNOWN
    return min(values, key=lambda c: c.rank)


@dataclasses.dataclass(frozen=True)
class Evidence:
    """1件の根拠。指示書 4.2 の形に合わせる。"""

    type: str                       # disassembly_symbol / byte_signature / runtime_capture ...
    note: str
    source: str | None = None
    bank: int | None = None
    cpu_address: int | None = None
    rom_offset: int | None = None

    def to_json(self) -> dict:
        out: dict = {"type": self.type, "note": self.note}
        if self.source is not None:
            out["source"] = self.source
        if self.bank is not None:
            out["bank"] = self.bank
        if self.cpu_address is not None:
            out["cpu_address"] = f"0x{self.cpu_address:04X}"
        if self.rom_offset is not None:
            out["rom_offset"] = f"0x{self.rom_offset:05X}"
        return out


@dataclasses.dataclass(frozen=True)
class Finding:
    """「何が・どこに・どれくらい確からしく」あるか。"""

    name: str
    confidence: Confidence
    evidence: tuple[Evidence, ...] = ()

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "confidence": self.confidence.value,
            "evidence": [e.to_json() for e in self.evidence],
        }
