# Claude Code Plays NetHack

## Mission
Explore the dungeon, descend levels, survive. Current goal: reach Dungeon Level 2+.

## How to Play

### Running the Game
- `./run --init` — start a fresh game (kills existing session)
- `./run` — view current game state (no input sent)
- `./run h j k l` — send commands (west/south/north/east)
- `./run --cleanup` — kill the tmux session
- `tmux attach -t claude-nethack` — attach live with native NetHack keys
  (read-write, unlike `./run`'s scripted input). Detach with `Ctrl-b` then
  `d` — this leaves the session and game running. Only `--cleanup` (or
  `tmux kill-session -t claude-nethack`) actually ends the game.

`--init` creates the character non-interactively via `run`'s
`NETHACK_COMMAND` (`nethack -u Claude-Val-Hum-Fem-Law`) — no manual
selection keys needed; the game never shows an interactive role/race/
alignment menu when the `-u` name-suffix form is used, so sending `v h l y`
does nothing useful (they'd be read as ordinary game keys instead).
If `--init` ever produces the wrong role/alignment (or a "welcome **back**"
message instead of "welcome to NetHack"), suspect a stale save for
character name "Claude" first, not the flag: `nethack -u name` silently
*restores* any existing save for that name instead of creating a new
character, regardless of the role/race/alignment suffix — check
`find "$(dirname "$(which nethack)")/../share/nethack/save" -iname '*Claude*'`
(or wherever this install's `nethack` shares saves) and delete a stale one
before retrying. Confirmed this session: two consecutive `--init` runs both
silently resumed the same stale Neutral-alignment T:1 save instead of
creating a fresh Lawful character, with no error or prompt indicating a
restore had happened.

### Output Format
`./run` prints two things when the game map is visible:
1. **Original map** — standard NetHack ASCII display + status bar
2. **Neighborhood of @** — a 13x13 visual grid around `@` plus a labeled line listing all 8 adjacent cells (e.g. `NW=. N=< NE=\| W=. E=. SW=. S=. SE=.`), followed by three computed lines:
   - `far:` — open-floor tile count in each of the 8 directions before hitting a wall/door/edge
   - `frontier:` — nearest unexplored tile or closed door within the grid, as a direction+distance from `@` (or `none` if the area is fully enclosed/explored)
   - `paths:` — a compressed route (direction+count segments, `+` marks a door) to reach the grid's edge in each of the 8 directions, or `blocked`

   See the `nethack-navigation` skill (`.claude/skills/nethack-navigation/SKILL.md`) for how to use these instead of hand-counting the grid.

When the screen shows text (inventory, `/` query results), the neighborhood is suppressed.
While invisible (no `@` glyph rendered), the neighborhood grid is replaced with a
one-line last-known position (from the most recent `/,m` or `/,o` call) instead of
disappearing outright — use `/,m` or `/,o` to refresh it.
A `--- Text Panel ---` section means a modal menu/pager is open: the game ignores
movement keys until you close it with `Space` or `Escape`.

### Reading the Output
- **Neighborhood line**: the quickest way to check adjacent cells — read `NW=` `N=` `NE=` etc. directly
- **13x13 grid**: for wider spatial context (6 cells in each direction)
- **Original map**: for full-map W/E and N/S awareness and overall layout

### Key Commands
- `h j k l` — move W/S/N/E
- `y u b n` — move NW/NE/SW/SE
- `o` + direction — open a door
- `C-d` + direction — kick (breaks open a locked door reliably; `#force`
  exists too but its `[y/n]` confirmation can get declined)
- `s` — search for hidden doors/passages (repeat multiple times). If a
  monster is in view (including your own pet), repeating `s` stops early
  with "You already found a monster. Use 'm' prefix to force another
  search." — prefix each repeat with `m` (e.g. `m s`) to force it anyway.
  **The `m` prefix means "force it anyway," not "safe to batch anyway"** —
  a batched `m s m s m s...` while a hostile is adjacent is exactly the
  batch the nethack-navigation skill's threat-ladder rule 3 forbids (it's
  cost Claude real HP more than once, since a room-search habit built up
  over many monster-free searches doesn't self-interrupt when one finally
  shows up in the same neighborhood grid). Check `/,m` first if anything
  is visible before sending a forced-search batch.
- `,` — pick up item
- `e` — eat (prompts for what; use this for corpses, not `,` which only
  picks the item up)
- `>` — descend stairs (must be standing on `>`). `./run` refuses to send
  `>` at all unless `NETHACK_CHECKLIST_DONE=1` is set on that call (e.g.
  `NETHACK_CHECKLIST_DONE=1 ./run '>'`) — run the nethack-navigation
  skill's "Before descending" checklist first, every time, not just when
  something feels off. **Two `>` on the same level is not a bug or a
  render glitch** — the Guidebook documents it as expected on an early
  level (typically Dlvl 2-4): one continues the main dungeon, the other
  branches into the Gnomish Mines, and they look identical until you
  descend one and check with `^X`. A Mines level is often substantially
  harder than a main-dungeon level at the same Dlvl (its monster
  selection can ignore normal difficulty capping) — enter around
  character level 5-6, not at level 1, unless there's a specific reason
  to go earlier. See References below.
- `S` — save and quit
- `.` — wait one turn
- `i` — inventory
- `/` — look at things (opens a submenu, see below)
- `#name` — extended command, e.g. `./run '#quit'` (Enter is sent automatically)
- `^P` — message history, one message back per press: `./run '^P'` or `./run C-p`
  (use after batched moves to catch messages that scrolled by, e.g. what hit you)
- `Space` — dismisses "--More--" prompts, but `./run` already sends it
  automatically before your keys whenever you pass at least one argument
  (a no-op when nothing's pending) — **don't send it yourself**, chained or
  standalone; a call whose only argument is `Space` no longer does
  anything a plain next action wouldn't already do for free.
  **This auto-`Space` is only a safe no-op before `--More--`/text-panel
  prompts, never before a `[yn]` confirmation** — a `[yn]` prompt treats
  `Space` as an actual answer (accepting the shown default, not ignoring
  it), so it silently resolves the prompt before your real key arrives.
  Confirmed this session: `./run S` then a separate `./run y` moved the
  player instead of confirming the save, because the second call's
  auto-`Space` had already answered "n" to "Really save? [yn] (n)". Any
  action that opens a `[yn]` prompt (`S`, `#force`, some `#loot`/kick
  flows) must send its answer in the **same** `./run` call as the
  triggering key (e.g. `./run S y`), never a follow-up call.
  **The character-creation reroll menu (`NETHACKOPTIONS=reroll`, `--init`)
  is a second exception, not just `[yn]` prompts** — sending `p`/`r`/`n`
  through `./run` (any real key, since it always auto-`Space`s first)
  corrupts the menu into a degraded one-shot `[yn]` prompt instead of the
  real repeatable "p - start / r - reroll" menu. Confirmed this session:
  `./run p` to accept a roll produced exactly this collapse. Use raw
  `tmux send-keys -t claude-nethack "<key>"` for every key during the
  reroll menu instead of `./run` — only switch back to `./run` once the
  game has actually started (the "Velkommen..." intro line has appeared).
- `Escape` — cancel a command (fails with "client is read-only" if a
  read-only tmux viewer is attached — use the next real action instead,
  which dismisses via the automatic `Space` above)
- `w` + letter — wield a weapon (needed for a launcher: bow/crossbow/sling)
- `x` — exchange primary/alternate weapon
- `Q` + letter — set quiver (preferred ammo for `f`)
- `f` — fire quivered ammo in a direction (launcher must be wielded)
- `t` — throw any item by hand (prompts for item, then direction)
- `#adjust` + count + letter — split a stack into a new slot (e.g. to
  light/use only one item, not the whole stack)
- `_` — travel: opens a cursor, steer it with movement keys or a map
  symbol, confirm the destination with `.` (or cancel with `Space`/`Escape`)
- `#terrain` + `a` — show all known terrain on the level (strips
  objects/monsters), e.g. `./run '#terrain' a`

**Both `_` and `#terrain` leave the game in a cursor/modal state that
intercepts the *next* command if not explicitly closed first.** Confirmed
this session: sending plain movement keys (`h`, `j`, ...) right after one of
these moved an invisible cursor instead of the player — the printed map and
position looked plausible, but `T:` (turn count) stayed frozen, the only
tell. Always follow `_`/`#terrain` with an explicit `.` (confirm) or
`Space`/`Escape` (cancel) before sending any other command, and if a batch
of moves ever shows an unchanged `T:`, suspect this first.

### The `/` (Look) Command
Use `./run '/' <option>` to query the map. Options:
- `o` — nearby objects (e.g. `./run '/' o`)
- `O` — all objects shown on map
- `m` — nearby monsters
- `M` — all monsters shown on map
- `i` — something you're carrying
- `?` — identify a symbol by typing it

Output shows items/monsters with their map coordinates. Dismiss with `Space`.
Use this regularly for situational awareness instead of building custom tools.

### Map Symbols
- `@` — player (Claude)
- `d` / `f` — pet (dog / cat)
- `.` — floor
- `#` — corridor
- `-` — horizontal wall
- `\|` — vertical wall (NOTE: escape as `\|` in markdown tables!)
- `+` — closed door
- `<` — stairs up
- `>` — stairs down (descend target)
- `$` — gold
- `?` — scroll
- `!` — potion
- `)` — weapon
- `[` — armor
- `%` — corpse / food
- `{` — fountain/sink/boulder (context glyph, not an item — walking onto one
  and trying `,` prompts "You could drink the water..." instead of a pickup;
  `#dip` a **long sword specifically** here for a lawful Valkyrie's
  Excalibur chance (1/6 per dip, needs level 5+, no effect on any other
  weapon type — check inventory for one before planning around this),
  `#quaff`/dip-self is high-risk and mostly skipped)

## Gameplay Knowledge

### Character: Always Pick Valkyrie
- Excellent starting stats (18+ Str, 18 Con, 16 HP)
- Strong melee combat from the start
- Tourist is terrible — weak weapon, low survivability

### Dungeon Exploration
- Every game has a randomly generated layout; never assume previous maps apply
- Explore systematically: clear each room, follow every corridor
- Use `s` (search) repeatedly near walls to find hidden doors/passages
- Look for wall discontinuities (`.` symbols breaking `---` patterns)
- Open doors render as `-` or `|` (matching passage direction), nearly identical
  to wall glyphs in monochrome — scrutinize walls for out-of-place characters
- Small starting rooms often have hidden exits — search all walls

### Combat
- Move into enemies to attack (automatic melee)
- Pets help fight and eat corpses
- Monitor HP; retreat when low — "low" means well above half max, not
  down at 1 HP; decide to disengage before it's forced
- Early enemies (newt, sewer rat, grid bug) are easy for Valkyrie
- Look up an unfamiliar monster (`/,?`) before engaging, not after
- Let the pet step onto an unidentified item first — its reaction (or
  lack of one) is a free, safe cursed-item check

### Formatting Pitfall
When writing markdown tables that contain the pipe character `|`, always escape it as `\|`. Otherwise the table rendering breaks and the cell appears empty.

## References
`docs/GuideBookv5.0.0.md` is the official rules reference (mechanics,
commands) — grep it first for any mechanic question. It doesn't cover
community strategy (role builds, survival heuristics, branch-difficulty
comparisons); for that, check `docs/wiki/*.md` (saved copies of the pages
below) before fetching the live page from nethackwiki.com.
- [Difficulty](https://nethackwiki.com/wiki/Difficulty) — how dungeon-level difficulty gates monster/room generation
- [Monster difficulty](https://nethackwiki.com/wiki/Monster_difficulty) — the per-monster 1-57 difficulty rating
- [Gnomish Mines](https://nethackwiki.com/wiki/Gnomish_Mines) — Mines vs. main-dungeon danger, Minetown, entry timing
- [Valkyrie](https://nethackwiki.com/wiki/Valkyrie) — role-specific early strategy
- [Standard strategy](https://nethackwiki.com/wiki/Standard_strategy) / [Why do I keep dying?](https://nethackwiki.com/wiki/Why_do_I_keep_dying) — general early-game survival
- [Identification](https://nethackwiki.com/wiki/Identification) — engrave-testing, BUC-testing, price-ID
- [Elbereth](https://nethackwiki.com/wiki/Elbereth) — engraving to make most monsters flee; who ignores it, what erases it
