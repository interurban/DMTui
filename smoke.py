"""Headless smoke test — drives the app with a pilot and saves screenshots."""

import asyncio
import json
import os
import random

# Keep the run fully offline: never auto-fetch the SRD library from Open5e.
os.environ.setdefault("VTT_OFFLINE", "1")

import app as appmod
import ddb
from app import BattleApp
from battle import Combatant
from ddb import parse_ddb_url
from modals import HelpModal, ListModal, TextModal
from textual.widgets import Input, Static

SHOTS = os.path.join(os.path.dirname(__file__), "shots")

# campaign boot is mocked offline: the three default character ids (plus one
# more for the manual import test) resolve to canned D&D Beyond payloads
DEFAULT_IDS = [91566422, 112516506, 90060446]


def _canned(name, race, cls, level, hp, stats, items, spells=None, bonus=0):
    return {
        "name": name,
        "classes": [{"level": level, "definition": {"name": cls}}],
        "race": {"fullName": race},
        "baseHitPoints": hp,
        "bonusHitPoints": bonus,
        "removedHitPoints": 0,
        "stats": [{"id": i, "value": v} for i, v in enumerate(stats, start=1)],
        "inventory": items,
        "spells": spells or {},
        "modifiers": {},
    }


def _weapon(name, dice, stat_bonus, *, atype=1, damage_type="Bludgeoning", ranged=False):
    d = {"name": name, "damage": {"diceString": dice, "value": 0}, "damageBonus": 0,
         "damageType": damage_type, "attackType": atype}
    if ranged:
        d["range"] = 80
    return {"equipped": True, "definition": d}


def _armor(name, ac, atype):
    return {"equipped": True, "definition": {"name": name, "armorClass": ac, "armorTypeId": atype}}


CANNED = {
    91566422: _canned(
        "Zephyr", "Gnome", "Wizard", 4, 20, [8, 14, 10, 17, 10, 10],
        [_weapon("Quarterstaff", "1d6", 0)],
        spells={"0": [{"definition": {"name": "Fire Bolt", "level": 0}}],
                "1": [{"definition": {"name": "Shield", "level": 1}}]},
        bonus=4,
    ),
    112516506: _canned(
        "Lyra", "Halfling", "Rogue", 3, 18, [10, 18, 12, 12, 12, 14],
        [_armor("Leather", 11, 1), _weapon("Shortbow", "1d6", 0, damage_type="Piercing", ranged=True)],
    ),
    90060446: _canned(
        "Tess", "Human", "Fighter", 3, 28, [16, 10, 14, 8, 12, 8],
        [_armor("Plate", 18, 3), _weapon("Greatsword", "2d6", 0, damage_type="Slashing")],
    ),
    9876543: _canned(
        "Nix", "Dwarf", "Cleric", 2, 14, [12, 12, 12, 12, 12, 12],
        [_weapon("Warhammer", "1d8", 0)],
    ),
}
ddb.fetch_character_data = lambda cid: CANNED[cid]


class _Seq:
    """Canned RNG stub for smoke: yields fixed values from randint."""

    def __init__(self, values):
        self._v = iter(values)

    def randint(self, a, b):
        return next(self._v)

    def choice(self, values):
        return values[0]


async def _wait_pcs(pilot, n):
    app = pilot.app
    for _ in range(50):
        await pilot.pause()
        if len([c for c in app.combatants if c.kind == "PC"]) == n:
            return
    raise AssertionError(f"expected {n} PCs after boot, got {len(app.combatants)}")


async def _wait_modal(pilot, cls):
    for _ in range(50):
        await pilot.pause()
        if isinstance(pilot.app.screen, cls):
            return
    raise AssertionError(f"expected {cls.__name__}, got {type(pilot.app.screen).__name__}")


