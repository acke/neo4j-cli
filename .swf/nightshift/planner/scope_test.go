// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

package planner

import (
	"os/exec"
	"strings"
	"testing"
)

func edit(p string) string {
	return "diff --git a/" + p + " b/" + p + "\n" +
		"index 1111111..2222222 100644\n" +
		"--- a/" + p + "\n" +
		"+++ b/" + p + "\n" +
		"@@ -1 +1 @@\n-old\n+new\n"
}

func rename(from, to string) string {
	return "diff --git a/" + from + " b/" + to + "\n" +
		"similarity index 100%\n" +
		"rename from " + from + "\n" +
		"rename to " + to + "\n"
}

func symlink(p string) string {
	return "diff --git a/" + p + " b/" + p + "\n" +
		"new file mode 120000\n" +
		"index 0000000..2222222\n" +
		"--- /dev/null\n" +
		"+++ b/" + p + "\n" +
		"@@ -0,0 +1 @@\n+target.go\n\\ No newline at end of file\n"
}

func modeChange(p string) string {
	return "diff --git a/" + p + " b/" + p + "\n" +
		"old mode 100644\n" +
		"new mode 100755\n"
}

func TestCheckScope(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Fatal("git is required: check-scope reads patches with git apply")
	}
	files := []string{"pkg/a.go", "pkg/b.go", ".github/workflows/x.yml", "go.mod"}
	carve := []string{"go.mod", "internal/auth/"}

	for _, tc := range []struct {
		name  string
		patch string
		want  string // substring of the expected violation; "" means the patch passes
	}{
		{"in-scope edit", edit("pkg/a.go"), ""},
		{"two in-scope files", edit("pkg/a.go") + edit("pkg/b.go"), ""},
		{"file outside the cluster", edit("pkg/a.go") + edit("pkg/other.go"), "pkg/other.go: outside the cluster"},
		{"glob is not a pattern", edit("pkg/*.go"), "outside the cluster"},
		{"dot-dot path", edit("pkg/../other.go"), "outside the cluster"},
		{"carve-out beats the cluster list: .github", edit(".github/workflows/x.yml"), "carve-out path"},
		{"carve-out beats the cluster list: go.mod", edit("go.mod"), "carve-out path"},
		{"baseline .claude", edit(".claude/settings.json"), "carve-out path"},
		{"baseline .agents", edit(".agents/skills/s/SKILL.md"), "carve-out path"},
		{"baseline .swf", edit(".swf/swf.yml"), "carve-out path"},
		{"baseline AGENTS.md", edit("AGENTS.md"), "carve-out path"},
		{"baseline CLAUDE.md", edit("CLAUDE.md"), "carve-out path"},
		{"baseline .gitattributes", edit(".gitattributes"), "carve-out path"},
		{"baseline .gitmodules", edit(".gitmodules"), "carve-out path"},
		{"configured directory", edit("internal/auth/token.go"), "carve-out path"},
		{"carve-out ignores case", edit(".GitHub/workflows/y.yml"), "carve-out path"},
		{"rename", rename("pkg/a.go", "pkg/b.go"), "rename or copy"},
		{"rename into a carve-out", rename("pkg/a.go", "AGENTS.md"), "carve-out path"},
		{"new symlink", symlink("pkg/a.go"), "mode 120000"},
		{"mode change", modeChange("pkg/a.go"), "mode change"},
		{"empty patch", "  \n", "patch is empty"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s, err := CheckScope(files, carve, []byte(tc.patch))
			if err != nil {
				t.Fatalf("CheckScope error: %v", err)
			}
			var got []string
			for _, v := range s.Violations {
				got = append(got, v.String())
			}
			joined := strings.Join(got, "; ")
			switch {
			case tc.want == "" && len(got) > 0:
				t.Fatalf("expected the patch to pass, got: %s", joined)
			case tc.want != "" && !strings.Contains(joined, tc.want):
				t.Fatalf("violations %q do not contain %q", joined, tc.want)
			}
		})
	}
}

func TestCheckScopeRefusesAnUnreadablePatch(t *testing.T) {
	if _, err := CheckScope([]string{"a.go"}, nil, []byte("not a patch\n")); err == nil {
		t.Fatal("expected an error for text that is not a patch")
	}
}

func TestScanHeaders(t *testing.T) {
	for _, tc := range []struct{ name, patch, want string }{
		{"binary patch", "diff --git a/x b/x\nindex 1..2 100644\nGIT binary patch\nliteral 0\n", "binary change"},
		{"binary files line", "diff --git a/x b/x\nBinary files a/x and b/x differ\n", "binary change"},
		{"submodule", "diff --git a/x b/x\nnew file mode 160000\n", "mode 160000"},
		{"index with symlink mode", "diff --git a/x b/x\nindex 1..2 120000\n", "mode 120000"},
		{"copy", "diff --git a/x b/y\ncopy from x\ncopy to y\n", "rename or copy"},
		{"plain edit", edit("pkg/a.go"), ""},
		{"content that looks like a header", "diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-new file mode 120000\n+rename from y\n", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			vs := scanHeaders([]byte(tc.patch))
			if tc.want == "" && len(vs) > 0 {
				t.Fatalf("unexpected violations: %v", vs)
			}
			if tc.want != "" && !(len(vs) > 0 && strings.Contains(vs[0].Reason, tc.want)) {
				t.Fatalf("violations %v do not contain %q", vs, tc.want)
			}
		})
	}
}
