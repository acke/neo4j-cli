#!/usr/bin/env python3
"""Cost block for a card record: python3 -I bench/card_cost.py <session_id> [--split NAME=ISO_UTC ...].

Reads the Claude Code transcript of one session (plus its subagent transcripts) and prints the `cost` JSON of
`swf-card-record/1`. Dollars are an API list-price estimate, not billed spend. A model without a price here gives
`unavailable`, never 0. Transcripts store a streaming snapshot of output_tokens per message (input and cache
tokens are exact), so output tokens and dollars are a floor, not a total. `--split` marks where a phase starts (ISO UTC); the phase before the first split is `start`.
"""
import argparse, collections, glob, json, os, sys
from datetime import datetime

# USD per million tokens. Fitted exactly to Claude Code's own total_cost_usd over bench/results (198 runs).
# cache_write_1h is 2x input (Anthropic's 1-hour cache ratio); the fit only covers 5-minute writes.
PRICES = {
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.10, "cache_write_5m": 2.50, "cache_write_1h": 4.00},
}
PRICE_BASIS = "API list price"
UNAVAILABLE = "unavailable"


def transcripts(session_id, projects_dir):
    main = glob.glob(os.path.join(projects_dir, "*", session_id + ".jsonl"))
    if not main:
        sys.exit(f"no transcript for session {session_id} under {projects_dir}")
    subs = glob.glob(os.path.join(projects_dir, "*", session_id, "**", "*.jsonl"), recursive=True)
    return main[0], sorted(subs)


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def messages(path):
    """One entry per API message id: the transcript repeats a message once per content block."""
    seen = {}
    for line in open(path, encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        u = m.get("usage")
        if not m.get("id") or not u:
            continue
        calls = {b["id"] for b in m.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"}
        prev = seen.get(m["id"])
        if prev is None or u.get("output_tokens", 0) >= prev["usage"].get("output_tokens", 0):
            seen[m["id"]] = {"usage": u, "model": m.get("model"), "ts": d["timestamp"], "calls": calls | (prev["calls"] if prev else set())}
        elif prev:
            prev["calls"] |= calls
    return seen.values()


def dollars(model, u):
    p = PRICES.get(model)
    if p is None:
        return None
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens", 0)
    w5m = cc.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) - w1h)
    return (u.get("input_tokens", 0) * p["input"] + u.get("output_tokens", 0) * p["output"]
            + u.get("cache_read_input_tokens", 0) * p["cache_read"] + w5m * p["cache_write_5m"] + w1h * p["cache_write_1h"]) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--split", action="append", default=[], metavar="NAME=ISO_UTC")
    a = ap.parse_args()

    splits = sorted((parse_ts(t), n) for n, t in (s.split("=", 1) for s in a.split))
    main_path, sub_paths = transcripts(a.session_id, a.projects_dir)
    msgs = [m for p in [main_path] + sub_paths for m in messages(p)]

    def phase(ts):
        name = "start"
        for t, n in splits:
            if parse_ts(ts) >= t:
                name = n
        return name

    ph = collections.defaultdict(lambda: {"messages": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                                          "cache_creation_input_tokens": 0, "tool_calls": 0, "dollars": 0.0, "first": None, "last": None})
    unpriced = set()
    for m in msgs:
        r, u = ph[phase(m["ts"])], m["usage"]
        r["messages"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            r[k] += u.get(k, 0)
        r["tool_calls"] += len(m["calls"])
        d = dollars(m["model"], u)
        if d is None:
            unpriced.add(m["model"])
        else:
            r["dollars"] += d
        t = parse_ts(m["ts"])
        r["first"] = min(r["first"] or t, t)
        r["last"] = max(r["last"] or t, t)

    out = {}
    for name, r in ph.items():
        out[name] = {k: r[k] for k in ("messages", "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "tool_calls")}
        out[name]["seconds"] = round((r["last"] - r["first"]).total_seconds())
        out[name]["dollars"] = UNAVAILABLE if unpriced else round(r["dollars"], 4)
    total = UNAVAILABLE if unpriced else round(sum(r["dollars"] for r in ph.values()), 4)
    print(json.dumps({"session_id": a.session_id, "phases": out, "subagent_transcripts": len(sub_paths),
                      "dollars_computed": total, "price_basis": PRICE_BASIS, "output_tokens_lower_bound": True,
                      "unpriced_models": sorted(m or "unknown" for m in unpriced)}, indent=1))


if __name__ == "__main__":
    main()
