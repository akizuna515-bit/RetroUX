"""ゲーム内の文字コードを読む（2026-07-29）。

★★ 表は `memory_map.yaml` の `text:` にある（ROM 由来の唯一の出典）★★
  ここには**読み方だけ**を書く。表をコードに複製しない。

出どころ: セーブステートの CHR-RAM を PNG に描いて字形を読んだ
（`docs/how-to-read-rom.md` 5章）。敵83体・道具61件で裏を取ってある。

⚠ **FC のフォントは字数が少なく、無いカタカナは平仮名で代用されている。**
  「べりアル」「りビングデッド」「マりア」は**画面に出るとおり**。整えない。
"""

from __future__ import annotations

# 濁点・半濁点が付いた形。★どちらも**直前の文字**に付く
VOICED = {
    "か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
    "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
    "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
    "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ",
    "カ": "ガ", "キ": "ギ", "ク": "グ", "コ": "ゴ", "サ": "ザ",
    "シ": "ジ", "ス": "ズ", "タ": "ダ", "テ": "デ", "ト": "ド",
    "ハ": "バ", "ヒ": "ビ", "フ": "ブ", "ホ": "ボ",
}
SEMI_VOICED = {
    "は": "ぱ", "ひ": "ぴ", "ふ": "ぷ", "へ": "ぺ", "ほ": "ぽ",
    "ハ": "パ", "ヒ": "ピ", "フ": "プ", "ホ": "ポ",
}
BLANK = "␣"


class Charset:
    """`memory_map.yaml` の `text:` から作る文字コード表。"""

    def __init__(self, spec: dict | None) -> None:
        spec = spec or {}
        self.table: dict[int, str] = {}
        for base, run in (spec.get("runs") or {}).items():
            for offset, char in enumerate(str(run)):
                self.table[int(base) + offset] = char
        for code, char in (spec.get("single") or {}).items():
            self.table[int(code)] = str(char)
        self.dakuten = spec.get("dakuten")
        self.handakuten = spec.get("handakuten")
        self.separator = spec.get("separator")

    @property
    def usable(self) -> bool:
        """表があるか。**無ければ何も読まない**（推測で文字を出さない）。"""
        return bool(self.table)

    def decode(self, raw: bytes | bytearray | list[int]) -> tuple[str, list[int]]:
        """バイト列 → (文字列, 読めなかったコード)。

        ★読めなかったコードは**返して呼び出し側に見せる**。
          黙って落とすと「なぜかこの敵だけ名前が短い」になる。
        """
        out: list[str] = []
        unknown: list[int] = []
        for byte in raw:
            if self.separator is not None and byte == self.separator:
                break                       # 区切りで終わり
            if self.dakuten is not None and byte == self.dakuten:
                if out and out[-1] in VOICED:
                    out[-1] = VOICED[out[-1]]
                else:
                    out.append("゛")
                    unknown.append(byte)
                continue
            if self.handakuten is not None and byte == self.handakuten:
                if out and out[-1] in SEMI_VOICED:
                    out[-1] = SEMI_VOICED[out[-1]]
                else:
                    out.append("゜")
                    unknown.append(byte)
                continue
            char = self.table.get(byte)
            if char is None:
                unknown.append(byte)
                out.append(f"<{byte:02X}>")
            else:
                out.append(char)
        return "".join(out).replace(BLANK, " ").strip(), unknown

    def decode_names(self, raw: bytes | bytearray | list[int],
                     length: int, count: int) -> list[str]:
        """区切りで区切られた名前を `count` 人ぶん読む。

        ⚠ 読めない文字が混ざった名前は**返さない**（空文字にする）。
          半端に化けた名前を出すより、役割名のままのほうがまし。
        """
        names: list[str] = []
        step = length + 1                   # 名前 + 区切り
        for i in range(count):
            chunk = bytes(raw[i * step:i * step + length])
            if len(chunk) < length:
                names.append("")
                continue
            text, unknown = self.decode(chunk)
            names.append("" if unknown else text)
        return names


def from_memory_map(memory_map: dict) -> Charset:
    return Charset((memory_map or {}).get("text"))
