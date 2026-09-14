"""Append one JSON line per ./run call to turn_log.jsonl.

Usage: python3 turn_log.py "<keys sent>" "<./run output text>"
"""
import collections
import json
import os
import re
import sys

# Anchored to this file's location, not the caller's CWD -- a relative
# "game_state/..." string silently resolves to nothing (FileNotFoundError,
# caught) when this script is run from inside helper/ instead of the project
# root, which happened repeatedly this session and looked like clean, low
# data (empty counts, "turns on this level: 0") rather than a broken path.
GAME_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "game_state")

STATUS_RE = re.compile(
    r"Dlvl:(\d+)\s+\$:(\d+)\s+HP:(-?\d+)\((\d+)\)\s+Pw:(-?\d+)\((\d+)\)\s+AC:(-?\d+)\s+Xp:(\d+)\s+T:(\d+)"
)
POS_RE = re.compile(r"^pos: (-?\d+),(-?\d+)$", re.MULTILINE)
NEW_COORDS_RE = re.compile(r"^new_coords: (.+)$", re.MULTILINE)

COMMAND_SUBGOAL = {
    "s": "search", "m s": "search",
    ".": "rest",
    "_": "travel",
    ",": "loot", "/": "loot",
    "o": "explore", "C-d": "explore", "#terrain": "explore", "#terrain a": "explore",
    "#pray": "combat",
    "<": "movement", ">": "movement",
}

MOVE_KEYS = set("hjklyubn")

MESSAGE_SUBGOAL = [
    ("You hit ", "combat"), ("You miss ", "combat"), ("You kill ", "combat"),
    ("bites!", "combat"), ("misses!", "combat"),
    (" - a ", "loot"), ("Things that are here", "loot"), ("You see here", "loot"),
    ("You find ", "search"), ("hidden", "search"),
    ("door opens", "explore"), ("crashes open", "explore"), ("is locked", "explore"),
    ("Really step onto that", "explore"),
    ("You die", "death"),
]


def classify(message: str, keys: str) -> str:
    if keys.strip() == "Space":
        return "protocol_violation"  # Space should only be chained, per CLAUDE.md
    for substr, msg_goal in MESSAGE_SUBGOAL:
        if substr in message:
            return msg_goal
    tokens = keys.split()
    # A leading "Space" only dismisses a pending --More--; it isn't itself
    # an action, so it shouldn't disqualify an otherwise-uniform batch from
    # the token checks below (confirmed this session: "Space l l l" fell to
    # "other" even though it's 3 real movement keys plus a dismissal).
    body = tokens[1:] if tokens[:1] == ["Space"] else tokens
    # A repeated forced-search batch ("m s m s m s...") never equals the
    # dict's literal "m s" key, no matter how many repeats -- root cause is
    # the exact-match lookup, not the specific string, so check by token.
    if body and all(t in ("s", "m") for t in body):
        return "search"
    # Same token-based reasoning as the search check above: a batched move
    # ("l l l") never equals a COMMAND_SUBGOAL dict key either, so it fell
    # into "other" -- which turned out to be 84% of a real game's log,
    # almost entirely bare hjklyubn movement, not truly unclassifiable turns.
    if body and all(len(t) == 1 and t in MOVE_KEYS for t in body):
        return "movement"
    # A rest batch ("." "." ".") is the same story again -- only the exact
    # single "." matches the dict.
    if body and all(t == "." for t in body):
        return "rest"
    # "_ < ." / "_ > ." (open travel, jump to a symbol, confirm) never
    # equals the dict's bare "_" key either; any keys starting the travel
    # prompt are the same subgoal regardless of how it's steered/confirmed.
    if tokens[:1] == ["_"]:
        return "travel"
    return COMMAND_SUBGOAL.get(keys, "other")


def parse_status(text: str) -> dict | None:
    m = STATUS_RE.search(text)
    if not m:
        return None
    dlvl, gold, hp, hp_max, pw, pw_max, ac, xp, t = map(int, m.groups())
    entry = {
        "t": t, "dlvl": dlvl, "hp": hp, "hp_max": hp_max,
        "pw": pw, "pw_max": pw_max, "ac": ac, "xp": xp, "gold": gold,
    }
    pos = POS_RE.search(text)
    if pos:
        entry["row"], entry["col"] = int(pos.group(1)), int(pos.group(2))
    new_coords = NEW_COORDS_RE.search(text)
    if new_coords:
        entry["new_coords"] = [
            [int(r), int(c)] for r, c in
            (pair.split(",") for pair in new_coords.group(1).split())
        ]
    return entry


