"""人が書いた名前を、実行時に ROM の (kind, id) へ解くための名前表（RX3-0074 / 2026-09-04）。

★★ Git に置く正本へ、ROM 依存の id を手で書かせない ★★

```text
勇者メモ（人が書いた名前 / 入手した: とうぞくのかぎ）
        +
Runtime Name Dictionary（ユーザーの ROM から起こした名前 / rom_names）
        ↓ fold（かなを畳む / RX3-0070 と同じ）で**完全一致**（★引くのは `hero_memo._rule`）
entity name → (kind, id)                 ★item:88
```

## ⚠⚠ 守ること（指示書 §7〜§9）

```text
★完全一致（fold 後）だけ      ⚠ 部分一致・類似度は**使わない**（新しい判定を増やさない）
⚠ 解けない名前は解けないまま  ★`unresolved` に残す（黙って捨てない）
⚠ 同じ名前が 2 つの id を持つ  ★両方へ解く（⚠ 曖昧ではない。原作が同名で 2 体持つ）
```

⚠⚠ 2026-10-03（RX3-0432）: 旧 Guide Master の「関連する名前」を解く部分
（`resolve_topic` / `resolve_all` / `resolve_rules` / `derived_rules` / `all_rules` /
`summary` / 弱い Rule）を**消しました**。★残るのは名前表（`name_index`）だけです。
"""
from __future__ import annotations

from dq3.knowledge import rom_names
from dq3.knowledge.concepts import fold

__all__ = ["fold", "name_index"]


def name_index(rom_path=None) -> dict[tuple[str, str], list[tuple[int, str]]]:
    """★(kind, fold(名前)) → [(id, ROM の綴り)]。⚠ ROM が無ければ空。"""
    data = rom_names._load(rom_path)
    got: dict[tuple[str, str], list[tuple[int, str]]] = {}
    if data is None:
        return got
    for kind, table in (data.get("names") or {}).items():
        for key, name in table.items():
            got.setdefault((kind, fold(name)), []).append((int(key), name))
    return got
