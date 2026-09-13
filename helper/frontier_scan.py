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


def map_coverage(map_lines):
    """% of known map cells (rows/cols actually captured) that are non-blank
    -- a rough "how much of this level have I actually seen" gauge. Excludes
    status-bar rows the same way find_frontiers does; doesn't distinguish
    floor from wall, just seen vs. unseen."""
    rows = [r for r in map_lines if not cp.tm.is_status_line(r)]
    total = sum(len(r) for r in rows)
    if total == 0:
        return 0.0
    seen = sum(1 for r in rows for c in r if c != " ")
    return seen / total


# (upper bound, label) -- coverage < bound gets that label; falls through to
# "max" past the last one. A lot of a captured level is permanent rock/border
# that never reveals, so treat >50% as effectively fully explored rather than
# expecting 100%.
COVERAGE_BANDS = [(0.10, "sparse"), (0.25, "low"), (0.40, "medium"), (0.50, "high")]


def coverage_band(frac):
    for bound, label in COVERAGE_BANDS:
        if frac < bound:
            return label
    return "max"


def directional_coverage(map_lines):
    """Same idea as map_coverage, split into N/S and E/W halves at the
    map's own fixed midpoint -- not the player's position. A player-relative
    split gives each half a different-sized denominator (a bucket right next
    to an edge is tiny and trivially ~100% seen), which made a lopsided
    level near a wall misreport a real gap as "92% explored." A fixed split
    keeps all four buckets the same size, so the percentage means the same
    thing in each of them.

    Each row is walked over its own real length, not padded out to the
    widest row -- padding would invent phantom blank cells past a row's
    actual captured length (tmux capture-pane represents unexplored trailing
    space by ending the line early, not with literal spaces), inflating
    every bucket's denominator far past map_coverage's, and desyncing the
    two: confirmed this session, a padded-to-71-cols version totaled 4189
    cells against map_coverage's 913 for the same capture, so the printed
    per-direction percentages read far lower than they should and didn't
    reconcile with the overall coverage line at all.

    Trailing all-blank rows are dropped before picking mid_r -- the tmux
    pane is taller than NetHack's own ~21-row playfield, so the tail of
    `map_lines` is dead terminal padding, not unexplored level. Splitting
    on the raw row count (mid_r = len(rows)//2) put the N/S boundary deep
    inside that padding, so the S bucket measured space that can never
    have content -- it read 0% regardless of what the level actually
    contained (confirmed this session: a 59-row capture with real content
    ending at row 21 put mid_r at row 29)."""
    rows = [r for r in map_lines if not cp.tm.is_status_line(r)]
    while rows and not rows[-1].strip():
        rows.pop()
    if not rows:
        return {d: 0.0 for d in "NSEW"}
    mid_r = len(rows) // 2
    mid_c = max((len(r) for r in rows), default=0) // 2
    seen = {"N": 0, "S": 0, "E": 0, "W": 0}
    total = {"N": 0, "S": 0, "E": 0, "W": 0}
    for r, row in enumerate(rows):
        ns = "N" if r < mid_r else "S" if r > mid_r else None
        for c, cell in enumerate(row):
            ew = "W" if c < mid_c else "E" if c > mid_c else None
            for d in (ns, ew):
                if d is None:
                    continue
                total[d] += 1
                if cell != " ":
                    seen[d] += 1
    return {d: (seen[d] / total[d] if total[d] else 0.0) for d in seen}


