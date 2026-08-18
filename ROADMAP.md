# Ward roadmap

Ward is a private, table-side tool for the Dungeon Master in an in-person D&D
game. It remembers volatile state, preserves campaign continuity, and retrieves
references without trying to simulate the game. The DM's rulings and physical
table are authoritative.

## Product moments

Ward is organized around three moments rather than a growing feature catalog:

1. **Resume** — reopen the exact encounter that was interrupted, with its round,
   turn, HP, conditions, reminders, and spatial notes intact.
2. **Run** — keep the common table loop fast: initiative, turns, HP, conditions,
   quick rolls, and glanceable references.
3. **Prepare** — manage campaign parties and notes, reusable monster setups, and
   named encounter history without changing the fight currently on the table.

## Current focus — trust and table validation

- **Complete: campaign continuity.** Campaigns own parties, notes, a lookup
  preference, and any number of Current/Paused/Complete encounters.
- **Complete: preparation.** Reusable monster setups combine with the selected
  campaign party without becoming played encounters themselves.
- **Complete: DM references.** DM Screen and Party Reference are read-only,
  glanceable views that do not replace character sheets or rulings.
- **Complete: backup and recovery.** A portable Ward backup contains campaigns,
  parties, notes, played encounters, and reusable monster setups; restore first
  preserves the data it replaces.
- **Complete: table ambience.** Optional soundtrack controls use a replaceable
  stream catalog and a narrow external-player boundary rather than binding Ward
  to a music service.
- **Next: real-session observation.** Use Ward at several physical tables and
  record which actions interrupt play, which shortcuts are remembered, and
  which screens go unused. Simplify from evidence before adding automation.

## Deferred until table use proves the need

- **Timed reminders.** Optional round counts may be useful, but Ward will not
  infer spell durations, automate concentration, or advance effects on the
  DM's behalf.
- **Rules-reference variants.** The campaign's 2014/2024 preference currently
  guides optional lookups only. Ward must not imply rules enforcement unless a
  genuinely edition-specific reference earns its place.

## Deliberate non-goals

- Ward is not a VTT: no terrain simulation, legal-move system, line of sight,
  range enforcement, pathfinding, area geometry, or remote player view.
- No player client, networking, full character-sheet replacement, spell-slot
  manager, or authoritative encounter-balancing engine.
- The token map is only a quick note mirroring the physical table.
- Encounter-assistant pressure labels are rough suggestions for DM review, not
  calculated balance or a promise of difficulty.
- No LLM router or agent framework. Optional assistance remains a small lookup
  and catalog-only suggestion surface.
