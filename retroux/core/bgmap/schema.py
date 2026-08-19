"""JSON Schema をごく小さく確かめる（2026-08-02 / Phase 2）。

⚠ `jsonschema` を入れていないので、**必要な分だけ**自前で見ます。

★見るもの:

    type / required / additionalProperties / properties / items
    enum / minimum / maximum / minItems / maxItems / pattern
    $ref（★`#/$defs/...` だけ）/ anyOf

⚠ 見ないもの: `oneOf` / `allOf` / `if-then` / `format` など。
  ★使っていない機能を「通った」ことにしないよう、
    **知らないキーワードが出たら知らせます**（黙って飛ばしません）。
"""

from __future__ import annotations

import json
import pathlib
import re

#: ★分かっているキーワード。⚠ これ以外が出たら報告する
KNOWN = {"$schema", "$id", "title", "description", "$defs", "type", "required",
         "additionalProperties", "properties", "items", "enum", "minimum",
         "maximum", "minItems", "maxItems", "pattern", "$ref", "anyOf",
         "propertyNames", "const"}

_TYPES = {"object": dict, "array": list, "string": str, "integer": int,
          "number": (int, float), "boolean": bool, "null": type(None)}


class SchemaError(Exception):
    """⚠ スキーマ自体がおかしい（★見つけたら黙らない）。"""


def load(path) -> dict:
    return json.loads(pathlib.Path(path).read_bytes().decode("utf-8"))


def unsupported_keywords(schema: dict) -> set:
    """★このスキーマで使われている、私が見られないキーワード。"""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("properties", "$defs"):
                    for sub in value.values():
                        walk(sub)
                    continue
                if key not in KNOWN:
                    found.add(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return found


def validate(data, schema: dict, root: dict | None = None,
             where: str = "$") -> list:
    """★合わないところを**全部**返します（最初の1件で止めません）。"""
    root = root if root is not None else schema
    problems: list = []

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise SchemaError(f"⚠ 外部参照は見られません: {ref}")
        target = root
        for part in ref[2:].split("/"):
            target = target[part]
        return validate(data, target, root, where)

    if "anyOf" in schema:
        for option in schema["anyOf"]:
            if not validate(data, option, root, where):
                return []
        return [f"{where}: ⚠ anyOf のどれにも合いません"]

    kinds = schema.get("type")
    if kinds is not None:
        kinds = [kinds] if isinstance(kinds, str) else list(kinds)
        # ⚠ bool は int の仲間なので、integer 判定から外す
        ok = any(isinstance(data, _TYPES[k])
                 and not (k in ("integer", "number") and isinstance(data, bool))
                 for k in kinds)
        if not ok:
            return [f"{where}: ⚠ 型が {kinds} でない（{type(data).__name__}）"]

    if "const" in schema and data != schema["const"]:
        problems.append(f"{where}: ⚠ {schema['const']!r} でない")
    if "enum" in schema and data not in schema["enum"]:
        problems.append(f"{where}: ⚠ {data!r} は {schema['enum']} にない")
    if isinstance(data, str) and "pattern" in schema:
        if not re.search(schema["pattern"], data):
            problems.append(f"{where}: ⚠ pattern に合わない: {data!r}")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            problems.append(f"{where}: ⚠ {data} < {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            problems.append(f"{where}: ⚠ {data} > {schema['maximum']}")

    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                problems.append(f"{where}: ⚠ {key} がありません")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in data:
                if key not in props:
                    problems.append(f"{where}: ⚠ 余計な項目 {key}")
        extra = schema.get("additionalProperties")
        for key, value in data.items():
            if key in props:
                problems += validate(value, props[key], root, f"{where}.{key}")
            elif isinstance(extra, dict):
                problems += validate(value, extra, root, f"{where}.{key}")

    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            problems.append(f"{where}: ⚠ 件数 {len(data)} < {schema['minItems']}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            problems.append(f"{where}: ⚠ 件数 {len(data)} > {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(data):
                problems += validate(item, item_schema, root, f"{where}[{i}]")
    return problems
