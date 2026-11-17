# Card comparisons, Nov 17, 2026

Parent and changed builds of each merged card, run under `swf-bench-protocol/2` with `run.py --bin PATH --arm LABEL`. The changed build is the merge commit, and the parent is its first parent (`<sha>^1`, or `<sha>^` for the squash commit of 1615). 3 runs per task and arm, so this is a smoke comparison, not statistics.

A build wins only on a material drop in tool-output bytes with success held. Any other result is a non-win.

Cells are `successes/runs, median tool-output bytes`.

| Card | Task | Parent | Changed |
| --- | --- | --- | --- |
| 1614 format error names the valid values | T1 | 3/3, 3955 | 3/3, 2940 |
| 1614 format error names the valid values | T2 | 3/3, 3047 | 3/3, 3365 |
| 1614 format error names the valid values | T3 | 0/3, 951 | 3/3, 617 |
| 1614 format error names the valid values | T4 | 3/3, 6963 | 3/3, 6963 |
| 1614 format error names the valid values | T5 | 3/3, 3027 | 3/3, 3027 |
| 1614 format error names the valid values | T6 | 3/3, 4029 | 3/3, 4029 |
| 1614 format error names the valid values | T7 | 3/3, 19191 | 3/3, 18621 |
| 1614 format error names the valid values | T8 | 3/3, 5626 | 3/3, 5626 |
| 1614 format error names the valid values | T9 | 3/3, 7045 | 3/3, 7123 |
| 1614 format error names the valid values | T10 | 3/3, 4471 | 3/3, 2593 |
| 1615 `--limit` on `aura instance list` | T1 | - | - |
| 1615 `--limit` on `aura instance list` | T2 | - | - |
| 1615 `--limit` on `aura instance list` | T3 | - | - |
| 1615 `--limit` on `aura instance list` | T4 | - | - |
| 1615 `--limit` on `aura instance list` | T5 | - | - |
| 1615 `--limit` on `aura instance list` | T6 | - | - |
| 1615 `--limit` on `aura instance list` | T7 | - | - |
| 1615 `--limit` on `aura instance list` | T8 | 3/3, 5653 | 3/3, 5654 |
| 1615 `--limit` on `aura instance list` | T9 | 3/3, 7059 | 3/3, 7137 |
| 1615 `--limit` on `aura instance list` | T10 | 3/3, 3799 | 3/3, 4402 |
| 1616 `read_only` in `agent-context` | T1 | 3/3, 2940 | 3/3, 3955 |
| 1616 `read_only` in `agent-context` | T2 | 3/3, 3365 | 3/3, 3366 |
| 1616 `read_only` in `agent-context` | T3 | 3/3, 617 | 3/3, 617 |
| 1616 `read_only` in `agent-context` | T4 | 3/3, 6963 | 3/3, 6963 |
| 1616 `read_only` in `agent-context` | T5 | 3/3, 3027 | 3/3, 3027 |
| 1616 `read_only` in `agent-context` | T6 | 3/3, 4029 | 3/3, 4029 |
| 1616 `read_only` in `agent-context` | T7 | 3/3, 14835 | 3/3, 14834 |
| 1616 `read_only` in `agent-context` | T8 | 3/3, 5626 | 3/3, 5556 |
| 1616 `read_only` in `agent-context` | T9 | 3/3, 7123 | 3/3, 7045 |
| 1616 `read_only` in `agent-context` | T10 | 3/3, 3021 | 3/3, 4471 |
| 1618 `--format jsonl` | T1 | 3/3, 2940 | 3/3, 3976 |
| 1618 `--format jsonl` | T2 | 3/3, 3366 | 3/3, 3068 |
| 1618 `--format jsonl` | T3 | 3/3, 617 | 3/3, 624 |
| 1618 `--format jsonl` | T4 | 3/3, 6963 | 3/3, 6984 |
| 1618 `--format jsonl` | T5 | 3/3, 2647 | 3/3, 3041 |
| 1618 `--format jsonl` | T6 | 3/3, 4029 | 3/3, 4050 |
| 1618 `--format jsonl` | T7 | 3/3, 22283 | 3/3, 14954 |
| 1618 `--format jsonl` | T8 | 3/3, 5626 | 3/3, 5653 |
| 1618 `--format jsonl` | T9 | 3/3, 8198 | 3/3, 5571 |
| 1618 `--format jsonl` | T10 | 3/3, 4471 | 3/3, 2779 |

## Reading it

- **1614 wins on T3.** The parent fails all 3 runs (951 bytes of tool output), and the changed build passes all 3 (617 bytes). The error now names the valid `--format` values. T3 was the one task failing on the pinned release.
- **1615, 1616 and 1618 are non-wins.** Every task passes on both arms, and the byte differences sit inside run-to-run noise. No task in T1 to T10 lists many instances, reads the `read_only` marker in `agent-context`, or asks for `--format jsonl`, so the benchmark can't see what these cards added. That is a gap in the tasks, not evidence against the cards.
- **Single-run swings are noise.** For example T9 on 1618 drops from 8198 to 5571 bytes, but T9 varies a lot between runs of the same build.

Raw runs: `bench/results/<card>-parent/` and `bench/results/<card>-changed/`, one directory per task and run, each with `stream.jsonl` and `result.json`. The dev environment `devcliswf` was up for the whole batch. Results were scanned for the Aura client ID and secret and for API-key shapes before committing, with no hits.
