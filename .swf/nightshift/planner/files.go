// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

package planner

import (
	"path"
	"regexp"
	"strings"
)

var (
	filesHead = regexp.MustCompile(`(?i)^\s*(?:#+\s*|\*\*)?files\*{0,2}\s*:?\*{0,2}\s*:?\s*$`)
	// Linear escapes markdown punctuation, e.g. exec\_ops.go.
	unescape  = regexp.MustCompile("\\\\([_*`\\[\\]()#.\\-])")
	pathShape = regexp.MustCompile(`^[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*$`)
)

// SafePath reports whether p may reach a shell command or an edit scope:
// relative, no "." or ".." segment, a plain character set, and a file name
// with an extension.
func SafePath(p string) bool {
	if !pathShape.MatchString(p) || !strings.Contains(path.Base(p), ".") {
		return false
	}
	for _, seg := range strings.Split(p, "/") {
		if seg == "." || seg == ".." {
			return false
		}
	}
	return true
}

// ParseFiles returns the safe, sorted, deduplicated paths named in the
// card's "Files:" section, and whether the section exists. The section is a
// heading line followed by lines up to a blank line or the next heading.
func ParseFiles(description string) (files []string, hasSection bool) {
	var body []string
	in := false
	for _, ln := range strings.Split(description, "\n") {
		if !in {
			in = filesHead.MatchString(ln)
			hasSection = hasSection || in
			continue
		}
		if strings.TrimSpace(ln) == "" || strings.HasPrefix(strings.TrimSpace(ln), "#") {
			if len(body) > 0 {
				break
			}
			continue
		}
		body = append(body, ln)
	}
	seen := map[string]bool{}
	for _, tok := range strings.Fields(unescape.ReplaceAllString(strings.Join(body, "\n"), "$1")) {
		tok = strings.Trim(tok, "`'\"()[]<>,;:!?")
		tok = strings.TrimSuffix(tok, ".")
		if strings.Contains(tok, "://") || !SafePath(tok) || seen[tok] {
			continue
		}
		seen[tok] = true
		files = append(files, tok)
	}
	sortStrings(files)
	return files, hasSection
}
