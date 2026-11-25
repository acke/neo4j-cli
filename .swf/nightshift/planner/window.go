// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

package planner

import (
	"time"
	_ "time/tzdata" // the runner needs no system zoneinfo
)

var berlin = mustLoad("Europe/Berlin")

func mustLoad(name string) *time.Location {
	loc, err := time.LoadLocation(name)
	if err != nil {
		panic(err)
	}
	return loc
}

// InWindow reports whether now is inside 03:00 to 07:00 Europe/Berlin.
func InWindow(now time.Time) bool {
	h := now.In(berlin).Hour()
	return h >= 3 && h < 7
}
