"""セーブステートから RAM を読む（MVP2 Phase 5 の土台）。

★なぜ道具にするか:

  ここまでの解析（呪文ビット・敵HP・敵ステータス表・経験値の表）は、
  どれも「セーブステートの RAM を読んで、条件で絞る」の繰り返しだった。
  同じ読み取りコードが `work/` の中に何度も書かれ、
  **1か所直すと他が古いまま**という形になっていた。

★エミュレータを止めずに解析できるのが利点。
  FCEUX を動かしたまま、別のシェルでセーブステートを読める。

⚠ **セーブステートは「そのとき」の RAM でしかない。**
  フィールドで保存したものに戦闘中の値は入っていない。
  「値があること≠有効」（playbook #14）はここでも同じ。
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

RAM_SIZE = 0x800
"""ファミコンの内蔵 RAM（$0000-$07FF）。"""


class SavestateError(RuntimeError):
    """セーブステートを読めなかった。"""


@dataclass(frozen=True)
class Snapshot:
    """1つのセーブステートから取り出した RAM。"""

    name: str
    data: bytes

    def __getitem__(self, addr: int) -> int:
        return self.data[addr]

    def word(self, addr: int) -> int:
        """16ビット・リトルエンディアンで読む。"""
        return self.data[addr] + self.data[addr + 1] * 256

    def slice(self, start: int, end: int) -> bytes:
        return self.data[start:end + 1]


def read_savestate(path: Path | str) -> bytes:
    """FCEUX のセーブステート（.fcN）から RAM を取り出す。

    ★形式: 先頭16バイトが FCSX ヘッダ、残りが zlib 圧縮。
      その中の `RAM\\0` セクションが $0000-$07FF。
      （playbook「FCEUX のセーブステートから RAM を取り出す」と同じ手順）
    """
    p = Path(path)
    try:
        raw = zlib.decompress(p.read_bytes()[16:])
    except (OSError, zlib.error) as exc:
        raise SavestateError(f"{p.name} を展開できません: {exc}") from exc

    i = raw.find(b"RAM\x00")
    if i < 0:
        raise SavestateError(f"{p.name} に RAM セクションがありません")
    size = int.from_bytes(raw[i + 4:i + 8], "little")
    data = raw[i + 8:i + 8 + size]
    if len(data) < RAM_SIZE:
        raise SavestateError(
            f"{p.name} の RAM が短すぎます（{len(data)} バイト）")
    return data[:RAM_SIZE]


def load_all(directory: Path | str, pattern: str = "*.fc[0-9]") -> list[Snapshot]:
    """フォルダのセーブステートをまとめて読む。

    ⚠ 読めないものは**飛ばすが黙らない**。呼び出し側が件数を見て
      「思ったより少ない」に気づけるように、戻り値の数で分かるようにする。
    """
    out: list[Snapshot] = []
    for path in sorted(Path(directory).glob(pattern)):
        try:
            out.append(Snapshot(name=path.name, data=read_savestate(path)))
        except SavestateError:
            continue
    return out


def diff(a: Snapshot, b: Snapshot,
         start: int = 0, end: int = RAM_SIZE - 1) -> dict[int, tuple[int, int]]:
    """2つの RAM の違い。{アドレス: (前, 後)}。"""
    return {
        addr: (a.data[addr], b.data[addr])
        for addr in range(start, end + 1)
        if a.data[addr] != b.data[addr]
    }


def stable(snapshots: list[Snapshot],
           start: int = 0, end: int = RAM_SIZE - 1) -> list[int]:
    """すべてのスナップショットで**同じ値**のアドレス。

    ★「変わらないもの」を探すのは、名前や設定のように
      冒険を通じて動かない値を見つけるときに効く。
    """
    if not snapshots:
        return []
    first = snapshots[0]
    return [
        addr for addr in range(start, end + 1)
        if all(s.data[addr] == first.data[addr] for s in snapshots)
    ]


def changing(snapshots: list[Snapshot],
             start: int = 0, end: int = RAM_SIZE - 1) -> list[int]:
    """スナップショット間で**値が動く**アドレス。"""
    fixed = set(stable(snapshots, start, end))
    return [a for a in range(start, end + 1) if a not in fixed]
