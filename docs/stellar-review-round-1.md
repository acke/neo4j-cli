# Stellar review: one full round on neo4j-cli

First real run of the standalone `stellar-review` plugin on Go code. Reviewed range: `d3c7be2~1..d3c7be2` (`feat(aura): add --dry-run to instance delete`, 4 files, `internal/commands/aura/instance/delete.go` plus tests, changie entry, regenerated skill bundle).

## Setup

| Item | Value |
| --- | --- |
| Plugin | `oskarhane/oskars.ai` `plugins/stellar-review` v0.1.2, commit `6a61068`, pinned clone outside the repo |
| Install | None. `claude plugin install` / `opencode plugin add` write user config, so the pipeline ran from the clone: `scripts/stellar-prep.sh local`, then the four pass agents. Python ran under `python3 -I` |
| Review checkout | Scratch clone of this repo at `d3c7be2`; `STELLAR_BASE_REF` pointed at `d3c7be2~1` because the commit is already merged (no PR, so round-1 semantics, empty ledger) |
| Passes | `stellar-{structure,branching,boundaries,comparison}`, one agent per brief, run by local opencode, model `fireworks-ai/accounts/fireworks/routers/glm-fast-latest` for all four (the plugin recommends a strong model for `structure`; not tried) |
| Round | Full, not `--quick`. Ledger rolled with `ledger.py update` |
| Repo changes | `.stellar/` in `.gitignore`. No stellar code is vendored here |

Pipeline output: 13 units (4 changed), 2 sites, 0 similar pairs, 4 in scope, 9 sealed, 0 dependency-dirty expansion. 4 briefs, about 17 KB total.

## What the four passes found

| Pass | Findings | Verdict on the round |
| --- | --- | --- |
| structure | 0 | Correct placement; checked precedent in the tree before saying so |
| branching | 2 medium | See below |
| boundaries | 0 | Right answer, one wrong supporting claim |
| comparison | 0 | Checked the two sites; right answer |

Ledger after the round: 2 open findings, both medium, both on `delete.go`.

### Finding 1: dry-run belongs in a shared layer (branching, medium, `delete.go:57`)

Claim: the inline `--dry-run` branch is a one-off; model it once next to the confirm gate so write leaves declare `--dry-run`.

Verdict: noise. The claim that the concept recurs is true (`desktop install` has its own `--dry-run`, as does `tools/releases-json`), but the three have different semantics and nothing else in the aura tree has one. The remedy is a premature abstraction for a single user, against this repo's "delete code, no new abstraction" rule. Over-ambitious by design: the plugin's doctrine pushes for "code judo".

### Finding 2: dry-run still pays the write gate (branching, medium, `delete.go:57`)

Claim: the leaf is annotated `write: "true"`, so `delete --dry-run` without `--rw` is rejected although it only does a GET.

Verdict: real, but a design question, not a defect. Checked on a build of `d3c7be2`: `neo4j-cli aura instance delete <id> --organization-id ... --project-id ... --dry-run --format json` exits 2 with `this command writes; pass --rw to allow it`. The behavior is true and the `Long` text ("needs no --yes --force") does not mention `--rw`. The shipped examples all pass `--rw`, so it reads as intended. Worth a doc line or a decision; not a medium by this repo's bar. Low.

### Passes with no findings

All three clean passes recorded their checks in `notes` and cited sibling code, which is where the review was most useful: they confirmed the synthesized `PrintRecord` map has precedent (`customermanagedkey/delete.go`, `virtualgraph/delete.go`, `project/get.go`), the dry-run guard sits before `confirm.Require` (the only order that gives the documented behavior), the changie body matches the `AssertOutJson` golden, and the bundle was regenerated.

One supporting claim was wrong. `boundaries` said the `, _ := cmd.Flags().GetBool(...)` discard is a repo-wide idiom at "30+ sites". Counted: 5 non-test sites use `cmd.Flags().GetBool` (this one plus 4 inside `internal/confirm/confirm.go`); 60 sites use `BoolVar`. `structure` reasoned "22 of 23 use BoolVar", also not the real ratio. The conclusion (the one aura leaf using inline `GetBool`) stands; the numbers behind it were invented. A reviewer who trusts counts the model quotes will be misled.

### Real vs noise summary

