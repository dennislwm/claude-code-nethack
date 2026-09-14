#!/usr/bin/env python3
"""Default map/neighborhood renderer, using tmux's own cursor position
instead of @ glyph search to find the player.

Curses parks the terminal cursor on the player's tile after every redraw,
regardless of whether @ is actually drawn there -- so this works through
invisibility and through human-class monsters (watchmen, priests,
shopkeepers...) that render as the same @ glyph and would otherwise make
glyph search ambiguous.

tmux's #{cursor_x},#{cursor_y} are already 0-indexed terminal-grid
coordinates in the same indexing capture-pane's lines use, so they map
directly to (row, col) into the captured map text -- no offset math needed.

Caller contract: never invoke this while a map-cursor interaction you
opened (`/` look, `_` travel, a targeting prompt) is still open -- always
dismiss it first (Space/Escape/confirm). While such a prompt is active,
tmux's cursor tracks THAT cursor instead of the player, and there is no way
to detect that condition from the captured text alone (confirmed empirically:
a mid-interaction read landed on a plausible-looking but wrong map tile with
no error). Once dismissed, NetHack's own redraw restores the cursor to the
player before the next capture -- no extra redraw step needed.

This intentionally does not modify transpose_map.py; it reuses its map
extraction helpers (which don't depend on @ at all) and replaces only the
player-locating step.
"""

import html
import os
import re
import subprocess
import sys
from collections import deque

import transpose_map as tm
import turn_log as tl

GRID_RADIUS = 6  # 13x13

LABELS = [
    ("NW", -1, -1), ("N", -1, 0), ("NE", -1, 1),
    ("W", 0, -1), ("E", 0, 1),
    ("SW", 1, -1), ("S", 1, 0), ("SE", 1, 1),
]


