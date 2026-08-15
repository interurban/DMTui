# Changelog

Sprint log for the Battle Tracker — a single-screen terminal combat tracker
for D&D 5e DMs (Textual). Run: `.venv/bin/python app.py`.

## SRD spellbook (complete)

The Open5e integration now covers spells, not just monsters — the generic
`srd.py` client meant to grow.

- **`srd.py`** — `spell_to_fields` + `get_srd_spells` convert Open5e v2 spells
  into engine-ready attack strings (`Fireball — 8d6 fire (dex DC 13)`,
  `Cure Wounds — 1d8+2 HP`, `Hold Person — (wis DC 13)`,
  `Magic Missile — 3 darts, 1d4+1 force`). Damage comes from `damage_roll`
  (else scraped from the description), save spells tag the ability, heal spells
  are detected by name, and "N darts" (incl. word forms like "three darts") is
  multiplied. SRD content ships under both `srd-2014`/`srd-2024`, so
  `fetch_raw` now dedupes by name, preferring `srd-2014`.
- **Spellbook UI** — `v` opens `SpellBrowser`, a searchable picker mirroring
  `MonsterLibrary` (large, keep-open, `f` to fetch on demand). Selecting a
  spell appends its attack string to the **selected creature's** `spells` list,
  where it immediately becomes usable in the `a` attack flow.
- Tests: 4 new (spell conversion across damage/heal/save/darts, engine
  resolution, fetch+cache). 58 unit tests + full smoke pass.

## Open5e SRD integration + enhanced monster library (complete)

The tracker can now pull the official D&D 5e System Reference Document from
Open5e and drop those creatures into a fight.

- **`srd.py`** — a generic Open5e v2 client. `fetch_raw` / `get_collection`
  paginate, filter to the freely redistributable SRD documents (`srd-2014`,
  `srd-2024`), and cache results to `.cache/open5e/<name>.json` so a session
  only hits the network once. It is built to grow: future content (spells,
  magic items, conditions, …) slots in by adding an endpoint + a transform.
- **Monster conversion** — `srd_monster_to_fields` maps a raw Open5e creature
  into the same field dicts the rest of the app feeds to `Combatant`: AC, HP,
  size/type role, ability scores, saves, speed, proficiency (derived from CR),
  skills, passive Perception, hit dice, and the detail-card note. Statblock
  action text is parsed into attack lines the engine already understands —
  weapon lines (`Scimitar +4 · 1d6+2 sl`), save-DC spell lines
  (`Fire Breath — 18d6 fire (dex DC 21)`), with plain abilities (Multiattack,
  Nimble Escape, …) falling through to traits.
- **Bigger, faster add-monster UI** — `b` now opens `MonsterLibrary`, a
  near-full-screen searchable picker that merges the 20 hand-authored
  templates (`[built-in]`) with the ~650 SRD monsters (`[SRD]`). Type to
  filter by name/type/source; Enter or `a` adds the pick and **keeps the
  picker open** so several monsters drop in mid-fight without re-opening;
  `f` fetches the SRD library on demand (one-time, then cached); `Esc` closes.
- `app.py` — `_browse_flow` loads the SRD cache (or fetches in the background
  on first open), `_add_monster_entry` routes built-in vs SRD adds, and
  `_spawn_srd` / `_add_combatant` / `_number_name` share the spawn+place+undo
  logic. `.cache/` is gitignored; `VTT_OFFLINE` disables network fetches.
- Tests: 4 new (SRD conversion, fetch+cache round-trip, offline failure,
  engine-resolution contract) — 55 unit tests pass; full smoke passes.

## Map centring + detail card polish (complete)

- Loaded PCs now land in the middle of the map: `_place_pc` spirals outward
  from the grid centre, so a party clusters mid-map, spread a cell apart,
  instead of hugging the top-left corner. Boot waits for the map grid to
  reach its real size first (`_wait_map_ready`) so centred placement doesn't
  race the initial layout.
- Detail card: weapon damage types spelled out in full — "1d8+2 piercing",
  not "pie".
- Detail card: the `SKILLS` label dropped from the skills row.
- Smoke: the blocked-move check no longer assumes top-left boot geometry; it
  parks Lyra directly above Zephyr first.

## Detail card note + smoke suite fixes (complete)

- The DDB import note no longer re-lists ability scores — the detail card
  already shows them; it now reads "Wood Elf Ranger 7. Imported from
  D&D Beyond."
- The campaign smoke scenario had never run green. Three fixes: the second
  campaign-menu open pressed `shift+c`, which never matched `Binding("C")`
  (now presses `"C"`); the load-order assertion ignored that a save preserves
  party order (Lyra leads after her init-30 sort); and a manual combatant
  wipe before `ctrl+n` skipped the confirm modal and broke the undo/redo
  assertions that followed.