def find_frontiers(map_lines, colors):
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
            if any(
                cp.tm.cell_at(map_lines, r + dr, c + dc) == " "
                for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)
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
    try:
        with open(tl.current_log_path()) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # one torn/corrupt line must not sink every future scan
                if entry.get("subgoal") != "search" or "row" not in entry:
                    continue
                if dlvl is not None and entry.get("dlvl") != dlvl:
                    continue
                if t_range is not None and not (t_range[0] <= entry.get("t", -1) <= t_range[1]):
                    continue
                key = (entry["row"], entry["col"])
                counts[key] = counts.get(key, 0) + entry.get("search_count", 0)
    except FileNotFoundError:
        pass
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
    assert map_coverage(["--", "  "]) == 0.5
    assert map_coverage(["St:18/05", "--"]) == 1.0  # status row excluded, not counted as blank
    assert coverage_band(0.05) == "sparse"
    assert coverage_band(0.46) == "high"
    assert coverage_band(0.50) == "max"
    assert coverage_band(0.99) == "max"

    # Fixed 3x3 grid split at its own midpoint (row 1, col 1), independent
    # of where the player stands. North row and west column are blank;
    # south row and east column are fully seen.
    #   row0 "   " (north row, all blank)
    #   row1 " . " (middle row: west cell blank, east cell blank)
    #   row2 " .." (south row: west cell blank, east cell seen)
    lopsided = ["   ", " . ", " .."]
    dc = directional_coverage(lopsided)
    assert dc["N"] == 0.0        # 0 of 3 north cells seen
    assert dc["W"] == 0.0        # 0 of 3 west cells seen
    assert dc["S"] == 2 / 3      # 2 of 3 south cells seen
    assert dc["E"] == 1 / 3      # 1 of 3 east cells seen
    assert min(dc, key=dc.get) in ("N", "W")  # tied for least-explored

    # A player standing right next to an edge must not inflate that side's
    # coverage -- the split point is the map's own midpoint, not the player's,
    # so a small explored sliver near an edge doesn't read as "100% explored."
    # (Content is on the LAST row here, not a middle one, so the trailing-
    # blank-row trim below doesn't remove it and change the test's shape.)
    edge_grid = ["    ", "    ", "  .."]
    dc2 = directional_coverage(edge_grid)
    assert dc2["E"] < 0.5  # only 1 of 3 east-half cells seen, not 100%

    # Ragged rows (tmux capture-pane's real shape -- unexplored trailing
    # space ends the line early, it isn't padded with literal " ") must not
    # get padded out to the widest row -- that invents phantom blank cells
    # past each short row's real length, inflating the denominator far past
    # map_coverage's and desyncing the two (confirmed this session: 4189
    # padded cells vs. 913 real ones for the same live capture). A ragged
    # grid's N+S total and W+E total must each equal its real cell count.
    ragged = [".", "..", "..."]  # 1+2+3 = 6 real cells total
    dc3 = directional_coverage(ragged)
    real_cells = sum(len(r) for r in ragged)
    assert real_cells == 6
    # every cell is fully seen ("." only), so each half's own ratio is 1.0
    # regardless of how the 6 real cells split across the buckets --
    # padding would instead pull every ratio below 1.0 by mixing in blanks.
    assert dc3["N"] == 1.0 and dc3["S"] == 1.0
    assert dc3["W"] == 1.0 and dc3["E"] == 1.0
    assert (1, 1) not in result

    # Trailing all-blank rows (dead terminal space below NetHack's own
    # ~21-row playfield -- the tmux pane is taller than the game itself
    # uses) must not shift mid_r into that padding. A 3-row real level
    # followed by 7 blank rows must split the same as the 3-row level
    # alone, not put N=all-3-rows, S=all-padding (which reads S as 0%
    # forever regardless of what the level contains).
    padded = [".", "..", "..."] + [""] * 7
    dc4 = directional_coverage(padded)
    assert dc4 == dc3

    # Rows blank because of pure whitespace, not true "" entries, get
    # treated identically -- still just padding.
    padded_ws = [".", "..", "..."] + [" " * 5] * 7
    assert directional_coverage(padded_ws) == dc3

    # A neighboring line that's simply SHORTER (no trailing space at all)
    # must count as blank too -- this is how tmux capture-pane actually
    # represents unexplored space, not padded literal " " characters.
    short_lines = ["##", "#"]  # row1 ends before row0's col1
    assert (0, 1) in find_frontiers(short_lines, {})

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
        # ponytail: annotate, never drop -- search is probabilistic (10x
        # empty is evidence, not proof a door isn't there), so a hard
        # exclusion risks permanently burying a real lead. Sort exhausted
        # tiles last, tagged, so they're still visible if worth retrying.
        frontiers = sorted(
            find_frontiers(lines, colors),
            key=lambda rc: (counts.get(rc, 0) >= SEARCH_EXHAUSTED, abs(rc[0] - pr) + abs(rc[1] - pc)),
        )
        for r, c in frontiers:
            n = counts.get((r, c), 0)
            tag = f" [searched {n}x]" if n else ""
            print(f"{cp.offset_str(r - pr, c - pc)} ({r},{c}): {lines[r][c]!r}{tag}")
        pct = map_coverage(lines)
        turns = sum(tl.subgoal_breakdown(dlvl=dlvl, t_range=t_range).values())
        print(f"coverage: {pct:.0%} ({coverage_band(pct)}), turns on this level: {turns}")
        dc = directional_coverage(lines)
        lowest = min(dc, key=dc.get)
        by_dir = " ".join(f"{d}={dc[d]:.0%}" for d in ("N", "S", "E", "W"))
        print(f"by direction: {by_dir} -- least explored: {lowest}")
