"""Convert MCP tool input schemas into Jarvis's tool-declaration format.

Jarvis declarations look like {"name", "description", "parameters"} where
`parameters` is a small JSON Schema object (see core/tools.py). Claude and
OpenAI accept real JSON Schema, so for them an MCP `inputSchema` only needs
minimal cleanup (to_parameters). Gemini, through google.generativeai, only
accepts an OpenAPI subset: its Schema has just type / format / description /
nullable / enum / items / properties / required / min_items / max_items, and
an unknown key fails the whole request. to_gemini_parameters() rewrites a
schema into that subset, or raises SchemaError when it can't.
"""

from __future__ import annotations

import copy
from typing import Any

# The only Schema fields google.generativeai's protos.Schema knows about.
GEMINI_KEYS = {"type", "format", "description", "nullable", "enum", "items", "properties", "required", "min_items", "max_items"}
GEMINI_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
# Formats Gemini's function-calling API accepts, per type.
GEMINI_FORMATS = {"string": {"enum", "date-time"}, "number": {"float", "double"}, "integer": {"int32", "int64"}}

_MAX_REF_DEPTH = 16


class SchemaError(ValueError):
    """The schema can't be expressed for this provider."""


def to_parameters(schema: dict | None) -> dict:
    """Claude/OpenAI: pass the JSON Schema through with minimal cleanup."""
    params = copy.deepcopy(schema) if isinstance(schema, dict) else {}
    params.pop("$schema", None)
    params["type"] = "object"  # both providers require an object at the root
    if not isinstance(params.get("properties"), dict):
        params["properties"] = {}
    return params


def to_gemini_parameters(schema: dict | None) -> dict | None:
    """Gemini: sanitize to the OpenAPI subset. Returns None for a no-argument tool
    (Gemini rejects an OBJECT with empty properties, so `parameters` is omitted)."""
    root = schema if isinstance(schema, dict) else {}
    defs = {}
    for key in ("$defs", "definitions"):
        if isinstance(root.get(key), dict):
            defs.update(root[key])
    converted = _convert(root, defs, depth=0, path="parameters")
    if converted.get("type") != "object":
        raise SchemaError("tool input schema is not an object")
    if not converted.get("properties"):
        return None
    return converted


def _resolve_ref(node: dict, defs: dict, depth: int) -> dict:
    ref = node["$ref"]
    if depth > _MAX_REF_DEPTH:
        raise SchemaError(f"$ref '{ref}' is recursive or too deep")
    name = ref.rsplit("/", 1)[-1]
    if not ref.startswith("#/") or name not in defs:
        raise SchemaError(f"unresolvable $ref '{ref}'")
    # Sibling keys (e.g. a description next to the $ref) win over the target's.
    merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
    return merged


def _infer_type(node: dict) -> str:
    if "properties" in node:
        return "object"
    if "items" in node:
        return "array"
    return "string"  # untyped/"any" value: a string is the safest subset


def _convert(node: Any, defs: dict, depth: int, path: str) -> dict:
    if not isinstance(node, dict):
        raise SchemaError(f"{path}: schema node is not an object")
    if "$ref" in node:
        return _convert(_resolve_ref(node, defs, depth), defs, depth + 1, path)

    node = dict(node)
    nullable = bool(node.get("nullable"))

    # allOf with a single entry is just a wrapper (pydantic emits these).
    if "allOf" in node:
        parts = node.pop("allOf")
        if not isinstance(parts, list) or len(parts) != 1:
            raise SchemaError(f"{path}: allOf with several schemas is not supported")
        node = {**parts[0], **node}
        return _convert(node, defs, depth + 1, path)

    # anyOf/oneOf: [X, {"type": "null"}] -> X, nullable. Anything else can't be expressed.
    for key in ("anyOf", "oneOf"):
        if key in node:
            options = node.pop(key)
            if not isinstance(options, list):
                raise SchemaError(f"{path}: {key} must be a list")
            non_null = [o for o in options if not (isinstance(o, dict) and o.get("type") == "null")]
            if len(non_null) != 1:
                raise SchemaError(f"{path}: {key} with {len(non_null)} non-null choices is not supported")
            nullable = nullable or len(non_null) != len(options)
            merged = _convert({**non_null[0], **{k: v for k, v in node.items() if k != "type"}}, defs, depth + 1, path)
            if nullable:
                merged["nullable"] = True
            return merged

    # type: ["string", "null"] -> string, nullable.
    type_ = node.get("type")
    if isinstance(type_, list):
        non_null = [t for t in type_ if t != "null"]
        if len(non_null) != 1:
            raise SchemaError(f"{path}: union type {type_} is not supported")
        nullable = nullable or len(non_null) != len(type_)
        type_ = non_null[0]
    if type_ is None:
        type_ = _infer_type(node)
    if type_ not in GEMINI_TYPES:
        raise SchemaError(f"{path}: type '{type_}' is not supported")

    out: dict[str, Any] = {"type": type_}
    if isinstance(node.get("description"), str) and node["description"]:
        out["description"] = node["description"]
    if nullable:
        out["nullable"] = True

    if "const" in node and "enum" not in node:
        node["enum"] = [node["const"]]
    if isinstance(node.get("enum"), list):
        values = [v for v in node["enum"] if v is not None]
        if type_ == "string" and values and all(isinstance(v, str) for v in values):
            out["enum"] = values
        elif values:
            # Gemini only takes string enums; keep the choice visible to the model instead.
            hint = "Allowed values: " + ", ".join(str(v) for v in values) + "."
            out["description"] = f"{out['description']} {hint}" if "description" in out else hint

    fmt = node.get("format")
    if isinstance(fmt, str) and fmt in GEMINI_FORMATS.get(type_, set()):
        out["format"] = fmt

    if type_ == "array":
        items = node.get("items")
        if isinstance(items, list):  # tuple-style items
            items = items[0] if len(items) == 1 else None
        out["items"] = _convert(items, defs, depth + 1, f"{path}[]") if isinstance(items, dict) else {"type": "string"}
        for src, dst in (("minItems", "min_items"), ("maxItems", "max_items")):
            if isinstance(node.get(src), int) and not isinstance(node.get(src), bool):
                out[dst] = node[src]

    if type_ == "object":
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        required = [r for r in node.get("required") or [] if isinstance(r, str)]
        converted_props = {}
        for name, prop in properties.items():
            try:
                converted_props[name] = _convert(prop, defs, depth + 1, f"{path}.{name}")
            except SchemaError:
                if name in required:
                    raise  # the model could never fill a required argument it can't see
                # An optional argument Gemini can't describe is simply not offered.
        nested_empty = not converted_props and path != "parameters"
        if nested_empty:
            # A free-form nested object ({"type": "object"} with no properties) is
            # rejected by Gemini, so it can't be offered at all.
            raise SchemaError(f"{path}: free-form object with no properties is not supported")
        out["properties"] = converted_props
        kept_required = [r for r in required if r in converted_props]
        if kept_required:
            out["required"] = kept_required

    # Belt and braces: never emit a key Gemini doesn't know.
    return {k: v for k, v in out.items() if k in GEMINI_KEYS}
