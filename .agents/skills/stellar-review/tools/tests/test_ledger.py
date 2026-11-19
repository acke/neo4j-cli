"""Tests for ledger.py and incremental.py on a fixture Go repo (offline)."""

import json
import os
import unittest

import helpers
import incremental
import ledger

LIB = "pkg/lib.go"
OTHER = "pkg/other.go"
SHA_BOGUS = "0123456789abcdef0123456789abcdef01234567"


def finding(unit, path, severity="medium"):
    return {"area": "boundaries", "severity": severity, "path": path,
            "start_line": 1, "end_line": 2, "unit": unit, "checklist_id": "std-5",
            "quote": "q", "why": "w", "remedy": "r", "confidence": "high"}


def review(findings=(), resolutions=()):
    return {"version": 1, "findings": list(findings), "resolutions": list(resolutions)}


class GoRepo(helpers.RepoFixture):
    """main has lib.go (Untouched, Parse) and other.go (Other); the PR edits
    Parse's body and adds Extra."""

    def setUp(self):
        super().setUp()
        self.write(LIB, "package pkg\n\nfunc Untouched() {}\n\nfunc Parse(s string) int {\n\treturn len(s)\n}\n")
        self.write(OTHER, "package pkg\n\nfunc Other() int {\n\treturn 1\n}\n")
        self.base = self.commit("base")
        self.git("checkout", "-q", "-b", "pr")
        self.write(LIB, "package pkg\n\nfunc Untouched() {}\n\nfunc Parse(s string) int {\n\treturn len(s) + 1\n}\n\nfunc Extra() {}\n")
        self.commit("pr")

    def uid(self, name, path=LIB):
        return f"{path}::{name}"


class TestRounds(GoRepo):
    def test_first_round_judges_only_hunk_units(self):
        scope = ledger.compute_scope(self.facts_now(self.base), ledger.empty_ledger())
        self.assertTrue(scope["full"])
        self.assertEqual(scope["review_units"], sorted([self.uid("Extra"), self.uid("Parse")]))
        self.assertEqual(scope["sealed_units"], [self.uid("Untouched")])

    def test_second_round_without_a_push_is_empty(self):
        f = self.facts_now(self.base)
        led = ledger.apply_update(f, ledger.empty_ledger(), review(), [])
        scope = ledger.compute_scope(f, led)
        self.assertFalse(scope["full"])
        self.assertEqual(scope["review_units"], [])
        self.assertEqual(led["last_head"], f["head"])

    def test_second_round_reuses_ledger_and_scopes_to_the_new_push(self):
        f1 = self.facts_now(self.base)
        led = ledger.apply_update(f1, ledger.empty_ledger(), review([finding(self.uid("Parse"), LIB)]), [])
        self.assertEqual(list(led["findings"]), ["F-1-1"])

        self.write(LIB, "package pkg\n\nfunc Untouched() {}\n\nfunc Parse(s string) int {\n\treturn len(s) + 2\n}\n\nfunc Extra() {}\n")
        self.commit("fix")
        scope = ledger.compute_scope(self.facts_now(self.base), led)
        self.assertFalse(scope["full"])
        self.assertEqual(scope["review_units"], [self.uid("Parse")])
        self.assertEqual([c["finding_id"] for c in scope["resolve_checks"]], ["F-1-1"])
        self.assertEqual(scope["resolve_checks"][0]["reason"], "unit changed since filing")

        led = ledger.apply_update(self.facts_now(self.base), led,
                                  review(resolutions=[{"finding_id": "F-1-1", "addressed": True}]), [],
                                  allowed_resolve_ids={"F-1-1"})
        self.assertEqual(led["findings"]["F-1-1"]["status"], "resolved")
        self.assertEqual(led["resolved_tail"][0]["id"], "F-1-1")

    def test_rebased_head_never_widens_scope(self):
        f1 = self.facts_now(self.base)
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(), [])

        # main moves on: edits another file and an unrelated unit of lib.go
        self.git("checkout", "-q", "main")
        self.write(OTHER, "package pkg\n\nfunc Other() int {\n\treturn 2\n}\n")
        self.write(LIB, "package pkg\n\nfunc Untouched() { _ = 1 }\n\nfunc Parse(s string) int {\n\treturn len(s)\n}\n")
        new_base = self.commit("main moves")
        self.git("checkout", "-q", "pr")
        self.git("rebase", "-q", "main")

        f2 = self.facts_now(new_base)
        self.assertNotEqual(f2["head"], f1["head"])
        self.assertNotIn(self.uid("Other", OTHER), [u["id"] for u in f2["units"]])
        scope = ledger.compute_scope(f2, led)
        self.assertEqual(scope["review_units"], [])
        self.assertEqual(scope["stats"]["units_changed"], 0)

    def test_unit_equal_to_base_is_not_changed_even_if_ledger_differs(self):
        # the ledger knows a stale hash for a unit the PR no longer differs on
        f = self.facts_now(self.base)
        led = ledger.apply_update(f, ledger.empty_ledger(), review(), [])
        led["units"][self.uid("Untouched")] = "stale:stale"
        scope = ledger.compute_scope(f, led)
        self.assertEqual(scope["review_units"], [])

    def test_waiver_and_resolve_escape_hatch(self):
        f = self.facts_now(self.base)
        led = ledger.apply_update(
            f, ledger.empty_ledger(),
            review([finding(self.uid("Parse"), LIB), finding(self.uid("Extra"), LIB)]), ["F-1-1:ok"])
        self.assertEqual(led["findings"]["F-1-1"]["status"], "waived")
        led = ledger.apply_update(f, led, review(), [], resolves=["F-1-2:fixed elsewhere"])
        self.assertEqual(led["findings"]["F-1-2"]["status"], "resolved")
        d = ledger.round_dispositions(led, 2)
        self.assertEqual(d["resolved"], ["F-1-2"])

    def test_out_of_scope_resolution_is_ignored(self):
        f = self.facts_now(self.base)
        led = ledger.apply_update(f, ledger.empty_ledger(), review([finding(self.uid("Parse"), LIB)]), [])
        led = ledger.apply_update(f, led, review(resolutions=[{"finding_id": "F-1-1", "addressed": True}]), [],
                                  allowed_resolve_ids=set())
        self.assertEqual(led["findings"]["F-1-1"]["status"], "open")

    def test_trim_for_comment_drops_resolved(self):
        f = self.facts_now(self.base)
        led = ledger.apply_update(f, ledger.empty_ledger(), review([finding(self.uid("Parse"), LIB)]), [])
        led = ledger.apply_update(f, led, review(), [], resolves=["F-1-1:x"])
        trimmed = ledger.trim_for_comment(led)
        self.assertEqual(trimmed["findings"], {})
        self.assertEqual(trimmed["resolved_tail"][0]["id"], "F-1-1")


