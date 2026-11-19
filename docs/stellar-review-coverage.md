# Stellar coverage of the two review bots

Evidence for retiring `claude-review-conventions.yml` and `claude-review-security.yml` in favour of stellar. Every check the bots make is mapped to a stellar home or marked as a gap with a proposed rule or an explicit drop.

Sources, all read at the commit that wrote this file:

- Bots: `.github/prompts/claude-review-{conventions,security}.md`, the two workflows, `.github/scripts/enforce-claude-verdict.sh`.
- Stellar: `relate` repo, `.agents/skills/stellar-review/` (SKILL, `passes/`, `references/`, `tools/`), `.agents/skills/security-review/SKILL.md`, `.github/workflows/opencode-review-{stellar,security}.yml`, `.github/prompts/opencode-review-*.md`.
- Existing neo4j-cli gates: `Makefile`, `.github/workflows/{test,license}.yml`, `AGENTS.md`.

## The stellar lanes

| Lane | What it judges |
| --- | --- |
| `stellar` | Code quality only, four passes over pre-digested briefs: `structure` (file size, layer placement), `branching` (special cases, code-judo), `boundaries` (wrappers, casts, helper reuse, sequencing), `comparison` (similar units, inconsistent handling). Severity `blocker`/`medium`/`nit`. |
| `security` | `security-review` skill: scope, threat model, input/output validation, authN/authZ, secrets/PII, dependency risk, error leakage. Severity `Critical`/`High`/`Medium`/`Low` by exploitability. Generic, not Go-specific. |
| CI gate | Not a review lane. A `make` target or test that already fails the build. |

Stellar has no lane that judges a diff against a repo rulebook such as `AGENTS.md`. Its doctrine (`references/full-checklist.md`) carries a recurring-pattern checklist fed by the host repo's rules; neo4j-cli has no such block yet.

Status values: **covered** (a lane does it), **CI** (a gate already fails the build, so the review check is redundant and dropped), **gap** (no home; rule proposed below).

## Conventions bot

| # | Check | Stellar home | Status |
| --- | --- | --- | --- |
| C1 | Cobra layout: leaf in its own `<action>.go`, colocated `<action>_test.go`, parent `<resource>.go` at most 80 lines with no inline leaf bodies | `stellar` `structure` flags misplaced logic and busy files, but knows neither the 80-line limit nor the leaf/test pairing | gap, rule R1 |
| C2 | Neo4j license header on new `.go` files | `make license-check` in `license.yml` | CI, drop |
| C3 | Changelog entry (`.changes/unreleased/neo4j-cli-<Kind>-*.yaml`) for user-facing changes; none for internal-only | `changie.yml` only batches on push to `main`; nothing fails a PR | gap, rule R2 |
| C4 | Skill bundle regenerated when the command tree, `Short`/`Long`/`Example` or flag usage changes | `make generate-check` in `test.yml` plus `TestGenerator_RoundTrip` | CI, drop |
| C5 | Flush-left `Example:` on every runnable leaf | `TestAllLeafCommands_HaveExamples` in `make test` | CI, drop |
| C6 | gofmt and golangci-lint hygiene | `make fmt-check`, golangci-lint step in `test.yml` | CI, drop |
| C7 | Command naming: singular nouns, `<resource> <action>`, at most one positional | `TestInputIdentifiers_AreKebabCase` covers kebab-case only; singular nouns and the positional limit are untested | gap, rule R3 |
| C8 | Flag conventions: `--format json\|table\|toon` on reads, `--wait` on async operations | none | gap, rule R4 |
| C9 | Test layout: colocated, named per command, shared helpers in `helpers_test.go`, table-driven for new suites | none; `comparison` would not see it | gap, rule R5 |
| C10 | Out-of-scope list: no security findings, no style preferences outside `AGENTS.md`, no refactoring suggestions, no coverage opinions | `stellar` is built to give refactoring suggestions (code-judo is its highest-value pass); security goes to the `security` lane | decision: drop the "no refactoring" limit (see Decisions) |
| C11 | Cite a named `AGENTS.md` rule or stay silent; when unsure, do not post | `stellar` requires `quote`, `why` and `remedy` per finding and drops findings outside scope; rule-citation applies to R1 to R5 only | covered, with R1 to R5 citing their `AGENTS.md` section |
| C12 | No-op pass when the diff has no convention-relevant changes (docs, `.github/`) | `facts.has_code_changes` false posts a scripted no-op | covered |
| C13 | Severity `Critical`/`High`/`Medium`/`Low`; `Critical`/`High` reserved for CI-failing rules | `blocker`/`medium`/`nit`; mapping in Decisions | covered, mapping |
| C14 | Treat diff text as untrusted data | `opencode-review-protocol.md` carries the same instruction | covered |

