# NetHack Navigation Skill

Move safely through the dungeon without silent stalls or unintended travel,
and handle any monster/HP-risk moment without an unattended batch costing HP.

Trigger: always, on every `./run --init` (start of a new game) — this is
mechanics, not a per-goal check. Also on the user's word "explore" or similar
(e.g. "keep exploring", "continue"), before the first movement/travel key of
any new exchange, sending more than ~3 movement keys unverified, any use of
`_` (travel), any monster sighted/adjacent/attacking or killed, right after
taking stairs (`>`/`<`) — the neighborhood grid is for the old level until
re-read — or the moment a hostile/unconfirmed-area reason for manual
stepping ends (killed, fled, or area now confirmed explored): re-check
whether travel (rung 7) is now the right mode, rather than continuing
manual stepping out of habit carried over from the caution that just
ended. Confirmed this session: an entire multi-tile traverse through
already-explored ground was walked manually, step by step, purely because
manual mode was already in use from an earlier hostile encounter, not
because it was still the right choice. Also right before pressing `>` to
leave a level — see "Before descending" below.

Why: see memory entries `nethack_navigation_travel` and `nethack_stuck_input_diagnosis`.

## Procedure

1. **Know where you are before moving.** Use the last `./run` output's
   position, or run `/,m` (or `/,/` — nudge the self-cursor one step and back
   to read your own tile's coordinate — works even while invisible).
2. **Before moving, use the `far:` line's count for your intended
   direction** (e.g. `far: N=0 E=6 ...`) — it's computed by the tool, not
   hand-counted off the printed grid (don't count grid cells by eye; the
   padding makes manual counts unreliable). Move exactly that many keys, up
   to the wall/door/edge it reports. Only fall back to blind ≤3-key batches
   when the state isn't confirmed clean. Check all 8 directions at every
   corridor step — branches don't announce themselves.
3. **After any move, check the `new:` line before doing anything else.**
   Any offset listed there was just revealed by that exact move — chase it
   next, before searching, before continuing in the original direction.
   Unlike `frontier:` (a snapshot of what's still unexplored, re-checkable
   any time), `new:` reports a one-time reveal and is gone once the next
   move overwrites it — ignoring it wastes information the move already
   paid for. Cost this session: `new: S1 S1E1` was reported and not acted
   on, leading to ~15 more turns of unrelated dead-end searching before
   backtracking to follow it.
   Priority when more than one applies: `new:` first (perishable), then
   `frontier:` (persistent, free), then `frontier_scan.py` only once both
   are empty/blocked (see rung 5 below).
   `frontier: X (unexplored)` is a candidate to try, not a confirmed
   opening — a blank tile is genuinely unknown until walked into, and can
   turn out to be solid rock. Confirmed this session: `frontier: N1
   (unexplored)` with `far:N=0`/`paths:N=blocked` (both correctly refusing
   to call an unrevealed tile passable) turned out to be rock — walking
   `k` into it produced no move, no message, no turn cost. Unverified
   hypothesis, not measured: the higher `frontier_scan.py`'s `coverage:` %
   climbs, the more of these dead-end candidates should show up relative to
   real openings, since real openings tend to get found earlier (closer to
   already-explored ground). Don't treat that as a threshold to code
   against — it's a reason to expect more misses late in a level, not a
   rule for when to stop trying.
4. **After any batch or submenu use (`/,m`, `/,o`, `_`, `#terrain`), verify
   before continuing.** If a frame repeats unchanged, run
   `tmux capture-pane -p -t claude-nethack | tail -3` for a stuck `--More--`
   or other prompt FIRST — before re-checking with another `/,m` or similar,
   which can itself open a new prompt and restart the confusion. Trust
   `/,m`'s reported coordinate, the label line, and the `far:` line over
   hand-reading the printed grid — all three are computed by the tool from
   the same cursor position, while eyeballing the grid's padded text is
   unreliable. In a clean state the grid center is always the player by
   construction.
5. **A dead-end-looking corner may just be a monster glyph on the tile** —
   before concluding a wall/dead-end, check whether a stationary monster is
   sitting on that square and look past/through it. If it's a mold/lichen
   (brown mold `F` and similar), don't melee it either way — they deal
   automatic damage back to any melee attacker regardless of whether your
   attack lands; route around, or clear it with a ranged attack (thrown
   weapon, wand, spellbook) instead.
6. **Walking a room's perimeter, watch every wall tile passed, not just the
   4 corners** — a `#terrain` glimpse or a few blocked-move attempts don't
   confirm a room is closed. Three distinct anomaly shapes, all easy to
   walk right past mid-sweep without stopping to test them: (a) a glyph
   substitution — `-` caps top/bottom walls, `|` caps left/right walls
   (per CLAUDE.md's Map Symbols), so the wrong one appearing on a given
   edge is the tell; (b) a **length mismatch** — a wall row ending shorter
   than the floor row it caps means that column has no wall glyph at all,
   not a substituted one, and is just as easy to miss since it looks like
   the wall simply "ran out"; (c) a tile visible **past** a confirmed-solid
   wall — NetHack's line of sight shows corridors beyond a wall you can't
   walk through, and it's easy to only look at the wall glyph itself and
   the floor on your own side, never what's rendered a tile or two further
   out on the far side. Confirmed this session: (a) on a room's west wall
   (mid-row, not a corner) turned out to be a genuine passable opening
   leading to a new encounter and new territory; (b) at a room's top-right
   corner (`---|---------` capping a 1-column-wider `|............#`
   below it) turned out to hide an unexplored corridor stub; (c) a
   corridor sitting one tile past a room's east wall, visible several rows
   down in the printed grid, went unnoticed because the wall itself tested
   solid and nothing further out was checked. None were caught during the
   original sweep, only later by eye on a rendered map. Test any such tile
   in the moment (walk onto it if reachable, or verify with `#terrain`
   which strips objects/monsters and shows raw wall data), not deferred to
   a final pass before marking the room done. Often it's just an
   irregular room shape, not a door — confirm rather than assume either
   way, but confirm at the time, not later. **When a 10x search still
   concludes empty, check the `frontier:` line already printed that same
   turn before moving to anything else** — unlike `frontier_scan.py`'s
   full-map offset (a straight-line guess), this one is BFS-derived and
   names a real, walkable step, computed for free whether or not it gets
   read. Confirmed this session: `frontier: N1 (unexplored)` was already
   correct at a dead end that had just failed a 10x search, and went
   unwalked while the conversation moved on to unrelated topics — the
   tooling had the right answer, it just wasn't checked at the moment the
   search concluded.
   Same rule applies to `frontier: ... (closed door)` — it means unexplored
   space is still reachable through that door, so don't treat the room or
   level as done, and don't take stairs, while one is still standing there
   unopened. Unlike the two cases above, `frontier:` is recomputed on every
   single call, not a one-time reveal — the gap isn't urgency, it's that a
   closed-door reading can sit on-screen for several consecutive turns while
   attention is on something else (loot, combat, reaching stairs) and never
   get read at all. Confirmed this session: `frontier: N1W3 (closed door)`
   was printed for several turns while navigating toward `>`, and was never
   opened or even acknowledged before starting the pre-descent checkpoint.

   Before leaving any room or area (not just before taking stairs — that
   has its own extra check, see "Before descending" below), run this
   checklist — each row is a distinct way "explored" turns out to be
   premature, seen this session:

   | check | what "done" looks like |
   |---|---|
   | Room coverage | every room/corridor in the area visited at least once — check `#terrain a`'s full map for a room or passage never walked into, not just the ones on the route out. Prerequisite for the rows below: they're only meaningful applied per-room, not just at the room you're leaving from. `helper/frontier_scan.py`'s `coverage: NN% (band)` line is a fast heuristic for "roughly how much is left" (below `max`, i.e. >50%, expect more to find) — not a substitute for the `#terrain a` eyeball check, since it counts any non-blank cell, including a room already seen through a still-closed door. |
   | `frontier:` | `none (fully enclosed/explored within radius)` at every room's perimeter, not just the one you're standing in — a `closed door` reading means unexplored space is still reachable |
   | Perimeter anomalies | every wall tile walked, not just corners — the three anomaly shapes above (glyph substitution, length mismatch, tile visible past a "solid" wall) |
   | Known doors, level-wide | `all_doors`/`all_closed_doors` from `helper/cursor_probe.py` (rung 5, "Fastest way to reach a target") checked at least once after `#terrain a` — a door far from your current position doesn't show up in the local `frontier:` box at all |
   | Loot | every corpse/item tile stepped onto and read via "Things that are here", not just `/,o`'s map-relative list — see memory `nethack_checklist` step 1 |

   A kill message and a dropped-item glyph on the vacated tile are also a
   loot event, distinct from the room-exit pass above — confirmed this
   session: a mummy's `[` drop was visible in the same output as "You
   destroy the gnome mummy!" and went unchecked because the next move
   headed straight for an unrelated frontier instead. Check the drop
   (walk onto it and read "Things that are here", or explicitly decide to
   skip it) before the next move, not deferred to the room-exit checklist.

   Any weapon or armor pickup is also an equip-decision moment, not just a
   loot event — check it the same turn, not deferred. Compare against what's
   currently wielded/worn (base damage die and weight for a weapon, AC and
   weight for armor) and either wield/wear the upgrade (`w`/`W`) or explicitly
   decide to keep the current gear (e.g. an enchanted weapon can beat an
   unenchanted one with a better base die — enchantment isn't visible until
   worn/wielded or identified, so this is a judgment call, not something to
   compute and defer). Confirmed this session: a dwarvish spear was picked up
   and logged, then never compared against the wielded +1 spear — it sat in
   inventory unused for the rest of the level.
7. **Using `_` (travel):**
   - Only confirm with `.` when the cursor's description line names an
     explored, reachable tile you actually intend to reach (not "unexplored
     area ... (no travel path)").
   - If the cursor lands on an unexplored/unreachable tile, do not confirm —
     dismiss with `Space` instead, then re-verify per step 3 before resuming
     movement (confirming there does not fail safely; it can silently
     fall back to a different remembered target).
   - To reach the edge of an unexplored area: travel-confirm to the nearest
     explored tile/coordinate right next to it, then walk the final 1-2
     steps manually into the unexplored space.
   - Prefer travel over manual stepping for any multi-tile move through
     already-explored ground. This rule already existed and still got
     violated for an entire level: `turn_log.py --breakdown` on Dlvl:1
     showed `_` used exactly once in 431 turns — a `far:`/`paths:` count
     of 3+ through known ground is the same signal every time, but seeing
     it printed isn't the same as acting on it. Before sending 3+ manual
     movement keys through ground already on the map, stop and use `_`
     instead — don't treat this as covered just because the words exist.

## Fastest way to reach a target

Given a target tile, use the cheapest rung that applies:

1. **Already adjacent to it** — just step onto it, no travel command needed.
2. **Explored, with a known map symbol** (stairs, altar, fountain, a door) —
   open `_`, press the symbol to jump the cursor to the nearest match, but
   **confirm the description line names the specific tile you mean** before
   pressing `.` — pressing a symbol can jump to the *wrong* instance when
   more than one is known (e.g. two altars, two doors).
3. **Explored, no distinct symbol** (a plain floor coordinate) — open `_`,
   move the cursor there with movement keys, confirm with `.` only once the
   description line names that explored tile.
4. **At or beyond the edge of explored territory** — travel-confirm to the
   nearest explored tile adjacent to it, then walk the final 1-2 steps
   manually. Never confirm directly on the unexplored target itself — see
   step 6's caveat, confirming there can silently teleport you to an
   unrelated remembered destination instead of failing safely.
5. **Local box fully enclosed** (`frontier: none`, `paths:` all blocked) —
   before spending turns on blind searching, check the whole level at once:
   open `#terrain` then `a` (known terrain only), then run `frontier_scan.py`
   against that capture (not a `./run` keystroke — `python3 helper/frontier_scan.py`)
   to list every passable tile on the level adjacent to unexplored space,
   nearest first, each printed as a walkable N/S/E/W offset from `@` (e.g.
   `S2E14`) — a full-map version of `nearest_frontier`, which only looks in
   the local box and forgets what it saw once you walk elsewhere. Finds in
   one call what walking and 10x-searching every dead-end in turn does not.
   **The offset is a straight-line distance, not a walking instruction** —
   don't chase its diagonal (e.g. move NE because the label reads `N4E3`);
   check `far:`/`paths:` for which cardinal direction is actually open at
   each step, the same as any other move (cost 3 wasted wall-bumps this
   session).
   Empty result: fall back to `all_doors`/`all_closed_doors` from
   `helper/cursor_probe.py` (`import sys; sys.path.insert(0, "helper");
   import cursor_probe as cp; cp.all_doors(map_lines, cp.parse_colors(pane))` /
   `cp.all_closed_doors(map_lines)`) for the door-specific view. Walk to the
   nearest useful tile found. A tile tagged `[searched Nx]` (from this
   game's own turn log) is sorted last, not removed — search is
   probabilistic, so a high count is a low-priority lead, never a
   zero-priority one; still worth a shot once other leads run out.
   This count (and the `turns on this level:` line) is already scoped to
   the *current* visit to the current Dlvl:N, not every visit ever logged
   — Dlvl:N repeats across branches (e.g. once in the Mines, once in the
   main dungeon), so an unscoped count would silently mix an earlier
   branch's searches into this level's tally. No extra step needed; the
   CLI does this automatically from the log itself.
   The same run also prints `by direction: N=.. S=.. E=.. W=.. -- least
   explored: X` — check this before treating a whole side of the map as
   done, not just the nearest-tile list above (this session's stairs-down
   miss, see rung 6's loop-vs-dead-end note, sat behind exactly the
   direction this line would have flagged).
6. **No travel path at all, even to a nearby tile** (fully walled off) —
   is this really a dead end, or just where I stopped looking? Search for
   hidden passages before manual walking further.
   A corridor that seems to loop back into already-known territory is a
   different question than a wall — has it actually been walked to its
   real end, or dismissed as "just a loop" partway through? Confirmed this
   session: a branch judged as looping back turned out to lead straight to
   the level's stairs down a few tiles past the point where it was given
   up on — "loops back" and "dead end" aren't the same conclusion until
   the branch is walked all the way.
   A boulder blocking the route is a different obstacle, not rock. "In
   vain" means the tile the boulder would land ON is blocked (wall,
   monster, another boulder/item, or unplugged water/lava) — not that the
   direction itself is bad; the same direction can push it successfully
   several times in a row, then suddenly fail once it rolls into a tile
   with an obstruction ahead, which is new terrain showing up, not the
   direction going stale. Has it actually been pushed from every open
   angle, or does one failure read as the route being blocked?
   Weapons never work on a boulder, melee or thrown — it isn't a monster,
   there's no attack prompt. If pushing is genuinely exhausted from every
   angle, check inventory for an item before giving up on the route: a
   wand, engrave with it (`E` + its letter) first to check charges — "too
   worn out to engrave" means empty, no need to waste a real zap finding
   that out — a working wand of striking or teleportation reliably clears
   it (striking shatters it, teleportation moves it elsewhere like any
   item), and polymorph is worth a try but only sometimes
   destroys/transforms it; wand of digging does *not* work on boulders
   despite digging through rock generally, don't waste a charge testing
   that. A pick-axe (or dwarvish mattock): `w` to wield it first (merely
   carrying one doesn't trigger a dig prompt), then `a` + its letter + the
   boulder's direction — shatters it into rocks (sometimes a gem). A
   stone-to-flesh spell also works, turning it into a movable chunk of
   meat. None available: treat the route as blocked for now and go
   around — but is "for now" still true, or was that decided before the
   last unwalked branch got checked?

## Threat ladder (any monster encounter or HP-risk moment)

Read top to bottom — stop at the first rung that applies.

1. **Check hostility before engaging.** `/,m` any monster whose hostility is
   unclear before moving toward or into it. Peaceful — never attack (moving
   into it prompts an attack-confirmation; accepting costs alignment/god
   favor for no benefit). Route around it instead (diagonal or alternate
   direction).
2. **Treat heavy hitters and stealers as special-handling targets, not a
   trade-blows-in-melee default.** Two distinct dangers, same rule because
   both call for the same fix (range, not proximity):
   - *Heavy hitters* (damage risk): rothes deal 3 attacks/turn, 10-20+
     damage per exchange — far more than gnomes/dwarves/gnomish wizards.
     Anything hitting double-digit damage per turn: disengage well above
     50% HP, not after already critical. Don't assume safety from species
     name alone — a kitten once hit for 3-5 repeatedly and crashed HP
     14->9 in a single 3-turn batch.
   - *Stealers* (permanent-loss risk, not damage): nymphs (`n`) steal a
     carried item and teleport away on a successful hit against you;
     leprechauns (`l`) do the same with gold. The theft triggers on any
     successful hit against you, so proximity itself is the risk. Low HP
     threat, high item-loss threat: worth killing from range
     or simply avoiding rather than trading blows to "just kill it quick."
   While either type is still in line of sight and not yet adjacent, fire
   on it (`f`, quivered ammo, launcher wielded) or throw (`t`) before
   closing to melee — a wielded launcher sitting in inventory doesn't help
   if the fight is already hand-to-hand by the time it's remembered.
   Confirmed this session: a rothe (explicitly a heavy hitter per this same
   rule) was walked straight into melee with a bow, arrows, a crossbow,
   bolts, a sling, and throwable daggers all in inventory the whole time —
   none were used. This isn't "always shoot before melee" for every
   monster (wastes ammo and turns against anything trivial); it's specific
   to these two flagged cases.
3. **Never batch multiple turns once a hostile is adjacent, known alive
   nearby, or has attacked this exchange.** This is the rule that actually
   got Claude killed (Dlvl:2, T:448: a 20-keypress force-search batch while
   a jackal was mid-attack ran to HP 0 before the output was even checked).
   The rule is about the batch itself, not the specific key — it applies
   equally to search (`s`), wait (`.`), travel (`_`), and repeated movement.
   Send exactly 1 action per tool call and check the HP shown in the
   response before sending the next one, until the threat is dead or
   confirmed gone via `/,m`. A "not currently adjacent" melee monster can
   still close the distance within a single multi-turn batch, so this
   applies doubly to resting/waiting to regen HP: cap each batch to 3 turns
   and check `/,m` before continuing, even when nothing is known nearby.
4. **Last resort at critical HP: `#pray`** (confirm the `[yn]` prompt with
   `y`). Can trigger full HP restoration via divine intervention (confirmed
   once: deity Tyr, HP 1->53). Legitimate emergency action, not a routine
   tactic — prayers can be refused if overused or if alignment/luck is poor.

## Entering a shop

Trigger: a peaceful `@`-glyph monster in a room full of stacked item glyphs
(`*`, `)`, `%`, `!`, `?`, `=`, `(`, `]`, `/`, `"`) — that's a shopkeeper's
store, not a random NPC encounter.

| check | what to do |
|---|---|
| Hostility | confirm peaceful via `/,m` (threat ladder rung 1 — don't re-derive this, just apply it here too). The shopkeeper blocks their own doorway tile and won't swap there (see memory `nethack_shopkeeper_invisible`) — route through a different row/column if blocked, don't force it. |
| Rations | check your own food inventory (`i`) *before* buying — only worth spending on food if actually low/out, and only if the price is affordable right now. Confirmed this session: 0 food carried, 30 gold on hand, cheapest ration in stock was 60 zorkmids — correctly skipped rather than a reflex buy. |
| Necessities | read the full `/,o` listing (not just what's visible on-screen) specifically for a pickaxe or other tool you're missing, before leaving — don't assume it's there or not there from a glance. |
| Prices | invisible until you stand on the item ("You see here a cyan potion (for sale, 27 zorkmids)") or `#chat` while on it — there's no price list, each stack has to be walked individually. |

## Before descending (`>`)

Run step 6's pre-leaving checklist in full FIRST, before any coverage/turns
judgment — descending is a case of "leaving an area", just the whole-level
kind, and the checklist is what surfaces the concrete facts the judgment
below needs. Skipping straight to the coverage number and deciding from that
alone is the exact failure this section exists to prevent (confirmed this
session: doing that led to a real, avoidable descend — the checklist's
`all_doors` row turned up 8 known open doors on the level, all flagged
`adjacent_unexplored`, that a bare `coverage: 46%` reading gave no visibility
into at all).

Next — this is a checkpoint for the level about to be left, not something
to redo per room, and it belongs here, before the decision below, not
after it: a mandatory step placed after the decision paragraph reliably
gets skipped once the decision is already reached (confirmed this session:
the checklist and the weigh-cost judgment below were both done, "descend"
was decided, and this step never ran at all). Run
`python3 helper/turn_log.py --breakdown` (defaults to the current level) and check
**every** subgoal it prints, not just whichever one was debt last time —
which subgoal is actually a problem varies level to level (a maze-like
level might rack up search-debt instead of the protocol_violation/travel
pattern seen on Dlvl:1). The CLI ranks by raw count, not by "debt-ness" —
a small count can still be 100% waste. Read each line against its
direction:

| subgoal | debt direction |
|---|---|
| `protocol_violation` | high = bad, always (pure overhead, see step 7's `_` note on when a standalone `Space` is unavoidable vs. not) |
| `travel` | near-0 = bad *if* the level had long explored corridors (reverse debt, see step 7's last bullet) — near-0 on a tiny level is fine |
| `other` | high = a `classify()` gap, not player debt — means something is silently uncategorized again, worth a code fix, not a play-habit fix |
| `search`, `combat`, `loot`, `explore`, `movement` | context-dependent — no fixed direction; judge against what the level actually contained (e.g. high `search`% on a level with few hidden doors found is debt, the same % after cracking open three vaults isn't) |

The level is already fully explored by this point — you can't go back and
fix its turns. The only output that matters is: carry one concrete
adjustment into the next level, not a retrospective on this one. Skip this
entirely if the level was a quick pass-through with too few turns to be
meaningful.

With the checklist's actual findings in hand, then weigh cost:
- A concrete lead from the checklist (an `all_doors`-flagged
  `adjacent_unexplored` door, a `frontier: ... (closed door)`, a `new:` not
  yet chased) beats any turns-based argument — these are known, located
  targets, not the diffuse "some % is still blank" signal `coverage:` gives.
  Go get them regardless of turns already sunk.
- Only once the checklist comes back clean (no concrete leads left, just
  `frontier: X (unexplored)` candidates that may well be rock — see step 3)
  does the turns-vs-coverage tradeoff apply: weigh coverage
  (`helper/frontier_scan.py`'s `coverage:` line, or the same in
  `game_view.html`) against turns already sunk on this level
  (`sum(helper/turn_log.py`'s `subgoal_breakdown(dlvl).values())`, or the
  `T:` delta since arriving). A shrinking coverage band per turn spent with
  no remaining concrete leads is a diminishing-returns signal — chasing the
  last slice of a level costs the same turns (hunger, time, risk) whether
  that slice holds a vault or three more dead-end rock pockets, and there's
  no fixed number of turns where that trade flips (a made-up threshold here
  would be exactly the kind of unmeasured number rejected for the
  frontier/coverage correlation earlier — don't add one). Judgment call: if
  turns-on-level is already large and coverage has been climbing slowly,
  that's a reason to descend below `max`; if turns-on-level is still low,
  low coverage is just "haven't looked yet," not debt.

Before actually pressing `>`, chain 5 whys from "why descend now" down to a
concrete fact from the checklist/retrospective above, not a feeling —
each answer should cite a number or a named finding, not "seems done."
Example chain: why descend? standing on `>`. why is that enough? coverage
is in the `high`/`max` band. why not push the remaining gap? the frontier
tiles flagging it are already searched past the 10x exhaustion bar. why
trust those are dead ends? the same search method already found real
hidden doors elsewhere this level, so it isn't failing to find things.
why stop rather than search more? turns already sunk here are large and
climbing coverage slowly, per the turns-vs-coverage tradeoff above. If the
chain bottoms out on an assumption instead of a fact ("probably nothing
left," "should be fine") — that's the checklist not actually being clean;
go finish it before deciding, not after.

Only once the retrospective above has actually run and the checklist is
clean does pressing `>` follow — not before either one.

## After descending (arriving on a new level)

The pre-descent checklist governs the level you just left; it says nothing
about the one you just landed on. Right after arriving — before the first
exploration move — check `^X` and read the "You are in/on ..." line: it's
the only way to tell the Gnomish Mines from the Dungeons of Doom, since the
status bar's `Dlvl:N` reads identically in both (see "No stairs down
anywhere on this level" below for why this matters mid-Mines-climb too).
Confirmed this session: two Mines levels in a row got explored for a
"second staircase down" before `^X` was checked, because the previous
level's `>` not being a `branch staircase down` was wrongly treated as
proof the new level itself must be main dungeon.

## No stairs down anywhere on this level (fully explored)

This is a level/branch problem, not a tile-reaching problem — the ladder
above doesn't cover it. The Gnomish Mines dead-end (their lowest level has
no stairs further down, per the guidebook); reaching that point is normal,
not a sign of missed exploration. Before concluding a level is a dead end:

1. Confirm via `#terrain` that no `>` exists anywhere on the known map (not
   just the local box).
2. If truly none, climb back up (`<`) through the levels you came from
   toward the branch point — the one main-dungeon level with **two** down
   staircases, one continuing the main dungeon and one branching into the
   Mines. Take the other staircase to keep progressing instead of treating
   a Mines dead end as a reason to stop or resign.
   The status bar's `Dlvl:N` reads identically in both branches — it
   cannot tell you which one you're on. After each climb, check `^X`
   ("You are in the Gnomish Mines, on level N" vs "You are on level N
   of the Dungeons of Doom") before assuming that level is the branch
   point — confirmed this session: a level one climb above a Mines
   dead end was still Mines, not yet the branch, and got explored for a
   nonexistent second staircase before `^X` caught it.