- 51 unit tests + full smoke pass.

## Second review fix pass (complete)

A second comprehensive review by two fresh staff developers (engine + parser,
and TUI + smoke). Full findings live in `REVIEW.md` under "Review pass 2".
Tests went 32 → 41; every fix below is locked in with a regression test:

- "Healing Word" (and Regenerate, Healing Spirit, …) now heals — the heal
  regex missed the "healing" word prefix and *damaged* its target instead.
- DDB hit-dice sort was a no-op (sorted tuples, not die sizes); output is now
  stable largest-die-first regardless of key order.
- Spells: save hints now work even with no dice (Hold Person logs the save);
  heals can't be halved by a save hint; only an explicit "N darts" multiplies.
- Downed targets log "is already down" instead of "already at max HP".
- The round always advances on `n`, even when everyone is dead (scan wrap).
- A missed attack no longer pushes a phantom undo entry.
- Undoing a load/reset/new-encounter fully restores the previous world
  (round + turn), not a hybrid; redo re-applies it symmetrically.
- Load pushes its undo entry only after a successful restore.
- `ctrl+p` palette binding added (was advertised, never bound).
- `@AA1`-style Excel coordinates now work in `find`.
- Battle log capped at 200 messages; map no longer clips on small terminals.
- DDB import: flat damage bonus no longer double-counted into to-hit, negative
  to-hit renders cleanly, heavy armour ignores DEX, non-JSON bodies wrapped.

## Review fix pass — comprehensive code review (complete)

Two staff developers reviewed the whole codebase (engine + parser, and the
TUI + smoke suite). Full findings and per-item rationale live in `REVIEW.md`.
Everything below was fixed in this pass and locked in with regression tests
(tests 19 → 32):

- Combat engine: critical hits no longer double the flat damage bonus;
  spell resolution handles save DCs (half damage on a save), heals
  (Cure Wounds heals instead of hurting), and multi-dart lines (Magic Missile).
- Reset actually resets: `build_encounter` clones the shared singletons per
  call, so `r` no longer hands back the objects you were damaging.
- Round counter advances when the dead-skip scan wraps past the current turn
  (previously the turn could strand on a skipped creature / sole survivor).
- Undo/redo revert combatant state without rewinding the turn or round.
- Fixed a real crash: `s` referenced an undefined `SAVE_PATH` (the smoke test
  monkeypatched it, hiding the bug).
- Map no longer clips its bottom row (header + `MAP_ROWS` rows off-by-one).
- Full map returns `None` instead of the occupied `(0,0)`; spawn/import/add
  log a warning and skip. `coord_name` continues Excel-style past `Z`.
- Heal/damage reject non-positive amounts and log the applied (clamped) delta.
- Import shows a blocking modal while the fetch runs; DDB parsing hardened
  (None spell definitions, unordered stats dicts, string armor ids, trusted
  `attackBonus`, multi-die hit dice, clamped removed HP, wrapped network
  errors).
- Save/load validates structure; missing `stats` in a hand-edited save no
  longer crashes the detail card; help is a plain sync action.

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
## Round 3 + UX pass (complete)

- **Inline damage/heal entry** — `d`/`h` arms entry; digits in status row; Enter applies, Esc cancels, Backspace edits. Replaces `_run_number`/`_make_number_modal`/`_number_flow`. Regression tests: `test_resolve_spell_regenerate_without_hp`, `test_resolve_damage_spell_mentioning_hp_is_not_heal`, `test_resolve_spell_zero_darts_not_multiplied`, `test_resolve_crit_multi_die_no_bonus`.

- **Enter = attack** — Opens attack-with list (same as `a`); in entry mode applies the number.

- **`r` = roll init, `shift+r` = reset** — `r` rolls monster initiative; `shift+r` resets HP/conditions/inits to round 1. Old `r` = reset removed.

- **Detail card spacing** — blank lines after AC/vitals row, after Skills row, before note.

- **Map tokens centered** — `_map_cell` centers glyph in cell; `short_label` caps at 3 chars.

- **Battle log flip + help hint removed** — `_log_text` newest-on-top; `_refresh_log` `scroll_home`; `_log_status_text` drops `? help`.

- **Modal centering + sizing** — `ModalScreen` `center middle`; `.modal-box` width 57; `#modal-list` height 15; HelpModal keys updated.

- **Campaign system** — default "My Campaign" seeded with `[91566422, 112516506, 90060446]`; `campaigns.json` `gitignored`; `C` key opens menu (load/save/blank); app remembers last active campaign.

- **Tests**: 10 regression tests added; total 51 pass.

- **`ctrl+p`** now maps to `command_palette`.
