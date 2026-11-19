"""Go unit extraction for the stellar-review facts pack: `func` and `type`
declarations with stable IDs and whitespace-insensitive content hashes.

Pure text processing: no git, no I/O. facts.py owns the git side.
Limits, by design (not a lexer): a `type (...)` group and a multi-line raw
string containing braces are not tracked unit by unit.
"""

from __future__ import annotations

import hashlib
import re

GO_EXT = ".go"

# `func Name(`, `func (r *Recv[T]) Name(`. Methods are qualified by receiver
# type so two `Run` methods on different types get distinct, order-stable IDs.
FUNC_RE = re.compile(
    r"^func\s+(?:\(\s*(?:\w+\s+)?\*?\s*(?P<recv>[A-Za-z_]\w*)[^)]*\)\s*)?(?P<name>[A-Za-z_]\w*)"
)
# `type Name ...` (struct, interface, alias, defined type). `type (` has no name.
TYPE_RE = re.compile(r"^type\s+(?P<name>[A-Za-z_]\w*)")

BODY_CAP_LINES = 120
TRUNCATION_MARKER = "// ... (truncated)"


def strip_strings_comments(line: str, in_block: bool) -> tuple[str, bool]:
    """Remove string/rune literals and comments for brace counting. The
    caller threads the block-comment state across lines."""
    out = []
    i = 0
    while i < len(line):
        ch = line[i]
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
            else:
                i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "/" and nxt == "/":
            break
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < len(line) and line[i] != quote:
                i += 2 if line[i] == "\\" and quote != "`" else 1
            i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block


def find_unit_end(lines: list[str], start: int, kind: str) -> int:
    """1-based end line of the unit starting at 0-based index `start`."""
    depth = 0
    parens = 0
    seen_open = False
    in_block = False
    for i in range(start, len(lines)):
        cleaned, in_block = strip_strings_comments(lines[i], in_block)
        depth += cleaned.count("{") - cleaned.count("}")
        parens += cleaned.count("(") - cleaned.count(")")
        seen_open = seen_open or "{" in cleaned
        if seen_open and depth <= 0:
            return i + 1
        # `type X int` / `type X = Y` / a body-less func declaration
        if not seen_open and parens <= 0 and not cleaned.rstrip().endswith((",", "(")):
            if kind == "type" or i + 1 >= len(lines) or not lines[i + 1].lstrip().startswith("{"):
                return i + 1
    return len(lines)


def unit_id(path: str, name: str) -> str:
    """The one owner of the unit-ID format (`path::name`)."""
    return f"{path}::{name}"


def truncate_body(body: str) -> tuple[str, bool]:
    lines = body.splitlines()
    if len(lines) <= BODY_CAP_LINES:
        return body, False
    return "\n".join(lines[:BODY_CAP_LINES]) + "\n" + TRUNCATION_MARKER, True


def extract_signature(body: str) -> str:
    """Up to the body-opening `{` at paren depth 0, whitespace-collapsed."""
    depth = 0
    out = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch == "{":
            break
        out.append(ch)
    return " ".join("".join(out).split())[:400]


def content_hash(text: str) -> str:
    """Whitespace-insensitive content hash."""
    norm = "\n".join(line.rstrip() for line in text.strip().splitlines() if line.strip())
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def signature_hash(signature: str) -> str:
    return hashlib.sha256(" ".join(signature.split()).encode()).hexdigest()[:16]


def _record(path: str, kind: str, name: str, start: int, end: int, body: str, signature: str) -> dict:
    """Every unit carries the full record shape; facts._mark_changed is the
    only flag-flipper."""
    capped, truncated = truncate_body(body)
    return {
        "id": unit_id(path, name),
        "path": path,
        "kind": kind,
        "name": name,
        "start": start,
        "end": end,
        "signature": signature,
        "signature_hash": signature_hash(signature) if signature else "",
        "hash": content_hash(body),
        "body": capped,
        "body_truncated": truncated,
        "changed": False,
        "is_new": False,
    }


def extract_units(path: str, content: str) -> list[dict]:
    """Func and type units of a Go file. Duplicate names (build-tag twins)
    get a `#2`, `#3` suffix in file order."""
    if not path.endswith(GO_EXT):
        return []
    lines = content.splitlines()
    seen: dict[str, int] = {}
    units: list[dict] = []
    for idx, line in enumerate(lines):
        m = FUNC_RE.match(line)
        kind = "fn"
        if not m:
            m = TYPE_RE.match(line)
            kind = "type"
        if not m:
            continue
        name = m.group("name")
        if kind == "fn" and m.groupdict().get("recv"):
            name = f"{m.group('recv')}.{name}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        if count:
            name = f"{name}#{count + 1}"
        end = find_unit_end(lines, idx, kind)
        body = "\n".join(lines[idx:end])
        units.append(_record(path, kind, name, idx + 1, end, body, extract_signature(body)))
    return units


def file_unit(path: str, content: str) -> dict:
    """Whole-file fallback for a Go file with no func or type unit."""
    return _record(path, "file", "__file__", 1, len(content.splitlines()), content, "")
