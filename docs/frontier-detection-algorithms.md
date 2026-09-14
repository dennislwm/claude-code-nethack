# Frontier Detection Algorithms — Design Notes

Notes from reviewing `helper/frontier_scan.py` against published frontier-exploration
and pathfinding research, after two real false-positive/false-negative bugs found
in the same session (see git history for `frontier_scan.py`).

## What `frontier_scan.py` does today

Run after `./run '#terrain' a` (a manual, external step). The script scans the
whole remembered map and classifies every passable tile into one of three
buckets:

1. **Blank-adjacent** — a passable tile touching an unrevealed (` `) cell.
2. **Dead-end** — a corridor tile (`#`) with ≤1 passable neighbor, even with
   zero blank neighbors (every side already revealed by line-of-sight or an
   earlier visit).
3. **Revealed-but-unwalked fork** — a corridor tile with 2+ passable
   neighbors, never itself visited, adjacent to a tile that *was* visited —
   the player walked past it without turning in.

Results are sorted by Manhattan distance from `@`, with tiles the player has
already searched 10+ times (`SEARCH_EXHAUSTED`) sorted last but never dropped.
Consumed manually, mid-exploration, to pick the next walking target.

A `visited` set (every `(row, col)` the player actually stood on, pulled from
`turn_log`'s own per-move position field) now gates buckets 1 and 3 — bucket 2
(dead-ends) is deliberately exempt, since visiting a dead-end is exactly when
it becomes worth searching, not a reason to stop reporting it.

## Algorithms considered, not yet implemented

| Algorithm | Cost | Effort | Duplicates existing code | Overlaps existing code | Separation of concerns | Independent to add? |
|---|---|---|---|---|---|---|
| Min-frontier-size filtering (Yamauchi) | ~free (length check) | trivial | no | no | clean, orthogonal | yes |
| Reachability filtering (verify a candidate is actually walkable from `@`, not just geometrically adjacent) | O(cells) BFS per call | moderate — needs a maze-solver over `#`/`.`/`+` | overlaps `cursor_probe`'s existing local BFS (`edge_paths`, `nearest_frontier`) | yes, real overlap | blurs detection (this file) vs. routing (`cursor_probe`) — currently kept apart | no — needs a router to exist first |
| Utility ranking (distance × information-gain, not pure nearest) | cheap once real path distances exist | moderate | no | none yet | clean addition to the sort key | depends on the reachability BFS above (today's sort uses Manhattan, not path cost) |
| BotHack's "large sealed rectangular void" fallback — flag a suspiciously large unexplored blank region with no bordering frontier at all, as a signal to search walls facing it | O(cells), one flood-fill pass | moderate | no | none — genuinely new capability | separate function, clean | yes, fully independent |

**Recommendation:** the reachability-BFS and utility-ranking items are coupled
to each other and to new shared machinery, and they'd meaningfully overlap
`cursor_probe.py`'s existing local-BFS functions — worth a deliberate decision
(extend `cursor_probe`, or a new shared router module both files import)
rather than an ad-hoc addition to `find_frontiers`. The min-frontier-size
filter and the sealed-void fallback are both cheap and fully independent —
safe to add in isolation whenever there's a concrete case for them, same
pattern as the visited-tiles fix.

## Bugs found and fixed this session

- **False negative**: a corridor fork fully revealed by line-of-sight on both
  branches, with only one branch ever walked, was invisible to both the
  blank-adjacency and dead-end checks (neither blank-adjacent nor degree ≤1).
  Fixed by the `visited`-based fork check (bucket 3 above).
- **False positive (dominant)**: 53 of 69 reported frontiers on one live level
  were tiles the player had already stood on, re-flagged every run — a
  narrow 1-tile corridor is naturally flanked by permanent, never-revealing
  rock, which trips the blank-adjacency check forever once walked. Fixed by
  excluding `visited` tiles from the blank-adjacency check (not the dead-end
  check, which needs them to stay for searching).

## References

- Yamauchi, B. (1997). *A Frontier-Based Approach for Autonomous Exploration.*
  IEEE CIRA. https://dl.acm.org/doi/abs/10.1145/280765.280773
- *Frontier Based Exploration for Autonomous Robot* — https://arxiv.org/pdf/1806.03581
- *Frontier Detection and Reachability Analysis for 2D Graph-SLAM* — https://arxiv.org/pdf/2009.02869
- BotHack (NetHack bot, Clojure) — https://github.com/krajj7/BotHack, tutorial: https://github.com/krajj7/BotHack/blob/master/doc/tutorial.md
- TAEB / ANBF (NetHack bots, Perl) — https://github.com/TAEB/TAEB, https://github.com/TAEB/ANBF
- *Exploration in NetHack With Secret Discovery* (IEEE Transactions on Games) — https://arxiv.org/abs/1711.03087
- LuckyMera (hybrid symbolic/RL NetHack agent) — https://arxiv.org/pdf/2307.08532
- *Pathfinding in Random Partially Observable Environments* — https://arxiv.org/pdf/2209.04801
- FOV using recursive shadowcasting — https://www.roguebasin.com/index.php/FOV_using_recursive_shadowcasting
- *What the Hero Sees* (seen vs. visible vs. unknown map state) — https://journal.stuffwithstuff.com/2015/09/07/what-the-hero-sees/
- Field of Vision (RogueBasin) — https://www.roguebasin.com/index.php/Field_of_Vision
