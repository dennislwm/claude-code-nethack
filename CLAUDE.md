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

During `--init`, you must manually select the character:
pick `v` (Valkyrie), `h` (human), `l` (lawful), `y` (confirm).
The `-p valkyrie` flag in the script does NOT work reliably.

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
- `>` — descend stairs (must be standing on `>`)
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
  anything a plain next action wouldn't already do for free
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
- Monitor HP; retreat when low
- Early enemies (newt, sewer rat, grid bug) are easy for Valkyrie

### Formatting Pitfall
When writing markdown tables that contain the pipe character `|`, always escape it as `\|`. Otherwise the table rendering breaks and the cell appears empty.
