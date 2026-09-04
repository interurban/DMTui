# Developing Ward

## Tests

```sh
.venv/bin/python tests.py              # unit tests (pure logic + imports)
.venv/bin/python tests_music_ui.py     # music player + config tests
.venv/bin/python tests_tabletop_audio.py  # Tabletop Audio catalog tests
.venv/bin/python smoke.py              # headless UI drive-through, screenshots in shots/
```

`requirements.txt` remains available for older checkout-based setups; new setups
should use `pip install -e .` so the launcher and dependency metadata stay
together.

## Code layout

Ward keeps its code as importable top-level modules (so `.venv/bin/python app.py`
works straight from a checkout) and ships thin `ward`/`dmtui` console-script
packages that delegate to them. `pyproject.toml` lists both the packages and the
top-level `py-modules` that ship with them.

- `app.py` — the `BattleApp` TUI: bindings, flows, rendering, CSS.
- `battle.py` — data model (`Combatant`), dice engine, attack resolution,
  monster library, the starting encounter.
- `campaigns.py` — campaign, party roster, lookup preference, and notes
  persistence.
- `encounter_store.py` — named campaign encounters, status, current pointers,
  atomic persistence, and legacy migration.
- `persistence.py` — shared atomic JSON-write primitive used by Ward's stores
  and cache.
- `music.py` / `ward/music_config.json` — replaceable stream catalog and
  external-player boundary.
- `tabletop_audio.py` — Tabletop Audio catalog client, local ranking, and
  playback boundary.
- `openai_client.py` — the optional OpenAI chat / encounter-planning client.
- `ward_backup.py` — portable Ward data backups and validated recovery.
- `ddb.py` — D&D Beyond character-service parsing (`extract_combatant`).
- `modals.py` — number/list/text prompts, the help screen, and the import
  busy-modal.
- `widgets.py` — initiative row, token map, scroll containers.
- `dm_screen.py` — the fixed, glanceable 5e quick-reference panels.
- `ward/` — the installed `ward` command and module entry point.
- `srd.py` — generic Open5e v2 client: `fetch_raw` / `get_collection` paginate
  and cache any collection, so other content (magic items, conditions, …) can be
  added by supplying an endpoint + transform.

## Product docs

- `CHANGELOG.md` — sprint log.
- `REVIEW.md` — staff code-review findings and every fix that came out of them.
- `ROADMAP.md` — prioritized next features and explicit non-goals.