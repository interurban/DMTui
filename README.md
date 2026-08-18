# Ward

A private, table-side control surface for an in-person D&D game. Ward remembers
volatile encounter state, keeps campaign continuity, and retrieves quick
references without trying to simulate the game. The DM's rulings and physical
table remain authoritative.

![Ward encounter screen](shots/01-start.png)

Built with [Textual](https://textual.textualize.io/).

## Run

```sh
python -m venv .venv
.venv/bin/pip install -e .
ward
```

The editable install provides `ward` and `python -m ward`. The former `dmtui`
command and module remain compatibility aliases. Running
`.venv/bin/python app.py` still works from a checkout.

`?` opens the in-app key guide. `CHANGELOG.md` is the sprint log; `REVIEW.md`
documents both staff code-review passes and every fix that came out of them.
`ROADMAP.md` tracks the prioritized next features and explicit non-goals.

The optional `/` lookup and `Shift+E` encounter assistant use the OpenAI model
configured in `llm_config.json`. For local secret storage, copy `.env.example` to `.env`
and add your key:

```sh
cp .env.example .env
```

Then edit `.env`:

```env
OPENAI_API_KEY=sk-your-key-here
```

`.env` is ignored by Git. You can also provide the key through the shell:

```sh
export OPENAI_API_KEY="sk-your-key-here"
```

The app loads `.env` automatically when it starts.

Ward is organized around three moments: **Resume** an ongoing fight, **Run**
what tonight needs, or **Prepare** a campaign and its future encounters. On a
fresh install, Ward offers campaign setup, a ready-to-run sample, or a standalone
empty encounter. Campaign setup asks for a name and party; each party member can
be a D&D Beyond URL, character ID, or plain name. Returning launches put the
last active encounter first and keep specialist preparation tools inside the
campaign folio.

Played encounters are remembered automatically in the ignored
`campaign-encounters.json`; there is no manual save step. Each campaign keeps
its own encounter index. Starting another fight pauses the campaign's current
encounter instead of replacing it, so ten fights can be named, browsed, and
resumed independently. The startup screen resumes the most recently active
fight; **Campaigns** opens any campaign without silently starting one.

A campaign is the long-running game. It owns its party roster, lookup reference
preference, and notes in the ignored `campaigns.json`. A roster entry may be a D&D Beyond
character (refetched when a new encounter starts) or a manually named
adventurer (started from editable defaults). `Shift+C` opens the active
campaign during play. Editing the campaign party never rewrites the encounter
already on the table; it takes effect the next time that campaign starts an
encounter. Conversely, encounter damage, conditions, and edits stay in that
fight and do not silently rewrite the campaign roster.

`Shift+C` opens the campaign folio. It puts resume/new-encounter actions first,
then groups encounter preparation, campaign details, backup/recovery, and
campaign switching. The encounter index sorts **Current** first,
then **Paused**, then **Complete**, with round, creature count, and last-updated
date. Selecting an encounter offers resume, rename, or mark complete. Resuming
a completed encounter reopens it and pauses the previous current fight.

Choose **Ward data** from the campaign folio to export campaigns, parties,
notes, played encounters, and reusable monster setups into a portable JSON
backup under `ward-backups/`. Ward can restore any listed backup and first
creates a safety backup of the data being replaced. The same restore option is
available on an otherwise empty first-run screen when backups exist. These
files are ignored by Git; copy important backups outside the checkout for
protection from checkout loss, and to another disk or storage service for
protection from disk loss.

Older single-resume `encounter.json` files migrate automatically as a named
**Recovered encounter** the first time the new encounter store is opened.

Press `Shift+E` to ask the optional encounter assistant for a monster lineup.
The preview may include a rough pressure signal informed by the loaded party,
but it is explicitly not encounter balancing. The DM judges suitability, and
accepted creatures always resolve to existing built-in/SRD statblocks.

For reference, the tracked `llm_config.json` contains only non-secret settings:

```json
{
  "model": "gpt-4o-mini"
}
```

Campaign details can hold a 2014 or 2024 **rules reference** preference. It
guides optional lookups only; Ward does not enforce either ruleset or alter the
encounter engine around it.

### Soundtrack streaming

Press `Shift+P`, or choose **Music** from the campaign folio, to start, pause,
resume, stop, or change the table soundtrack. Ward stays silent until the DM
starts a stream and stops its player when Ward exits.

The tracked `ward/music_config.json` is the starter catalog and replaceable
boundary:

```json
{
  "backend": "auto",
  "volume": 55,
  "sources": [
    {
      "name": "Drone Zone",
      "url": "https://somafm.com/m3u/dronezone.m3u",
      "note": "Atmospheric textures with minimal beats · SomaFM"
    }
  ]
}
```

Add, remove, or replace source entries without changing Python. `auto` prefers
`mpv` and falls back to `ffplay`; set the backend explicitly to either name if
needed. Set `WARD_MUSIC_CONFIG=/path/to/music.json` to keep a personal catalog
outside the checkout or override the packaged default. Sources are passed to
the player as arguments, never through a shell.
The starter station is SomaFM's permanent external-player playlist for
[Drone Zone](https://somafm.com/dronezone/directstreamlinks.html), offered for
individual personal listening. Streaming is disabled with `WARD_OFFLINE=1`.

### DM Screen mode

Press `Ctrl+2` to replace the four encounter panels with a fixed, glanceable
5e reference: combat quick rules, conditions, quick numbers, and DC/roll
guidance. Press `Ctrl+3` for Party Reference: current HP, AC, passive checks,
saves, spell DCs, and PC conditions/reminders. Press `Ctrl+1` to return to the
encounter, or `s` to cycle through all three modes. Bare `Tab` and function keys
are left to normal terminal/desktop behavior. The references are intentionally
read-only; the physical table remains authoritative.

The small token map is a spatial note that mirrors the physical table. It does
not calculate range, movement, terrain, line of sight, areas, or legal actions.

### D&D Beyond imports

Character imports use D&D Beyond's character-service endpoint. If the battle
log reports access denied or HTTP 403, open that character in D&D Beyond,
change its privacy to **Public**, save it, and retry the import. The importer
cannot parse a character when D&D Beyond denies the service request.

### Preparation tools

Use `Ctrl+E` to save or start a prepared encounter. Prepared encounters are
reusable monster setups, not played fights: they store only monsters and
starting positions. Starting one creates a new campaign-owned encounter copy
with the campaign party, leaving both the template and previous fight intact.
Monsters return at full HP with clear conditions and unrolled initiative.
Older templates that contain PCs are loaded safely—the embedded PCs are ignored.

Monsters added from the quick picker or searchable library are scattered across
the top-centre of the map's first four rows, keeping newly imported enemies
visible and easy to distinguish from the party.

Press `Shift+C` and choose the active campaign's notes to keep NPC names, clues,
loot, passwords, or anything else useful between sessions. `Ctrl+Enter`
remembers the notes; `Esc` cancels.

## Keys

| Key | Action |
| --- | --- |
| `↑`/`↓` or `k`/`j` | select previous/next creature |
| `←`/`→` | −1/+1 HP |
| `g` | grab a token (arrows place it, `g`/`Esc` drops) |
| `n` | next turn |
| `Enter` / `a` | attack with the selected creature |
| `d` / `h` | damage / heal (amount prompt) |
| `0`–`9` / `Backspace` | type or edit an inline damage/healing amount |
| `c` | toggle a condition |
| `m` / `Ctrl+m` / `b` / `Shift+m` | quick add / browse the searchable monster library |
| `v` | spellbook — browse the SRD and add a spell to the selected creature |
| `x` | remove the selected creature (asks first) |
| `r` / `t` | roll monster initiative / set a creature's initiative |
| `Shift+i` | enter initiative for each unrolled PC in sequence |
| `+` | duplicate the selected monster at full HP |
| `Shift+r` | reset the encounter (undoable) |
| `i` | import a PC from a D&D Beyond URL |
| `p` | add a PC from a name |
| `Shift+p` | open soundtrack controls |
| `e` | edit the selected creature (name, HP, AC, init mod, role, note, scores) |
| `Shift+e` | ask for a catalog-only encounter suggestion with rough pressure guidance |
| `f` | find a creature by name or map coordinate (`@B3`, `@AA1`) |
| `u` / `Shift+u` | undo / redo |
| `s` | cycle Combat → DM Screen → Party Reference |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | open Combat / DM Screen / Party Reference |
| `Shift+c` | open the active campaign, party, and notes |
| `Ctrl+n` | name and start another encounter; keep the current one saved |
| `Ctrl+e` | save/start prepared encounters |
| `/` | ask the OpenAI DM assistant |
| `/roll 2d6+4` | roll dice locally without using OpenAI |
| `q` / `?` | quit / help |

## Attacks & spells

Weapon lines (`Longsword +7 · 1d8+4 sl`) roll `d20 + bonus` vs the target's AC;
a natural 20 crits (dice doubled, the flat bonus once) and a natural 1 always
misses. Spells are best-effort: `(Dex DC 12)` hints give the target a saving
throw (half damage on a success) and are still rolled for no-damage control
spells (e.g. Hold Person), heal/cure/regain spells restore HP instead of
dealing damage (save hints never halve a heal), and `3 darts` lines
(Magic Missile) roll the dice three times.

`/roll 2d6+4` and `/r 1d20+7` roll locally without contacting OpenAI. Other
`/` questions use the optional DM assistant with a small encounter context;
cached SRD spell details are added only when the question clearly names a
spell.

## Dev

```sh
.venv/bin/python tests.py   # unit tests (pure logic + imports)
.venv/bin/python smoke.py   # headless UI drive-through, screenshots in shots/
```

`requirements.txt` remains available for older checkout-based setups; new
setups should use `pip install -e .` so the launcher and dependency metadata
stay together.

## Open5e SRD content

Press `Ctrl+m` (or `b`) to open the monster library and `v` to open the spellbook. Both merge
the hand-authored templates with the official D&D 5e **System Reference
Document**, fetched from [Open5e](https://open5e.com) on first use and cached to
`.cache/open5e/`. The first open fetches in the background (needs network, once);
subsequent opens are instant. SRD creatures/spells are converted into the same
statblocks the rest of the app uses, so they're indistinguishable in play. Set
`WARD_OFFLINE=1` to disable all network fetches. `VTT_OFFLINE` remains a
compatibility alias for older setups.

- `srd.py` is the generic client — `fetch_raw` / `get_collection` paginate and
  cache any Open5e v2 collection, so other content (magic items, conditions, …)
  can be added by supplying an endpoint + transform.


## Layout

- `app.py` — the `BattleApp` TUI: bindings, flows, rendering, CSS.
- `battle.py` — data model (`Combatant`), dice engine, attack resolution,
  monster library, the starting encounter.
- `campaigns.py` — campaign, party roster, lookup preference, and notes persistence.
- `encounter_store.py` — named campaign encounters, status, current pointers,
  atomic persistence, and legacy migration.
- `music.py` / `ward/music_config.json` — replaceable stream catalog and
  external-player boundary.
- `ward_backup.py` — portable Ward data backups and validated recovery.
- `ward/` — the installed `ward` command and module entry point.
- `ddb.py` — D&D Beyond character-service parsing (`extract_combatant`).
- `widgets.py` — initiative row, token map, scroll containers.
- `modals.py` — number/list/text prompts, the help screen, and the import
  busy-modal.
- `dm_screen.py` — the fixed, glanceable 5e quick-reference panels.
- `ROADMAP.md` — prioritized future work and product boundaries.
- `REVIEW.md` / `CHANGELOG.md` — staff review findings + fixes, sprint log.
