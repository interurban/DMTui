# Changelog

Sprint log for the Battle Tracker — a single-screen terminal combat tracker
for D&D 5e DMs (Textual). Run: `.venv/bin/python app.py`.

## Sprint F — Polish + monster library (complete)

Finished off the tool:

- Split the monolith: `app.py` 1663 → 1114 lines. `modals.py` (prompt/help
  screens + the new `MonsterBrowser`), `widgets.py` (initiative row, token
  map, scroll containers), `ddb.py` (import parsing, from Sprint E). `MapGrid`
  duck-types the app, breaking the import cycle.
- Monster library doubled: 10 → 20 templates (Bandit, Bandit Captain,
  Giant Rat, Gnoll, Harpy, Kobold, Owlbear, Specter, Troll, Zombie).
- `b` monster library: searchable picker — type to filter live, Enter adds a
  single match or hands you to the list. Spawning now shares `_spawn_monster`.
- README (run, key map, dev, layout) + `requirements.txt` (textual>=8.2).
- Tests: 19 (all templates well-formed via `encounter_monster`, unique names).
  Smoke adds a browser scenario (filter → add Troll → undo).

## Sprint B — Editability + encounter building (complete)

Made the encounter yours to build:

- `e`: edit the selected creature — name, max HP (current HP clamps), AC,
  initiative mod, role, note, and all six ability scores. Mods/saves in the
  detail card recompute live. Undo-safe (snapshot pushed before the change).
- `p`: add a PC from a name prompt — default stats (10s), AC 10, HP 10,
  auto-placed on a free map spot and selected. Multiple PCs work everywhere
  (import, add, attack, initiative).
- `ctrl+n`: new blank encounter (confirm-first when creatures exist) —
  undoable and redoable like every other change.
- Help text + detail hint bar updated (`e edit` now in the hints; `x remove`
  is behind its confirm).

## Sprint C — Undo + persistence (complete)

Made mistakes cheap and sessions durable:

- `u` / `shift+u`: undo/redo with full-state snapshots (HP, conditions,
  position, initiative, adds/removes, round, turn, selection), capped at 50.
  Every mutating action pushes a snapshot: damage/heal, attacks, movement,
  condition toggles, initiative roll/set, add monster, import, remove, reset.
- `x` removal now asks for confirmation before removing a creature.
- `s` / `l`: save the whole session to `encounter.json` and load it back —
  HP, positions, conditions, round, turn all survive a restart.
- Fixed a real bug: JSON round-trips turned `stats`' integer keys into strings,
  which broke ability mods/saves after a load.
- Help text + log-status hints updated for undo/save/load; `encounter.json`
  added to `.gitignore`.
- Tests: 13 unit (new JSON round-trip regression), smoke extended with
  confirm-remove, undo/redo, and save/load scenarios.

## Sprint A — Dice + attack resolution (complete)

Made the stat blocks real instead of decorative:

- `battle.py`: `roll_dice()` parses expressions like `2d6+3`; `resolve_attack()`
  rolls a weapon (`d20 + bonus` vs AC, nat 20 crits and doubles damage dice,
  nat 1 always misses) or a spell (first dice expression found is rolled).
  `Combatant.spells` field added; `Goblin Shaman` template + encounter monster
  "Mog".
- `app.py`: `a` key opens an attack flow — pick weapon/spell, pick a living
  target, resolve, and log the result (`Dent: Longsword → 18 vs AC 18 — hit
  for 7 damage (3 +4)`). Kills log a death line and drop concentration.
  Injectable `self._rng` for deterministic tests.
- `tests.py` (new): 12 unit tests for dice + resolver + map helpers.
- `smoke.py`: attack scenario added; full suite passes (`SMOKE OK`).

## Earlier — Core tracker (baseline)

- One-screen 2×2 grid: token map (adaptive columns/rows on resize), initiative
  order with HP bars/AC/condition chips, battle log, rich combatant detail card
  (stats, saves, skills, passive perception, attacks, spells, traits).
- Turn/round cycling with dead-combatant skipping; initiative roll/set + sort;
  damage/heal (±1 quick keys + amount modal); condition toggles; monster
  templates; click/grab/place movement with collision checks; find (name / role
  / @coordinate); D&D Beyond import (unofficial endpoint, best-effort parse);
  reset; help; per-panel command hints.

## Next

- No planned sprints — the tool is feature-complete. Ideas if it grows again:
  monster stat blocks in the detail card, condition-tied map colours,
  turn timer / encounter notes.