async def main() -> None:
    os.makedirs(SHOTS, exist_ok=True)
    appmod.CAMPAIGN_PATH = os.path.join(SHOTS, "campaigns-test.json")
    appmod.SAVE_PATH = os.path.join(SHOTS, "encounter-test.json")
    for p in (appmod.CAMPAIGN_PATH, appmod.SAVE_PATH):
        if os.path.exists(p):
            os.remove(p)

    app = BattleApp()
    async with app.run_test(size=(130, 50)) as pilot:
        await _wait_pcs(pilot, 3)
        await pilot.pause()

        # campaign boot imported the three default PCs, no monsters yet
        pcs = [c for c in app.combatants if c.kind == "PC"]
        assert [c.name for c in pcs] == ["Zephyr", "Lyra", "Tess"], [c.name for c in pcs]
        assert [c.ddb_id for c in pcs] == DEFAULT_IDS, [c.ddb_id for c in pcs]
        assert len(app.combatants) == 3
        assert app.round == 1
        zephyr, lyra, tess = pcs
        assert (zephyr.hp, zephyr.max_hp, zephyr.ac) == (24, 24, 12)
        assert (lyra.hp, lyra.max_hp, lyra.ac) == (21, 21, 15)
        assert (tess.hp, tess.max_hp, tess.ac) == (34, 34, 18)
        assert all(c.init is None for c in app.combatants)
        assert zephyr.attacks and zephyr.attacks[0].startswith("Quarterstaff +1 · 1d6-1")
        assert lyra.attacks[0].startswith("Shortbow +6 · 1d6+4")
        assert tess.attacks[0].startswith("Greatsword +5 · 2d6+3")
        assert "Fire Bolt" in zephyr.spells and "Shield" in zephyr.spells
        app.save_screenshot(os.path.join(SHOTS, "01-start.png"))

        # inline damage: d arms entry, digits show in the status bar, enter applies
        hp0 = zephyr.hp
        await pilot.press("d")
        await pilot.pause()
        status = str(app.query_one("#init-status", Static).content)
        assert "DAMAGE" in status and "Enter" in status, status
        await pilot.press("5")
        await pilot.pause()
        status = str(app.query_one("#init-status", Static).content)
        assert "5" in status, status
        await pilot.press("enter")
        await pilot.pause()
        assert app._hp_entry is None
        assert zephyr.hp == hp0 - 5, zephyr.hp
        app.save_screenshot(os.path.join(SHOTS, "02-damage.png"))

        # Esc cancels a half-typed entry without applying it
        hp1 = zephyr.hp
        await pilot.press("d", "3")
        await pilot.pause()
        assert app._hp_entry is not None
        await pilot.press("escape")
        await pilot.pause()
        assert app._hp_entry is None
        assert zephyr.hp == hp1, zephyr.hp

        # the newest message renders at the TOP of the battle log
        newest = app._messages[-1][0]
        log_lines = str(app.query_one("#log-content", Static).content).splitlines()
        assert newest in log_lines[0], (newest, log_lines[0])

        # detail card has breathing room after the vitals row and before the note
        detail = str(app.query_one("#detail", Static).content)
        assert "\n\n" in detail, detail

        # next turn a few times
        for _ in range(4):
            await pilot.press("n")
            await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "03-turns.png"))

        # toggle a condition on the selected creature (list is sorted by name,
        # so the first row — "blinded" — is what Enter applies)
        cond_sel = app._sel
        await pilot.press("c")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "04-condition-modal.png"))
        await pilot.press("enter")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "05-condition-applied.png"))
        assert cond_sel.conditions, f"{cond_sel.name} should have a condition toggled"

        # add a monster (first alphabetically = Bandit)
        before = len(app.combatants)
        await pilot.press("m")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "06-monster-modal.png"))
        await pilot.press("enter")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "07-monster-added.png"))
        assert len(app.combatants) == before + 1
        bandit = next(c for c in app.combatants if c.name.startswith("Bandit"))
        assert bandit.init is None

        # r rolls initiative for monsters (d20 + modifier), never for PCs
        await pilot.press("r")
        await pilot.pause()
        assert bandit.init is not None, bandit.init
        assert all(c.init is None for c in pcs), [c.init for c in pcs]
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "rolls" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "17-monster-init.png"))

        # help overlay
        await pilot.press("?")
        await pilot.pause()
        assert isinstance(app.screen, HelpModal), type(app.screen)
        app.save_screenshot(os.path.join(SHOTS, "08-help.png"))
        await pilot.press("escape")
        await pilot.pause()

        # remove the Bandit with confirmation
        app._sel = bandit
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "09-remove-confirm.png"))
        await pilot.press("enter")      # confirm the removal
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "09-removed.png"))
        assert not any(c.name.startswith("Bandit") for c in app.combatants)

        # reset (shift+r): full HP, conditions and initiative cleared, round 1
        await pilot.press("shift+r")
        await pilot.pause()
        assert all(c.hp == c.max_hp for c in app.combatants)
        assert all(not c.conditions for c in app.combatants)
        assert all(c.init is None for c in app.combatants)
        assert app.round == 1
        app.save_screenshot(os.path.join(SHOTS, "10-reset.png"))

        # grab the selected token and place it on the map (down, then right)
        sel = app._sel
        sx, sy = sel.x, sel.y
        await pilot.press("g")          # grab
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "11-grabbed.png"))
        assert app._moving
        await pilot.press("down")
        await pilot.pause()
        assert (sel.x, sel.y) == (sx, sy + 1), (sel.x, sel.y)
        await pilot.press("right")
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

        # click the moved token on the map to select it (zephyr now at sx-1, sy+1)
        map_widget = app.query_one("#map")
        cell_w = map_widget.cell_w
        app._sel = tess
        await pilot.pause()
        await pilot.click(map_widget, offset=(4 + sel.x * cell_w + cell_w // 2, 1 + sel.y))
        await pilot.pause()
        assert app._sel.name == "Zephyr", app._sel.name
        app.save_screenshot(os.path.join(SHOTS, "13-click-selected.png"))

        # block: park Lyra directly above Zephyr, grab and nudge up — she holds
        lyra.x, lyra.y = zephyr.x, zephyr.y - 1
        await pilot.press("g")
        await pilot.pause()
        hx, hy = app._sel.x, app._sel.y
        await pilot.press("up")
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
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "Zephyr" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "15-log.png"))

        # map tokens are centered in their cell (3-char label in a 4-wide cell)
        tmp = Combatant(name="Mog", kind="monster", hp=1, max_hp=1, ac=10)
        assert app._map_cell(0, 0, [tmp], 4).plain == "Mog ", repr(app._map_cell(0, 0, [tmp], 4).plain)
        assert app._map_cell(0, 0, [tmp], 3).plain == "Mog", repr(app._map_cell(0, 0, [tmp], 3).plain)

        # next turn and watch the ▶ marker move; turn change is logged
        t0 = app._turn
        await pilot.press("n")
        await pilot.pause()
        assert app._turn is not t0
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "Turn →" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "16-turn.png"))

        # resolve a guaranteed hit: zephyr's Quarterstaff vs the first living
        # creature. a canned RNG forces d20=15 (a solid hit, no crit) then d6=3,
        # so the damage is deterministic and the assert can't pass vacuously.
        app._rng = _Seq([15, 3])
        app._sel = zephyr
        await pilot.pause()
        targets = [t for t in app.combatants if t.alive and t is not zephyr]
        target = targets[0]
        assert target is lyra, target.name  # insertion order: Lyra first
        hp_before = target.hp
        await pilot.press("a")
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "21-attack-modal.png"))
        await pilot.press("enter")          # pick first weapon (Quarterstaff)
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "22-target-modal.png"))
        await pilot.press("enter")          # pick first living target
        await pilot.pause()
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "hit" in log_txt, log_txt
        assert target.hp == hp_before - 2, (target.hp, hp_before)  # d6=3 + flat -1
        app.save_screenshot(os.path.join(SHOTS, "23-attack-resolved.png"))

        # undo the attack (hp restored), then redo it (hp applied again).
        # Undo must revert combatant state without rewinding turn/round.
        rnd_before, turn_before = app.round, app._turn.name
        hp_after = [c for c in app.combatants if c.name == target.name][0].hp
        await pilot.press("u")
        await pilot.pause()
        t_undone = [c for c in app.combatants if c.name == target.name][0]
        assert t_undone.hp == hp_before, (t_undone.hp, hp_before)
        assert app.round == rnd_before and app._turn.name == turn_before, (app.round, app._turn.name)
        await pilot.press("shift+u")
        await pilot.pause()
        t_redone = [c for c in app.combatants if c.name == target.name][0]
        assert t_redone.hp == hp_after, (t_redone.hp, hp_after)
        app.save_screenshot(os.path.join(SHOTS, "24-undo-redo.png"))
        zephyr = [c for c in app.combatants if c.name == "Zephyr"][0]
        lyra = [c for c in app.combatants if c.name == "Lyra"][0]
        tess = [c for c in app.combatants if c.name == "Tess"][0]

        # a miss must not push an undo entry (regression: phantom undo on a
        # no-op attack) — natural 1 always misses
        app._rng = _Seq([1])
        undo_len = len(app._undo)
        app._sel = zephyr
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert len(app._undo) == undo_len, (len(app._undo), undo_len)
        lyra_now = [c for c in app.combatants if c.name == "Lyra"][0]
        assert lyra_now.hp == hp_after, (lyra_now.hp, hp_after)
        app._rng = random.Random(7)  # back to a real RNG for the rest of the flow

        # save the session to disk, damage a PC, then load it back
        hp0 = zephyr.hp
        await pilot.press("s")
        await pilot.pause()
        assert os.path.exists(appmod.SAVE_PATH)
        await pilot.press("d", "5", "enter")
        await pilot.pause()
        assert zephyr.hp == hp0 - 5, zephyr.hp
        await pilot.press("l")
        await pilot.pause()
        zephyr_loaded = [c for c in app.combatants if c.kind == "PC"][0]
        assert zephyr_loaded.hp == hp0, zephyr_loaded.hp
        os.remove(appmod.SAVE_PATH)
        app.save_screenshot(os.path.join(SHOTS, "25-save-load.png"))
        zephyr = [c for c in app.combatants if c.name == "Zephyr"][0]
        lyra = [c for c in app.combatants if c.name == "Lyra"][0]
        tess = [c for c in app.combatants if c.name == "Tess"][0]

        # initiative: AC shows in the init rows
        row_text = str(app._rows[id(tess)].render().plain)
        assert "AC 18" in row_text, row_text
        assert "--" in row_text, row_text  # blank init shows as --

        # t sets a creature's initiative and auto-sorts to the top
        app._sel = lyra
        await pilot.press("t")
        await pilot.pause()
        app.screen.query_one(Input).value = "30"
        await pilot.press("enter")
        await pilot.pause()
        assert lyra.init == 30, lyra.init
        assert app.combatants[0] is lyra, [c.name for c in app.combatants]
        app.save_screenshot(os.path.join(SHOTS, "18-set-init.png"))

        # import a PC from a D&D Beyond URL (network mocked offline)
        assert parse_ddb_url("https://www.dndbeyond.com/characters/9876543") == 9876543
        assert parse_ddb_url("9876543") == 9876543
        assert parse_ddb_url("https://example.com/other") is None

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
        nix = [c for c in app.combatants if c.name == "Nix"][0]
        assert nix.kind == "PC" and nix.hp == 16 and nix.max_hp == 16
        assert nix.ac == 11 and nix.role == "Cleric 2"
        assert nix.init is None and nix.init_mod == 1
        assert nix.attacks and nix.attacks[0].startswith("Warhammer +3 · 1d8+1"), nix.attacks
        log_txt = str(app.query_one("#log-content", Static).content)
        assert "Imported Nix" in log_txt, log_txt
        app.save_screenshot(os.path.join(SHOTS, "20-imported.png"))

        # edit a name (e -> first field -> type + enter), then undo it
        app._sel = zephyr
        await pilot.pause()
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
        zephyr = [c for c in app.combatants if c.name == "Zephyr"][0]
        lyra = [c for c in app.combatants if c.name == "Lyra"][0]
        tess = [c for c in app.combatants if c.name == "Tess"][0]

        # edit AC (e -> down down -> ac field), then undo it
        app._sel = tess
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        app.screen.query_one(Input).value = "16"
        await pilot.press("enter")
        await pilot.pause()
        assert tess.ac == 16, tess.ac
        app.save_screenshot(os.path.join(SHOTS, "27-edit-ac.png"))
        await pilot.press("u")
        await pilot.pause()
        tess = [c for c in app.combatants if c.name == "Tess"][0]
        assert tess.ac == 18, tess.ac

        # add a PC from scratch (p -> name -> enter)
        n = len(app.combatants)
        await pilot.press("p")
        await pilot.pause()
        app.screen.query_one(Input).value = "Borin"
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.combatants) == n + 1, len(app.combatants)
        borin = [c for c in app.combatants if c.name == "Borin"][0]
        assert borin.kind == "PC" and borin.ac == 10 and borin.hp == 10 and borin.max_hp == 10
        assert app._sel is borin
        app.save_screenshot(os.path.join(SHOTS, "28-add-pc.png"))

        # campaigns: save the current party as a new campaign (C), then load it
        await pilot.press("C")
        await _wait_modal(pilot, ListModal)
        app.save_screenshot(os.path.join(SHOTS, "31-campaign-menu.png"))
        await pilot.press("down")       # -> "Save current party as a new campaign"
        await pilot.press("enter")
        await _wait_modal(pilot, TextModal)
        app.screen.query_one(Input).value = "Test Party"
        await pilot.press("enter")
        await pilot.pause()
        with open(appmod.CAMPAIGN_PATH) as f:
            camps = json.load(f)
        assert camps["active"] == "Test Party", camps["active"]
        assert len(camps["campaigns"]["Test Party"]["character_ids"]) == 4
        assert set(camps["campaigns"]["Test Party"]["character_ids"]) == set(DEFAULT_IDS + [9876543])

        # load the saved campaign back (active campaign is the first menu option)
        await pilot.press("C")
        await _wait_modal(pilot, ListModal)
        await pilot.press("enter")      # -> load: Test Party
        await _wait_pcs(pilot, 4)
        # Lyra was sorted first (init 30) when the party was saved, so she leads
        assert [c.name for c in app.combatants if c.kind == "PC"] == ["Lyra", "Zephyr", "Tess", "Nix"]
        app.save_screenshot(os.path.join(SHOTS, "32-campaign-loaded.png"))

        # with everyone dead, advancing must still begin a new round — the
        # dead-skip scan wraps the whole list (regression: round never advanced)
        await pilot.press("shift+r")
        await pilot.pause()
        for c in app.combatants:
            c.hp = 0
        r0 = app.round
        await pilot.press("n")
        await pilot.pause()
        assert app.round == r0 + 1, (app.round, r0)

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
        assert len(app.combatants) == 4, len(app.combatants)
        await pilot.press("shift+u")
        await pilot.pause()
        assert len(app.combatants) == 0, len(app.combatants)

        # monster library browser (b): type a filter, Enter adds the match.
        # "goblin shaman" is built-in-only (absent from the SRD cache), so it is
        # always a single match regardless of whether SRD data is present.
        await pilot.press("b")
        await pilot.pause()
        await pilot.press(*tuple("goblin shaman"))
        await pilot.pause()
        app.save_screenshot(os.path.join(SHOTS, "30-monster-browser.png"))
        await pilot.press("enter")
        await pilot.pause()
        assert [c.name for c in app.combatants] == ["Goblin Shaman"], [c.name for c in app.combatants]
        shaman = app.combatants[0]
        assert shaman.max_hp == 17 and shaman.ac == 13 and shaman.init_mod == 2
        assert any("Nimble Escape" in t for t in shaman.traits)
        # the picker stays open after adding — close it, then undo
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("u")
        await pilot.pause()
        assert len(app.combatants) == 0, len(app.combatants)

        for p in (appmod.CAMPAIGN_PATH,):
            if os.path.exists(p):
                os.remove(p)

        print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())