| Item | Real | Noise | Note |
| --- | --- | --- | --- |
| Finding 1 | | x | Premature abstraction |
| Finding 2 | x (low) | | Confirmed by running the build |
| Clean verdicts from structure, comparison | x | | Checked against code |
| Boundaries "30+ sites" | | x | 5 sites |
| Missed: ignored error from `GetBool` at `delete.go:57` | x | | Never surfaced as a site; error is unreachable (flag registered at `delete.go:87`), so no defect, but a boundary-class site the tooling should list |

Net: 2 findings, 0 clear defects, about one half-useful. The round cost four model calls and some minutes; for a 90-line leaf change it found nothing the repo's gates would not. It is not yet a useful gate for Go.

## Go gaps, confirmed or refuted

Counts are at `fork/main` (`dc69525`) except where noted.

| Gap from the card | Verdict | Evidence |
| --- | --- | --- |
| No Go boundary sites | Confirmed | `facts.sites` held 2 entries, both `new_branch`. The diff's `, _ :=` error discard (`delete.go:57`) is not a site. Site kinds are the same set for every language; no ignored errors, `any`, type assertions, `panic`, mutex or goroutines for Go |
| `type X ...` other than struct/interface missed | Confirmed | `units.py` Go pattern is `^type X (struct\|interface)`. 40 such declarations in 885 `.go` files, e.g. `type AuraApiVersion string`, `type PrintableConfigData []PrintableConfigEntry` |
| Methods keyed without receiver | Confirmed | Go `fn` regex drops the receiver, unit id is `path::name`. 44 `AsArray` and 39 `MarshalJSON` methods (card said 42 and 37). Same-name methods on different receivers inside one file are common: 20 files, e.g. `internal/skill/list.go` (3 `AsArray`, 3 `MarshalJSON`), `internal/auraclient/graphql.go` (`List`/`Get`/`Create`/`Delete` x2), `internal/analytics/mocks/mock_analytics.go` (`Do` x7). Unit ids `path::name` collide there. Not hit by this round, so no finding was misattributed |
| No Go import edges | Confirmed | `facts.deps` is `null` for this round; import extraction exists for Python, TypeScript and JavaScript only. Dependency-dirty expansion therefore never fires for Go: 0 expanded units |
| No `_test.go` handling | Confirmed | Tests are plain `go` units in scope with production code (`TestDeleteInstanceDryRun*` reviewed as ordinary units). 455 of 885 Go files are tests. Seen here: `boundaries` deferred the overlap between the two new tests and `TestDeleteInstanceNotInProject` to comparison, which had no similar pair to judge, so test duplication was never assessed |

### Gaps the card did not list

1. **Unit end is wrong when a raw string spans lines.** `TestDeleteInstanceDryRun` really ends at line 292 (`delete_test.go`); stellar recorded `263-276` and `body_truncated: false`. The brace scanner strips strings per line, so the multi-line backtick JSON literal's braces unbalance it and the unit stops at the closing `}` of the JSON. The passes never saw `AssertCalledTimes`, `AssertCalledWithMethod`, `AssertOutJson`, which is where the test asserts anything. Same for `TestDeleteInstanceDryRunNotFound` (`294-307`, the `errors.As` assertions cut off). Raw strings are everywhere in this repo's tests and `Long`/`Example` text. This is the most damaging gap seen: any test-quality or boundary judgment on such a unit is on a partial body.
2. **Round-1 diff warnings.** `ledger.py brief` printed 9 `no diff section for changed file` warnings in a round with no incremental diff. Harmless, but it reads like a failure.
3. **Merged commit needs a faked base.** `stellar-prep.sh local` has no `--base/--head` for a merged range; `STELLAR_BASE_REF` plus a local branch was needed. CI use on a PR is unaffected.
4. **Model-quoted counts are unreliable** (see above). Findings that rest on "N sites" need a script, not the model.

## Verdict

- Pipeline runs unchanged on Go for plain function-level review: units, scope, briefs, ledger and the four passes worked without errors.
- Findings were thin and low value for this change. The clean passes were the most useful part.
- For S3 (upstream Go support), priority order from this round: multi-line raw strings in the unit scanner (gap 1), Go boundary sites (ignored errors, assertions, `any`), receiver-qualified method ids, non-struct `type` units, Go import edges, `_test.go` as its own class.
- Not tried: a stronger model for `structure`, a PR-based round with an existing ledger, the CI workflow template.
