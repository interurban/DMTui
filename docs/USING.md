# Using Ward

The full key reference and feature guide. The in-app guide (`?`) shows the same
bindings live.

## Keys

Ward is keyboard-first. Each panel footer shows only the commands most useful
there. Shortcut letters are highlighted inside their action labels; `Ctrl` and
symbol shortcuts stay explicit.

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
| `m` / `Shift+M` | quick add / browse the searchable monster library |
| `b` | spellbook — browse the SRD and add a spell to the selected creature |
| `-` | remove the selected creature (asks first); enters a negative value while editing initiative |
| `r` / `t` | roll monster initiative / set a creature's initiative |
| `Ctrl+T` | enter initiative for each unrolled PC in sequence |
| `+` | duplicate the selected monster at full HP |
| `Ctrl+R` | reset the encounter (undoable) |
| `i` | import a PC from a D&D Beyond URL |
| `p` | add a PC from a name |
| `Ctrl+K` | open soundtrack controls |
| `e` | edit the selected creature (name, HP, AC, init mod, role, note, scores) |
| `Ctrl+G` | ask for a catalog-only encounter suggestion with rough pressure guidance |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo |
| `s` | cycle Combat → DM Screen → Party Reference |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | open Combat / DM Screen / Party Reference |
| `Ctrl+O` | open the active campaign, party, encounters, and notes |
| `Ctrl+N` | name and start another encounter; keep the current one saved |
| `Ctrl+E` | save/start prepared encounters |
| `/` | Ask AI about the encounter or rules |
| `/roll 2d6+4` | roll dice locally without using OpenAI |
| `Ctrl+Q` / `?` | quit / help |

`Ctrl+M` cannot be a distinct shortcut in a traditional terminal because it
emits the same control character as Enter. Ward uses `Shift+M` for the full
library so attack and confirmation remain reliable. Bare `Tab` and function keys
are left to normal terminal/desktop behavior.

## Campaigns & encounters

Played encounters are remembered automatically in the ignored
`campaign-encounters.json`; there is no manual save step. `Ctrl+N` names and
starts another fight while keeping the current one saved; starting a fight
pauses the campaign's current encounter instead of replacing it. The startup
screen resumes the most recently active fight; **Campaigns** opens any campaign
without silently starting one.

`Ctrl+O` opens the campaign folio — resume/new-encounter actions first, then
encounter preparation, campaign details, backup/recovery, and campaign
switching. The encounter index sorts **Current**, then **Paused**, then
**Complete**, showing round, creature count, and last-updated date. Selecting an
encounter offers resume, rename, or mark complete.

A campaign owns its party roster, lookup reference preference, and notes (in the
ignored `campaigns.json`). A roster entry may be a D&D Beyond character or a
manually named adventurer. Editing the campaign party never rewrites the
encounter already on the table; it takes effect the next time that campaign
starts an encounter. Older single-resume `encounter.json` files migrate
automatically as a named **Recovered encounter**.

Choose **Ward data** from the campaign folio to export campaigns, parties,
notes, played encounters, and reusable monster setups into a portable JSON
backup under `ward-backups/`. Restoring first creates a safety backup of the
data being replaced. Copy important backups outside the checkout (and to another
disk) for real protection.

## Attacks & spells

Weapon lines (`Longsword +7 · 1d8+4 sl`) roll `d20 + bonus` vs the target's AC;
a natural 20 crits (dice doubled, the flat bonus once) and a natural 1 always
misses. Spells are best-effort:

- `(Dex DC 12)` hints give the target a saving throw (half damage on a success)
  and are still rolled for no-damage control spells (e.g. Hold Person).
- Heal/cure/regain spells restore HP instead of dealing damage (save hints never
  halve a heal).
- `3 darts` lines (Magic Missile) roll the dice three times.

`/roll 2d6+4` and `/r 1d20+7` roll locally without contacting OpenAI. A roll may
contain at most 1,000 dice, preventing an accidental expression from blocking
the table UI. Other `/` questions use the optional DM assistant with a small
encounter context; cached SRD spell details are added only when the question
clearly names a spell.

