// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

package planner

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"
)

func at(t *testing.T, s string) time.Time {
	t.Helper()
	v, err := time.Parse(time.RFC3339, s)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestInWindow(t *testing.T) {
	for _, tc := range []struct {
		name string
		utc  string
		want bool
	}{
		{"winter open 03:00 CET", "2026-01-15T02:00:00Z", true},
		{"winter before 03:00 CET", "2026-01-15T01:59:00Z", false},
		{"winter last minute 06:59 CET", "2026-01-15T05:59:00Z", true},
		{"winter closed 07:00 CET", "2026-01-15T06:00:00Z", false},
		{"summer open 03:00 CEST", "2026-07-15T01:00:00Z", true},
		{"summer closed 07:00 CEST", "2026-07-15T05:00:00Z", false},
		{"spring forward: 01:59 CET", "2026-03-29T00:59:00Z", false},
		{"spring forward: 03:00 CEST", "2026-03-29T01:00:00Z", true},
		{"fall back: 06:59 CET", "2026-10-25T05:59:00Z", true},
		{"fall back: 07:00 CET", "2026-10-25T06:00:00Z", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := InWindow(at(t, tc.utc)); got != tc.want {
				t.Fatalf("InWindow(%s) = %v, want %v", tc.utc, got, tc.want)
			}
		})
	}
}

func TestParseFiles(t *testing.T) {
	for _, tc := range []struct {
		name    string
		desc    string
		want    []string
		section bool
	}{
		{"bullets and backticks", "Intro.\n\nFiles:\n\n- `internal/a/x.go`\n- internal/a/y.go (the parser)\n\nMore.", []string{"internal/a/x.go", "internal/a/y.go"}, true},
		{"heading and escapes", "## Files\n* internal/a/exec\\_ops.go\n", []string{"internal/a/exec_ops.go"}, true},
		{"bold heading, section ends at next heading", "**Files:**\ninternal/b/z.go\n## Items\ninternal/c/no.go", []string{"internal/b/z.go"}, true},
		{"dedupe and sort", "Files:\n- b/z.go\n- a/y.go\n- b/z.go", []string{"a/y.go", "b/z.go"}, true},
		{"unsafe paths dropped", "Files:\n- ../etc/passwd.x\n- /abs/x.go\n- a/../b.go\n- a/$(id).go\n- https://github.com/x/y.go\n- ok/a.go", []string{"ok/a.go"}, true},
		{"empty section", "Files:\n\nnothing here", nil, true},
		{"no section", "mentions internal/a/x.go in prose", nil, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, has := ParseFiles(tc.desc)
			if has != tc.section || !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("got %v, %v; want %v, %v", got, has, tc.want, tc.section)
			}
		})
	}
}

func card(id string, prio int, files ...string) Card {
	return Card{Identifier: id, URL: "https://linear.app/" + id, Priority: prio,
		Description: "Files:\n- " + strings.Join(files, "\n- ")}
}

