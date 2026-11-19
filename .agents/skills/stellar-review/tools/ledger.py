#!/usr/bin/env python3
"""stellar-review cross-round ledger.

Keeps per-unit state (content hash) and finding lifecycles (open / resolved /
waived) across review rounds, so round N+1 re-reviews exactly what changed,
never the whole diff again.

    ledger.py scope  --facts F [--ledger L] [--out scope.json]
    ledger.py update --facts F [--ledger L] --findings R [--scope S]
                     [--resolve ID:note ...] [--waive ID:reason ...] [--out L2]

With no --ledger (or a missing file), round 1 judges the units the diff hunks
touch. The ledger is the only stateful component: CI round-trips it through
the PR summary comment, locally it lives at .stellar/ledger.json.

Scope rule: a unit is "changed" only if it differs from the merge base (the
facts pack says so) AND from the ledger. A rebase or force-push moves hashes
without the PR touching the code, so it never widens scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

import facts as facts_mod
from facts import ensure_parent

VERSION = 1
RESOLVED_TAIL_CAP = 12
SEALED_NOTE = "sealed units cannot produce new findings this round"
QUOTE_WS = re.compile(r"\s+")


def empty_ledger() -> dict:
    # units: uid -> "hash:signature_hash" (compact: the PR comment blob must
    # stay far under GitHub's 65536-char limit)
    return {"version": VERSION, "rounds": 0, "last_head": None, "units": {},
            "findings": {}, "resolved_tail": []}


def unit_hash(led: dict, uid: str) -> str | None:
    v = led["units"].get(uid)
    return v.split(":", 1)[0] if v else None


def load_ledger(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return empty_ledger()
    with open(path) as fh:
        led = json.load(fh)
    if led.get("version") != VERSION:
        raise SystemExit(f"ledger.py: unsupported ledger version {led.get('version')}")
    return led


def save_ledger(led: dict, path: str) -> None:
    with open(ensure_parent(path), "w") as fh:
        json.dump(led, fh, indent=1, sort_keys=True)
        fh.write("\n")


def trim_for_comment(led: dict) -> dict:
    """The comment-embedded form: live state plus the resolved tail, no full
    resolved history."""
    return {**led, "findings": {k: f for k, f in led["findings"].items()
                                if f["status"] != "resolved"}}


def file_proxy_hash(facts: dict, path: str) -> str | None:
    """The file's content hash. Unit-less findings ride it, so their
    resolution checks fire on ANY change to the file."""
    for f in facts["files"]:
        if f["path"] == path:
            return f.get("content_hash")
    return None


def _staleness_reason(f: dict, facts_units: dict, facts: dict) -> str | None:
    """Why a filed finding needs a resolution check this round (None = untouched,
    carry it as context). The file-level rule exists because a fix can land in a
    sibling unit (helper extracted, call site fixed)."""
    uid = f.get("unit")
    if uid:
        if uid not in facts_units:
            return "unit no longer exists"
        if facts_units[uid]["hash"] != f.get("unit_hash_at_filing"):
            return "unit changed since filing"
        filed_file_hash = f.get("file_hash_at_filing")
        if filed_file_hash and file_proxy_hash(facts, f["path"]) != filed_file_hash:
            return "file changed since filing (its fix may have landed in a sibling unit)"
        return None
    if file_proxy_hash(facts, f["path"]) != f.get("unit_hash_at_filing"):
        return "file changed since filing"
    return None


def compute_scope(facts: dict, led: dict) -> dict:
    full = led["rounds"] == 0
    open_findings = {k: f for k, f in led["findings"].items() if f["status"] == "open"}
    waived = {k: f for k, f in led["findings"].items() if f["status"] == "waived"}
    facts_units = {u["id"]: u for u in facts["units"]}

    # Judged against the LEDGER (previous round) and the merge base: a push
    # that touches nothing since the last round scopes to zero units.
    changed = {uid for uid, u in facts_units.items()
               if (u["changed"] or u["is_new"])
               and (uid not in led["units"] or unit_hash(led, uid) != u["hash"])}

    resolve_checks = []
    for fid, f in sorted(open_findings.items()):
        reason = _staleness_reason(f, facts_units, facts)
        if reason:
            resolve_checks.append({"finding_id": fid, "unit": f.get("unit"),
                                   "path": f["path"], "reason": reason,
                                   "summary": f.get("summary", ""),
                                   "remedy": f.get("remedy", ""),
                                   "quote": f.get("quote", "")})

    if full:
        # Round 1 judges the units the diff hunks touch (plus new units); the
        # rest of a changed file is context.
        hbp = facts_mod.hunks_by_path(facts)
        judged = {uid for uid, u in facts_units.items()
                  if u["is_new"] or facts_mod.range_in_hunks(u["path"], u["start"], u["end"], hbp)}
    else:
        judged = changed
    review = sorted(judged)
    sealed = sorted(set(facts_units) - judged)

    return {
        "version": VERSION,
        "round": led["rounds"] + 1,
        "full": full,
        "head": facts["head"],
        "review_units": review,
        "review_files": sorted({facts_units[uid]["path"] for uid in review}),
        "sealed_units": sealed,
        "sealed_note": SEALED_NOTE,
        "resolve_checks": resolve_checks,
        "open_findings": [
            {"id": fid, "path": f["path"], "lines": f["lines"], "severity": f["severity"],
             "summary": f["summary"], "unit": f.get("unit")}
            for fid, f in sorted(open_findings.items())],
        "waived": [
            {"id": fid, "path": f["path"], "summary": f["summary"], "reason": f.get("waive_reason", "")}
            for fid, f in sorted(waived.items())],
        # Already litigated and closed: later rounds neither re-report nor
        # contradict these remedies.
        "resolved_recent": led.get("resolved_tail", []),
        "stats": {"units_total": len(facts_units), "units_changed": len(changed),
                  "units_sealed": len(sealed), "units_in_scope": len(review)},
    }


def _close_from_spec(led: dict, specs: list[str], round_no: int, status: str, note_key: str) -> None:
    """Close open findings from "finding-id:note" specs: the one lifecycle
    idiom shared by waivers and the resolve escape hatch."""
    for spec in specs:
        fid, _, note = spec.partition(":")
        f = led["findings"].get(fid.strip())
        if f and f["status"] == "open":
            f["status"] = status
            f["round_closed"] = round_no
            f[note_key] = note.strip()


def round_dispositions(led: dict, round_no: int) -> dict:
    """The round's finding dispositions: new / carried / resolved / waived."""
    after = led["findings"]
    by_id = lambda f: f["id"]  # noqa: E731
    return {
        "new": sorted((f for f in after.values()
                       if f.get("round_filed") == round_no and f["status"] == "open"), key=by_id),
        "carried": sorted((f for f in after.values()
                           if f["status"] == "open" and f.get("round_filed") != round_no), key=by_id),
        "resolved": sorted(f["id"] for f in after.values()
                           if f["status"] == "resolved" and f["round_closed"] == round_no),
        "waived": sorted((f for f in after.values()
                          if f["status"] == "waived" and f["round_closed"] == round_no), key=by_id),
    }


