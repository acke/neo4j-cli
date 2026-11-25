// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

// Package planner plans the nightly drain of Review Task cards: it turns
// cards into per-package clusters and decides which may run now.
package planner

import (
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"path"
	"sort"
	"strings"
	"time"
)

// Card is one open Review Task card.
type Card struct {
	Identifier  string `json:"identifier"`
	Title       string `json:"title"`
	URL         string `json:"url"`
	Description string `json:"-"`
	Priority    int    `json:"-"` // Linear: 1 urgent .. 4 low, 0 none
}

// MaxFiles is the most files a card may name. A larger card is skipped.
const MaxFiles = 8

// Cluster is one night's unit of work: files of one Go package from one card.
type Cluster struct {
	ID      string   `json:"id"`
	Key     string   `json:"key"`
	Card    string   `json:"card"`
	URL     string   `json:"url"`
	Package string   `json:"package"`
	Files   []string `json:"files"`
	Test    string   `json:"test_command"` // the fast check for this package
	Brief   Brief    `json:"brief"`        // the card's text, for the model that works the cluster
}

// Brief is a card's text. It travels in the queue, as in relate's night-shift.
type Brief struct {
	Title string `json:"title"`
	Body  string `json:"body"`
}

// Skipped is a card the planner cannot work, with the reason.
type Skipped struct {
	Card   string `json:"card"`
	URL    string `json:"url"`
	Reason string `json:"reason"`
}

// Held is a cluster that touches files under human work.
type Held struct {
	ID    string   `json:"id"`
	Files []string `json:"files"`
}

// Queue is the planner's output.
type Queue struct {
	Version         int       `json:"version"`
	GeneratedAt     string    `json:"generated_at"`
	InWindow        bool      `json:"in_window"`
	Runnable        []Cluster `json:"runnable"`
	DeferredOutside []Cluster `json:"deferred_outside_window"`
	HeldBusy        []Held    `json:"held_busy"`
	Skipped         []Skipped `json:"skipped"`
}

// Options tune Plan.
type Options struct {
	Now   time.Time
	Busy  map[string]bool // files under an open human PR
	Force bool            // run outside the window
}

// Plan clusters cards and sorts them into runnable, deferred, held and skipped.
func Plan(cards []Card, o Options) Queue {
	// Most urgent card first; a card without priority goes last.
	sort.SliceStable(cards, func(i, j int) bool {
		a, b := rank(cards[i].Priority), rank(cards[j].Priority)
		if a != b {
			return a < b
		}
		return cards[i].Identifier < cards[j].Identifier
	})

	q := Queue{Version: 1, GeneratedAt: o.Now.In(berlin).Format(time.RFC3339), InWindow: InWindow(o.Now),
		Runnable: []Cluster{}, DeferredOutside: []Cluster{}, HeldBusy: []Held{}, Skipped: []Skipped{}}
	run := q.InWindow || o.Force

	for _, c := range cards {
		files, has := ParseFiles(c.Description)
		switch {
		case !has:
			q.Skipped = append(q.Skipped, Skipped{c.Identifier, c.URL, "no Files: section"})
			continue
		case len(files) == 0:
			q.Skipped = append(q.Skipped, Skipped{c.Identifier, c.URL, "Files: section names no valid path"})
			continue
		case len(files) > MaxFiles:
			q.Skipped = append(q.Skipped, Skipped{c.Identifier, c.URL, fmt.Sprintf("Files: section names %d files, more than %d", len(files), MaxFiles)})
			continue
		}
		for _, cl := range clusters(c, files) {
			if busy := intersect(cl.Files, o.Busy); len(busy) > 0 {
				q.HeldBusy = append(q.HeldBusy, Held{cl.ID, busy})
			} else if run {
				q.Runnable = append(q.Runnable, cl)
			} else {
				q.DeferredOutside = append(q.DeferredOutside, cl)
			}
		}
	}
	return q
}

func rank(p int) int {
	if p == 0 {
		return 5
	}
	return p
}

// clusters groups a card's files by Go package.
func clusters(c Card, files []string) []Cluster {
	byPkg := map[string][]string{}
	for _, f := range files {
		byPkg[path.Dir(f)] = append(byPkg[path.Dir(f)], f) // files is sorted
	}
	pkgs := make([]string, 0, len(byPkg))
	for p := range byPkg {
		pkgs = append(pkgs, p)
	}
	sortStrings(pkgs)

	out := make([]Cluster, 0, len(pkgs))
	for _, p := range pkgs {
		fs := byPkg[p]
		sum := sha1.Sum([]byte(c.Identifier + "|" + p + "|" + strings.Join(fs, "|")))
		out = append(out, Cluster{
			ID:      c.Identifier + "-" + slug(p),
			Key:     hex.EncodeToString(sum[:])[:10],
			Card:    c.Identifier,
			URL:     c.URL,
			Package: p,
			Files:   fs,
			Test:    testCommand(p),
			Brief:   Brief{Title: c.Title, Body: c.Description},
		})
	}
	return out
}

// testCommand is the fast check for one Go package. The ./ prefix keeps a
// directory name that starts with - from being read as a flag.
func testCommand(pkg string) string {
	if pkg == "." {
		return "go test ."
	}
	return "go test ./" + pkg
}

func slug(pkg string) string {
	return strings.NewReplacer("/", "-", ".", "root").Replace(pkg)
}

func intersect(files []string, busy map[string]bool) []string {
	var out []string
	for _, f := range files {
		if busy[f] {
			out = append(out, f)
		}
	}
	return out
}

func sortStrings(s []string) { sort.Strings(s) }
