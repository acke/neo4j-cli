#!/usr/bin/env python3
"""stellar-review facts extractor: the deterministic facts pack for a review
round — changed Go files, their func/type units with stable IDs and content
hashes, and per-file diff hunks. Stdlib only, no network, byte-identical
output for identical input.

    facts.py [--base SHA] [--head SHA] [--out PATH] [--repo DIR]

--base defaults to `git merge-base HEAD origin/main` (then `main`), --head to
HEAD, --out to <repo>/.stellar/facts.json. CI passes --base/--head from the
pull-request payload (shallow checkouts have no merge base).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

from units import GO_EXT, content_hash, extract_units, file_unit, unit_id

VERSION = 1


def ensure_parent(path: str) -> str:
    """Create the output file's parent directory; return the absolute path."""
    out = os.path.abspath(path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return out


def git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", repo, *args], check=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out.stdout.decode("utf-8", errors="replace")


def default_base(repo: str) -> str:
    for ref in ("origin/main", "main"):
        try:
            return git(repo, "merge-base", "HEAD", ref).strip()
        except subprocess.CalledProcessError:
            continue
    raise SystemExit("facts.py: cannot resolve a merge base; pass --base explicitly")


def _units_or_file(path: str, content: str) -> list[dict]:
    units = extract_units(path, content)
    if not units and path.endswith(GO_EXT):
        units = [file_unit(path, content)]
    return units


def _file_facts(repo: str, base: str, head: str, row: tuple[str, str, str],
                status: dict[str, tuple[str, str | None]]) -> tuple[dict, list[dict], list[dict]]:
    """One changed file: record, head units, base units."""
    added_s, deleted_s, path = row
    binary = added_s == "-"
    st, old_path = status.get(path, ("m", None))
    base_path = old_path or path

    _, ranges = parse_file_diff(git(repo, "diff", "--unified=0", base, head, "--", base_path, path))
    record = {
        "path": path,
        "status": st,
        "old_path": old_path,
        "added": 0 if binary else int(added_s),
        "deleted": 0 if binary else int(deleted_s),
        "content_hash": None,
        "hunks": ranges,
    }
    if st == "d" or not path.endswith(GO_EXT):
        return record, [], []

    # A head-side read failure must never silently drop a live file's units.
    head_content = git(repo, "show", f"{head}:{path}")
    record["content_hash"] = content_hash(head_content)

    base_units: list[dict] = []
    if st != "a":
        try:
            base_content = git(repo, "show", f"{base}:{base_path}")
        except subprocess.CalledProcessError:
            # fail-open (units read as new/changed), but loud
            print(f"facts.py: warning: cannot read base blob {base_path}", file=sys.stderr)
        else:
            base_units = _units_or_file(base_path, base_content)
            # Renames register base units under the NEW path id, so the
            # comparison with head units just works.
            if old_path:
                for u in base_units:
                    u["id"] = unit_id(path, u["name"])
    return record, _units_or_file(path, head_content), base_units


def _mark_changed(units: list[dict], base_units: dict[str, dict]) -> list[str]:
    """Flag each head unit against the merge-base inventory. The content hash
    is authoritative: a unit whose normalized body equals base is unchanged
    even if a hunk touched its span. Returns the ids of deleted units."""
    head_ids = set()
    for u in units:
        head_ids.add(u["id"])
        prev = base_units.get(u["id"])
        u["is_new"] = prev is None
        u["changed"] = prev is None or prev["hash"] != u["hash"]
    return sorted(uid for uid in base_units if uid not in head_ids)


def build_facts(repo: str, base: str, head: str) -> dict:
    numstat = git(repo, "diff", "--numstat", "-z", "--find-renames", base, head)
    name_status = git(repo, "diff", "--name-status", "-z", "--find-renames", base, head)
    status = parse_name_status_z(name_status)

    files: list[dict] = []
    units: list[dict] = []
    base_units: dict[str, dict] = {}
    for row in parse_numstat_z(numstat):
        record, head_units, base_us = _file_facts(repo, base, head, row, status)
        files.append(record)
        units.extend(head_units)
        base_units.update({u["id"]: u for u in base_us})

    deleted = _mark_changed(units, base_units)
    units.sort(key=lambda u: u["id"])
    files.sort(key=lambda f: f["path"])
    return {
        "version": VERSION,
        "base": base,
        "head": head,
        "files": files,
        "units": units,
        "changed_units": [u["id"] for u in units if u["changed"]],
        "deleted_units": deleted,
    }


def parse_name_status_z(raw: str) -> dict[str, tuple[str, str | None]]:
    """`git diff --name-status -z`: path -> (status, old_path|None)."""
    toks = raw.split("\0")
    out: dict[str, tuple[str, str | None]] = {}
    i = 0
    while i < len(toks):
        code = toks[i]
        if not code:
            i += 1
            continue
        if code[0] in ("R", "C"):
            out[toks[i + 2]] = ("renamed" if code[0] == "R" else "copied", toks[i + 1])
            i += 3
        else:
            out[toks[i + 1]] = (code[0].lower(), None)
            i += 2
    return out


def parse_numstat_z(raw: str) -> list[tuple[str, str, str]]:
    """`git diff --numstat -z`: [(added, deleted, new_path)]. Rename rows
    carry an empty path field followed by old/new path tokens."""
    toks = raw.split("\0")
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if not tok.strip():
            i += 1
            continue
        parts = tok.split("\t")
        if len(parts) >= 3 and parts[2]:
            out.append((parts[0], parts[1], parts[2]))
            i += 1
        else:
            out.append((parts[0], parts[1], toks[i + 2]))
            i += 3
    return out


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_file_diff(diff_text: str) -> tuple[set[int], list[list[int]]]:
    """One file's unified diff -> (added new-file line numbers, [start, end]
    new-file range per hunk; a deletion-only hunk contributes the line it
    anchored at)."""
    added: set[int] = set()
    ranges: list[list[int]] = []
    new_line = 0
    hunk_start = hunk_end = None
    for line in diff_text.splitlines():
        if HUNK_RE.match(line):
            if hunk_start is not None:
                ranges.append([hunk_start, max(hunk_end, hunk_start)])
            new_line = int(HUNK_RE.match(line).group(1))
            hunk_start, hunk_end = new_line, new_line - 1
            continue
        if hunk_start is None or line.startswith("\\"):
            continue  # file headers / "No newline at end of file"
        if line.startswith("+"):
            added.add(new_line)
            hunk_end = new_line
            new_line += 1
        elif not line.startswith("-"):
            hunk_end = new_line
            new_line += 1
    if hunk_start is not None:
        ranges.append([hunk_start, max(hunk_end, hunk_start)])
    return added, ranges


def hunks_by_path(facts_doc: dict) -> dict[str, list[list[int]]]:
    return {f["path"]: f["hunks"] for f in facts_doc["files"]}


def range_in_hunks(path: str, start: int, end: int, hbp: dict) -> bool:
    """A line range [start, end] intersects one of the file's hunk ranges."""
    return any(s <= end and start <= e for s, e in hbp.get(path, []))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="base SHA (default: merge-base HEAD origin/main)")
    ap.add_argument("--head", default="HEAD", help="head SHA (default: HEAD)")
    ap.add_argument("--out", help="output path (default: <repo>/.stellar/facts.json)")
    ap.add_argument("--repo", default=".", help="repository directory")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    head = git(repo, "rev-parse", args.head).strip()
    base = git(repo, "rev-parse", args.base or default_base(repo)).strip()
    facts = build_facts(repo, base, head)
    out = ensure_parent(args.out or os.path.join(repo, ".stellar", "facts.json"))
    with open(out, "w") as fh:
        json.dump(facts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"facts: {len(facts['files'])} files, {len(facts['units'])} units "
          f"({len(facts['changed_units'])} changed) -> {out}")


if __name__ == "__main__":
    main()
