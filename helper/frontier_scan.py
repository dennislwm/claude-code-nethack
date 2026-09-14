"""List every passable tile on the known map adjacent to unexplored (blank)
space -- a full-level version of cursor_probe.nearest_frontier, which only
looks in the player's local grid box. Run right after `./run '#terrain' a`.

Usage: python3 frontier_scan.py
"""
import json
import subprocess

import cursor_probe as cp
import turn_log as tl

SEARCH_EXHAUSTED = 10  # 10x searched, nothing found -- CLAUDE.md's own bar

# map_coverage/coverage_band/directional_coverage/COVERAGE_BANDS/MAP_CELLS
# live in cursor_probe.py, not here -- this module already imports
# cursor_probe (a reverse import would be circular), so it's the only
# module that can hold the shared logic without duplicating it. Confirmed
# this session: a duplicate copy sitting in cursor_probe.py for the HTML
# renderer had silently kept the old, buggy dynamic-denominator behavior
# after this file's copy was fixed -- two copies means a fix in one place
# isn't a fix. Use cp.map_coverage / cp.coverage_band /
# cp.directional_coverage / cp.MAP_CELLS directly.


def visited_tiles(dlvl=None, t_range=None):
    """Every (row,col) the player actually stood on, from this game's own
    turn log -- same scoping as search_counts (dlvl/t_range), since Dlvl:N
    repeats across branches. Used to catch a corridor fork that's fully
    revealed on both sides (by line-of-sight down a straight passage) but
    only one side was ever walked: neither existing check catches it,
    since a revealed-not-walked branch has no blank neighbor (LOS already
    filled it in) and isn't a dead end (it has 2+ passable neighbors)."""
    seen = set()
    for entry in tl.read_log_entries():
        if "row" not in entry:
            continue
        if dlvl is not None and entry.get("dlvl") != dlvl:
            continue
        if t_range is not None and not (t_range[0] <= entry.get("t", -1) <= t_range[1]):
            continue
        seen.add((entry["row"], entry["col"]))
    return seen


def find_frontiers(map_lines, colors, visited=frozenset()):
    frontiers = []
    for r, row in enumerate(map_lines):
        if cp.tm.is_status_line(row):
            continue  # status text ("Co:18", "In:8"...) isn't terrain
        for c, cell in enumerate(row):
            if cell in (" ", ""):
                continue
            if not cp.is_passable(map_lines, r, c, colors):
                continue
            # cell_at (not a hand-rolled bounds check) so a neighbor past
            # the end of a shorter line counts as blank too -- tmux
            # capture-pane represents unexplored trailing space by simply
            # ending the line early, not by padding it with literal " ".
            # A hand-rolled check that rejects out-of-range before ever
            # comparing to " " misses that identical case (confirmed this
            # session: a real corridor tile went unflagged this way).
            # Once a tile has actually been visited, standing on it already
            # resolved whatever local mystery a blank neighbor implied --
            # if it were real floor, walking onto this tile would have
            # revealed it. A blank neighbor that survives a visit is
            # permanent, unreachable rock (typically a diagonal corner past
            # a 1-wide corridor's flank), not a lead. Confirmed this
            # session: 53 of 69 reported frontiers on one live level were
            # tiles already stood on, re-flagged every run because this
            # exclusion existed only on the newer fork check below, not
            # here -- the dominant false-positive source, not the
            # diagonal-corner case it was first suspected to be.
            neighbors = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]
            if (r, c) not in visited and any(
                cp.tm.cell_at(map_lines, r + dr, c + dc) == " " for dr, dc in neighbors
            ):
                frontiers.append((r, c))
                continue
            # A corridor tile can dead-end with zero blank neighbors: every
            # cell around it already got revealed (by line-of-sight down a
            # straight corridor, or from an earlier visit) even though the
            # branch itself was never walked to its real end. The 8-neighbor
            # blank check above misses this -- confirmed this session, a
            # dead-end corridor tile with exactly one passable neighbor
            # (nothing continues past it) was the level's real lead. Flag
            # any passable, non-room cell whose passable-neighbor count is
            # <=1 as a frontier too; a room floor tile is excluded since a
            # room interior legitimately has few open neighbors without
            # being a dead end.
            if cell == "#":
                passable_neighbors = sum(
                    1 for dr, dc in neighbors
                    if cp.is_passable(map_lines, r + dr, c + dc, colors)
                )
                if passable_neighbors <= 1:
                    frontiers.append((r, c))
                    continue
                # Revealed-but-unwalked fork: a corridor tile with 2+
                # passable neighbors, never itself visited, sitting next
                # to a tile that WAS visited -- the player walked past it
                # (saw it via line-of-sight down the passage) without
                # turning into it. Confirmed this session: this is exactly
                # the shape of corridor the blank-adjacency and dead-end
                # checks both miss.
                if (r, c) not in visited and any(
                    (r + dr, c + dc) in visited for dr, dc in neighbors
                ):
                    frontiers.append((r, c))
    return frontiers


