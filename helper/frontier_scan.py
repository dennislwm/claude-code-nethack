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


def search_counts():
    """Total search_count per (row,col), summed across this game's whole
    turn_log -- replaces a separate hand-marked exhausted file, since the
    log already carries everything needed (row/col + search_count) now
    that classify() tags batched searches correctly. One file, not two."""
    counts = {}
    try:
        with open(tl.current_log_path()) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # one torn/corrupt line must not sink every future scan
                if entry.get("subgoal") == "search" and "row" in entry:
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
    assert (1, 1) not in result

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
        counts = search_counts()
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
        turns = sum(tl.subgoal_breakdown().values())
        print(f"coverage: {pct:.0%} ({coverage_band(pct)}), turns on this level: {turns}")