def _resolved_tail(led: dict) -> list[dict]:
    """The most recent resolved findings, compact: the next rounds' "already
    litigated" memory. Capped: it rides the PR summary comment."""
    resolved = sorted((f for f in led["findings"].values() if f["status"] == "resolved"),
                      key=lambda f: f.get("round_closed", 0), reverse=True)
    return [{"id": f["id"], "path": f["path"], "summary": f.get("summary", ""),
             "remedy": f.get("remedy", ""), "round_closed": f.get("round_closed", 0)}
            for f in resolved[:RESOLVED_TAIL_CAP]]


def hash_quote(quote: str) -> str:
    return hashlib.sha256(QUOTE_WS.sub(" ", quote.strip()).encode()).hexdigest()[:16]


def apply_update(facts: dict, led: dict, review: dict, waivers: list[str],
                 allowed_resolve_ids: set[str] | None = None,
                 resolves: list[str] | None = None) -> dict:
    round_no = led["rounds"] + 1
    facts_units = {u["id"]: u for u in facts["units"]}

    # Model resolutions are accepted only for ids this round's scope checked,
    # so a confused model cannot resolve a finding on untouched code
    # (None = permissive, for callers without a scope document).
    for res in review.get("resolutions", []):
        fid = res.get("finding_id")
        if allowed_resolve_ids is not None and fid not in allowed_resolve_ids:
            print(f"ledger.py: ignoring out-of-scope resolution for {fid}", file=sys.stderr)
            continue
        f = led["findings"].get(fid)
        if f and f["status"] == "open" and res.get("addressed"):
            f["status"] = "resolved"
            f["round_closed"] = round_no
    _close_from_spec(led, resolves or [], round_no, "resolved", "resolve_note")

    seq = sum(1 for f in led["findings"].values() if f.get("round_filed") == round_no)
    for find in review.get("findings", []):
        seq += 1
        fid = f"F-{round_no}-{seq}"
        uid = find.get("unit")
        filed_hash = facts_units.get(uid, {}).get("hash") if uid else file_proxy_hash(facts, find["path"])
        led["findings"][fid] = {
            "id": fid,
            "unit": uid,
            "path": find["path"],
            "lines": [find.get("start_line"), find.get("end_line")],
            "severity": find["severity"],
            "area": find["area"],
            "checklist_id": find.get("checklist_id", ""),
            "quote_hash": hash_quote(find.get("quote", "")),
            "summary": find.get("why", "")[:200],
            "remedy": find.get("remedy", "")[:300],
            "status": "open",
            "unit_hash_at_filing": filed_hash,
            "file_hash_at_filing": file_proxy_hash(facts, find["path"]),
            "quote": find.get("quote", "")[:400],
            "round_filed": round_no,
            "confidence": find.get("confidence", "high"),
        }

    # applied after filing so a finding can be filed and waived in one update
    _close_from_spec(led, waivers, round_no, "waived", "waive_reason")

    # Units that vanished from the diff's file set stay in the ledger but stop
    # participating in scope (they are neither in facts nor sealed).
    for uid, u in facts_units.items():
        led["units"][uid] = f"{u['hash']}:{u['signature_hash']}"

    led["resolved_tail"] = _resolved_tail(led)
    led["rounds"] = round_no
    led["last_head"] = facts["head"]
    return led


