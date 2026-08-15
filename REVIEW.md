# Code review — findings & fixes

Comprehensive read-only review by two staff developers (one on
`battle.py` / `ddb.py` / `tests.py`, one on `app.py` / `modals.py` /
`widgets.py` / `smoke.py`). Both verified the full test + smoke suites pass
before review. Findings below are ordered by severity; everything was fixed in
the same pass and locked in with regression tests.

## Critical

- None.

## Major

### M1. `action_next_turn` could strand the turn on a dead/skipped wrap
`app.py` — the round only incremented when the *raw* next index wrapped to 0.
When the dead-skip scan wrapped past index 0 (e.g. the sole survivor is before
the current turn), the round never advanced and the turn could land back on a
dead creature.
**Fix:** increment the round after the scan: `if nxt <= start: self.round += 1`.
Verified in smoke (undo/redo section asserts turn/round survive undo).

### M2. Critical hits added the flat bonus twice
`battle.py:resolve_attack` — a nat-20 on `1d8+4` rolled `2×(1d8) + 8` instead of
`2×(1d8) + 4`. `tests.py` enshrined the wrong value (16 instead of 12).
**Fix:** on crit, re-roll the dice expression with the `[+-]N` suffix stripped
so the bonus is added once. `test_resolve_crit` now asserts `12`.

### M3. `build_encounter` returned the shared module singletons
`battle.py` — `PARTY + ENCOUNTER_MONSTERS` handed the *same* objects to every
caller, so `r` (reset) returned the exact monsters you'd been damaging; HP and
conditions never actually reset.
**Fix:** `build_encounter` deep-clones per call. Regression test mutates one
call's result and asserts the next call is untouched.

### M4. Spell resolution was too naive
`battle.py:resolve_attack` — spells always hit, always dealt damage: save-DC
spells never offered a save, heal spells ("Cure Wounds — 1d8+2 HP") *damaged*
their target, and "3 darts" lines (Magic Missile) rolled once instead of thrice.
**Fix:** spells now parse a `(Dex DC 12)` hint and grant the target a save
(half damage on success, logged as saved/failed), heal/cure/regain keywords
restore HP instead (applied in `_apply_attack_result`), and `N darts`/`N ×`
lines roll the dice expression N times. Covered by four new unit tests.

## Minor

- **`find_free_spot` returned an occupied `(0,0)` on a full map** — now returns
  `None`; spawn/import/add-PC callers log a warning and skip. Test added.
- **Map bottom row was clipped** — `MAP_ROWS = grid.size.height` but the map
  renders a header line + `MAP_ROWS` data rows. Now `height - 1`.
- **Heal/damage modals accepted non-positive amounts** and logged the *requested*
  rather than *applied* delta (a heal on a full-HP target logged "recovers 5").
  Amounts ≤ 0 are rejected; logs now use the clamped applied delta.
- **Undo rewound the turn/round** — undo of a damage reverted navigation too.
  `_restore(snap, keep_nav=True)` now reverts combatant state while preserving
  the current round/turn; load still applies the saved round/turn.
- **`action_save` crashed**: `SAVE_PATH` was referenced but never defined
  (the smoke test monkeypatched it, masking the bug). Now defined in `app.py`.
- **`coord_name` overflowed past `Z`** at 30 columns. Now Excel-style (`AA1`).
- **`_spawn_monster` numbering** counted `Goblin Boss`/`Goblin Shaman` as
  `Goblin` spawns (prefix match) and could double-assign a name. Now counts by
  exact name / trailing number.
- **`_restore` stats backfill** — a hand-edited save with no `stats` produced a
  `None` mod and crashed the detail card. Stats default to 10s; the saves row
  also renders `(—)` instead of crashing.
- **`_import_flow` had a ~15s interactive window** during the background fetch —
  keystrokes could leak into the live encounter. A blocking `ImportingModal` is
  shown while the fetch runs.
- **`hp_frac` crashed on `max_hp = 0`**, **`short_label` on an empty name** —
  both guarded.
- **`encounter_monster`** double-bound `**over` on known keys (`max_hp`, `ac`,
  `conditions`, …). Now built from a base dict with explicit copies.
- **`_remove_flow`** left `_sel` desynced from the advanced turn. Synced.
- **`action_load`** didn't validate structure — non-dict/corrupt saves crash or
  silently no-op. Now validated and wrapped.
- **`action_help`** double-wrapped itself (async action → run_worker → flow).
  Now a plain synchronous push.

## DDB import hardening (all tested)

- Spell entries with a `None` `definition` crashed the parser.
- Multi-die `hitPointDice` produced `"3d88"`-style concatenation → now
  `"3d8, 2d6"`.
- `stats` dicts (string keys, arbitrary order) were read by insertion order →
  now sorted by ability id.
- `armorTypeId` arriving as a string broke shield/armor detection → coerced.
- Magic weapons: an explicit `attackBonus` is trusted over the computed bonus
  (avoids double-counting the flat damage bonus).
- Negative `removedHitPoints` pushed `hp` above `max_hp` → clamped.
- `urlopen` raising `URLError`/`OSError`/`TimeoutError` leaked raw exceptions →
  now wrapped in `ValueError`; non-dict payloads rejected.

## Deliberately not changed

- **Weapon-like lines missing their `+N` bonus** still fall through to the spell
  branch and auto-hit. Every shipped template is well-formed (enforced by
  `test_monster_templates_are_well_formed`), so this only affects hand-authored
  data. Documented rather than special-cased.
- **Spells resolve against a single target**; multi-target/friendly-fire and
  spell slots are out of scope for this tracker.
- **`_number_flow` rejections** (e.g. damage 0) log a warning; the user can
  retry or Esc out.