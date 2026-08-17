# Battle Tracker

A single-screen terminal combat tracker for D&D 5e DMs. One screen holds the
whole battle: a token map on top, the initiative order, the battle log, and a
detail card for the selected creature.

![battle tracker](shots/01-start.png)

Built with [Textual](https://textual.textualize.io/).

## Run

```sh
python -m venv .venv
.venv/bin/pip install -e .
dmtui
```

The editable install provides both the `dmtui` command and `python -m dmtui`.
The legacy `.venv/bin/python app.py` launch still works from a checkout.

`?` opens the in-app key guide. `CHANGELOG.md` is the sprint log; `REVIEW.md`
documents both staff code-review passes and every fix that came out of them.
`ROADMAP.md` tracks the prioritized next features and explicit non-goals.

The `/` command and `Shift+E` AI encounter tool use the OpenAI model configured
in `llm_config.json`. For local secret storage, copy `.env.example` to `.env`
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

For reference, the tracked `llm_config.json` contains only non-secret settings:

```json
{
  "model": "gpt-4o-mini"
}
```

Campaign rulesets are configured in `campaigns.json` with `"ruleset": "2014"`
or `"ruleset": "2024"`. The active ruleset is included in DM chat context.

### DM Screen mode

Press `Ctrl+2` to replace the four encounter panels with a fixed, glanceable
5e reference: combat quick rules, conditions, quick numbers, and DC/roll
guidance. Press `Ctrl+3` for Party Reference: current HP, AC, passive checks,
saves, spell DCs, and PC conditions/reminders. Press `Ctrl+1` to return to the
encounter, or `s` to cycle through all three modes. Bare `Tab` and function keys
are left to normal terminal/desktop behavior. The references are intentionally
read-only; the physical table remains authoritative.

### D&D Beyond imports

Character imports use D&D Beyond's character-service endpoint. If the battle
log reports access denied or HTTP 403, open that character in D&D Beyond,
change its privacy to **Public**, save it, and retry the import. The importer
cannot parse a character when D&D Beyond denies the service request.

### Preparation tools

Use `Ctrl+E` to save or load named encounter templates. Saving captures the
current creatures and positions as a prepared starting state: HP is restored,
conditions are cleared, and initiative is left unrolled. Loading a template is
undoable.

Monsters added from the quick picker or searchable library are scattered across
the top-centre of the map's first four rows, keeping newly imported enemies
visible and easy to distinguish from the party.

Press `Shift+c` and choose **Edit campaign scratchpad** to keep multiline notes with
the active campaign—NPC names, clues, loot, passwords, or anything else useful
between sessions. `Ctrl+Enter` saves the scratchpad; `Esc` cancels.

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
| `e` | edit the selected creature (name, HP, AC, init mod, role, note, scores) |
| `Shift+e` | describe an encounter and preview an AI-generated monster lineup |
| `f` | find a creature by name or map coordinate (`@B3`, `@AA1`) |
| `u` / `Shift+u` | undo / redo |
| `s` | cycle Combat → DM Screen → Party Reference |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | open Combat / DM Screen / Party Reference |
| `Shift+c` | open campaigns; choose **Edit campaign scratchpad** for notes |
| `Ctrl+s` / `Ctrl+l` | save / load the encounter to `encounter.json` |
| `Ctrl+n` | new blank encounter |
| `Ctrl+e` | save/load named encounter templates |
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
`VTT_OFFLINE=1` to disable all network fetches.

- `srd.py` is the generic client — `fetch_raw` / `get_collection` paginate and
  cache any Open5e v2 collection, so other content (magic items, conditions, …)
  can be added by supplying an endpoint + transform.


## Layout

- `app.py` — the `BattleApp` TUI: bindings, flows, rendering, CSS.
- `battle.py` — data model (`Combatant`), dice engine, attack resolution,
  monster library, the starting encounter.
- `ddb.py` — D&D Beyond character-service parsing (`extract_combatant`).
- `widgets.py` — initiative row, token map, scroll containers.
- `modals.py` — number/list/text prompts, the help screen, and the import
  busy-modal.
- `dm_screen.py` — the fixed, glanceable 5e quick-reference panels.
- `ROADMAP.md` — prioritized future work and product boundaries.
- `REVIEW.md` / `CHANGELOG.md` — staff review findings + fixes, sprint log.