def search_counts(dlvl=None, t_range=None):
    """Total search_count per (row,col), summed across this game's whole
    turn_log -- replaces a separate hand-marked exhausted file, since the
    log already carries everything needed (row/col + search_count) now
    that classify() tags batched searches correctly. One file, not two.

    Defaults to every dlvl/visit ever logged, same as before. Pass dlvl to
    scope to one level, and t_range=(start, end) to scope to one visit --
    same pattern as turn_log.subgoal_breakdown(), needed for the same
    reason: Dlvl:N repeats across branches (Mines vs. main dungeon), so a
    bare dlvl filter conflates two unrelated visits' searches into one
    misleading per-tile count."""
    counts = {}
    for entry in tl.read_log_entries():
        if entry.get("subgoal") != "search" or "row" not in entry:
            continue
        if dlvl is not None and entry.get("dlvl") != dlvl:
            continue
        if t_range is not None and not (t_range[0] <= entry.get("t", -1) <= t_range[1]):
            continue
        key = (entry["row"], entry["col"])
        counts[key] = counts.get(key, 0) + entry.get("search_count", 0)
    return counts


def _demo():
    lines = [
        "-----",
        "|...|",
        "|...  ",
        "-----",
    ]
    colors = {}
    result = find_frontiers(lines, colors)
    assert (2, 3) in result
    assert (1, 1) not in result

    # A neighboring line that's simply SHORTER (no trailing space at all)
    # must count as blank too -- this is how tmux capture-pane actually
    # represents unexplored space, not padded literal " " characters.
    short_lines = ["##", "#"]  # row1 ends before row0's col1
    assert (0, 1) in find_frontiers(short_lines, {})

    # A dead-end corridor tile with no blank neighbor at all (every
    # surrounding cell already revealed) must still be flagged -- degree-1
    # passable-neighbor count, not blank-adjacency, catches it.
    #   ----
    #   |..|#
    #   ----#
    #      #   <- dead end, col 6, all neighbors non-blank
    dead_end = [
        "----",
        "|..|#",
        "----#",
        "    #",
    ]
    de_frontiers = find_frontiers(dead_end, {})
    assert (3, 4) in de_frontiers

    # A T-junction fork fully revealed by line-of-sight on both arms, only
    # one of which was ever walked, must be flagged even though it's
    # neither blank-adjacent nor a dead end (degree 2). @ stood at (1,1)
    # and (1,2) (visited); the branch at (0,1) forks off but was never
    # stepped into.
    #   ...
    #   .#.
    #   .@@
    #   ...
    fork = [
        "...",
        ".#.",
        ".@@",
        "...",
    ]
    visited = {(2, 1), (2, 2)}
    fork_frontiers = find_frontiers(fork, {}, visited)
    assert (1, 1) in fork_frontiers
    assert (1, 1) not in find_frontiers(fork, {})  # absent without visited data

    # A status-bar row ("Co:18 In:8...") must never be scanned as terrain --
    # its text is passable-looking and sits next to real blank space, which
    # false-flagged status characters as frontiers on the live game screen.
    status_lines = ["#..", "St:18/05 Dx:13 Co:18"]
    assert all(r != 1 for r, c in find_frontiers(status_lines, {}))
    assert cp.offset_str(1, 2) == "S1E2"
    assert cp.offset_str(0, 0) == "here"

    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write(json.dumps({"row": 2, "col": 3, "subgoal": "search", "search_count": 7}) + "\n")
            f.write('{"row": 2, truncated garbage not json\n')  # must not crash the scan
            f.write(json.dumps({"row": 2, "col": 3, "subgoal": "search", "search_count": 4}) + "\n")
            f.write(json.dumps({"row": 0, "col": 0, "subgoal": "other"}) + "\n")
        real_path = tl.current_log_path
        tl.current_log_path = lambda: path
        try:
            assert search_counts() == {(2, 3): 11}
        finally:
            tl.current_log_path = real_path
    finally:
        os.remove(path)

    # Same Dlvl:N searched on two different visits (e.g. Mines then main
    # dungeon) -- dlvl/t_range scope to one visit instead of conflating both.
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write(json.dumps({"dlvl": 3, "t": 100, "row": 5, "col": 5, "subgoal": "search", "search_count": 3}) + "\n")
            f.write(json.dumps({"dlvl": 3, "t": 900, "row": 5, "col": 5, "subgoal": "search", "search_count": 6}) + "\n")
            f.write(json.dumps({"dlvl": 4, "t": 150, "row": 5, "col": 5, "subgoal": "search", "search_count": 9}) + "\n")
        real_path = tl.current_log_path
        tl.current_log_path = lambda: path
        try:
            assert search_counts() == {(5, 5): 18}
            assert search_counts(dlvl=3) == {(5, 5): 9}
            assert search_counts(dlvl=3, t_range=(0, 200)) == {(5, 5): 3}
            assert search_counts(dlvl=3, t_range=(800, 1000)) == {(5, 5): 6}
        finally:
            tl.current_log_path = real_path
    finally:
        os.remove(path)

    counts = {(2, 3): 11}
    ordered = sorted(result, key=lambda rc: (counts.get(rc, 0) >= SEARCH_EXHAUSTED, abs(rc[0] - 2) + abs(rc[1] - 2)))
    assert ordered[-1] == (2, 3)  # exhausted sorts last, never dropped
    assert (2, 3) in ordered
    print("ok")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        _demo()
    else:
        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", "claude-nethack"],
            capture_output=True, text=True, check=True,
        ).stdout
        lines = pane.split("\n")
        colors = cp.parse_colors("claude-nethack")
        pr, pc = cp.cursor_row_col("claude-nethack")
        # Scope both to this visit, not every visit to this Dlvl:N ever --
        # the same number repeats across branches (Mines vs. main dungeon),
        # and current_visit_t_range finds the exact boundary (no guessing)
        # since every log entry already records its own dlvl.
        status = tl.parse_status(pane)
        dlvl = status["dlvl"] if status else None
        t_range = tl.current_visit_t_range(dlvl) if dlvl is not None else None
        counts = search_counts(dlvl=dlvl, t_range=t_range)
        visited = visited_tiles(dlvl=dlvl, t_range=t_range)
        # ponytail: annotate, never drop -- search is probabilistic (10x
        # empty is evidence, not proof a door isn't there), so a hard
        # exclusion risks permanently burying a real lead. Sort exhausted
        # tiles last, tagged, so they're still visible if worth retrying.
        frontiers = sorted(
            find_frontiers(lines, colors, visited),
            key=lambda rc: (counts.get(rc, 0) >= SEARCH_EXHAUSTED, abs(rc[0] - pr) + abs(rc[1] - pc)),
        )
        for r, c in frontiers:
            n = counts.get((r, c), 0)
            tag = f" [searched {n}x]" if n else ""
            print(f"{cp.offset_str(r - pr, c - pc)} ({r},{c}): {lines[r][c]!r}{tag}")
        pct = cp.map_coverage(lines)
        # subgoal_breakdown already reads+parses the whole log once and
        # returns every category -- keep the dict instead of discarding it
        # down to just the sum, since movement share is a free byproduct
        # of a call already being made, not a second pass.
        subgoals = tl.subgoal_breakdown(dlvl=dlvl, t_range=t_range)
        turns = sum(subgoals.values())
        movement_pct = subgoals.get("movement", 0) / turns if turns else 0.0
        print(f"coverage: {pct:.0%} ({cp.coverage_band(pct)}), turns on this level: {turns} ({movement_pct:.0%} movement)")
        dc = cp.directional_coverage(lines, row_offset=1)
        ranked = sorted(dc, key=dc.get)  # least explored first
        by_dir = " ".join(f"{d}={dc[d]:.0%}" for d in ("N", "S", "E", "W"))
        print(f"by direction: {by_dir} -- least explored: {','.join(ranked)}")