## Security bot

| # | Check | Stellar home | Status |
| --- | --- | --- | --- |
| S1 | Go vulnerability classes through the pinned `golang-security` skill (`samber/cc-skills-golang` v1.4.0), review mode, data-flow tracing of changed files | `security` lane, generic checklist: input validation, path and URL constraints, authN/authZ, secrets and PII, dependency risk, error leakage; red flags include raw command execution and hardcoded secrets | partial; Go-specific classes are not enumerated: gap, rule R6 |
| S2 | Review mode only, never audit mode (cost) | stellar rounds are incremental by design: ledger seals untouched units, scope is the delta | covered |
| S3 | `govulncheck` scan of dependencies | `Govulncheck` step in `test.yml` (ubuntu) | CI, drop |
| S4 | New or changed dependencies justified | `security-review` "Dependency Risk" step | covered |
| S5 | Severity comes from the skill and is preserved, `Critical` to `Low` | `security` lane uses the same four levels by exploitability | covered |
| S6 | Inline comments only for security issues, not style or tests | `security` prompt carries the same scope limit | covered |
| S7 | No-op pass when no `.go`/`go.mod`/`go.sum` change | `security` lane no-ops on docs-only diffs, and never on `.github/workflows/`, `.github/scripts/`, `.github/prompts/` or `.agents/skills/` (stricter than the bot) | covered, superset |
| S8 | Skill unavailable: verdict `fail`, loud summary, no hand-rolled fallback | protocol parameter `<NO_FALLBACK>` = hand-rolled security checks | covered |

## Workflow mechanics shared by both bots

| # | Check | Stellar home | Status |
| --- | --- | --- | --- |
| M1 | Skip drafts; run only for MEMBER/OWNER/COLLABORATOR authors | stellar and security run on drafts (draft fast gate) with a same-repo guard only | changed behaviour, see Decisions |
| M2 | One sticky summary comment per review kind, edited in place | `post.py` rolls one summary per kind and one ledger | covered; marker strings differ |
| M3 | Verdict as `<!-- claude-verdict: pass\|fail -->` | `<!-- opencode-verdict: pass\|fail -->`, derived by script | covered; marker name differs |
| M4 | Verdict bound to the head SHA (`<!-- claude-head-sha -->`); a stale verdict does not count | the head SHA lives only inside the compressed `stellar-ledger` block (`last_head`); no plain marker | gap, rule R7 |
| M5 | Fail-closed verdict gate (`enforce-claude-verdict.sh`) | `enforce-opencode-verdict.sh`, same four tiers | covered |
| M6 | Retry the model run when no verdict landed | not needed: the model writes only `findings.json`, scripts post and derive the verdict, so "model skipped the verdict write" cannot occur | drop |
| M7 | Workflow-edit escape hatch (`github_token`, `VERDICT_BOT_LOGIN`) | claude-code-action specific; stellar runs through OpenCode and does not mint the App token | drop with the bots |
| M8 | Review model `sonnet`, narrow allowed-tools list | per-pass `STELLAR_MODEL_*` secrets; tool list lives in the OpenCode agent config | covered, different config |