func TestPlan(t *testing.T) {
	inWin := at(t, "2026-01-15T03:00:00Z") // 04:00 CET
	outWin := at(t, "2026-01-15T12:00:00Z")

	t.Run("one cluster per package", func(t *testing.T) {
		q := Plan([]Card{card("D-1", 2, "a/x.go", "a/y.go", "b/z.go")}, Options{Now: inWin})
		if len(q.Runnable) != 2 || q.Runnable[0].Package != "a" || q.Runnable[1].Package != "b" {
			t.Fatalf("runnable = %+v", q.Runnable)
		}
	})

	t.Run("card naming more than eight files is skipped", func(t *testing.T) {
		var fs []string
		for i := 1; i <= 9; i++ {
			fs = append(fs, fmt.Sprintf("pkg/f%d.go", i))
		}
		q := Plan([]Card{card("D-2", 1, fs...), card("D-2b", 1, fs[:8]...)}, Options{Now: inWin})
		if len(q.Runnable) != 1 || q.Runnable[0].Card != "D-2b" || len(q.Runnable[0].Files) != 8 ||
			len(q.Skipped) != 1 || !strings.Contains(q.Skipped[0].Reason, "9 files, more than 8") {
			t.Fatalf("queue = %+v", q)
		}
	})

	t.Run("held cluster touches busy file", func(t *testing.T) {
		q := Plan([]Card{card("D-3", 1, "a/x.go", "b/y.go")},
			Options{Now: inWin, Busy: map[string]bool{"b/y.go": true}})
		if len(q.Runnable) != 1 || q.Runnable[0].Package != "a" ||
			len(q.HeldBusy) != 1 || !reflect.DeepEqual(q.HeldBusy[0].Files, []string{"b/y.go"}) {
			t.Fatalf("queue = %+v", q)
		}
	})

	t.Run("card without Files is skipped with a reason", func(t *testing.T) {
		q := Plan([]Card{{Identifier: "D-4", Description: "just prose"}, {Identifier: "D-5", Description: "Files:\n- nope"}},
			Options{Now: inWin})
		if len(q.Runnable) != 0 || len(q.Skipped) != 2 ||
			q.Skipped[0].Reason != "no Files: section" || !strings.Contains(q.Skipped[1].Reason, "no valid path") {
			t.Fatalf("skipped = %+v", q.Skipped)
		}
	})

	t.Run("outside the window defers, force runs", func(t *testing.T) {
		cards := []Card{card("D-6", 1, "a/x.go")}
		q := Plan(cards, Options{Now: outWin})
		if q.InWindow || len(q.Runnable) != 0 || len(q.DeferredOutside) != 1 {
			t.Fatalf("queue = %+v", q)
		}
		if q = Plan(cards, Options{Now: outWin, Force: true}); len(q.Runnable) != 1 {
			t.Fatalf("forced queue = %+v", q)
		}
	})

	t.Run("urgent first, no priority last", func(t *testing.T) {
		q := Plan([]Card{card("D-9", 0, "a/x.go"), card("D-8", 3, "b/x.go"), card("D-7", 1, "c/x.go")}, Options{Now: inWin})
		var got []string
		for _, c := range q.Runnable {
			got = append(got, c.Card)
		}
		if !reflect.DeepEqual(got, []string{"D-7", "D-8", "D-9"}) {
			t.Fatalf("order = %v", got)
		}
	})
}

func TestLinearPaginates(t *testing.T) {
	page := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "k" {
			t.Errorf("Authorization = %q", r.Header.Get("Authorization"))
		}
		var body struct{ Variables map[string]any }
		_ = json.NewDecoder(r.Body).Decode(&body)
		page++
		more, id := page == 1, fmt.Sprintf("D-%d", page)
		if more && body.Variables["after"] != nil || !more && body.Variables["after"] != "c1" {
			t.Errorf("page %d after = %v", page, body.Variables["after"])
		}
		fmt.Fprintf(w, `{"data":{"issues":{"nodes":[{"identifier":%q,"title":"t","url":"u","description":null,"priority":2}],"pageInfo":{"hasNextPage":%v,"endCursor":"c1"}}}}`, id, more)
	}))
	defer srv.Close()

	cards, err := Linear{Key: "k", Label: "Review Task", Project: "p", Endpoint: srv.URL}.ReviewTasks(context.Background())
	if err != nil || len(cards) != 2 || cards[1].Identifier != "D-2" {
		t.Fatalf("cards = %+v, err = %v", cards, err)
	}
}

func TestLinearError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, `{"errors":[{"message":"bad key"}]}`)
	}))
	defer srv.Close()
	if _, err := (Linear{Endpoint: srv.URL}).ReviewTasks(context.Background()); err == nil || !strings.Contains(err.Error(), "bad key") {
		t.Fatalf("err = %v", err)
	}
}

func TestTestCommand(t *testing.T) {
	q := Plan([]Card{card("D-1", 1, "a/b/x.go", "root.go", "-odd/y.go")}, Options{Now: at(t, "2026-01-15T03:00:00Z")})
	got := map[string]string{}
	for _, c := range q.Runnable {
		got[c.Package] = c.Test
	}
	want := map[string]string{"a/b": "go test ./a/b", ".": "go test .", "-odd": "go test ./-odd"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("test commands = %v, want %v", got, want)
	}
}

func TestClusterCarriesTheCardText(t *testing.T) {
	cards := []Card{
		{Identifier: "D-1", Title: "fix a", Description: "Files:\n- a/x.go\nthe body", Priority: 1},
		{Identifier: "D-2", Title: "skipped", Description: "no files here"},
	}
	q := Plan(cards, Options{Now: at(t, "2026-01-15T03:00:00Z")})
	if len(q.Runnable) != 1 || q.Runnable[0].Brief.Title != "fix a" || !strings.Contains(q.Runnable[0].Brief.Body, "the body") {
		t.Fatalf("runnable = %+v", q.Runnable)
	}
	text, _ := json.Marshal(q.Skipped)
	if strings.Contains(string(text), "skipped") && strings.Contains(string(text), "no files here") {
		t.Fatalf("a skipped card's text is in the queue: %s", text)
	}
}
