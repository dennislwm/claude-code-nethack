"""Append one JSON line per ./run call to turn_log.jsonl.

Usage: python3 turn_log.py "<keys sent>" "<./run output text>"
"""
import collections
import json
import re
import sys

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
    try:
        with open("game_state/.current_turn_log") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "game_state/turn_log.jsonl"


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
    if entry["subgoal"] == "search":
        entry["search_count"] = keys.split().count("s")
    if entry["hp"] <= 0:
        entry["died"] = True
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


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
    entries = []
    try:
        with open(current_log_path()) as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # one torn/corrupt line must not sink the whole count
    except FileNotFoundError:
        return {}
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
    print("ok")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _demo()
    elif sys.argv[1] == "--breakdown":
        dlvl = int(sys.argv[2]) if len(sys.argv) > 2 else None
        counts = subgoal_breakdown(dlvl)
        total = sum(counts.values())
        for subgoal, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"{subgoal:20} {n:4}  {n / total:.0%}")
    else:
        keys, output = sys.argv[1], sys.argv[2]
        print(log_turn(keys, output))
