#!/usr/bin/env python3
"""Verify every Anchor account SIZE constant against its Borsh layout."""

from __future__ import annotations

import re
import sys
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "protocol/anchor/programs/boulder_rollers/src"
# The core program's modules; stage 1 accounts size themselves with INIT_SPACE.
TEXT = "\n".join(
    path.read_text()
    for path in sorted(SRC.glob("*.rs"))
    if not path.name.startswith(("stage1", "smoke_helpers"))
)

TYPE_SIZES = {
    "u8": 1,
    "i8": 1,
    "bool": 1,
    "u16": 2,
    "i16": 2,
    "u32": 4,
    "i32": 4,
    "f32": 4,
    "u64": 8,
    "i64": 8,
    "f64": 8,
    "u128": 16,
    "i128": 16,
    "Pubkey": 32,
    # Anchor serializes fieldless enums as their u8 variant discriminator.
    "BalanceAuthorityModel": 1,
    "CardType": 1,
    "RiderBalanceStatus": 1,
    # Non-account custom struct embedded in VaultLeaderboard.entries.
    "LeaderEntry": 32 + 4 + 8,
}

MAX_VEC_LENGTHS = {
    ("VaultLeaderboard", "entries"): 10,
}


def strip_line_comments(source: str) -> str:
    return re.sub(r"//[^\n]*", "", source)


def field_size(account: str, field: str, type_name: str) -> int | None:
    type_name = type_name.strip()
    if type_name in TYPE_SIZES:
        return TYPE_SIZES[type_name]

    match = re.fullmatch(r"\[\s*(\w+)\s*;\s*(\d+)\s*\]", type_name)
    if match and match.group(1) in TYPE_SIZES:
        return TYPE_SIZES[match.group(1)] * int(match.group(2))

    match = re.fullmatch(r"Option\s*<\s*(.+)\s*>", type_name)
    if match:
        inner = field_size(account, field, match.group(1))
        return None if inner is None else 1 + inner

    match = re.fullmatch(r"Vec\s*<\s*(.+)\s*>", type_name)
    if match:
        inner = field_size(account, field, match.group(1))
        max_len = MAX_VEC_LENGTHS.get((account, field))
        if inner is None or max_len is None:
            return None
        return 4 + (max_len * inner)

    return None


def matching_brace(source: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unclosed brace at byte {open_index}")


def impl_blocks(source: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in re.finditer(r"\bimpl\s+(\w+)\s*\{", source):
        open_index = source.find("{", match.start())
        close_index = matching_brace(source, open_index)
        blocks[match.group(1)] = source[open_index + 1 : close_index]
    return blocks


def evaluate_usize_constants(block: str) -> dict[str, int]:
    expressions = {
        match.group(1): " ".join(match.group(2).split())
        for match in re.finditer(
            r"pub\s+const\s+(\w+)\s*:\s*usize\s*=\s*([^;]+);",
            strip_line_comments(block),
            re.S,
        )
    }
    resolved: dict[str, int] = {}

    while expressions:
        progress = False
        for name, raw_expression in list(expressions.items()):
            expression = raw_expression
            for const_name, value in resolved.items():
                expression = expression.replace(f"Self::{const_name}", str(value))
            expression = expression.replace("_", "")
            if "Self::" in expression:
                continue
            if not re.fullmatch(r"[\d\s+*()/.-]+", expression):
                continue
            value = eval(expression, {"__builtins__": {}}, {})
            if not isinstance(value, int):
                continue
            resolved[name] = value
            del expressions[name]
            progress = True
        if not progress:
            break

    return resolved


def account_structs(source: str) -> dict[str, list[tuple[str, str]]]:
    structs: dict[str, list[tuple[str, str]]] = {}
    pattern = r"#\[account\]\s*(?:#\[derive[^\]]*\]\s*)?pub struct (\w+)\s*\{(.*?)\n\}"
    for match in re.finditer(pattern, source, re.S):
        name, body = match.group(1), match.group(2)
        fields = []
        for line in body.splitlines():
            field_match = re.match(r"\s*pub\s+(\w+)\s*:\s*([^,]+),", line)
            if field_match:
                fields.append((field_match.group(1), field_match.group(2).strip()))
        structs[name] = fields
    return structs


def main() -> int:
    structs = account_structs(TEXT)
    blocks = impl_blocks(TEXT)
    constants = {
        name: evaluate_usize_constants(block)
        for name, block in blocks.items()
    }

    print(f"source: {SRC}")
    print(f"{'struct':<28}{'declared':>9}{'computed':>9}  verdict")
    print("-" * 62)
    issues = 0

    for name, fields in sorted(structs.items()):
        computed = 8
        unknown = []
        for field, type_name in fields:
            size = field_size(name, field, type_name)
            if size is None:
                unknown.append(f"{field}:{type_name}")
            else:
                computed += size

        declared = constants.get(name, {}).get("SIZE")
        if unknown:
            verdict = f"UNKNOWN ({', '.join(unknown)})"
            issues += 1
        elif declared is None:
            verdict = "MISSING OR UNPARSED SIZE"
            issues += 1
        elif declared == computed:
            verdict = "OK"
        else:
            verdict = f"MISMATCH ({declared - computed:+d})"
            issues += 1

        print(f"{name:<28}{str(declared or '-'):>9}{computed:>9}  {verdict}")

    print(f"\nverified={len(structs) - issues} failed={issues} total={len(structs)}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