def _cmd_scope(args: argparse.Namespace, facts: dict, led: dict) -> None:
    scope = compute_scope(facts, led)
    out = json.dumps(scope, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(ensure_parent(args.out), "w") as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)
    s = scope["stats"]
    print(f"scope: round {scope['round']} ({'full' if scope['full'] else 'incremental'}): "
          f"{s['units_in_scope']}/{s['units_total']} units in scope, "
          f"{s['units_sealed']} sealed, {len(scope['resolve_checks'])} resolution checks",
          file=sys.stderr)


def _cmd_update(args: argparse.Namespace, facts: dict, led: dict) -> None:
    with open(args.findings) as fh:
        review = json.load(fh)
    allowed = None
    if args.scope:
        # a flag with a missing file fails closed and loudly
        with open(args.scope) as fh:
            allowed = {rc["finding_id"] for rc in json.load(fh).get("resolve_checks", [])}
    led = apply_update(facts, led, review, args.waive, allowed_resolve_ids=allowed, resolves=args.resolve)
    out_path = args.out or args.ledger
    if not out_path:
        raise SystemExit("ledger.py update: pass --ledger or --out")
    save_ledger(led, out_path)
    open_n = sum(1 for f in led["findings"].values() if f["status"] == "open")
    print(f"ledger: round {led['rounds']} recorded, {open_n} open findings -> {out_path}", file=sys.stderr)


COMMANDS = {
    "scope": {"handler": _cmd_scope, "extra_args": []},
    "update": {"handler": _cmd_update, "extra_args": [
        (("--findings",), {"required": True}),
        (("--scope",), {"help": "scope.json; resolutions are accepted only for ids in its resolve_checks"}),
        (("--resolve",), {"action": "append", "default": [],
                          "help": "finding-id:note; human escape hatch for fixes the staleness rules cannot see"}),
        (("--waive",), {"action": "append", "default": [],
                        "help": "finding-id:reason; marks an open finding waived"}),
    ]},
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, spec in COMMANDS.items():
        p = sub.add_parser(name)
        p.add_argument("--facts", required=True)
        p.add_argument("--ledger")
        p.add_argument("--out")
        for flags, kwargs in spec["extra_args"]:
            p.add_argument(*flags, **kwargs)
    args = ap.parse_args()
    with open(args.facts) as fh:
        facts = json.load(fh)
    COMMANDS[args.cmd]["handler"](args, facts, load_ledger(args.ledger))


if __name__ == "__main__":
    main()
