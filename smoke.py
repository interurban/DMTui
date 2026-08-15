"""Headless smoke test — drives the app with a pilot and saves screenshots."""

import asyncio
import os

from app import BattleApp
from ddb import parse_ddb_url
from textual.widgets import Input, Static

SHOTS = os.path.join(os.path.dirname(__file__), "shots")


async def main() -> None:
    os.makedirs(SHOTS, exist_ok=True)
    app = BattleApp()
    async with app.run_test(size=(130, 50)) as pilot:
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "01-start.png"))

        # default encounter: Dent is the only PC, everyone's initiative is blank
        pcs = [c for c in app.combatants if c.kind == "PC"]
        assert [c.name for c in pcs] == ["Dent"], pcs
        assert all(c.init is None for c in app.combatants)
        dent = pcs[0]
        assert dent.hp == 60 and dent.max_hp == 60 and dent.ac == 22

        # damage Goblin 2 by 5 (encounter order: Dent, Hobgoblin, G1, G2, …)
        await pilot.press("j", "j", "j")  # move to Goblin 2
        assert app._sel.name == "Goblin 2", app._sel.name
        await pilot.press("d", "5", "enter")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "02-damage.png"))

        # next turn a few times
        for _ in range(4):
            await pilot.press("n")
            await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "03-turns.png"))

        # toggle a condition (poisoned) on the selected creature
        await pilot.press("c")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "04-condition-modal.png"))
        await pilot.press("enter")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "05-condition-applied.png"))

        # add a monster
        await pilot.press("m")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "06-monster-modal.png"))
        await pilot.press("enter")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "07-monster-added.png"))

        # help overlay
        await pilot.press("?")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "08-help.png"))
        await pilot.press("escape")

        await pilot.press("x")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "09-remove-confirm.png"))
        await pilot.press("enter")      # confirm the removal
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "09-removed.png"))

        # reset
        await pilot.press("r")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "10-reset.png"))

        # grab the selected token and place it on the map
        sel = app._sel
        sx, sy = sel.x, sel.y
        await pilot.press("g")          # grab
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "11-grabbed.png"))
        assert app._moving
        await pilot.press("right", "down")
        await pilot.pause()
        assert (sel.x, sel.y) == (sx + 1, sy + 1), (sel.x, sel.y)
        await pilot.press("g")          # drop
        await pilot.pause()
        assert not app._moving
        app.save_screenshot(os.path.join(SHOTS, "12-placed.png"))

        # not grabbed → left/right adjust HP, not position
        hp0 = sel.hp
        await pilot.press("left")
        await pilot.pause()
        assert (sel.x, sel.y) == (sx + 1, sy + 1), "position must not change without grab"
        assert sel.hp == hp0 - 1, sel.hp
        await pilot.press("right")
        await pilot.pause()
        assert sel.hp == hp0, sel.hp
        assert (sel.x, sel.y) == (sx + 1, sy + 1)

        # movement must NOT appear in the battle log
        log_txt = app.query_one("#log-content", Static).content
        assert "moved to" not in str(log_txt) and "placed at" not in str(log_txt)

        # click a token on the map to select it (Goblin 1 at 11,6)
        map_widget = app.query_one("#map")
        cell_w = map_widget.cell_w
        await pilot.click(map_widget, offset=(4 + 11 * cell_w + cell_w // 2, 1 + 6))
        await pilot.pause()
        assert app._sel.name == "Goblin 1", app._sel.name
        app.save_screenshot(os.path.join(SHOTS, "13-click-selected.png"))

        # block: grab Goblin 1 and nudge west — Goblin 2 holds (10,6)
        await pilot.press("g")
        await pilot.pause()
        hx, hy = app._sel.x, app._sel.y
        await pilot.press("left")
        await pilot.pause()
        assert (app._sel.x, app._sel.y) == (hx, hy), "occupied cell must block"
        await pilot.press("g")          # drop
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "14-blocked.png"))

        # damage the clicked token straight from the map selection
        hp0 = app._sel.hp
        await pilot.press("d", "3", "enter")
        await pilot.pause()
        assert app._sel.hp == hp0 - 3
        # battle log records the damage
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "Goblin 1" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "15-log.png"))

        # next turn and watch the ▶ marker move; turn change is logged
        t0 = app._turn
        await pilot.press("n")
        await pilot.pause()
        assert app._turn is not t0
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "Turn →" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "16-turn.png"))

        # resolve an attack: dent's Longsword vs the first living creature
        app._rng = __import__("random").Random(7)
        dent = [c for c in app.combatants if c.kind == "PC"][0]
        app._sel = dent
        await pilot.pause()
        targets = [t for t in app.combatants if t.alive and t is not dent]
        target = targets[0]
        hp_before = target.hp
        await pilot.press("a")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "21-attack-modal.png"))
        await pilot.press("enter")          # pick first weapon (Longsword)
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "22-target-modal.png"))
        await pilot.press("enter")          # pick first living target
        await pilot.pause()
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "→" in log_txt and ("hit" in log_txt or "miss" in log_txt), log_txt
        assert target.hp <= hp_before, (target.hp, hp_before)
        app.save_screenshot(os.path.join(SHOTS, "23-attack-resolved.png"))

        # undo the attack (hp restored), then redo it (hp applied again)
        hp_after = [c for c in app.combatants if c.name == target.name][0].hp
        await pilot.press("u")
        await pilot.pause()
        t_undone = [c for c in app.combatants if c.name == target.name][0]
        assert t_undone.hp == hp_before, (t_undone.hp, hp_before)
        await pilot.press("shift+u")
        await pilot.pause()
        t_redone = [c for c in app.combatants if c.name == target.name][0]
        assert t_redone.hp == hp_after, (t_redone.hp, hp_after)
        app.save_screenshot(os.path.join(SHOTS, "24-undo-redo.png"))

        # save the session to disk, damage a PC, then load it back
        import app as appmod
        dent = [c for c in app.combatants if c.kind == "PC"][0]
        appmod.SAVE_PATH = os.path.join(SHOTS, "encounter-test.json")
        await pilot.press("s")
        await pilot.pause()
        assert os.path.exists(appmod.SAVE_PATH)
        hp0 = dent.hp
        await pilot.press("d", "5", "enter")
        await pilot.pause()
        assert dent.hp == hp0 - 5, dent.hp
        await pilot.press("l")
        await pilot.pause()
        dent_loaded = [c for c in app.combatants if c.kind == "PC"][0]
        assert dent_loaded.hp == hp0, dent_loaded.hp
        os.remove(appmod.SAVE_PATH)
        app.save_screenshot(os.path.join(SHOTS, "25-save-load.png"))

        # initiative: AC shows in the init rows
        dent = [c for c in app.combatants if c.kind == "PC"][0]
        row_text = str(app._rows[id(dent)].render().plain)
        assert "AC 22" in row_text, row_text
        assert "--" in row_text, row_text  # blank init shows as --

        # o rolls initiative for all monsters (d20 + modifier), never for PCs
        for m in (c for c in app.combatants if c.kind != "PC"):
            assert m.init is None
        await pilot.press("o")
        await pilot.pause()
        assert dent.init is None, "PCs are not auto-rolled"
        monsters = [c for c in app.combatants if c.kind != "PC"]
        assert all(m.init is not None for m in monsters), [m.init for m in monsters]
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "rolls" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "17-monster-init.png"))

        # t sets a creature's initiative and auto-sorts to the top
        app._sel = dent
        await pilot.press("t")
        await pilot.pause()
        app.screen.query_one(Input).value = "30"
        await pilot.press("enter")
        await pilot.pause()
        assert dent.init == 30, dent.init
        assert app.combatants[0] is dent, [c.name for c in app.combatants]
        app.save_screenshot(os.path.join(SHOTS, "18-set-init.png"))

        # import a PC from a D&D Beyond URL (network mocked offline)
        assert parse_ddb_url("https://www.dndbeyond.com/characters/9876543") == 9876543
        assert parse_ddb_url("9876543") == 9876543
        assert parse_ddb_url("https://example.com/other") is None

        canned = {
            "name": "Zephyr",
            "classes": [{"level": 4, "definition": {"name": "Wizard"}}],
            "race": {"fullName": "Gnome"},
            "baseHitPoints": 20,
            "bonusHitPoints": 4,
            "removedHitPoints": 2,
            "stats": [
                {"id": 1, "value": 8},
                {"id": 2, "value": 14},
                {"id": 3, "value": 10},
                {"id": 4, "value": 17},
                {"id": 5, "value": 10},
                {"id": 6, "value": 10},
            ],
            "inventory": [
                {
                    "equipped": True,
                    "definition": {
                        "name": "Quarterstaff",
                        "damage": {"diceString": "1d6", "value": 3},
                        "damageBonus": 0,
                        "damageType": "Bludgeoning",
                        "attackType": 1,
                    },
                }
            ],
            "spells": {
                "0": [{"definition": {"name": "Fire Bolt", "level": 0}}],
                "1": [{"definition": {"name": "Shield", "level": 1}}],
            },
            "modifiers": {},
        }
        import ddb
        ddb.fetch_character_data = lambda _cid: canned
        n = len(app.combatants)
        await pilot.press("i")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "19-import-modal.png"))
        app.screen.query_one(Input).value = "https://www.dndbeyond.com/characters/9876543"
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
            if len(app.combatants) == n + 1:
                break
        assert len(app.combatants) == n + 1, len(app.combatants)
        zephyr = [c for c in app.combatants if c.name == "Zephyr"][0]
        assert zephyr.kind == "PC" and zephyr.hp == 22 and zephyr.max_hp == 24
        assert zephyr.ac == 12 and zephyr.role == "Wizard 4"
        assert zephyr.init is None and zephyr.init_mod == 2
        assert "STR 8, DEX 14, CON 10, INT 17, WIS 10, CHA 10" in zephyr.note, zephyr.note
        assert zephyr.attacks and zephyr.attacks[0].startswith("Quarterstaff +1 · 1d6-1"), zephyr.attacks
        assert "Fire Bolt" in zephyr.spells and "Shield" in zephyr.spells, zephyr.spells
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "Imported Zephyr" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "20-imported.png"))

        # edit a name (e -> first field -> type + enter), then undo it
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.screen.query_one(Input).value = "Zephyrin"
        await pilot.press("enter")
        await pilot.pause()
        assert any(c.name == "Zephyrin" for c in app.combatants), [c.name for c in app.combatants]
        app.save_screenshot(os.path.join(SHOTS, "26-edit-name.png"))
        await pilot.press("u")
        await pilot.pause()
        assert any(c.name == "Zephyr" for c in app.combatants), [c.name for c in app.combatants]

        # edit AC (e -> down down -> ac field), then undo it
        grish = [c for c in app.combatants if c.name == "Grish"][0]
        app._sel = grish
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        app.screen.query_one(Input).value = "18"
        await pilot.press("enter")
        await pilot.pause()
        assert grish.ac == 18, grish.ac
        app.save_screenshot(os.path.join(SHOTS, "27-edit-ac.png"))
        await pilot.press("u")
        await pilot.pause()
        grish = [c for c in app.combatants if c.name == "Grish"][0]
        assert grish.ac == 17, grish.ac

        # add a PC from scratch (p -> name -> enter)
        n = len(app.combatants)
        await pilot.press("p")
        await pilot.pause()
        app.screen.query_one(Input).value = "Lyra"
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.combatants) == n + 1, len(app.combatants)
        lyra = [c for c in app.combatants if c.name == "Lyra"][0]
        assert lyra.kind == "PC" and lyra.ac == 10 and lyra.hp == 10 and lyra.max_hp == 10
        assert lyra.stats == {1: 10, 2: 10, 3: 10, 4: 10, 5: 10, 6: 10}, lyra.stats
        assert app._sel is lyra
        app.save_screenshot(os.path.join(SHOTS, "28-add-pc.png"))

        # new blank encounter (ctrl+n -> confirm), then undo/redo it
        await pilot.press("ctrl+n")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "29-new-encounter.png"))
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.combatants) == 0, len(app.combatants)
        assert app.round == 1
        await pilot.press("u")
        await pilot.pause()
        assert len(app.combatants) == n + 1, len(app.combatants)
        await pilot.press("shift+u")
        await pilot.pause()
        assert len(app.combatants) == 0, len(app.combatants)

        # monster library browser (b): type a filter, Enter adds the match
        await pilot.press("b")
        await pilot.pause()
        await pilot.press("t", "r", "o", "l")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "30-monster-browser.png"))
        await pilot.press("enter")
        await pilot.pause()
        assert [c.name for c in app.combatants] == ["Troll"], [c.name for c in app.combatants]
        troll = app.combatants[0]
        assert troll.max_hp == 84 and troll.ac == 15 and troll.init_mod == 1
        assert any("Regeneration" in t for t in troll.traits)
        await pilot.press("u")
        await pilot.pause()
        assert len(app.combatants) == 0, len(app.combatants)

        print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())