class TestIncremental(GoRepo):
    def head(self):
        return self.git("rev-parse", "HEAD")

    def test_ancestor_last_head_is_the_base(self):
        last = self.head()
        self.write(LIB, "package pkg\n\nfunc Untouched() {}\n\nfunc Parse(s string) int {\n\treturn 0\n}\n\nfunc Extra() {}\n")
        self.commit("next")
        self.assertEqual(incremental.resolve_base(self.dir, last, self.head()), (last, "ancestor"))

    def test_rebased_last_head_falls_back_to_their_merge_base_not_main(self):
        last = self.head()
        self.git("checkout", "-q", "main")
        self.write(OTHER, "package pkg\n\nfunc Other() int {\n\treturn 2\n}\n")
        self.commit("main moves")
        self.git("checkout", "-q", "pr")
        self.git("rebase", "-q", "main")
        base, reason = incremental.resolve_base(self.dir, last, self.head())
        self.assertEqual(reason, "diverged-merge-base")
        self.assertEqual(base, self.base)

    def test_unreachable_last_head_gives_no_base_and_never_widens_scope(self):
        self.assertEqual(incremental.resolve_base(self.dir, SHA_BOGUS, self.head()),
                         (None, "last-head-unreachable"))
        self.assertEqual(incremental.resolve_base(self.dir, "not-a-sha", self.head()),
                         (None, "no-valid-last-head"))
        self.assertEqual(incremental.resolve_base(self.dir, None, self.head()),
                         (None, "no-valid-last-head"))

        # the ledger still scopes incrementally: unreachable last_head is not
        # a reason for a full re-review
        f = self.facts_now(self.base)
        led = ledger.apply_update(f, ledger.empty_ledger(), review(), [])
        led["last_head"] = SHA_BOGUS
        scope = ledger.compute_scope(f, led)
        self.assertFalse(scope["full"])
        self.assertEqual(scope["review_units"], [])

    def test_patch_is_limited_to_pr_files_and_literal(self):
        last = self.head()
        self.write(LIB, "package pkg\n\nfunc Untouched() {}\n\nfunc Parse(s string) int {\n\treturn 0\n}\n\nfunc Extra() {}\n")
        self.write(OTHER, "package pkg\n\nfunc Other() int {\n\treturn 9\n}\n")
        self.commit("next")
        patch = incremental.incremental_patch(self.dir, last, self.head(), [LIB])
        self.assertIn(LIB, patch)
        self.assertNotIn(OTHER, patch)
        self.assertEqual(incremental.incremental_patch(self.dir, last, self.head(), [":(exclude)pkg/lib.go"]), "")
        self.assertEqual(incremental.incremental_patch(self.dir, last, self.head(), []), "")


class TestCLI(GoRepo):
    """The scripts end to end, no network."""

    def run_tool(self, script, *args):
        import subprocess
        import sys
        tools = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return subprocess.run([sys.executable, os.path.join(tools, script), *args],
                              check=True, capture_output=True, text=True, cwd=self.dir)

    def test_facts_scope_update_incremental_round_trip(self):
        out = os.path.join(self.dir, ".stellar")
        facts_p, scope_p, led_p, rev_p, patch_p = (os.path.join(out, n) for n in
                                                  ("facts.json", "scope.json", "ledger.json", "review.json", "inc.patch"))
        self.run_tool("facts.py", "--base", self.base, "--out", facts_p, "--repo", self.dir)
        self.run_tool("ledger.py", "scope", "--facts", facts_p, "--out", scope_p)
        with open(scope_p) as fh:
            self.assertTrue(json.load(fh)["full"])
        with open(rev_p, "w") as fh:
            json.dump(review(), fh)
        self.run_tool("ledger.py", "update", "--facts", facts_p, "--findings", rev_p, "--out", led_p)
        self.run_tool("ledger.py", "scope", "--facts", facts_p, "--ledger", led_p, "--out", scope_p)
        with open(scope_p) as fh:
            self.assertEqual(json.load(fh)["review_units"], [])
        res = self.run_tool("incremental.py", "--facts", facts_p, "--ledger", led_p, "--out", patch_p, "--repo", self.dir)
        self.assertIn("reason=ancestor", res.stdout)


if __name__ == "__main__":
    unittest.main()
