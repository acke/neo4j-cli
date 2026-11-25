// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

// Command nightshift plans the nightly drain of Review Task cards and checks
// the model's patch before it is published.
//
//	nightshift window [--now RFC3339]
//	nightshift plan [--now RFC3339] [--force] [--busy-files FILE] [--out FILE]
//	nightshift check-scope --files-from FILE --patch FILE|- [--carve-out PATH]... [--carve-out-file FILE]
//
// plan reads LINEAR_API_KEY from the environment and prints the queue as JSON.
// window exits 0 inside 03:00 to 07:00 Europe/Berlin, 1 outside.
// check-scope exits 0 when the patch stays inside the cluster, 1 when it does
// not, and 2 when the patch can't be read. Exit 2 is a failure too.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"swf/nightshift/planner"
)

func main() {
	if len(os.Args) < 2 {
		die("usage: nightshift window|plan|check-scope [flags]")
	}
	args := os.Args[2:]
	switch os.Args[1] {
	case "window":
		runWindow(args)
	case "plan":
		runPlan(args)
	case "check-scope":
		runCheckScope(args)
	default:
		die("unknown command " + os.Args[1])
	}
}

func runWindow(args []string) {
	fs := flag.NewFlagSet("window", flag.ExitOnError)
	now := fs.String("now", "", "RFC3339 time, default now")
	_ = fs.Parse(args)
	if !planner.InWindow(parseNow(*now)) {
		os.Exit(1)
	}
}

func runPlan(args []string) {
	fs := flag.NewFlagSet("plan", flag.ExitOnError)
	now := fs.String("now", "", "RFC3339 time, default now")
	force := fs.Bool("force", false, "plan runnable work outside the window")
	busyFile := fs.String("busy-files", "", "file of paths under human work, one per line")
	out := fs.String("out", "", "write the queue here instead of stdout")
	label := fs.String("label", "Review Task", "Linear label")
	project := fs.String("project", "neo4j-cli software factory (swf)", "Linear project")
	_ = fs.Parse(args)

	key := os.Getenv("LINEAR_API_KEY")
	if key == "" {
		die("LINEAR_API_KEY is not set")
	}
	busy, err := readLines(*busyFile)
	if err != nil {
		die(err.Error())
	}
	cards, err := planner.Linear{Key: key, Label: *label, Project: *project}.ReviewTasks(context.Background())
	if err != nil {
		die(err.Error())
	}
	q := planner.Plan(cards, planner.Options{Now: parseNow(*now), Busy: busy, Force: *force})
	text, _ := json.MarshalIndent(q, "", " ")
	text = append(text, '\n')
	if *out == "" {
		os.Stdout.Write(text)
	} else if err := os.WriteFile(*out, text, 0o644); err != nil {
		die(err.Error())
	}
	fmt.Fprintf(os.Stderr, "nightshift: %d runnable, %d deferred, %d held, %d skipped, in_window=%v\n",
		len(q.Runnable), len(q.DeferredOutside), len(q.HeldBusy), len(q.Skipped), q.InWindow)
}

type multiFlag []string

func (m *multiFlag) String() string     { return strings.Join(*m, ",") }
func (m *multiFlag) Set(v string) error { *m = append(*m, v); return nil }

func runCheckScope(args []string) {
	fs := flag.NewFlagSet("check-scope", flag.ExitOnError)
	filesFrom := fs.String("files-from", "", "file of the cluster's paths, one per line")
	patchFile := fs.String("patch", "", "the patch to check, or - for stdin")
	carveFile := fs.String("carve-out-file", "", "file of carve-out paths, one per line (a trailing / means a directory)")
	var carve multiFlag
	fs.Var(&carve, "carve-out", "carve-out path; repeatable (a trailing / means a directory)")
	_ = fs.Parse(args)
	if *filesFrom == "" || *patchFile == "" {
		die("check-scope needs --files-from and --patch")
	}

	files, err := readLines(*filesFrom)
	if err != nil {
		die(err.Error())
	}
	extra, err := readLines(*carveFile)
	if err != nil {
		die(err.Error())
	}
	for p := range extra {
		carve = append(carve, p)
	}
	var patch []byte
	if *patchFile == "-" {
		patch, err = io.ReadAll(os.Stdin)
	} else {
		patch, err = os.ReadFile(*patchFile)
	}
	if err != nil {
		die(err.Error())
	}

	var list []string
	for f := range files {
		list = append(list, f)
	}
	s, err := planner.CheckScope(list, carve, patch)
	if err != nil {
		die(err.Error())
	}
	for _, v := range s.Violations {
		fmt.Fprintln(os.Stderr, "nightshift: rejected: "+v.String())
	}
	if len(s.Violations) > 0 {
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "nightshift: patch stays inside the cluster, %d file(s)\n", len(s.Touched))
}

func parseNow(raw string) time.Time {
	if raw == "" {
		return time.Now()
	}
	t, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		die("--now: " + err.Error())
	}
	return t
}

func readLines(path string) (map[string]bool, error) {
	set := map[string]bool{}
	if path == "" {
		return set, nil
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if s := strings.TrimSpace(sc.Text()); s != "" {
			set[s] = true
		}
	}
	return set, sc.Err()
}

func die(msg string) {
	fmt.Fprintln(os.Stderr, "nightshift: "+msg)
	os.Exit(2)
}
