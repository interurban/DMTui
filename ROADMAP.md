# Ward roadmap

Ward is a digital DM screen for an in-person D&D game. The physical table is
authoritative; Ward should remove bookkeeping and lookup interruptions without
trying to become a VTT.

## Priorities

### Phase 1 — Preparation speed

1. **Named encounter templates** — save and reload prepared encounters with
   monsters, positions, default HP, clear conditions, and unrolled initiative.
2. **Campaign scratchpad** — keep a small persistent text area for NPC names,
   clues, loot, passwords, and other session notes.

### Phase 2 — Party awareness

3. **Party reference mode** — compact AC, passive Perception, passive Insight,
   saves, spell DCs, and current HP for quick secret checks.
4. **Better prepared-party workflows** — make campaign loading and encounter
   templates work together without replacing imported character data.

### Phase 3 — Lightweight effects

5. **Timed effects** — add optional round counts to reminders only after
   turn reminders have been used at the table. Keep this manual and explicit;
   do not infer spell durations or automate concentration.

## Deliberate non-goals

- No terrain simulation, line of sight, range enforcement, pathfinding, or AoE
  geometry.
- No player client, networking, full character-sheet replacement, spell-slot
  manager, or encounter-balancing engine.
- No LLM router or agent framework. Chat remains a small lookup box, with local
  SRD data supplying obvious spell context when useful.

## Current status

The table-speed release is complete: DM Screen mode, Quick Numbers, fast
initiative entry, duplicate monster, bloodied state, turn reminders, local
dice commands, and laptop-safe shortcuts are shipped. Phase 1 is now in
progress.
