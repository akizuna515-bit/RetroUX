"""人が書く YAML を、**重複キーを見逃さずに**読む（RX3-0441 / 2026-09-28）。

## ⚠⚠ なぜ要るか

★素の `yaml.safe_load` は、同じキーを 2 度書いても**後のほうで黙って上書き**します。

```yaml
- id: 070_lastkey1
  scenario: last_key
  memo: |
    最後の鍵の情報を聞く
  scenario: last_key     # ⚠⚠ 2 度目。★素の loader は何も言わない
```

⚠ 2026-09-27 に勇者メモの原本で**5 件**起きました（★片方だけ直しても気づけない形）。
→ ★読み込みの段で **ERROR にします**。

## ★使い方

```python
from dq3.yaml_strict import DuplicateKey, load_strict

try:
    doc = load_strict(path.read_bytes())
except DuplicateKey as exc:
    ...   # ⚠ exc.key / exc.line（1 起点）が分かる
```

⚠ `load_strict` は `yaml.safe_load` と同じものを返します（★型は変えません）。
★重複が無ければ素通りするので、**置き換えるだけ**で使えます。
"""
from __future__ import annotations


class DuplicateKey(Exception):
    """⚠ 同じ辞書の中に同じキーが 2 度ある。"""

    def __init__(self, key, line: int, first_line: int) -> None:
        #: ★重複したキー
        self.key = key
        #: ★2 度目が書かれている行（1 起点）
        self.line = line
        #: ★1 度目の行（1 起点）
        self.first_line = first_line
        super().__init__("⚠⚠ %d 行目のキー `%s` が重複しています（★1 度目は %d 行目 / "
                         "YAML は後のほうで黙って上書きします）" % (line, key, first_line))


def strict_loader():
    """★重複キーで止まる loader の型を作る（⚠ 呼ぶたびに新しい型）。"""
    import yaml

    class _Loader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        # ★素の `construct_mapping` は重複を黙って潰すので、★鍵を 1 つずつ見る
        loader.flatten_mapping(node)
        got: dict = {}
        lines: dict = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                hashable = key in got
            except TypeError:                      # ⚠ 畳めない鍵は素の loader に任せる
                hashable = False
            if hashable:
                raise DuplicateKey(key, key_node.start_mark.line + 1, lines[key])
            lines[key] = key_node.start_mark.line + 1
            got[key] = loader.construct_object(value_node, deep=deep)
        return got

    _Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return _Loader


def load_strict(raw):
    """★`yaml.safe_load` と同じ。⚠ ただし重複キーは `DuplicateKey` で止める。"""
    import yaml

    return yaml.load(raw, Loader=strict_loader())
