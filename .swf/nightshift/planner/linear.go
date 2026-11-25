// Copyright (c) "Neo4j"
// Neo4j Sweden AB [http://neo4j.com]

package planner

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// Source lists the open Review Task cards. Tests fake it; Linear implements it.
type Source interface {
	ReviewTasks(ctx context.Context) ([]Card, error)
}

// Linear reads cards over the GraphQL API.
type Linear struct {
	Key      string // personal API key, sent as is
	Label    string // "Review Task"
	Project  string // "neo4j-cli software factory (swf)"
	Endpoint string // default https://api.linear.app/graphql
	Client   *http.Client
}

const pullQuery = `query($label:String!,$project:String!,$after:String){
  issues(first:100, after:$after, filter:{
    labels:{name:{eq:$label}},
    project:{name:{eq:$project}},
    state:{type:{nin:["completed","canceled"]}}}){
    nodes{identifier title url description priority}
    pageInfo{hasNextPage endCursor}
  }}`

// ReviewTasks returns every open card carrying the label in the project.
func (l Linear) ReviewTasks(ctx context.Context) ([]Card, error) {
	var cards []Card
	var after *string
	for {
		var out struct {
			Issues struct {
				Nodes []struct {
					Identifier  string
					Title, URL  string
					Description *string
					Priority    int
				}
				PageInfo struct {
					HasNextPage bool
					EndCursor   string
				}
			}
		}
		vars := map[string]any{"label": l.Label, "project": l.Project, "after": after}
		if err := l.call(ctx, vars, &out); err != nil {
			return nil, err
		}
		for _, n := range out.Issues.Nodes {
			c := Card{Identifier: n.Identifier, Title: n.Title, URL: n.URL, Priority: n.Priority}
			if n.Description != nil {
				c.Description = *n.Description
			}
			cards = append(cards, c)
		}
		if !out.Issues.PageInfo.HasNextPage {
			return cards, nil
		}
		after = &out.Issues.PageInfo.EndCursor
	}
}

func (l Linear) call(ctx context.Context, vars map[string]any, into any) error {
	ep := l.Endpoint
	if ep == "" {
		ep = "https://api.linear.app/graphql"
	}
	cl := l.Client
	if cl == nil {
		cl = &http.Client{Timeout: 30 * time.Second}
	}
	body, _ := json.Marshal(map[string]any{"query": pullQuery, "variables": vars})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, ep, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", l.Key)
	resp, err := cl.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var env struct {
		Data   json.RawMessage
		Errors []struct{ Message string }
	}
	if err := json.NewDecoder(resp.Body).Decode(&env); err != nil {
		return fmt.Errorf("linear: status %d: %w", resp.StatusCode, err)
	}
	if len(env.Errors) > 0 {
		return fmt.Errorf("linear: %s", env.Errors[0].Message)
	}
	return json.Unmarshal(env.Data, into)
}