def current_log_path() -> str:
    pointer = os.path.join(GAME_STATE_DIR, ".current_turn_log")
    try:
        with open(pointer) as f:
            name = os.path.basename(f.read().strip())
    except FileNotFoundError:
        return os.path.join(GAME_STATE_DIR, "turn_log.jsonl")
    return os.path.join(GAME_STATE_DIR, name)


def read_log_entries():
    """Every parsed JSON entry in the current turn log, in file order --
    the shared skeleton behind current_visit_t_range, subgoal_breakdown,
    and frontier_scan's visited_tiles/search_counts, which each used to
    hand-roll the same open/read/json.loads/skip-torn-lines/missing-file
    loop. One place to get this right, four fewer copies to keep in sync."""
    try:
        with open(current_log_path()) as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # one torn/corrupt line must not sink the whole read
    except FileNotFoundError:
        return


def _last_entry(log_path):
    try:
        with open(log_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return None
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def log_turn(keys: str, output: str, log_path: str = None) -> dict | None:
    if not keys or "Unknown command" in output:
        return None
    if log_path is None:
        log_path = current_log_path()
    entry = parse_status(output)
    if entry is None:
        return None
    entry["keys"] = keys
    entry["subgoal"] = classify(output, keys)
    # A movement batch that didn't advance T: (a wall/dead-end bump) sent a
    # real tool call for zero game progress -- the same overhead category as
    # a standalone Space, just discovered by comparing to the last entry
    # instead of the keys alone. Only checked for "movement": search always
    # consumes a turn even when it finds nothing, so this can't false-flag
    # there, and a partially-successful batch (2 of 4 keys land) isn't
    # detectable this way -- the log only has the net position after the
    # whole call, not per-keystroke, so this only catches a fully wasted call.
    if entry["subgoal"] == "movement":
        last = _last_entry(log_path)
        if last is not None and last.get("t") == entry.get("t"):
            entry["subgoal"] = "protocol_violation"
        # A 3+ key manual batch that revealed nothing new is exactly the
        # case the skill's own travel rule already names: "3+ manual
        # movement keys through ground already on the map, stop and use
        # `_` instead." Cheap by construction -- new_coords is already
        # parsed for every entry, no extra lookback needed. Not exact (a
        # batch could reveal one new tile at the very end despite mostly
        # retreading known ground, or walk into a genuinely new but
        # already-lit room and dodge the flag), but it's the same signal
        # the rule itself already uses, not a new invented threshold.
        elif len(keys.split()) >= 3 and "new_coords" not in entry:
            entry["subgoal"] = "protocol_violation"
    if entry["subgoal"] == "search":
        entry["search_count"] = keys.split().count("s")
    if entry["hp"] <= 0:
        entry["died"] = True
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def current_visit_t_range(dlvl=None):
    """The (min_t, max_t) turn range of the CURRENT visit -- the log's
    tail run of entries at `dlvl` (defaults to the last entry's level) --
    exact, not a heuristic, since every entry already records which dlvl
    it was on, so walking backward from the log's tail while dlvl matches
    finds the current visit's start with no guessing. Only answers for
    whatever level the log's last entry is on: pass a `dlvl` that doesn't
    match the tail (a stale/historical level) and this returns None rather
    than reaching past the current visit into an earlier one -- reaching
    back further isn't the point, since the caller (frontier_scan's live
    scan) only ever wants "this visit," not some prior one. Feeds
    subgoal_breakdown's and search_counts' t_range param so a caller who
    only knows "what dlvl am I on" (not the turn it started) can still
    scope to just this visit, not conflate it with an earlier visit to the
    same Dlvl:N number in a different branch. Returns None if the log is
    empty or the tail isn't at `dlvl`."""
    entries = list(read_log_entries())
    if not entries:
        return None
    if dlvl is None:
        dlvl = entries[-1]["dlvl"]
    ts = []
    for e in reversed(entries):
        if e.get("dlvl") != dlvl:
            break
        if "t" in e:
            ts.append(e["t"])
    return (min(ts), max(ts)) if ts else None


def subgoal_breakdown(dlvl=None, t_range=None):
    """Count this game's turn_log entries by subgoal, filtered to one
    dungeon level -- defaults to whatever level the most recent entry is
    on, so a plain call answers "what have I been doing on the level I'm
    currently on" without the caller having to know the number.

    The log has no dungeon-branch field -- Dlvl:N repeats across branches
    (e.g. Dlvl:3 exists once in the Mines and once in the main dungeon),
    so a bare dlvl filter conflates both visits if a game entered a branch
    and came back. Pass t_range=(start, end) (each `T:` inclusive) to scope
    to one visit's actual turn span instead -- every entry already carries
    `t`, so no schema change is needed for this."""
    entries = list(read_log_entries())
    if dlvl is None and entries:
        dlvl = entries[-1]["dlvl"]
    matches = (e for e in entries if e.get("dlvl") == dlvl)
    if t_range is not None:
        lo, hi = t_range
        matches = (e for e in matches if lo <= e.get("t", -1) <= hi)
    return dict(collections.Counter(e["subgoal"] for e in matches))


def _demo():
    import os
    import tempfile

    frame = "Dlvl:2 $:3 HP:0(16) Pw:2(2) AC:6 Xp:1 T:448"
    entry = parse_status(frame)
    assert entry == {
        "t": 448, "dlvl": 2, "hp": 0, "hp_max": 16,
        "pw": 2, "pw_max": 2, "ac": 6, "xp": 1, "gold": 3,
    }
    entry = parse_status(frame + "\npos: 17,29")
    assert entry["row"] == 17 and entry["col"] == 29
    assert "new_coords" not in entry

    entry = parse_status(frame + "\npos: 17,29\nnew_coords: 17,41 17,42")
    assert entry["new_coords"] == [[17, 41], [17, 42]]
    assert classify("The jackal bites!", "m s") == "combat"
    assert classify("j - a spear.", "l") == "loot"
    assert classify("", "s") == "search"
    assert classify("", "m s m s m s") == "search"
    assert classify("", "l") == "movement"
    assert classify("", "l l l") == "movement"
    assert classify("", "Space l l l") == "movement"
    assert classify("", "Space h h h h h h") == "movement"
    assert classify("", "Space m s m s") == "search"
    assert classify("", ". . .") == "rest"
    assert classify("", ". .") == "rest"
    assert classify("", "_ < .") == "travel"
    assert classify("", "_ > .") == "travel"
    assert classify("", "<") == "movement"
    assert classify("", ">") == "movement"
    assert classify("", "Space") == "protocol_violation"  # a lone Space is unaffected by the strip
    assert classify("", "#terrain a") == "explore"
    assert classify("The jackal bites!", "l") == "combat"  # message wins over bare-move keys
    assert classify("You walk quietly.", "y") == "movement"

    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        assert log_turn("", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:1", tmp_path) is None
        assert log_turn("q", "Unknown command 'q'.", tmp_path) is None
        entry = log_turn("Space", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:1", tmp_path)
        assert entry["subgoal"] == "protocol_violation"
        entry = log_turn("m s m s m s", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:2", tmp_path)
        assert entry["subgoal"] == "search" and entry["search_count"] == 3
    finally:
        os.remove(tmp_path)

    # A movement batch that bumps into a wall (T: unchanged from the last
    # logged entry) is reclassified as protocol_violation -- a real tool
    # call spent for zero game progress, same overhead category as a
    # standalone Space. Search must NOT get the same treatment: it always
    # consumes a turn even when it finds nothing, so T: unchanged there
    # would be a bug elsewhere, not a legitimate case to special-case here.
    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        log_turn("l", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:5\npos: 3,4", tmp_path)
        entry = log_turn("l l", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:5\npos: 3,4", tmp_path)
        assert entry["subgoal"] == "protocol_violation"  # T: didn't advance -- wall bump
        entry = log_turn("l", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:6\npos: 3,5", tmp_path)
        assert entry["subgoal"] == "movement"  # T: advanced -- a real move, not flagged
        entry = log_turn("m s", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:6", tmp_path)
        assert entry["subgoal"] == "search"  # search stays search even if T: repeats
    finally:
        os.remove(tmp_path)

    # A 3+ key manual movement batch that reveals nothing new should have
    # used travel (`_`) instead -- SKILL.md's own step 7 rule, now enforced
    # in the log too. A batch that DOES reveal something new is real
    # exploration, not flagged; neither is a short (<3 key) batch, since
    # travel isn't worth the overhead for 1-2 steps.
    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        entry = log_turn("l l l", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:5\npos: 3,7", tmp_path)
        assert entry["subgoal"] == "protocol_violation"  # 3+ keys, nothing new revealed
        entry = log_turn(
            "l l l",
            "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:8\npos: 3,10\nnew_coords: 2,11",
            tmp_path,
        )
        assert entry["subgoal"] == "movement"  # revealed something new -- real exploration
        entry = log_turn("l l", "Dlvl:1 $:0 HP:16(16) Pw:2(2) AC:6 Xp:1 T:10\npos: 3,12", tmp_path)
        assert entry["subgoal"] == "movement"  # only 2 keys -- too short to bother with travel
    finally:
        os.remove(tmp_path)

    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        with open(tmp_path, "w") as f:
            f.write(json.dumps({"dlvl": 1, "subgoal": "movement"}) + "\n")
            f.write(json.dumps({"dlvl": 1, "subgoal": "movement"}) + "\n")
            f.write(json.dumps({"dlvl": 1, "subgoal": "search"}) + "\n")
            f.write('{"dlvl": 1, truncated garbage not json\n')  # must not crash the count
            f.write(json.dumps({"dlvl": 2, "subgoal": "movement"}) + "\n")  # different level, excluded
        real_path = current_log_path
        globals()["current_log_path"] = lambda: tmp_path
        try:
            assert subgoal_breakdown(dlvl=1) == {"movement": 2, "search": 1}
            assert subgoal_breakdown() == {"movement": 1}  # defaults to last entry's level (2)
        finally:
            globals()["current_log_path"] = real_path
    finally:
        os.remove(tmp_path)

    # Same Dlvl:N visited twice (e.g. Mines then main dungeon) -- t_range
    # scopes to one visit instead of conflating both.
    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        with open(tmp_path, "w") as f:
            f.write(json.dumps({"dlvl": 3, "t": 100, "subgoal": "combat"}) + "\n")
            f.write(json.dumps({"dlvl": 3, "t": 105, "subgoal": "combat"}) + "\n")
            f.write(json.dumps({"dlvl": 3, "t": 900, "subgoal": "loot"}) + "\n")
        real_path = current_log_path
        globals()["current_log_path"] = lambda: tmp_path
        try:
            assert subgoal_breakdown(dlvl=3) == {"combat": 2, "loot": 1}
            assert subgoal_breakdown(dlvl=3, t_range=(0, 200)) == {"combat": 2}
            assert subgoal_breakdown(dlvl=3, t_range=(800, 1000)) == {"loot": 1}
        finally:
            globals()["current_log_path"] = real_path
    finally:
        os.remove(tmp_path)

    # current_visit_t_range: dlvl 3 visited, left for dlvl 4, then came back
    # to dlvl 3 -- must find only the LAST run's span, not the first one's.
    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        with open(tmp_path, "w") as f:
            f.write(json.dumps({"dlvl": 3, "t": 100}) + "\n")
            f.write(json.dumps({"dlvl": 3, "t": 105}) + "\n")
            f.write(json.dumps({"dlvl": 4, "t": 150}) + "\n")
            f.write(json.dumps({"dlvl": 3, "t": 900}) + "\n")
            f.write(json.dumps({"dlvl": 3, "t": 905}) + "\n")
        real_path = current_log_path
        globals()["current_log_path"] = lambda: tmp_path
        try:
            assert current_visit_t_range() == (900, 905)  # defaults to tail's dlvl (3)
            assert current_visit_t_range(dlvl=3) == (900, 905)
            # dlvl=4 is a past visit, not the tail -- correctly None, not
            # the earlier (150, 150) run; that's not "the current visit."
            assert current_visit_t_range(dlvl=4) is None
            assert current_visit_t_range(dlvl=9) is None  # never visited
        finally:
            globals()["current_log_path"] = real_path
    finally:
        os.remove(tmp_path)
    print("ok")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _demo()
    elif sys.argv[1] == "--breakdown":
        dlvl = int(sys.argv[2]) if len(sys.argv) > 2 else None
        # Scope to this visit, not every visit ever logged to this Dlvl:N --
        # the same number repeats across branches (Mines vs. main dungeon).
        counts = subgoal_breakdown(dlvl, t_range=current_visit_t_range(dlvl))
        total = sum(counts.values())
        for subgoal, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"{subgoal:20} {n:4}  {n / total:.0%}")
    else:
        keys, output = sys.argv[1], sys.argv[2]
        entry = log_turn(keys, output)
        # Printed here (not just logged) so `run` can surface it the same
        # turn it happened, instead of only being visible later via
        # --breakdown -- confirmed this session: several consecutive
        # movement batches landed as protocol_violation (T: unchanged)
        # and went unnoticed for multiple calls in a row.
        if entry and entry.get("subgoal") == "protocol_violation":
            print(
                f"[turn_log] protocol_violation: {keys!r} batched keys, "
                "T: unchanged -- see SKILL.md threat-ladder rule 3 / travel rule"
            )
