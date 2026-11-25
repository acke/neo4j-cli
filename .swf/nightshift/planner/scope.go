// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

package planner

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"strings"
)

// BaselineCarveOut is always off limits, whatever the repo's config says.
// A trailing / means a directory, anything else is one file.
var BaselineCarveOut = []string{
	".github/", ".claude/", ".agents/", ".swf/", ".git/",
	".gitattributes", ".gitmodules", "AGENTS.md", "CLAUDE.md",
}

// Violation is one reason a patch is rejected.
type Violation struct {
	Path   string `json:"path"`
	Reason string `json:"reason"`
}

func (v Violation) String() string {
	if v.Path == "" {
		return v.Reason
	}
	return v.Path + ": " + v.Reason
}

// Scope is the result of checking a patch against a cluster.
type Scope struct {
	Touched    []string
	Violations []Violation
}

// CheckScope decides whether patch may be published for a cluster with the
// given files. It reads only the patch text, never a working tree, so it
// can't be fooled by edits the model made on disk. The paths come from
// `git apply --numstat`, the parser the publish step uses to apply the
// patch, so the two can't disagree about which files are touched.
//
// A patch is rejected if it touches a file outside files, a carve-out path
// (BaselineCarveOut plus carveOut), or if it renames, copies, changes a mode,
// adds a symlink or submodule, or is binary or empty. Carve-out wins over
// the cluster list: a cluster naming a carve-out path is still refused.
func CheckScope(files, carveOut []string, patch []byte) (Scope, error) {
	if len(bytes.TrimSpace(patch)) == 0 {
		return Scope{Violations: []Violation{{Reason: "patch is empty"}}}, nil
	}
	paths, err := touchedPaths(patch)
	if err != nil {
		return Scope{}, err
	}
	in := map[string]bool{}
	for _, f := range files {
		in[f] = true
	}
	carve := append(append([]string{}, BaselineCarveOut...), carveOut...)

	s := Scope{Touched: paths, Violations: scanHeaders(patch)}
	for _, p := range paths {
		switch {
		case inCarveOut(p, carve):
			s.Violations = append(s.Violations, Violation{p, "carve-out path"})
		case !in[p]:
			s.Violations = append(s.Violations, Violation{p, "outside the cluster"})
		}
	}
	return s, nil
}

var (
	modeLine  = regexp.MustCompile(`^(?:old mode|new mode|new file mode|deleted file mode) (\d+)$`)
	indexLine = regexp.MustCompile(`^index [0-9a-fA-F]+\.\.[0-9a-fA-F]+ (\d+)$`)
	moveLine  = regexp.MustCompile(`^(?:(?:rename|copy) (?:from|to) |(?:dis)?similarity index )`)
)

// scanHeaders flags patch features a cluster edit never needs. Hunk lines
// start with ' ', '+' or '-', so a file's content can't pose as a header.
func scanHeaders(patch []byte) []Violation {
	var vs []Violation
	seen := map[string]bool{}
	add := func(reason string) {
		if !seen[reason] {
			seen[reason] = true
			vs = append(vs, Violation{Reason: reason})
		}
	}
	for _, ln := range strings.Split(string(patch), "\n") {
		ln = strings.TrimSuffix(ln, "\r")
		switch {
		case moveLine.MatchString(ln):
			add("rename or copy")
		case strings.HasPrefix(ln, "GIT binary patch"), strings.HasPrefix(ln, "Binary files "):
			add("binary change")
		}
		if m := modeLine.FindStringSubmatch(ln); m != nil && m[1] != "100644" {
			add("mode " + m[1] + " (symlink, executable, submodule or mode change)")
		} else if m := indexLine.FindStringSubmatch(ln); m != nil && m[1] != "100644" {
			add("mode " + m[1] + " (symlink, executable or submodule)")
		}
		if strings.HasPrefix(ln, "old mode ") || strings.HasPrefix(ln, "new mode ") {
			add("mode change")
		}
	}
	return vs
}

// touchedPaths returns every path the patch names, as `git apply` sees them.
// Git runs in an empty directory with no config, so no repository, hook or
// attributes file can change how the patch is read.
func touchedPaths(patch []byte) ([]string, error) {
	dir, err := os.MkdirTemp("", "nightshift-scope-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(dir)

	cmd := exec.Command("git", "--literal-pathspecs", "apply", "--numstat", "-z")
	cmd.Dir = dir
	cmd.Stdin = bytes.NewReader(patch)
	cmd.Env = []string{
		"PATH=" + os.Getenv("PATH"),
		"HOME=" + dir,
		"GIT_CONFIG_GLOBAL=/dev/null",
		"GIT_CONFIG_SYSTEM=/dev/null",
		"GIT_CONFIG_NOSYSTEM=1",
		"GIT_LITERAL_PATHSPECS=1",
		"GIT_CEILING_DIRECTORIES=" + filepath.Dir(dir),
		"LC_ALL=C",
	}
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("git apply could not read the patch: %w: %s", err, strings.TrimSpace(stderr.String()))
	}

	toks := strings.Split(strings.TrimSuffix(stdout.String(), "\x00"), "\x00")
	var paths []string
	for i := 0; i < len(toks); i++ {
		f := strings.SplitN(toks[i], "\t", 3)
		if len(f) != 3 {
			return nil, fmt.Errorf("unexpected git apply output %q", toks[i])
		}
		if f[2] != "" {
			paths = append(paths, f[2])
			continue
		}
		// A rename or copy: the next two records are the old and new path.
		if i+2 >= len(toks) {
			return nil, errors.New("truncated git apply output")
		}
		paths = append(paths, toks[i+1], toks[i+2])
		i += 2
	}
	if len(paths) == 0 {
		return nil, errors.New("git apply found no files in the patch")
	}
	return paths, nil
}

// inCarveOut reports whether p is a carve-out path, ignoring case so a
// case-insensitive checkout can't reach .GitHub/ through .github/.
func inCarveOut(p string, carve []string) bool {
	for _, cand := range []string{p, path.Clean(p)} {
		low := strings.ToLower(cand)
		for _, c := range carve {
			c = strings.ToLower(c)
			if strings.HasSuffix(c, "/") && strings.HasPrefix(low, c) || low == c {
				return true
			}
		}
	}
	return false
}
