# Code review — findings & fixes

Two comprehensive read-only review passes, each by two staff developers (one
on `battle.py` / `ddb.py` / `tests.py`, one on `app.py` / `modals.py` /
`widgets.py` / `smoke.py`). Both reviews verified the full test + smoke suites
pass before reviewing. Findings are ordered by severity; everything was fixed
in the same pass and locked in with regression tests.

## Review pass 2 — findings & fixes

### Critical

- None.

### Major

### M1. "Healing Word" wasn't detected as a heal
`battle.py:_HEAL_RE` — `\bheal\b` requires a word boundary after "heal", so
"Healing Word" (and "Regenerate", "Healing Spirit", …) never matched and
**damaged** its target instead of healing. Only "Cure Wounds" was covered by
tests, so it slipped through pass 1.
**Fix:** match word prefixes — `\b(heal\w*|cure\w*|restore\w*|mend\w*|regain\w*|hit points|hp)\b`.
`test_resolve_spell_healing_word` locks it in.

### M2. The DDB hit-dice sort was a no-op
`ddb.py` — `sorted(hd.items(), key=_int)` passed each `(die, count)` *tuple* to
`_int`, which swallowed the type error and returned the `0` default, so every
key sorted equal and order was dict-insertion order. The multi-hit-dice test
passed only because its fixture happened to insert `"8"` first.
**Fix:** `key=lambda kv: -_int(kv[0])` (largest die first). A regression test
feeds the dict smallest-first and asserts stable `"3d8, 2d6"` output.

### Minor

- **Save-DC spells with no dice dropped the save** — save parsing lived inside
  the dice-only branch, so "Hold Person — (Wis DC 15)" reported a bare `damage
  0` with no save. The save block now runs for any spell hint (not just those
  with dice), and `_apply_attack_result` reports saved/failed even at 0 damage.
- **A heal carrying a `(Con DC N)` hint got halved** on a "successful" save.
  The save branch is now guarded with `not healing` — heals are never halved.
- **`N darts` matching was too loose** — `N ×`/`N times`/`0 darts` multiplied
  dice too. Scoped to an explicit `darts?` keyword with `N > 1`.
- **Downed/dead targets logged "is already at max HP."** — the `applied == 0`
  early-return hardcoded a heal message. Now branches on the delta sign
  ("already at max HP" vs "is already down").
- **`action_next_turn` never advanced the round with everyone dead** — the
  `nxt <= start` wrap only fired when the scan ended on a living creature.
  Now also `or scanned == n` when the scan exhausts the whole list. Smoke
  covers it (kill everyone, `n` still ticks the round).
- **A missed attack pushed a phantom undo entry** — `_apply_attack_result`
  pushed undo unconditionally, so a miss / 0-damage spell / full-HP heal left
  a no-op entry and cleared redo. Now only pushes undo when HP actually
  changed. Smoke asserts the undo stack is untouched after a nat-1 miss.
- **Undoing a load produced a hybrid state** — combatants reverted but the
  *loaded* round/turn stuck around. Snapshots now carry a `restore_nav` flag:
  world-replacing ops (load, reset, new encounter) restore round/turn on undo;
  plain mutations keep the current navigation. The flag propagates through
  undo *and* redo symmetrically. Verified by pilot (undo reverts round 99 → A,
  redo re-applies A).
- **`action_load` pushed a redundant undo entry when restore failed** — the
  undo snapshot is now taken first and only pushed after a successful restore.
- **`ctrl+p` palette was advertised but never bound** — the message bar and
  help listed it; nothing handled it. The binding is now added.
- **`find` couldn't parse Excel-style coordinates** — `@AA1` failed the
  single-letter parser. `_parse_coord` mirrors `coord_name` for arbitrary
  column lengths.
- **`_messages` grew unboundedly** — capped at 200 entries.
- **Small terminals clipped the map** — `MAP_ROWS` floored at 5 rendered more
  lines than a short map widget holds. Floor lowered to 1 so rendering always
  matches available rows.
- **Heal spells logged the un-clamped amount** — a target 2 HP from max
  "restored 12 HP". The log and undo now use the clamped applied delta.

## DDB import hardening (pass 2, all tested)

- **The flat damage bonus was double-counted in the to-hit default** — without
  an explicit `attackBonus`, to-hit was `stat + prof + dmg_bonus`; a
  `damageBonus: 3` Greataxe showed `+8 · 1d12+6`. In 5e the flat damage bonus
  doesn't help you hit, so the default is now `stat + prof` (`+5 · 1d12+6`).
- **Negative to-hit rendered `"+-2"`** (and `_ATK_RE` folded the stray `+` into
  the weapon name) — now `f"{to_hit:+d}"` → `"Cursed Blade -2"`.
- **Heavy armour applied a negative DEX penalty** (`min(dex_mod, 0)`); 5e
  heavy armour ignores DEX entirely. Now `+0` for `dex_cap == 0`.
- **A 200 with a non-JSON body** raised a raw `JSONDecodeError`; now wrapped in
  a friendly `ValueError`.

## Deliberately not changed (pass 2)

- **`_restore` re-maps the turn by name on keep_nav** — duplicate PC names
  resolve to the first match on undo. In practice names are unique; the risk is
  a silent turn jump, never a crash.
- **Undo of a move restores grab mode** (`_moving` back on) — arguably
  intended: you're still holding the token.
- **`CombatantRow` overflows at very narrow widths** — a `name_w` floor of 8 at
  an 80-column terminal; cosmetic, out of scope.
- **`action_help` double-wrapping / `_restore` index validation** — pass 1
  already fixed these; pass 2 confirmed no regression.

## Review pass 1 — findings & fixes

### Critical

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