def cursor_row_col(pane):
    """tmux's cursor position, already in the same (row, col) indexing as
    the captured map lines -- no conversion needed."""
    out = subprocess.run(
        ["tmux", "display-message", "-p", "-t", pane, "-F", "#{cursor_x},#{cursor_y}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    cx, cy = (int(v) for v in out.split(","))
    return cy, cx


def parse_colors(pane):
    """Parse the ANSI-tagged pane once into a row -> [color per visible
    column] list. An open door renders as the same '-'/'|' glyph as a plain
    wall (perpendicular to its wall's own orientation) -- the only way to
    tell them apart is terminal color, which plain `capture-pane -p` (used
    everywhere else in this file) strips. One parse per frame, so callers
    do a cheap list lookup instead of a subprocess call per cell."""
    out = subprocess.run(
        ["tmux", "capture-pane", "-e", "-p", "-t", pane],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    rows = []
    for line in out:
        colors, color, i = [], "0", 0
        while i < len(line):
            if line[i] == "\x1b" and line[i + 1:i + 2] == "[":
                end = line.index("m", i)
                color = line[i + 2:end]
                i = end + 1
                continue
            colors.append(color)
            i += 1
        rows.append(colors)
    return rows


def color_at(colors, row, col):
    if 0 <= row < len(colors) and 0 <= col < len(colors[row]):
        return colors[row][col]
    return "0"


WALLS = set("-|")  # '+' (door) and ' ' (unexplored) handled separately by callers


def is_door(map_lines, r, c):
    """True only if the '+' at (r,c) is a real closed door -- embedded in a
    wall run, i.e. at least one axis (N/S or E/W) has BOTH opposite
    neighbors being wall chars ('-'/'|'), the same "replaces a wall segment"
    structure all_doors uses for open doors. A spellbook lying on open
    floor also renders as '+' and can even collide with a real door's exact
    color (different spellbook identities render in different random
    colors -- confirmed this session: a shop spellbook and a real door both
    showed color "33"), so color can't disambiguate here the way it does
    for open doors. Structure is the only reliable signal."""
    if tm.cell_at(map_lines, r, c) != "+":
        return False
    n, s = tm.cell_at(map_lines, r - 1, c), tm.cell_at(map_lines, r + 1, c)
    w, e = tm.cell_at(map_lines, r, c - 1), tm.cell_at(map_lines, r, c + 1)
    return (n in WALLS and s in WALLS) or (w in WALLS and e in WALLS)


def is_passable(map_lines, r, c, colors=None):
    """True unless the tile is a wall or a real closed door. A denylist, not
    an allowlist -- NetHack has dozens of item/corpse glyphs (%, !, ?, ), [,
    $, *, ...) that all sit on walkable floor, and enumerating "floor-ish"
    characters missed '%' this session, silently treating every corpse as a
    wall and fragmenting open rooms into false dead ends. A '+' is only
    impassable when is_door() confirms it's a real door -- otherwise it's
    just an item (e.g. a spellbook) lying on open floor, walkable like any
    other item glyph. A '-'/'|' cell colored as a door (see parse_colors) is
    passable too -- default color "0" means "unknown/not checked", so
    callers that don't pass colors keep today's wall-only behavior."""
    cell = tm.cell_at(map_lines, r, c)
    color = color_at(colors, r, c) if colors else "0"
    if cell not in WALLS:
        if cell == "+":
            return not is_door(map_lines, r, c)
        return cell != " "
    return color not in ("0", "39", "37", "97")


def offset_str(fr, fc):
    """N/S/E/W direction+distance label for a (row, col) delta, e.g. (2, -3)
    -> 'S2W3', (0, 0) -> 'here'. Shared by print_neighborhood's frontier:
    line and frontier_scan.py, so a scan result is directly walkable
    instead of requiring manual (row,col) subtraction."""
    ns = f"N{-fr}" if fr < 0 else f"S{fr}" if fr > 0 else ""
    ew = f"W{-fc}" if fc < 0 else f"E{fc}" if fc > 0 else ""
    return (ns + ew) or "here"


def all_doors(map_lines, colors):
    """Scan the ENTIRE captured map (absolute row/col, not relative to the
    player like every other function here -- "where are all the doors on
    the level" has no natural center) for '-'/'|' cells colored as open
    doors (never '+' -- closed doors are a separate, unambiguous glyph
    nearest_frontier already handles) and flag which still lead somewhere
    unexplored (blank) along the door's own passage axis -- not all 8
    neighbors: the diagonal corners flanking a door are the wall junction's
    corner cells, permanently blank by map geometry (solid rock is never
    rendered) regardless of whether the door's actually-walkable sides have
    been explored. Checking all 8 flagged every door on a fully-walked level
    as still leading to "unexplored" space this session, purely from those
    permanently-blank corners. Per CLAUDE.md's Map Symbols, an open door's
    own glyph already names its passage axis: '|' passes N/S, '-' passes
    E/W. Only meaningful right after `#terrain` -> 'a'. Returns [(row, col,
    unexplored_adjacent), ...] -- a full-level inventory for planning,
    distinct from nearest_frontier's single nearest-actionable-thing
    answer."""
    doors = []
    for r, row in enumerate(map_lines):
        for c, cell in enumerate(row):
            if cell in "-|" and is_passable(map_lines, r, c, colors):
                axis = ((-1, 0), (1, 0)) if cell == "|" else ((0, -1), (0, 1))
                adjacent_unexplored = any(
                    tm.cell_at(map_lines, r + dr, c + dc) == " "
                    for dr, dc in axis
                )
                doors.append((r, c, adjacent_unexplored))
    return doors


def all_closed_doors(map_lines):
    """Scan the ENTIRE captured map for real closed-door '+' cells (see
    is_door -- a '+' can also be a spellbook item on open floor, and color
    doesn't disambiguate them). Only meaningful right after `#terrain` ->
    'a', for the same reason as all_doors: nearest_frontier only returns
    the single nearest one, which can be a dead-end interior door while a
    more useful closed door sits just a bit farther away in the same local
    box."""
    return [
        (r, c)
        for r, row in enumerate(map_lines)
        for c, cell in enumerate(row)
        if cell == "+" and is_door(map_lines, r, c)
    ]


def open_run(map_lines, pr, pc, dr, dc, max_dist, colors=None):
    """Count consecutive open tiles from (pr,pc) exclusive, stepping (dr,dc)
    each time, up to max_dist -- so batch size can be read directly instead
    of hand-counted off the printed grid. Recognizes a colored-as-door
    '-'/'|' as open when `colors` (from parse_colors) is supplied."""
    n = 0
    for i in range(1, max_dist + 1):
        r, c = pr + dr * i, pc + dc * i
        if not is_passable(map_lines, r, c, colors):
            break
        n = i
    return n


CARDINALS = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIAGONALS = ((-1, -1), (-1, 1), (1, -1), (1, 1))
NEIGHBORS = CARDINALS + DIAGONALS


def diagonal_ok(map_lines, pr, pc, ndr, ndc):
    """Vanilla NetHack forbids cutting a diagonal step into, out of, or past
    a doorway. (pr,pc) is the absolute cell being stepped FROM; (ndr,ndc) is
    the diagonal delta. Blocks the move if the source, the target, or either
    orthogonal cell the diagonal "cuts across" is a real door -- a '+' that's
    just an item on floor (see is_door) doesn't restrict diagonal movement."""
    if is_door(map_lines, pr, pc) or is_door(map_lines, pr + ndr, pc + ndc):
        return False
    return not is_door(map_lines, pr + ndr, pc) and not is_door(map_lines, pr, pc + ndc)


def nearest_frontier(map_lines, pr, pc, max_dist, colors=None):
    """BFS from (pr,pc) over floor/corridor tiles (8-directional, since
    NetHack movement is -- cardinal-only under-connects rooms at corners,
    as this session's own 2x2 pocket showed: it's reachable only via a
    diagonal step, which a cardinal-only BFS would wrongly call enclosed).
    Returns (dr, dc, kind) for the nearest tile adjacent to unexplored space
    ("unexplored") or a closed door ("door"), or None if the grid box is
    fully enclosed/explored with no door either -- so a room whose only way
    out is a closed door isn't misreported as a dead end just because the
    BFS can't see past it without opening it first (opening costs a turn,
    so the door itself -- not what's beyond it -- is the frontier).
    Recognizes a colored-as-door '-'/'|' as passable when `colors` (from
    parse_colors) is supplied, same as open_run/edge_paths."""
    seen = {(0, 0)}
    q = deque([(0, 0)])
    while q:
        dr, dc = q.popleft()
        for ndr, ndc in NEIGHBORS:
            r2, c2 = dr + ndr, dc + ndc
            if max(abs(r2), abs(c2)) > max_dist or (r2, c2) in seen:
                continue
            if ndr and ndc and not diagonal_ok(map_lines, pr + dr, pc + dc, ndr, ndc):
                continue
            cell = tm.cell_at(map_lines, pr + r2, pc + c2)
            if cell == " ":
                return r2, c2, "unexplored"
            if cell == "+" and is_door(map_lines, pr + r2, pc + c2):
                return r2, c2, "closed door"
            if is_passable(map_lines, pr + r2, pc + c2, colors):
                seen.add((r2, c2))
                q.append((r2, c2))
    return None


DIR_NAME = {
    (-1, 0): "N", (1, 0): "S", (0, -1): "W", (0, 1): "E",
    (-1, -1): "NW", (-1, 1): "NE", (1, -1): "SW", (1, 1): "SE",
}


def edge_paths(map_lines, pr, pc, max_dist, colors=None):
    """BFS from center over floor/corridor tiles (and through closed doors,
    since opening one is a real but doable action) with parent tracking, to
    find a turn-permitting route (not just a straight ray like open_run) to
    each of the N/S/E/W edges of the box. Returns {dir: [(step_dir, count,
    is_door), ...]} run-length-compressed segments -- a door tile always
    starts its own segment so the route doesn't silently hide the `o`+
    direction command it needs -- or {dir: None} if that edge is
    unreachable within max_dist even through doors. Recognizes a
    colored-as-door '-'/'|' as passable when `colors` (from parse_colors)
    is supplied, same as open_run."""
    parent = {(0, 0): None}
    door_at = set()
    q = deque([(0, 0)])
    found = {}
    while q and len(found) < 4:
        dr, dc = q.popleft()
        if dr == -max_dist:
            found.setdefault("N", (dr, dc))
        if dr == max_dist:
            found.setdefault("S", (dr, dc))
        if dc == max_dist:
            found.setdefault("E", (dr, dc))
        if dc == -max_dist:
            found.setdefault("W", (dr, dc))
        came_from = parent[(dr, dc)]
        last_dir = (dr - came_from[0], dc - came_from[1]) if came_from else None
        # ponytail: prefer continuing straight over turning, so BFS ties
        # resolve to clean runs instead of a step-by-step zigzag
        for ndr, ndc in sorted(NEIGHBORS, key=lambda d: d != last_dir):
            r2, c2 = dr + ndr, dc + ndc
            if max(abs(r2), abs(c2)) > max_dist or (r2, c2) in parent:
                continue
            if ndr and ndc and not diagonal_ok(map_lines, pr + dr, pc + dc, ndr, ndc):
                continue
            cell = tm.cell_at(map_lines, pr + r2, pc + c2)
            real_door = cell == "+" and is_door(map_lines, pr + r2, pc + c2)
            if real_door or is_passable(map_lines, pr + r2, pc + c2, colors):
                parent[(r2, c2)] = (dr, dc)
                if real_door:
                    door_at.add((r2, c2))
                q.append((r2, c2))

    results = {}
    for d in ("N", "S", "E", "W"):
        if d not in found:
            results[d] = None
            continue
        cell, steps = found[d], []
        while parent[cell] is not None:
            p = parent[cell]
            steps.append((cell[0] - p[0], cell[1] - p[1], cell in door_at))
            cell = p
        steps.reverse()
        segments = []
        for dr_dc, at_door in ((s[:2], s[2]) for s in steps):
            name = DIR_NAME[dr_dc]
            if segments and segments[-1][0] == name and not at_door and not segments[-1][2]:
                segments[-1] = (name, segments[-1][1] + 1, False)
            else:
                segments.append((name, 1, at_door))
        results[d] = segments
    return results


def new_tiles(map_lines, prev_lines, pr, pc):
    """Cells anywhere on the map that were blank last frame and are
    non-blank now -- what the last move(s) actually revealed, distinct from
    frontier_scan.py's "still adjacent to unexplored" (a persistent
    property, not a one-turn transition). Whole-frame, not just the local
    GRID_RADIUS box: a long movement batch can reveal tiles that end up
    farther than GRID_RADIUS from the final position, which a local-only
    scan would silently drop. Cost is the same negligible order as the
    local box (a full frame is a few thousand cells, still microseconds).
    prev_lines is None on the first ever call (no state file yet); report
    nothing rather than flagging the whole map as new."""
    if prev_lines is None:
        return []
    found = []
    for r, row in enumerate(map_lines):
        if r == 0:
            # Row 0 is always NetHack's message line ("You destroy the
            # kobold zombie!", etc.) in a real capture -- arbitrary text
            # that changes almost every turn, not terrain. cell_at can't
            # mask it the way is_status_line masks the bottom rows (message
            # text has no fixed keyword to match, and several existing
            # tests deliberately use row 0 of their small synthetic maps as
            # real terrain, unlike the real game's fixed screen layout) --
            # so it's skipped here, in the one function that scans every
            # row unconditionally on every call. Left unskipped, a longer
            # message than last turn's reveals "new" text past where the
            # old one ended, reported as a bogus reveal far north of the
            # player (confirmed this session: intermittent `new: N57...
            # N59...`-style noise, matching row 0 being far above the
            # player in this project's tall pane).
            continue
        for c in range(len(row)):
            # Both sides go through cell_at (not literal indexing), which
            # masks status-bar rows to blank -- symmetric masking, unlike an
            # earlier version that only masked prev_lines and so treated
            # status text as a permanent "new reveal" every single call.
            if tm.cell_at(map_lines, r, c) != " " and tm.cell_at(prev_lines, r, c) == " ":
                found.append((r - pr, c - pc))
    return found


NEW_TILES_CAP = 8  # more than this on one call -> summarize, don't enumerate


def format_new(found):
    if not found:
        return "none"
    if len(found) <= NEW_TILES_CAP:
        return " ".join(offset_str(dr, dc) for dr, dc in found)
    shown = " ".join(offset_str(dr, dc) for dr, dc in found[:NEW_TILES_CAP])
    return f"{shown} (+{len(found) - NEW_TILES_CAP} more, see frontier_scan.py)"


def print_neighborhood(map_lines, pos, pane, prev_lines=None):
    pr, pc = pos
    colors = parse_colors(pane)
    center_pad = "  " + " " * (GRID_RADIUS * 2)
    print("--- Neighborhood of @ (cursor-based) ---")
    print(f"pos: {pr},{pc}")
    print(center_pad + "N")
    for dr in range(-GRID_RADIUS, GRID_RADIUS + 1):
        row = " ".join(
            tm.cell_at(map_lines, pr + dr, pc + dc)
            for dc in range(-GRID_RADIUS, GRID_RADIUS + 1)
        )
        print(f"W {row} E" if dr == 0 else f"  {row}")
    print(center_pad + "S")
    print(" ".join(f"{d}={tm.cell_at(map_lines, pr + dr, pc + dc)}" for d, dr, dc in LABELS))
    print("far: " + " ".join(f"{d}={open_run(map_lines, pr, pc, dr, dc, GRID_RADIUS, colors)}" for d, dr, dc in LABELS))
    new = new_tiles(map_lines, prev_lines, pr, pc)
    print("new: " + format_new(new))
    # Absolute coords for turn_log.py -- a relative offset (used above) only
    # means anything at the instant it's printed; an absolute (row,col) is a
    # fixed map reference, so it's what's worth persisting for later review
    # of "was this reveal ever followed up on".
    if new:
        print("new_coords: " + " ".join(f"{pr + dr},{pc + dc}" for dr, dc in new))
    frontier = nearest_frontier(map_lines, pr, pc, GRID_RADIUS, colors)
    if frontier:
        fr, fc, kind = frontier
        print(f"frontier: {offset_str(fr, fc)} ({kind})")
    else:
        print("frontier: none (fully enclosed/explored within radius)")
    # per-direction escape routes -- useful for retreat/flee decisions
    # independent of whether a frontier was also found
    paths = edge_paths(map_lines, pr, pc, GRID_RADIUS, colors)
    print("paths: " + " ".join(
        f"{d}=blocked" if segs is None
        else f"{d}=" + "".join(
            f"{name}{n}+" if is_door else f"{name}{n}"
            for name, n, is_door in segs
        )
        for d, segs in paths.items()
    ))


def attempt_suffix(log_name):
    m = re.search(r"_(\d+)\.jsonl$", log_name)
    return f"_{m.group(1)}" if m else ""


def attempt_path(prefix, ext):
    """Translate turn_log.py's .current_turn_log pointer (turn_log_003.jsonl)
    into another per-game-attempt filename with the same numeric suffix,
    e.g. attempt_path("last_frame", "txt") -> last_frame_003.txt. Shared by
    any per-attempt state (frame cache, exhausted-search list, ...) so it
    resets on ./run --init exactly like the turn log does, instead of
    carrying stale data into a fresh game."""
    pointer = os.path.join(tl.GAME_STATE_DIR, ".current_turn_log")
    try:
        with open(pointer) as f:
            name = f"{prefix}{attempt_suffix(f.read().strip())}.{ext}"
    except FileNotFoundError:
        name = f"{prefix}.{ext}"
    return os.path.join(tl.GAME_STATE_DIR, name)


DLVL_RE = re.compile(r"Dlvl:(\d+)")


def current_frame_path(dlvl=None):
    """Per-dungeon-level frame file, not just per-game-attempt: comparing
    frames by screen row/col across a level change is meaningless -- the
    same position can hold a totally different tile on a different level,
    which would either silently miss real reveals (old level happened to
    have something non-blank there too) or flood "new:" with the whole
    level at once. A level change now just lands on an unwritten filename,
    which behaves exactly like the very first call -- no explicit
    "did the level change" detection needed."""
    prefix = "last_frame" if dlvl is None else f"last_frame_dlvl{dlvl}"
    return attempt_path(prefix, "txt")


# Standard xterm 16-color palette. "0"/"39" (no color / default) are handled
# separately in render_html -- they should follow the page's own text color,
# not a hardcoded one, so the page still works in both light and dark themes.
ANSI_HTML_COLOR = {
    "30": "#000000", "31": "#cd0000", "32": "#00cd00", "33": "#cdcd00",
    "34": "#0000ee", "35": "#cd00cd", "36": "#00cdcd", "37": "#e5e5e5",
    "90": "#7f7f7f", "91": "#ff0000", "92": "#00ff00", "93": "#ffff00",
    "94": "#5c5cff", "95": "#ff00ff", "96": "#00ffff", "97": "#ffffff",
}


def colorize(cells, sep=""):
    """Render [(char, color), ...] as HTML, merging consecutive same-color
    cells into one span. `sep` (e.g. " ") is stitched between cells within
    a run so grid-style spacing survives the merge -- it never affects
    color grouping since a separator carries no color of its own."""
    spans, run_color, run_chars = [], "0", []
    last_i = len(cells) - 1
    for i, (ch, color) in enumerate(cells):
        if color != run_color:
            if run_chars:
                spans.append((run_color, "".join(run_chars)))
            run_color, run_chars = color, []
        run_chars.append(ch if i == last_i else ch + sep)
    if run_chars:
        spans.append((run_color, "".join(run_chars)))
    return "".join(
        html.escape(text) if color in ("0", "39")
        # A compound SGR code (e.g. "1;33" bold+yellow) puts the actual
        # color param last; take it instead of failing the dict lookup.
        else f'<span style="color:{ANSI_HTML_COLOR.get(color.rsplit(";", 1)[-1], "inherit")}">{html.escape(text)}</span>'
        for color, text in spans
    )


def neighborhood_html(map_lines, colors, pr, pc, prev_lines):
    """Same content as print_neighborhood, colored and as one string --
    kept as its own small pass over the same GRID_RADIUS box (169 cells)
    rather than parametrizing print_neighborhood's print calls; the box is
    cheap enough that recomputing it once more per frame doesn't matter."""
    center_pad = "  " + " " * (GRID_RADIUS * 2)
    lines = ["--- Neighborhood of @ (cursor-based) ---", f"pos: {pr},{pc}", center_pad + "N"]
    for dr in range(-GRID_RADIUS, GRID_RADIUS + 1):
        cells = [
            (tm.cell_at(map_lines, pr + dr, pc + dc), color_at(colors, pr + dr, pc + dc))
            for dc in range(-GRID_RADIUS, GRID_RADIUS + 1)
        ]
        row_html = colorize(cells, sep=" ")
        lines.append(f"W {row_html} E" if dr == 0 else f"  {row_html}")
    lines.append(center_pad + "S")
    lines.append(" ".join(f"{d}={html.escape(tm.cell_at(map_lines, pr + dr, pc + dc))}" for d, dr, dc in LABELS))
    lines.append("far: " + " ".join(f"{d}={open_run(map_lines, pr, pc, dr, dc, GRID_RADIUS, colors)}" for d, dr, dc in LABELS))
    new = new_tiles(map_lines, prev_lines, pr, pc)
    lines.append("new: " + format_new(new))
    if new:
        lines.append("new_coords: " + " ".join(f"{pr + dr},{pc + dc}" for dr, dc in new))
    frontier = nearest_frontier(map_lines, pr, pc, GRID_RADIUS, colors)
    if frontier:
        fr, fc, kind = frontier
        lines.append(f"frontier: {offset_str(fr, fc)} ({kind})")
    else:
        lines.append("frontier: none (fully enclosed/explored within radius)")
    paths = edge_paths(map_lines, pr, pc, GRID_RADIUS, colors)
    lines.append("paths: " + " ".join(
        f"{d}=blocked" if segs is None
        else f"{d}=" + "".join(f"{name}{n}+" if is_door else f"{name}{n}" for name, n, is_door in segs)
        for d, segs in paths.items()
    ))
    return "\n".join(lines)


# NetHack's own fixed playfield size (include/global.h: COLNO 80, ROWNO
# 21; COLNO also matches tm.MAP_WIDTH, the column cutoff split_output
# already uses to separate map from overlay). Column 0 is structurally
# never used for terrain, so the real usable width is COLNO-1. This is the
# single canonical home for map_coverage/directional_coverage/
# COVERAGE_BANDS -- frontier_scan.py imports this module already (a
# reverse import would be circular), so it calls these via `cp.*` instead
# of keeping its own copy. Confirmed this session: the coverage line shown
# in the published HTML artifact (render_html below) was silently running
# a separate, unfixed duplicate of this logic the whole time a fix was
# believed to be live in frontier_scan.py alone.
NETHACK_COLNO = tm.MAP_WIDTH
NETHACK_ROWNO = 21
MAP_CELLS = (NETHACK_COLNO - 1) * NETHACK_ROWNO


def map_coverage(map_lines):
    """% of the level's true fixed cell count (MAP_CELLS) that's non-blank
    in the capture -- against NetHack's own playfield size, not the size
    of whatever got captured. A dynamic denominator (summing each row's
    own captured length) silently shrinks to match only what's been drawn
    so far, since tmux capture-pane trims unrevealed trailing space rather
    than padding it with literal " " -- confirmed this session, a live
    level read 43.6% coverage against the dynamic denominator but only
    15.6% against this fixed one, a ~2.8x overstatement."""
    rows = [r for r in map_lines if not tm.is_status_line(r)]
    seen = sum(1 for r in rows for c in r if c != " ")
    return seen / MAP_CELLS


# (upper bound, label) -- coverage < bound gets that label; falls through
# to "max" past the last one. A lot of a captured level is permanent
# rock/border that never reveals, so treat the top band as effectively
# fully explored rather than expecting 100%.
# ponytail: rescaled from the pre-fix thresholds (0.10/0.25/0.40/0.50) by
# the ~0.358x ratio observed when map_coverage's denominator changed from
# the captured-viewport size to MAP_CELLS, then doubled on user feedback
# that the first-pass bands felt too tight. Still one data point, not a
# calibration study; revisit against a range of real levels.
COVERAGE_BANDS = [(0.08, "sparse"), (0.18, "low"), (0.28, "medium"), (0.36, "high")]


def coverage_band(frac):
    for bound, label in COVERAGE_BANDS:
        if frac < bound:
            return label
    return "max"


def directional_coverage(map_lines, row_offset=0):
    """Same idea as map_coverage, split into N/S and E/W halves at
    NetHack's own fixed playfield midpoint -- not a midpoint computed from
    whatever got captured. A dynamic split suffers the identical
    self-referential-denominator bug as map_coverage's old dynamic form:
    as more of the level gets revealed, the midpoint itself drifts, so a
    percentage now isn't comparable to one ten turns ago, and which
    direction reads as "least explored" can flip for no reason other than
    capture size changing.

    `row_offset` is how many leading rows sit before the real playfield's
    own row 0 in `map_lines` -- pass 1 for a raw tmux capture-pane grab
    (NetHack always reserves screen row 0 for the message line, blank or
    not) or for `map_area` from `tm.split_output` (column-only split,
    rows stay aligned with the raw capture). Pass 0 (default) for a
    synthetic grid that already starts at the map's own row 0, e.g. tests.

    Terminal padding past the real playfield (the tmux pane is taller than
    NetHack's own 21-row map) is excluded by construction -- exactly
    NETHACK_ROWNO rows are read starting at row_offset, nothing beyond."""
    body = map_lines[row_offset:row_offset + NETHACK_ROWNO]
    mid_r = NETHACK_ROWNO // 2
    mid_c = NETHACK_COLNO // 2
    seen = {"N": 0, "S": 0, "E": 0, "W": 0}
    total = {
        "N": mid_r * NETHACK_COLNO,
        "S": (NETHACK_ROWNO - mid_r - 1) * NETHACK_COLNO,
        "W": NETHACK_ROWNO * mid_c,
        "E": NETHACK_ROWNO * (NETHACK_COLNO - mid_c - 1),
    }
    for r, row in enumerate(body):
        if tm.is_status_line(row):
            continue
        ns = "N" if r < mid_r else "S" if r > mid_r else None
        for c in range(NETHACK_COLNO):
            cell = row[c] if c < len(row) else " "
            ew = "W" if c < mid_c else "E" if c > mid_c else None
            if cell == " ":
                continue
            if ns:
                seen[ns] += 1
            if ew:
                seen[ew] += 1
    return {d: (seen[d] / total[d] if total[d] else 0.0) for d in seen}


def render_html(map_lines, colors, title="", pos=None, prev_lines=None, dlvl=None):
    """Static, self-refreshing HTML snapshot of the map, colored to match
    tmux's ANSI codes -- lets the game be watched in a browser tab instead
    of attaching a read-only tmux session. meta-refresh, not a JS poll:
    this file is rewritten by an external process each turn, not served by
    anything, and fetch() against a file:// URL is blocked by CORS in most
    browsers -- a plain timed page reload is what actually works here.
    Map cells are space-separated (sep=" ") to match the neighborhood
    grid's spacing below it."""
    rows = [
        colorize(
            [(ch, color_at(colors, r, c)) for c, ch in enumerate(line)],
            sep="" if tm.is_status_line(line) else " ",
        )
        for r, line in enumerate(map_lines)
    ]
    # Same blank-row collapsing stdout already gets (tm.squeeze_blanks) --
    # color lookup above stays keyed to the original row index, this only
    # trims the finished per-row strings, so colors can't get misaligned.
    body = "\n".join(tm.squeeze_blanks(rows))
    neighborhood = neighborhood_html(map_lines, colors, *pos, prev_lines) if pos else ""
    pct = map_coverage(map_lines)
    # Scoped to this visit, not every visit ever logged to this Dlvl:N --
    # see frontier_scan.py's CLI for why (same conflation-across-branches
    # bug, same fix).
    t_range = tl.current_visit_t_range(dlvl) if dlvl is not None else None
    subgoals = tl.subgoal_breakdown(dlvl=dlvl, t_range=t_range)
    turns = sum(subgoals.values())
    movement_pct = subgoals.get("movement", 0) / turns if turns else 0.0
    coverage = (
        f"coverage: {pct:.0%} ({coverage_band(pct)}), "
        f"turns on this level: {turns} ({movement_pct:.0%} movement)"
    )
    if pos:
        dc = directional_coverage(map_lines, row_offset=1)
        ranked = sorted(dc, key=dc.get)  # least explored first
        by_dir = " ".join(f"{d}={dc[d]:.0%}" for d in ("N", "S", "E", "W"))
        coverage += f"<br>by direction: {by_dir} -- least explored: {','.join(ranked)}"
    return (
        "<!doctype html>\n<html>\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta http-equiv="refresh" content="2">\n'
        f"<title>NetHack {html.escape(title)}</title>\n"
        "<style>\n"
        "  body { background:#111; color:#ddd; margin:0; padding:12px; }\n"
        "  .scroll { overflow-x:auto; }\n"
        '  pre { font-family: "IBM Plex Mono", ui-monospace, monospace;'
        " font-variant-ligatures: none; white-space: pre; margin:0;"
        " font-size:14px; line-height:1.2; width:max-content; }\n"
        "</style>\n</head>\n<body>\n"
        f'<div class="scroll"><pre class="map">{body}</pre></div>\n'
        f'<div class="scroll"><pre class="grid">{neighborhood}\n{coverage}</pre></div>\n'
        "</body>\n</html>\n"
    )


STABLE_VIEW_PATH = os.path.join(tl.GAME_STATE_DIR, "game_view.html")


def ensure_stable_view_link(target_path, link_path=STABLE_VIEW_PATH):
    """A fixed filename that always resolves to whatever this attempt's
    game_view_NNN.html currently is, so a bookmarked browser tab survives
    across ./run --init instead of breaking on the next attempt number."""
    target_name = os.path.basename(target_path)
    try:
        if os.readlink(link_path) == target_name:
            return
    except OSError:
        pass
    try:
        os.remove(link_path)
    except FileNotFoundError:
        pass
    os.symlink(target_name, link_path)


def should_save_frame(map_lines, prev_lines):
    """True unless the in-game turn (`T:`) is identical to the saved
    baseline's -- a blocked move (e.g. a diagonal cut into a doorway) costs
    no turn, so saving on every call was wiping a `new:` reveal's one-call
    visibility window even when the player never actually moved (confirmed
    this session: two failed move attempts in a row erased a reveal before
    it could be acted on). No prior baseline, or an unparseable status
    line, saves anyway rather than silently freezing the baseline forever."""
    if prev_lines is None:
        return True
    cur = tl.parse_status("\n".join(map_lines))
    prev = tl.parse_status("\n".join(prev_lines))
    if cur is None or prev is None:
        return True
    return cur["t"] != prev["t"]


def main():
    pane = sys.argv[1] if len(sys.argv) > 1 else "claude-nethack"
    raw_lines = sys.stdin.read().splitlines()
    map_area, overlay = tm.split_output(raw_lines)

    for line in tm.squeeze_blanks(map_area):
        print(line)

    dlvl_match = DLVL_RE.search("\n".join(map_area))
    frame_path = current_frame_path(dlvl_match.group(1) if dlvl_match else None)
    try:
        with open(frame_path) as f:
            prev_lines = f.read().splitlines()
    except FileNotFoundError:
        prev_lines = None

    pos = cursor_row_col(pane)
    print_neighborhood(map_area, pos, pane, prev_lines)

    view_path = attempt_path("game_view", "html")
    with open(view_path, "w") as f:
        f.write(render_html(
            map_area, parse_colors(pane),
            title=dlvl_match.group(0) if dlvl_match else "",
            pos=pos, prev_lines=prev_lines,
            dlvl=int(dlvl_match.group(1)) if dlvl_match else None,
        ))
    ensure_stable_view_link(view_path)

    if not overlay and should_save_frame(map_area, prev_lines):
        # A menu/panel overwrites map_area's columns with its own text or
        # blank padding -- persisting that would corrupt the next diff's
        # baseline (long-explored terrain would look freshly blank, then
        # falsely flag as "new:" once the panel closes). Keep the last
        # known-clean frame instead. should_save_frame additionally skips
        # the save when no real turn has passed (a blocked move, e.g. a
        # diagonal cut into a doorway) -- otherwise a `new:` reveal was
        # wiped by the very next call even when the player never actually
        # moved, giving it a shorter window to act on than one real turn.
        with open(frame_path, "w") as f:
            f.write("\n".join(map_area))

    if overlay:
        print("--- Text Panel (modal: send Space/Escape to close it BEFORE moving) ---")
        for line in overlay:
            print(line)


def _demo():
    status = "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:5"
    same_turn = [status, "|...|"]
    next_turn = [status.replace("T:5", "T:6"), "|...|"]
    assert should_save_frame(same_turn, None) is True  # no baseline yet
    assert should_save_frame(same_turn, same_turn) is False  # blocked move, no turn spent
    assert should_save_frame(next_turn, same_turn) is True  # a real turn passed
    assert should_save_frame(["no status line"], same_turn) is True  # unparseable, save anyway

    prev = ["-----", "|...|", "|.   ", "-----"]
    curr = ["-----", "|...|", "|.#..", "-----"]
    assert new_tiles(curr, prev, 2, 2) == [(0, 0), (0, 1), (0, 2)]
    assert new_tiles(curr, None, 2, 2) == []
    # Row 0 is the message line in a real capture -- a longer message this
    # turn than last turn must never be reported as a "new" map reveal.
    msg_prev = ["You hit.", "|...|", "|...|", "-----"]
    msg_curr = ["You destroy the kobold zombie!", "|...|", "|...|", "-----"]
    assert new_tiles(msg_curr, msg_prev, 2, 2) == []
    assert offset_str(0, 1) == "E1"
    # A '|' door (N/S passage) with both real through-cells explored but
    # diagonal wall-corner cells still blank must NOT be flagged as leading
    # to unexplored space -- those corners are permanent void geometry, not
    # real dungeon squares (root cause of a false-positive this session).
    door_room = ["  #  ", "--|--", "  .  "]
    door_colors = [["0"] * 5, ["0", "0", "33", "0", "0"], ["0"] * 5]
    doors = all_doors(door_room, door_colors)
    assert doors == [(1, 2, False)]
    # But a '-' door (E/W passage) with a genuinely blank cell along ITS
    # axis must still be flagged True.
    door_open_lead = ["-----", "|...-", "|....", "-----"]
    lead_colors = [["0"] * 5, ["0", "0", "0", "0", "33"], ["0"] * 5, ["0"] * 5]
    doors2 = all_doors(door_open_lead, lead_colors)
    assert (1, 4, True) in doors2
    # A '+' embedded in a wall run (both N/S or both E/W neighbors are
    # walls) is a real door; a '+' sitting on open floor mid-room (a
    # spellbook item) is not, even with the identical glyph and even if
    # its color happens to match a real door's color -- confirmed this
    # session, a shop spellbook and a real closed door both rendered "33".
    real_door_room = ["--+--"]
    assert is_door(real_door_room, 0, 2)
    item_in_room = ["....", "..+.", "...."]
    assert not is_door(item_in_room, 1, 2)
    assert is_passable(item_in_room, 0, 0, None)  # sanity: '.' still passable
    assert is_passable(item_in_room, 1, 2, None)  # non-door '+' is walkable floor
    assert not is_passable(real_door_room, 0, 2, None)  # real door blocks passage
    # Denominator is NetHack's fixed playfield (MAP_CELLS), not the size
    # of whatever was passed in.
    assert map_coverage(["--", "  "]) == 2 / MAP_CELLS
    assert coverage_band(0.04) == "sparse"
    assert coverage_band(0.32) == "high"
    assert coverage_band(0.40) == "max"
    assert attempt_suffix("turn_log_003.jsonl") == "_003"
    assert attempt_suffix("") == ""
    assert format_new([]) == "none"
    assert format_new([(0, 1), (1, 0)]) == "E1 S1"
    many = [(0, i) for i in range(1, 12)]
    summarized = format_new(many)
    assert summarized.endswith("(+3 more, see frontier_scan.py)")
    shown_offsets = summarized.split(" (+")[0].split(" ")
    assert len(shown_offsets) == NEW_TILES_CAP

    page = render_html(["a@b"], {0: ["33", "0", "33"]}, title="T:1")
    assert '<meta http-equiv="refresh"' in page
    assert '<span style="color:#cdcd00">a </span>' in page  # space-joined, matching grid spacing
    assert '<span style="color:#cdcd00">b</span>' in page
    assert page.count("<span") == 2  # two yellow runs, plain '@ ' left uncolored

    compound = render_html(["x"], {0: ["1;33"]})
    assert '<span style="color:#cdcd00">x</span>' in compound  # bold+yellow -> yellow, not "inherit"

    with_grid = render_html(["x" * 13] * 13, {}, pos=(6, 6), prev_lines=None)
    assert "frontier:" in with_grid
    assert with_grid.count("<pre") == 2  # map and neighborhood text as separate blocks
    assert "by direction:" in with_grid
    assert "least explored:" in with_grid

    no_pos = render_html(["x" * 5] * 5, {})  # pos=None -- no directional line, no crash
    assert "by direction:" not in no_pos

    grid_colors = {r: ["33"] * 13 for r in range(13)}
    colored_grid = render_html(["x" * 13] * 13, grid_colors, pos=(6, 6))
    assert '<span style="color:#cdcd00">' in colored_grid.split('<pre class="grid">')[1]  # grid cell colored too

    padded = render_html(["a", "  ", "  ", "  ", "b"], {})
    map_block = padded.split('<pre class="map">')[1].split("</pre>")[0]
    assert map_block.count("\n") == 2  # 5 rows -> a, one collapsed blank, b
    print("ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        _demo()
    else:
        main()
