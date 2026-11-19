"""Tests for units.py: Go func and type extraction."""

import unittest

import helpers  # noqa: F401  (puts tools/ on sys.path)
import units

SRC = """package p

type Config struct {
	Name string
}

type ID int

type Runner interface {
	Run() error
}

type (
	Grouped int
)

func Top(a int) int { return a }

func (c *Config) Run() error {
	if c.Name == "}" { // brace in a string and comment }
		return nil
	}
	return nil
}

func (r Runner2) Run() error { return nil }

func Multi(
	a int,
	b string,
) error {
	return nil
}
"""


class TestExtractUnits(unittest.TestCase):
    def setUp(self):
        self.units = {u["name"]: u for u in units.extract_units("p/p.go", SRC)}

    def test_func_and_type_units_only(self):
        self.assertEqual(
            sorted(self.units),
            ["Config", "Config.Run", "ID", "Multi", "Runner", "Runner2.Run", "Top"])

    def test_methods_are_qualified_by_receiver(self):
        self.assertIn("p/p.go::Config.Run", {u["id"] for u in self.units.values()})
        self.assertIn("Runner2.Run", self.units)

    def test_unit_ends(self):
        self.assertEqual((self.units["ID"]["start"], self.units["ID"]["end"]), (7, 7))
        self.assertEqual(self.units["Top"]["end"], self.units["Top"]["start"])
        run = self.units["Config.Run"]
        self.assertEqual(run["end"] - run["start"], 5)
        multi = self.units["Multi"]
        self.assertEqual(multi["end"] - multi["start"], 5)

    def test_signature_stops_at_body(self):
        self.assertEqual(self.units["Multi"]["signature"], "func Multi( a int, b string, ) error")

    def test_hash_ignores_whitespace_not_content(self):
        a = units.extract_units("a.go", "package a\nfunc F() int {\n\treturn 1\n}\n")[0]
        b = units.extract_units("a.go", "package a\nfunc F() int {\n\treturn 1   \n\n}\n")[0]
        c = units.extract_units("a.go", "package a\nfunc F() int {\n\treturn 2\n}\n")[0]
        self.assertEqual(a["hash"], b["hash"])
        self.assertNotEqual(a["hash"], c["hash"])

    def test_duplicate_names_get_a_stable_suffix(self):
        got = units.extract_units("a.go", "package a\nfunc F() {}\nfunc F() {}\n")
        self.assertEqual([u["name"] for u in got], ["F", "F#2"])

    def test_non_go_files_have_no_units(self):
        self.assertEqual(units.extract_units("a.py", "def f():\n    pass\n"), [])


if __name__ == "__main__":
    unittest.main()
