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
documents the staff code review and every fix that came out of it.

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
| `x` | remove the selected creature (asks first) |
| `r` | reset to the scripted encounter |
| `o` / `t` | roll monster initiative / set a creature's initiative |
| `i` | import a PC from a D&D Beyond URL |
| `p` | add a PC from a name |
| `e` | edit the selected creature (name, HP, AC, init mod, role, note, scores) |
| `f` | find a creature by name or coordinate |
| `u` / `Shift+u` | undo / redo |
| `s` / `l` | save / load the encounter to `encounter.json` |
| `Ctrl+n` | new blank encounter |
| `q` / `?` | quit / help |

## Attacks & spells

Weapon lines (`Longsword +7 · 1d8+4 sl`) roll `d20 + bonus` vs the target's AC;
a natural 20 crits (dice doubled, the flat bonus once) and a natural 1 always
misses. Spells are best-effort: `(Dex DC 12)` hints give the target a saving
throw (half damage on a success), heal/cure/regain spells restore HP instead of
dealing damage, and `3 darts` lines (Magic Missile) roll the dice three times.

## Dev

```sh
.venv/bin/python tests.py   # unit tests (pure logic + imports)
.venv/bin/python smoke.py   # headless UI drive-through, screenshots in shots/
```

## Layout

- `app.py` — the `BattleApp` TUI: bindings, flows, rendering, CSS.
- `battle.py` — data model (`Combatant`), dice engine, attack resolution,
  monster library, the starting encounter.
- `ddb.py` — D&D Beyond character-service parsing (`extract_combatant`).
- `widgets.py` — initiative row, token map, scroll containers.
- `modals.py` — number/list/text prompts, the help screen, and the import
  busy-modal.
- `REVIEW.md` / `CHANGELOG.md` — staff review findings + fixes, sprint log.