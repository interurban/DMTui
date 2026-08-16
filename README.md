# Battle Tracker

A single-screen terminal combat tracker for D&D 5e DMs. One screen holds the
whole battle: a token map on top, the initiative order, the battle log, and a
detail card for the selected creature.

![battle tracker](shots/01-start.png)

Built with [Textual](https://textual.textualize.io/).

## Run

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

`?` opens the in-app key guide. `CHANGELOG.md` is the sprint log; `REVIEW.md`
documents both staff code-review passes and every fix that came out of them.

The `/` command asks the OpenAI model configured in `llm_config.json` for a
concise answer using the current encounter context. Set `api_key` in
`llm_config.json` or provide `OPENAI_API_KEY`.

For local secret storage, create the ignored `llm_config.local.json` beside
`llm_config.json`:

```json
{
  "api_key": "sk-your-key-here"
}
```

The local file overrides matching settings in `llm_config.json` and is not
tracked by Git.

Campaign rulesets are configured in `campaigns.json` with `"ruleset": "2014"`
or `"ruleset": "2024"`. The active ruleset is included in DM chat context.

### DM Screen mode

Press `Ctrl+2` to replace the
four encounter panels with a fixed, glanceable 5e reference: common actions,
conditions, combat rules, and DC/roll guidance. Press `Ctrl+1` to return to the
encounter, or `s` to switch between both modes. Bare `Tab` and function keys are
left to normal terminal/desktop behavior. The reference is intentionally
read-only; the physical table remains authoritative.

### D&D Beyond imports

Character imports use D&D Beyond's character-service endpoint. If the battle
log reports access denied or HTTP 403, open that character in D&D Beyond,
change its privacy to **Public**, save it, and retry the import. The importer
cannot parse a character when D&D Beyond denies the service request.

## Keys

| Key | Action |
| --- | --- |
| `↑`/`↓` or `k`/`j` | select previous/next creature |
| `←`/`→` | −1/+1 HP |
| `g` | grab a token (arrows place it, `g`/`Esc` drops) |
| `n` / `Enter` | next turn |
| `a` | attack with the selected creature (weapon/spell, then target) |
| `d` / `h` | damage / heal (amount prompt) |
| `c` | toggle a condition |
| `m` / `b` | add a monster / browse the searchable monster library |
| `v` | spellbook — browse the SRD and add a spell to the selected creature |
| `x` | remove the selected creature (asks first) |
| `r` / `t` | roll monster initiative / set a creature's initiative |
| `Shift+i` | enter initiative for each unrolled PC in sequence |
| `+` | duplicate the selected monster at full HP |
| `Shift+r` | reset the encounter (undoable) |
| `i` | import a PC from a D&D Beyond URL |
| `p` | add a PC from a name |
| `e` | edit the selected creature (name, HP, AC, init mod, role, note, scores) |
| `f` | find a creature by name or map coordinate (`@B3`, `@AA1`) |
| `u` / `Shift+u` | undo / redo |
| `s` | switch between combat and DM Screen |
| `Ctrl+s` / `Ctrl+l` | save / load the encounter to `encounter.json` |
| `Ctrl+n` | new blank encounter |
| `Ctrl+p` | command palette |
| `/` | ask the OpenAI DM assistant |
| `/roll 2d6+4` | roll dice locally without using OpenAI |
| `Ctrl+1` / `Ctrl+2` | combat view / fixed DM quick-reference screen |
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

## Open5e SRD content

Press `b` to open the monster library and `v` to open the spellbook. Both merge
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
- `REVIEW.md` / `CHANGELOG.md` — staff review findings + fixes, sprint log.
