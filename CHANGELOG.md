# Changelog

Sprint log for the Battle Tracker — a single-screen terminal combat tracker
for D&D 5e DMs (Textual). Run: `.venv/bin/python app.py`.

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

- **C: Undo + persistence** — undo stack (HP/conditions/removal), confirm on
  `x`, save/load encounters to disk.
- **B: Editability + encounter building** — edit combatant fields, blank/new
  encounter, add PC with stats, multiple PCs.
- **E: Tests + import hardening** — normalize DDB parsing against realistic
  payloads, split the monolith.