"""Shared fixture for the stellar-review tool tests: a throwaway git repo
with write/commit helpers. Offline by construction. Importing this module
puts tools/ on sys.path."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import facts  # noqa: E402


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        facts.git(self.dir, "init", "-q", "-b", "main")
        facts.git(self.dir, "config", "user.email", "t@t.t")
        facts.git(self.dir, "config", "user.name", "t")
        facts.git(self.dir, "config", "commit.gpgsign", "false")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, path, content):
        full = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)

    def git(self, *args):
        return facts.git(self.dir, *args).strip()

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def facts_now(self, base):
        return facts.build_facts(self.dir, base, self.git("rev-parse", "HEAD"))