## DM Screen & Party Reference

`Ctrl+2` replaces the encounter panels with a fixed, glanceable 5e reference:
combat quick rules, conditions, quick numbers, and DC/roll guidance. `Ctrl+3`
shows the Party Reference: current HP, AC, passive checks, saves, spell DCs, and
PC conditions/reminders. `Ctrl+1` returns to the encounter, or `s` cycles through
all three modes. The references are intentionally read-only; the physical table
remains authoritative.

The token map tracks approximate creature positions during an encounter. It does
not calculate range, movement, terrain, line of sight, areas, or legal actions.

## Monsters, spells & SRD content

`Shift+M` opens the monster library and `b` opens the spellbook. Both merge the
hand-authored templates with the official D&D 5e **System Reference Document**,
fetched from [Open5e](https://open5e.com) on first use and cached to
`.cache/open5e/`. The first open fetches in the background (needs network, once);
subsequent opens are instant. SRD creatures and spells convert into the same
statblocks the rest of the app uses.

Monsters added from the quick picker or searchable library are scattered across
the top-centre of the map's first four rows, keeping newly imported enemies
visible and easy to distinguish from the party.

### Preparation tools

`Ctrl+E` saves or starts a prepared encounter. Prepared encounters are reusable
monster setups, not played fights: they store only monsters and starting
positions. Starting one creates a new campaign-owned encounter copy with the
campaign party, leaving both the template and previous fight intact. Monsters
return at full HP with clear conditions and unrolled initiative. Older templates
that contain PCs are loaded safely — the embedded PCs are ignored.

## D&D Beyond imports

Character imports use D&D Beyond's character-service endpoint. If the battle log
reports access denied or HTTP 403, open that character in D&D Beyond, change its
privacy to **Public**, save it, and retry the import. The importer cannot parse a
character when D&D Beyond denies the service request.

## Soundtrack & Tabletop Audio

`Ctrl+K`, the top-bar note, or **Music** from the campaign folio start, pause,
resume, stop, or change the table soundtrack. The top bar shows the current
source: gold while playing, blue-gray when paused, and a muted note icon when
silent. Ward stays silent until the DM starts a stream and stops its player when
Ward exits.

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
      "note": "Atmospheric textures with minimal beats - SomaFM"
    }
  ]
}
```

Add, remove, or replace source entries without changing Python. An optional
boolean `loop` key keeps an individual configured stream looping. `auto` prefers
`mpv` and falls back to `ffplay`; set the backend explicitly to either name if
needed. Set `WARD_MUSIC_CONFIG=/path/to/music.json` to keep a personal catalog
outside the checkout or override the packaged default. Sources are passed to the
player as arguments, never through a shell.

When online, **Suggest Tabletop Audio** first asks which scene phase is running —
Town, Journey, Explore, or Battle — then offers up to five encounter-aware picks
from Tabletop Audio's free, downloadable 10-minute tracks. Ward uses the current
encounter name, non-PC foes, round, and chosen phase (never party names), ranks
the public metadata locally, and keeps every result inside the fantasy genre
with a whole-word phase keyword. If the optional OpenAI setup is available it can
expand only mood/setting vocabulary and exact catalog categories; an unavailable
or failed helper simply falls back to local encounter terms. Results can be
refined with an extra mood or keyword search before playing. SoundPads and
Patreon content are excluded. Selecting a result streams its public MP3 directly
to `mpv`/`ffplay` and loops it; Ward never downloads or caches audio. Catalog
metadata is cached for 24 hours at `.cache/tabletop_audio/catalog.json`, with a
brief stale-cache fallback if a refresh fails. Results visibly credit
**Tabletop Audio · CC BY-NC-ND 4.0**.

## Offline mode

Set `WARD_OFFLINE=1` to disable all network fetches (SRD, Tabletop Audio
catalog, and playback of cached Tabletop Audio audio — configured streams that
are already playing keep working). `VTT_OFFLINE` remains a compatibility alias
for older setups.