## Proposed rules for gaps

Each rule goes into the neo4j-cli copy of the stellar checklist (`references/full-checklist.md`, recurring-pattern block). Findings from these rules are `medium`, cite the `AGENTS.md` section and carry its remedy. Where a rule is mechanical, a script fact in `facts.py`/`briefs.py` is cheaper and steadier than a model judgement; the implementing card decides per rule.

| Rule | Text | Source section |
| --- | --- | --- |
| R1 | A new leaf constructor `newXxxCmd` lives in `<action>.go` with a colocated `<action>_test.go`. A parent `<resource>.go` over 80 lines, or one holding a leaf body, is a finding. Exceptions: `admin privilege` category leaves and `desktop project`/`desktop tag` catalog leaves. | Cobra Command Layout |
| R2 | A diff that changes observable output, flags, commands or errors without a `.changes/unreleased/neo4j-cli-<Kind>-*.yaml` entry is a finding. Internal-only diffs (refactors, CI, docs, transport migrations) need none. An entry whose body describes mechanics instead of user-visible impact is a finding. Mechanical: changed-file list against the unreleased directory, then one model judgement on "user-facing". | Build System, Changie |
| R3 | Command names are singular nouns in `<resource> <action>` form, with at most one positional argument; extra inputs become flags. | Architecture, CLI conventions |
| R4 | A read leaf exposes `--format json\|jsonl\|table\|toon`; an async operation exposes `--wait`. | Architecture, CLI conventions |
| R5 | Tests are colocated and named per command, not one monolith; shared helpers in `helpers_test.go`; new suites are table-driven. A concern-named file aggregating one cross-command concern is allowed. | Testing Framework |
| R6 | Add a Go addendum to `security-review`. First step of the implementing card: copy the vulnerability-class list from the pinned `golang-security` review mode (`samber/cc-skills-golang`, sha `e9761db859c6969b77a8fd0e8a243f4f28240211`) verbatim, so no class is lost. Add the repo-specific classes `AGENTS.md` names: secrets in argv instead of env, a minted secret not passed to `clievents.RegisterSecretValue`, free text through `RedactText` with a secret word before a colon, credential env vars read outside `GatedGetenv`, `log.Fatal` in command code. This card could not read the pinned plugin's text (not vendored in this repo or on this machine), so the class list is not reproduced here. | Secrets / Redaction, Credential env-var gate |
| R7 | The stellar summary comment carries `<!-- stellar-head-sha: <sha> -->` next to the verdict marker, written by `post.py`, so the autopilot's current-head check keeps working without decoding the ledger. | Autopilot skill, Step 6 |

## Decisions

- **Dropped, enforced by CI:** C2 (license), C4 (bundle regen), C5 (`Example:`), C6 (gofmt/lint), S3 (`govulncheck`). The bot only repeated a failing gate. Retiring the bot loses nothing.
- **Dropped, bot-specific machinery:** M6 (verdict retry) and M7 (escape hatch), as above.
- **Dropped limit:** C10 "no refactoring suggestions". Stellar's code-judo and decomposition findings are the intended replacement for it. Expect stellar to block PRs the conventions bot passed.
- **Severity mapping:** `Critical`/`High` map to `blocker`, `Medium` to `medium`, `Low` to `nit`. The autopilot wording "fix Critical, High and Medium, defer Low and nits" becomes "fix blocker and medium, defer nit", and `AGENTS.md` review-loop text follows.
- **Drafts (M1):** the bots skip drafts, so today's autopilot draft phase covers CI only. Stellar reviews drafts, which moves the first review round before the ready flip. The autopilot skill needs the phase boundaries revisited when the bots go.
- **Not covered here:** the `security` lane's rules, `golang-security` scope and the gap implementations belong to later cards in the chain. S7 (delete the bots) should wait on R1 to R7 landing or on an explicit drop of the rule it skips.
