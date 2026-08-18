"""Unit tests for the pure battle logic. Run: .venv/bin/python tests.py"""

import urllib.error
import urllib.request
import random
import json
import os
import tempfile
from unittest import mock

from battle import (
    action_targets,
    Combatant,
    coord_name,
    find_free_spot,
    find_monster_spot,
    resolve_attack,
    roll_dice,
    short_label,
)
from ddb import extract_combatant, fetch_character_data, parse_ddb_url, parse_ddb_urls
import campaigns as campaign_store
import encounter_store
import music
import openai_client
import persistence
import ward_backup


class Seq:
    """Deterministic RNG stub: yields canned values from randint."""

    def __init__(self, values):
        self._v = iter(values)

    def randint(self, a, b):
        return next(self._v)


def dent() -> Combatant:
    return Combatant("Dent", "PC", hp=60, max_hp=60, ac=22, init_mod=2)


def hobgoblin() -> Combatant:
    return Combatant("Hobgoblin", "monster", hp=28, max_hp=28, ac=18, init_mod=2)


def test_roll_dice():
    rng = Seq([3, 5])
    total, rolls, bonus = roll_dice("2d6+3", rng)
    assert total == 3 + 5 + 3 == 11
    assert rolls == [3, 5]
    assert bonus == 3

    total, rolls, bonus = roll_dice("1d20", Seq([7]))
    assert total == 7 and rolls == [7] and bonus == 0

    total, rolls, bonus = roll_dice("d4", Seq([2]))
    assert total == 2 and rolls == [2] and bonus == 0

    total, rolls, bonus = roll_dice("3d8-1", Seq([6, 2, 4]))
    assert total == 11 and rolls == [6, 2, 4] and bonus == -1

    for bad in ("2x6", "0d6", "2d0", "dice", ""):
        try:
            roll_dice(bad, Seq([1]))
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} should raise")


def test_resolve_hit():
    atk, tgt = dent(), hobgoblin()
    # d20=14 (+7 = 21 vs AC 18) -> hit; damage die d8=3
    res = resolve_attack(atk, "Longsword +7 · 1d8+4 sl", tgt, Seq([14, 3]))
    assert res["kind"] == "attack" and res["name"] == "Longsword"
    assert res["bonus"] == 7 and res["dtype"] == "sl"
    assert res["hit"] and not res["crit"]
    assert res["roll"] == 21 and res["ac"] == 18
    assert res["damage"] == 7 and res["dice"] == [3] and res["dice_bonus"] == 4


def test_resolve_miss():
    atk, tgt = dent(), hobgoblin()
    res = resolve_attack(atk, "Longsword +7 · 1d8+4 sl", tgt, Seq([3]))  # 3+7=10 < 18
    assert not res["hit"] and not res["crit"]
    assert res["damage"] == 0 and res["dice"] == []


def test_resolve_crit():
    atk, tgt = dent(), hobgoblin()
    # nat 20 always hits and doubles the damage dice (d8=3 then d8=5); the
    # flat +4 bonus is added ONCE (regression: it was added twice)
    res = resolve_attack(atk, "Longsword +7 · 1d8+4 sl", tgt, Seq([20, 3, 5]))
    assert res["hit"] and res["crit"]
    assert res["damage"] == 3 + 5 + 4 == 12
    assert res["dice"] == [3, 5] and res["dice_bonus"] == 4


def test_resolve_nat_one_always_misses():
    atk, tgt = dent(), hobgoblin()
    tgt.ac = 1  # even the lowest AC can't be hit on a natural 1
    res = resolve_attack(atk, "Longsword +7 · 1d8+4 sl", tgt, Seq([1]))
    assert not res["hit"] and res["damage"] == 0


def test_resolve_crit_beats_any_ac():
    atk, tgt = dent(), hobgoblin()
    tgt.ac = 99
    res = resolve_attack(atk, "Longsword +7 · 1d8+4 sl", tgt, Seq([20, 1, 1]))
    assert res["hit"] and res["crit"]


def test_resolve_spell_with_dice():
    atk, tgt = dent(), hobgoblin()
    # d20=10 + DEX save (none, so +0) = 10 < DC 12 -> not saved, full damage
    res = resolve_attack(atk, "Burning Hands — 15 ft. cone, 3d6 fire (Dex DC 12)", tgt, Seq([2, 4, 5, 10]))
    assert res["kind"] == "spell" and res["damage"] == 11
    assert res["dice"] == [2, 4, 5] and res["dice_bonus"] == 0
    assert res["save"]["dc"] == 12 and res["save"]["saved"] is False


def test_resolve_spell_save_half_damage():
    atk, tgt = dent(), hobgoblin()
    # d20=13 + 0 = 13 >= DC 12 -> saved, half damage (11 // 2 = 5)
    res = resolve_attack(atk, "Burning Hands — 15 ft. cone, 3d6 fire (Dex DC 12)", tgt, Seq([2, 4, 5, 13]))
    assert res["damage"] == 5 and res["save"]["saved"] is True


def test_resolve_spell_regressions():
    """Keep parser edge cases compact without hiding which case failed."""
    cases = [
        ("cure wounds", "Cure Wounds — 1d8+2 HP", [5], {"heal": True, "damage": 7}),
        ("healing word", "Healing Word — 1d4+3 HP", [4], {"heal": True, "damage": 7}),
        ("three darts", "Magic Missile — 3 darts, 1d4+1 force each", [2, 3, 1], {
            "heal": False, "damage": 9, "dice": [2, 3, 1],
        }),
        ("no dice", "Word of Censure", [1], {"damage": 0, "hit": True}),
        ("healing ignores save", "Regenerate — 4d8 HP (Con DC 12)", [1, 2, 3, 4, 20], {
            "heal": True, "damage": 10, "save": None,
        }),
        ("control spell save", "Hold Person — (Wis DC 15)", [3], {
            "damage": 0, "save.dc": 15, "save.saved": False,
        }),
        ("times sign", "Magic Missile — 3 × 1d4+1 force", [2], {
            "heal": False, "damage": 3, "dice": [2],
        }),
        ("regenerate keyword", "Regenerate — 4d8 (Con DC 12)", [1, 2, 3, 4, 20], {
            "heal": True, "damage": 10, "save": None,
        }),
        ("damage mentions hp", "Inflict Wounds — 2d8 necrotic, reduces max hp", [5, 6], {
            "heal": False, "damage": 11,
        }),
        ("zero darts", "Magic Missile — 0 darts, 1d4+1 force each", [2], {
            "heal": False, "damage": 3, "dice": [2],
        }),
    ]
    for label, attack, rolls, expected in cases:
        result = resolve_attack(dent(), attack, hobgoblin(), Seq(rolls))
        assert result["kind"] == "spell", label
        for path, value in expected.items():
            actual = result
            for key in path.split("."):
                actual = actual.get(key) if isinstance(actual, dict) else None
            assert actual == value, f"{label}: {path} was {actual!r}, expected {value!r}"


def test_resolve_critical_damage_variants():
    cases = [
        ("zero bonus", "Longsword +7 · 1d8+0 sl", [20, 3, 5], 8, [3, 5], 0),
        ("negative bonus", "Longsword +5 · 1d8-1 sl", [20, 3, 5], 7, [3, 5], -1),
        ("multiple dice", "Maul +5 · 2d6 bl", [20, 2, 3, 4, 1], 10, [2, 3, 4, 1], 0),
    ]
    for label, attack, rolls, damage, dice, bonus in cases:
        result = resolve_attack(dent(), attack, hobgoblin(), Seq(rolls))
        assert result["crit"], label
        assert (result["damage"], result["dice"], result["dice_bonus"]) == (damage, dice, bonus), label


def test_damage_and_healing_never_go_negative():
    target = hobgoblin()
    weapon = resolve_attack(dent(), "Weak Swipe +7 · 1d4-5 sl", target, Seq([10, 1]))
    spell = resolve_attack(dent(), "Weak Hex — 1d4-5 necrotic", target, Seq([1]))
    healing = resolve_attack(dent(), "Weak Cure — 1d4-5 HP", target, Seq([1]))
    assert weapon["damage"] == 0
    assert spell["damage"] == 0
    assert healing["heal"] and healing["damage"] == 0


def test_healing_can_target_self_and_downed_creatures():
    caster = Combatant("Healer", "PC", hp=4, max_hp=10, ac=10)
    downed = Combatant("Downed", "PC", hp=0, max_hp=10, ac=10)
    enemy = Combatant("Enemy", "monster", hp=5, max_hp=5, ac=10)
    combatants = [caster, downed, enemy]
    assert action_targets(combatants, caster, "Cure Wounds — 1d8+2 HP") == combatants
    assert action_targets(combatants, caster, "Longsword +4 · 1d8+2 sl") == [enemy]


def test_short_label():
    assert short_label("Goblin 2") == "G2"
    assert short_label("Syrva") == "Syr"
    assert short_label("Ogre") == "Ogr"
    assert short_label("Goblin Boss") == "Gob"
    assert short_label("") == "?"


def test_bloodied_boundary():
    c = Combatant("Target", "monster", hp=5, max_hp=10, ac=10)
    assert c.bloodied
    c.hp = 6
    assert not c.bloodied
    c.hp = 0
    assert not c.bloodied


def test_dm_screen_reference_panels_are_fixed_and_glanceable():
    from dm_screen import DM_SCREEN_PANELS, panel_text

    assert set(DM_SCREEN_PANELS) == {"numbers", "conditions", "combat", "rolls"}
    assert "HEALING POTIONS" in panel_text("numbers")
    assert "BLINDED" in panel_text("conditions")
    assert "OPPORTUNITY ATTACK" in panel_text("combat")
    assert "DC 15" in panel_text("rolls")
    assert panel_text("future") == "[dim]No reference available.[/]"


def test_coord_name():
    assert coord_name(0, 0) == "A1"
    assert coord_name(13, 7) == "N8"
    assert coord_name(26, 0) == "AA1"
    assert coord_name(51, 3) == "AZ4"
    assert coord_name(52, 0) == "BA1"
    assert coord_name(0, 9) == "A10"


def test_find_free_spot():
    a = Combatant("A", "monster", hp=1, max_hp=1, ac=10, x=2, y=0)
    b = Combatant("B", "monster", hp=1, max_hp=1, ac=10, x=1, y=0)
    # scans top-right inward, so (3,0) is free first
    assert find_free_spot([a, b], cols=4, rows=2) == (3, 0)


def test_find_free_spot_full_map_returns_none():
    filled = [
        Combatant(f"F{ix}", "monster", hp=1, max_hp=1, ac=10, x=x, y=y)
        for ix, (y, x) in enumerate((y, x) for y in range(2) for x in range(3))
    ]
    assert find_free_spot(filled, cols=3, rows=2) is None


def test_find_monster_spot_prefers_random_top_middle_band():
    spot = find_monster_spot([], cols=13, rows=20, rng=random.Random(7))
    assert spot is not None
    x, y = spot
    assert 3 <= x <= 9
    assert 0 <= y < 4


def test_find_monster_spot_falls_back_to_any_top_cell():
    occupied = [
        Combatant(f"M{index}", "monster", hp=1, max_hp=1, ac=10, x=x, y=y)
        for index, (y, x) in enumerate((y, x) for y in range(4) for x in range(3, 10))
    ]
    spot = find_monster_spot(occupied, cols=13, rows=20, rng=random.Random(7))
    assert spot is not None
    x, y = spot
    assert not (3 <= x <= 9 and 0 <= y < 4)
    assert 0 <= y < 4


def test_build_encounter_returns_fresh_clones():
    """build_encounter must not hand back the shared module singletons —
    mutating one call's result must not leak into the next."""
    from battle import build_encounter

    first = build_encounter()
    first[0].hp = 1
    first[0].conditions.add("stunned")
    second = build_encounter()
    assert first[0] is not second[0]
    assert second[0].hp == 60 and "stunned" not in second[0].conditions
    assert all(c.hp > 0 for c in second)


def test_encounter_monster_override_known_keys():
    from battle import encounter_monster

    mob = encounter_monster("Goblin", "Bob", max_hp=99, ac=13, conditions={"prone"})
    assert mob.max_hp == 99 and mob.ac == 13 and mob.conditions == {"prone"}
    assert mob.name == "Bob" and mob.role == "Small humanoid"


def test_parse_ddb_url():
    assert parse_ddb_url("https://www.dndbeyond.com/characters/9876543") == 9876543
    assert parse_ddb_url("9876543") == 9876543
    assert parse_ddb_url("https://example.com/other") is None
    assert parse_ddb_url("") is None
    assert parse_ddb_url("https://www.dndbeyond.com/characters/12345?foo=bar") == 12345


def test_parse_ddb_urls_accepts_multiline_paste_and_deduplicates():
    pasted = "\n".join([
        "https://www.dndbeyond.com/characters/12",
        "12",
        "not a character",
        "https://www.dndbeyond.com/characters/34",
        "",
    ])
    assert parse_ddb_urls(pasted) == [12, 34]


DEFAULT_STATS = {str(index): 10 for index in range(1, 7)}


def ddb_payload(name="Test", **overrides):
    """Build the stable part of a D&D Beyond response for focused parser tests."""
    character = {
        "name": name,
        "stats": dict(DEFAULT_STATS),
        "baseHitPoints": 10,
        "inventory": [],
        "modifiers": {},
    }
    character.update(overrides)
    return {"character": character}


def equipped_item(name, **definition):
    return {"equipped": True, "definition": {"name": name, **definition}}


REALISTIC = {
    "character": {
        "name": "Baldrik",
        "classes": [
            {
                "level": 3,
                "definition": {
                    "name": "Fighter",
                    "savingThrows": ["strength", "constitution"],
                },
            }
        ],
        "race": {"fullName": "Dwarf", "baseRaceName": "Dwarf"},
        "baseHitPoints": 22,
        "bonusHitPoints": 4,
        "removedHitPoints": 6,
        "stats": {"1": 16, "2": 12, "3": 15, "4": 8, "5": 10, "6": 10},
        "proficiencyBonus": 2,
        "speed": {"walk": 25},
        "hitPointDice": {"8": 3},
        "inventory": [
            {
                "equipped": True,
                "definition": {
                    "name": "Battleaxe",
                    "damage": {"diceString": "1d8", "value": 5},
                    "damageBonus": 0,
                    "damageType": "Slashing",
                    "attackType": 1,
                },
            },
            {
                "equipped": True,
                "definition": {
                    "name": "Shield",
                    "armorClass": 2,
                    "armorTypeId": 4,
                    "damage": None,
                },
            },
        ],
        "classFeatures": {"0": {"name": "Second Wind"}, "1": {"name": "Action Surge"}},
        "spells": {"0": [{"definition": {"name": "Booming Blade", "level": 0}}]},
        "modifiers": {
            "bonus": [
                {"type": "bonus", "subType": "armor-class", "fixedValue": 1, "friendlyTypeName": "Ring of Protection"}
            ],
            "proficiency": [
                {"type": "proficiency", "subType": "athletics"},
                {"type": "proficiency", "subType": "perception"},
                {"type": "expertise", "subType": "survival"},
            ],
        },
    }
}


def test_extract_combatant_realistic():
    c = extract_combatant(424242, REALISTIC)
    assert c.name == "Baldrik" and c.kind == "PC"
    assert c.role == "Fighter 3"
    assert c.max_hp == 22 + 4 + 2 * 3 and c.hp == c.max_hp - 6   # +CON per level
    assert c.level == 3
    assert c.ac == 10 + 2 + 1 + 1                                  # shield + dex + bonus
    assert c.init_mod == 1                                         # DEX 12
    assert c.saves == {1, 3}                                       # STR + CON
    assert c.skills == {"athletics": 5, "perception": 2, "survival": 4}
    assert c.passive_perception == 12
    assert c.speed == 25 and c.hit_dice == "3d8"
    assert c.attacks[0].startswith("Battleaxe +5 · 1d8+3"), c.attacks
    assert c.spells == ["Booming Blade"]
    assert any("racial traits" in t for t in c.traits) and "Second Wind" in c.traits
    assert "Fighter 3" in c.note and "Imported from D&D Beyond" in c.note
    assert "STR" not in c.note


def test_extract_combatant_sparse():
    c = extract_combatant(7, {})
    assert c.name == "Char 7"
    assert c.role == "Level 1 Adventurer"
    assert c.hp == 15 and c.max_hp == 15
    assert c.ac == 10 and c.init_mod == 0
    assert c.stats == {i: 10 for i in range(1, 7)}
    assert c.attacks == [] and c.spells == [] and c.traits == []


def test_extract_combatant_stats_int_list():
    c = extract_combatant(1, ddb_payload("Hasty", stats=[15, 14, 13, 12, 10, 8]))
    assert c.init_mod == 2 and c.stats[1] == 15 and c.stats[6] == 8


def test_extract_combatant_weapon_without_attack_fields_skipped():
    data = ddb_payload("Plain", inventory=[equipped_item("Lantern", damage=None)])
    c = extract_combatant(2, data)
    assert c.attacks == []


def test_extract_combatant_spell_without_definition():
    data = ddb_payload(
        "Sparrow",
        spells={"0": [{"definition": None}, {"definition": {"name": "Cure Wounds"}}]},
    )
    c = extract_combatant(3, data)
    assert c.spells == ["Cure Wounds"]


def test_extract_combatant_multi_hit_dice():
    c = extract_combatant(4, ddb_payload("Dicey", hitPointDice={"8": 3, "6": 2}))
    assert c.hit_dice == "3d8, 2d6"


def test_extract_combatant_hit_dice_sorted_descending():
    # Inserted smallest-first; output must still be largest-die-first.
    c = extract_combatant(4, ddb_payload("Dicey", hitPointDice={"6": 2, "8": 3}))
    assert c.hit_dice == "3d8, 2d6"


def test_extract_combatant_stats_dict_unordered():
    data = ddb_payload("Muddled", stats={"6": 8, "1": 15, "3": 12, "5": 10, "4": 10, "2": 14})
    c = extract_combatant(5, data)
    assert c.init_mod == 2 and c.stats[1] == 15 and c.stats[6] == 8
    assert c.stats == {1: 15, 2: 14, 3: 12, 4: 10, 5: 10, 6: 8}


def test_extract_combatant_armor_type_id_as_string():
    data = ddb_payload(
        "Bouncy",
        stats={**DEFAULT_STATS, "2": 12},
        inventory=[equipped_item("Shield", armorClass=2, armorTypeId="4")],
    )
    c = extract_combatant(6, data)
    assert c.ac == 10 + 1 + 2  # 10 + DEX + shield (armorTypeId came back as a string)


def test_extract_combatant_attack_bonus_trusted():
    data = ddb_payload(
        "Vexed",
        inventory=[equipped_item(
            "Flame Tongue", damage={"diceString": "2d6"}, damageType="Fire", attackBonus=9,
        )],
    )
    c = extract_combatant(7, data)
    assert c.attacks[0].startswith("Flame Tongue +9 · 2d6"), c.attacks


def test_extract_combatant_negative_attack_bonus_renders():
    data = ddb_payload(
        "Vexed",
        stats={**DEFAULT_STATS, "1": 16},
        inventory=[equipped_item(
            "Cursed Blade", damage={"diceString": "1d8"}, damageType="Slashing", attackBonus=-2,
        )],
    )
    c = extract_combatant(7, data)
    assert c.attacks[0].startswith("Cursed Blade -2 · 1d8"), c.attacks


def test_extract_combatant_damage_bonus_not_double_counted_to_hit():
    data = ddb_payload(
        "Smash",
        stats={**DEFAULT_STATS, "1": 16},
        proficiencyBonus=2,
        inventory=[equipped_item(
            "Greataxe", damage={"diceString": "1d12"}, damageType="Slashing", damageBonus=3,
        )],
    )
    c = extract_combatant(7, data)
    # the flat +3 damage bonus helps damage, not the to-hit roll
    assert c.attacks[0].startswith("Greataxe +5 · 1d12+6"), c.attacks


def test_extract_combatant_explicit_zero_attack_bonus_trusted():
    data = ddb_payload(
        "Weird",
        stats={**DEFAULT_STATS, "1": 16},
        proficiencyBonus=2,
        inventory=[equipped_item(
            "Weapon", damage={"diceString": "1d6"}, damageType="Bludgeoning", attackBonus=0,
        )],
    )
    c = extract_combatant(9, data)
    assert c.attacks[0].startswith("Weapon +0 · 1d6"), c.attacks


def test_extract_combatant_heavy_armor_ignores_negative_dex():
    data = ddb_payload(
        "Plod",
        stats={**DEFAULT_STATS, "2": 6},
        inventory=[equipped_item("Plate", armorClass=18, armorTypeId=3)],
    )
    c = extract_combatant(9, data)
    assert c.ac == 18, c.ac  # heavy armour ignores DEX entirely, even a -2 penalty


def test_extract_combatant_hit_dice_non_numeric_keys_filtered():
    dice = {"8": 3, "6": 2, "foo": 2, "d10": 1}
    c = extract_combatant(4, ddb_payload("Dicey", hitPointDice=dice))
    assert c.hit_dice == "3d8, 2d6"


def test_extract_combatant_negative_removed_hp_clamped():
    stats = {**DEFAULT_STATS, "1": 16, "3": 14}
    c = extract_combatant(8, ddb_payload("Hearty", stats=stats, removedHitPoints=-5))
    assert c.hp == c.max_hp  # a negative 'removed' value must not push hp above max


def test_extract_combatant_ignores_malformed_external_collection_rows():
    data = ddb_payload(
        "Resilient",
        classes=["bad class", {"level": 2, "definition": {"name": "Cleric"}}],
        inventory=[None, "bad item"],
        modifiers={"bonus": ["bad modifier", None]},
    )
    c = extract_combatant(10, data)
    assert c.name == "Resilient" and c.role == "Cleric 2"
    assert c.attacks == [] and c.ac == 10


def test_extract_combatant_ignores_mixed_stat_rows():
    data = ddb_payload(
        "Mixed Stats",
        stats=[{"id": 1, "value": 12}, "bad stat", {"id": 3, "value": 14}],
    )
    c = extract_combatant(11, data)
    assert c.stats == {1: 12, 2: 10, 3: 14, 4: 10, 5: 10, 6: 10}
    assert c.init_mod == 0


def test_fetch_character_data_network_error_raises_value_error():
    with mock.patch.object(urllib.request, "urlopen", side_effect=urllib.error.URLError("boom")):
        try:
            fetch_character_data(999999)
        except ValueError as exc:
            assert "reach" in str(exc)
        else:
            raise AssertionError("URLError should be wrapped in ValueError")


class _Resp:
    """Minimal urllib response stand-in for fetch tests."""

    def __init__(self, body: bytes):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_character_data_non_json_body_wrapped():
    with mock.patch.object(urllib.request, "urlopen", return_value=_Resp(b"<html>oops</html>")):
        try:
            fetch_character_data(999999)
        except ValueError as exc:
            assert "non-JSON body" in str(exc)
        else:
            raise AssertionError("a non-JSON 200 body should be wrapped in ValueError")


def test_fetch_character_data_http_error_non_json_body():
    import io

    err = urllib.error.HTTPError("http://x", 404, "Not Found", {}, io.BytesIO(b"<html>oops</html>"))
    with mock.patch.object(urllib.request, "urlopen", side_effect=err):
        try:
            fetch_character_data(999999)
        except ValueError as exc:
            assert "404" in str(exc)
        else:
            raise AssertionError("HTTPError should be wrapped in ValueError")


def test_fetch_character_data_invalid_utf8_wrapped():
    with mock.patch.object(urllib.request, "urlopen", return_value=_Resp(b"\xff\xfe\x00 garbage")):
        try:
            fetch_character_data(999999)
        except ValueError as exc:
            assert "non-JSON body" in str(exc)
        else:
            raise AssertionError("an invalid-UTF-8 body should be wrapped in ValueError")


def test_monster_templates_are_well_formed():
    """Every library template builds a sane Combatant via encounter_monster."""
    from battle import MONSTERS, encounter_monster

    assert len(MONSTERS) >= 15, len(MONSTERS)
    for name, t in MONSTERS.items():
        c = encounter_monster(name, name)
        assert c.name == name and c.kind == "monster"
        assert c.max_hp > 0 and c.ac >= 0
        assert isinstance(c.attacks, list) and c.attacks, (name, c.attacks)
        assert c.role and c.stats
        assert c.init is None and c.init_mod is not None


def test_monster_names_unique():
    from battle import MONSTERS

    assert len(set(MONSTERS)) == len(MONSTERS)


def test_combatant_snap_json_roundtrip():
    """Snapshots survive a JSON save/load: ability-score keys come back as
    strings and must be re-normalised to ints before use (regression)."""
    import json

    from app import BattleApp

    app = BattleApp()
    c = Combatant(
        name="Test", kind="PC", hp=12, max_hp=12, ac=15,
        stats={1: 19, 2: 10, 3: 12, 4: 10, 5: 10, 6: 10},
        saves={1}, proficiency=3,
    )
    loaded = json.loads(json.dumps(app._combatant_snap(c)))
    assert all(isinstance(k, str) for k in loaded["stats"])
    norm = {int(k): v for k, v in loaded["stats"].items()}
    restored = Combatant(**{**loaded, "stats": norm})
    restored.conditions = set(loaded.get("conditions", []))
    restored.saves = set(loaded.get("saves", []))
    assert restored.mod(1) == 4          # STR 19
    assert restored.save(1) == 7         # STR save is proficient (+3 prof)


def test_combatant_snapshot_preserves_turn_reminder():
    from app import BattleApp

    c = Combatant("Test", "PC", hp=12, max_hp=12, ac=15, reminder="WIS save DC 14")
    app = BattleApp()
    loaded = app._combatant_snap(c)
    assert loaded["reminder"] == "WIS save DC 14"


def test_party_context_includes_levels_and_strength_signals():
    from app import BattleApp

    app = BattleApp()
    app.combatants = [
        Combatant(
            "Fighter", "PC", hp=28, max_hp=32, ac=18, level=5, proficiency=3,
            role="Human Fighter 5", attacks=["Longsword +7 · 1d8+4 sl"],
        ),
        Combatant(
            "Wizard", "PC", hp=16, max_hp=20, ac=14, level=5, proficiency=3,
            role="Elf Wizard 5", spell_dc=15,
        ),
    ]
    context = app._party_context()
    assert "levels 5, 5" in context
    assert "total HP 44/52" in context
    assert "AC 14-18" in context
    assert "attack bonuses +7 to +7" in context
    assert "spell DCs 15" in context


def test_openai_response_preserves_compact_line_breaks():
    response = _Resp(json.dumps({
        "choices": [{"message": {"content": "Line one\nLine two\n\n\nLine three"}}]
    }).encode())
    with mock.patch.object(urllib.request, "urlopen", return_value=response):
        answer = openai_client.chat(
            "question", "context", config={"api_key": "test", "url": "https://example.test"}
        )
    assert answer == "Line one\nLine two\n\nLine three"


def test_openai_encounter_plan_uses_catalog_only_structured_output():
    response = _Resp(json.dumps({
        "choices": [{"message": {"content": json.dumps({
            "title": "Corrupted Order",
            "theme": "fallen knights",
            "pressure": "High",
            "monsters": [{"name": "Knight", "count": 2}],
        })}}]
    }).encode())
    requests = []

    def fake_urlopen(request, **_kwargs):
        requests.append(json.loads(request.data.decode()))
        return response

    with mock.patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        plan = openai_client.plan_encounter(
            "hard fight against corrupted knights",
            ["Knight", "Veteran"],
            "4 PCs; level unknown",
            config={"api_key": "test", "url": "https://example.test"},
        )
    assert plan["monsters"] == [{"name": "Knight", "count": 2}]
    assert plan["pressure"] == "High"
    schema = requests[0]["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert "Knight" in requests[0]["messages"][1]["content"]


def test_openai_config_layers_dotenv_and_local_options():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "llm_config.json")
        local_path = os.path.join(tmp, "llm_config.local.json")
        env_path = os.path.join(tmp, ".env")
        with open(path, "w", encoding="utf-8") as config_file:
            json.dump({"model": "base", "options": {"temperature": 0.1, "max_tokens": 80}}, config_file)
        with open(local_path, "w", encoding="utf-8") as local_file:
            json.dump({"model": "local", "options": {"max_tokens": 120}}, local_file)
        with open(env_path, "w", encoding="utf-8") as env_file:
            env_file.write('WARD_TEST_KEY="from file"\n')
        with mock.patch.dict(os.environ, {}, clear=True):
            config = openai_client.load_config(path)
            assert os.environ["WARD_TEST_KEY"] == "from file"
    assert config == {"model": "local", "options": {"temperature": 0.1, "max_tokens": 120}}


def test_openai_shared_response_errors_are_normalized():
    config = {"api_key": "test", "url": "https://example.test"}
    failures = [
        (urllib.error.URLError("offline"), "not reachable"),
        (_Resp(b"not json"), "invalid JSON"),
        (_Resp(json.dumps({"choices": []}).encode()), "empty answer"),
    ]
    for response, expected in failures:
        patch = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
        with mock.patch.object(urllib.request, "urlopen", **patch):
            try:
                openai_client.chat("question", "context", config=config)
            except RuntimeError as exc:
                assert expected in str(exc), (expected, str(exc))
            else:
                raise AssertionError(f"expected {expected!r} error")


def test_modified_bindings_use_one_ctrl_only_grammar():
    from app import BattleApp

    bindings = {binding.key: binding.action for binding in BattleApp.BINDINGS}
    assert {key: action for key, action in bindings.items() if key.startswith("ctrl+")} == {
        "ctrl+1": "combat_view",
        "ctrl+2": "dm_screen",
        "ctrl+3": "party_view",
        "ctrl+b": "browse",
        "ctrl+e": "encounter_templates",
        "ctrl+g": "ai_encounter",
        "ctrl+k": "music",
        "ctrl+n": "new_encounter",
        "ctrl+o": "campaign",
        "ctrl+q": "quit",
        "ctrl+r": "reset",
        "ctrl+t": "initiative_pass",
        "ctrl+y": "redo",
        "ctrl+z": "undo",
    }
    assert "q" not in bindings
    assert "ctrl+i" not in bindings and "ctrl+m" not in bindings  # terminal aliases for Tab / Enter
    assert not any(
        key.startswith("shift+") or (len(key) == 1 and key.isupper())
        for binding in BattleApp.BINDINGS
        for key in binding.key.split(",")
    )


def test_panel_key_hints_keep_only_the_local_working_set():
    from app import BattleApp, hint

    app = BattleApp()
    assert all(key in app._map_status_text().plain for key in ("↑↓", "←→", "g"))
    assert all(key in app._init_status_text().plain for key in ("n", "r", "t"))
    assert "Ctrl+T" not in app._init_status_text().plain
    assert all(key in app._log_status_text().plain for key in ("Ctrl+Z", "Ctrl+Y"))
    assert all(key in app._detail_status_text().plain for key in ("a", "d", "h", "c"))
    assert "Ctrl+O" not in app._detail_status_text().plain
    assert hint("n", "next turn").plain == "next turn"
    assert hint("ctrl+n", "new encounter").plain == "Ctrl+N new encounter"


def test_music_config_keeps_sources_swappable_and_validated():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "music.json")
        with open(path, "w", encoding="utf-8") as config_file:
            json.dump({
                "backend": "ffplay",
                "volume": 42,
                "sources": [
                    {"name": "Tavern", "url": "https://audio.example/tavern.m3u", "note": "Low chatter"},
                    {"name": "Dungeon", "url": "https://audio.example/dungeon.mp3"},
                ],
            }, config_file)
        config = music.load_config(path)
        assert (config.backend, config.volume) == ("ffplay", 42)
        assert [source.name for source in config.sources] == ["Tavern", "Dungeon"]
        assert config.sources[0].url.endswith("tavern.m3u")

        with open(path, "w", encoding="utf-8") as config_file:
            json.dump({"backend": "browser", "sources": []}, config_file)
        try:
            music.load_config(path)
        except ValueError as exc:
            assert "backend" in str(exc).lower()
        else:
            raise AssertionError("unsupported music backends must be rejected")


def test_music_player_uses_an_argument_list_and_owns_playback():
    class FakeProcess:
        def __init__(self):
            self.done = False
            self.signals = []
            self.terminated = False

        def poll(self):
            return 0 if self.done else None

        def send_signal(self, value):
            self.signals.append(value)

        def terminate(self):
            self.terminated = True
            self.done = True

        def wait(self, timeout):
            return 0

        def kill(self):
            self.done = True

    calls = []
    process = FakeProcess()

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    player = music.MusicPlayer(
        backend="auto",
        volume=37,
        which=lambda name: "/usr/bin/mpv" if name == "mpv" else None,
        popen=fake_popen,
    )
    source = music.MusicSource("Dungeon", "https://audio.example/dungeon.m3u")
    assert player.play(source) == "mpv"
    command, kwargs = calls[0]
    assert command[-1] == source.url and "--volume=37" in command
    assert "shell" not in kwargs and kwargs["start_new_session"] is True
    assert player.source == source and player.active_backend == "mpv"
    assert player.toggle_pause() is True
    assert player.toggle_pause() is False
    player.stop()
    assert process.terminated and not player.active and player.source is None


def test_music_pause_failure_does_not_corrupt_player_state():
    class FailingProcess:
        def poll(self):
            return None

        def send_signal(self, _value):
            raise OSError("player disappeared")

    player = music.MusicPlayer()
    player._process = FailingProcess()
    player._source = music.MusicSource("Dungeon", "https://audio.example/dungeon.m3u")
    try:
        player.toggle_pause()
    except RuntimeError as exc:
        assert "could not pause" in str(exc)
    else:
        raise AssertionError("pause process failures must be normalized")
    assert player.active and not player.paused


def test_music_nav_display_distinguishes_silent_playing_and_paused():
    from app import _music_nav_display

    class Player:
        source = None
        paused = False

    player = Player()
    assert _music_nav_display(player) == ("♫", "silent")
    player.source = music.MusicSource("Dungeon", "https://audio.example/dungeon.m3u")
    assert _music_nav_display(player) == ("♫  Dungeon", "playing")
    player.paused = True
    assert _music_nav_display(player) == ("Ⅱ  Dungeon", "paused")


def test_atomic_json_write_preserves_existing_data_on_failure():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "state.json")
        persistence.write_json_atomic(path, {"state": "before"}, indent=2)

        with mock.patch.object(persistence.json, "dump", side_effect=RuntimeError("broken encoder")):
            try:
                persistence.write_json_atomic(path, {"state": "after"}, indent=2)
            except RuntimeError as exc:
                assert "broken encoder" in str(exc)
            else:
                raise AssertionError("a failed JSON write must propagate its error")

        with open(path, encoding="utf-8") as state_file:
            assert json.load(state_file) == {"state": "before"}
        assert not os.path.exists(f"{path}.tmp")


def test_saved_campaigns_put_active_first_and_keep_empty_campaigns():
    from app import BattleApp

    data = {
        "active": "Zither Club",
        "campaigns": {
            "Empty": {"character_ids": []},
            "Alpha Team": {"character_ids": [1]},
            "Zither Club": {"character_ids": [2, "3"]},
        },
    }
    assert BattleApp()._saved_campaigns(data) == [
        ("Zither Club", 2),
        ("Alpha Team", 1),
        ("Empty", 0),
    ]


def test_campaign_book_migrates_legacy_ids_and_keeps_manual_members():
    book = campaign_store.normalize_book({
        "active": "Lost Mine",
        "campaigns": {
            "Lost Mine": {
                "character_ids": [12, "34", 12],
                "ruleset": "2014",
                "notes": "Find Gundren",
            },
            "Manual Game": {
                "party": [{"name": "Borin"}, {"name": "borin"}, {"ddb_id": 56, "name": "Nix"}],
                "ruleset": "2024",
            },
        },
    })
    assert book["version"] == 2
    assert book["campaigns"]["Lost Mine"]["party"] == [{"ddb_id": 12}, {"ddb_id": 34}]
    assert "character_ids" not in book["campaigns"]["Lost Mine"]
    assert book["campaigns"]["Manual Game"]["party"] == [
        {"name": "Borin"},
        {"name": "Nix", "ddb_id": 56},
    ]


def test_campaign_book_roundtrip_preserves_campaign_owned_party():
    data = {
        "active": "Stone Sea",
        "campaigns": {
            "Stone Sea": {
                "party": [{"name": "Mara"}, {"name": "Tovin", "ddb_id": 91}],
                "ruleset": "2024",
                "notes": "North wind",
            }
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "campaigns.json")
        campaign_store.write_book(path, data)
        loaded = campaign_store.read_book(path)
    assert campaign_store.party_for(loaded, "Stone Sea") == data["campaigns"]["Stone Sea"]["party"]
    assert loaded["campaigns"]["Stone Sea"]["notes"] == "North wind"


def test_campaign_book_sanitizes_malformed_state():
    assert campaign_store.normalize_book(None) == campaign_store.empty_book()
    assert campaign_store.normalize_book({"campaigns": []}) == campaign_store.empty_book()

    book = campaign_store.normalize_book({
        "active": "missing",
        "campaigns": {
            "": {},
            "Broken": "not a campaign",
            "  Keepers  ": {
                "party": [
                    None, "", True, 0, -1, "0", "  Borin  ",
                    {"ddb_id": "12"}, {"ddb_id": "12"}, {"ddb_id": False},
                ],
                "ruleset": None,
                "notes": None,
            },
        },
    })
    assert book == {
        "version": 2,
        "active": "Keepers",
        "campaigns": {
            "Keepers": {
                "party": [{"name": "Borin"}, {"ddb_id": 12}],
                "ruleset": "2014",
                "notes": "",
            }
        },
    }
    assert campaign_store.party_for(book, "missing") == []

    with tempfile.TemporaryDirectory() as tmp:
        invalid_path = os.path.join(tmp, "campaigns.json")
        with open(invalid_path, "w", encoding="utf-8") as campaign_file:
            campaign_file.write("not json")
        assert campaign_store.read_book(invalid_path) == campaign_store.empty_book()


def test_startup_menu_is_onboarding_when_campaign_book_is_empty():
    from app import BattleApp

    options, prompt, subtitle = BattleApp()._startup_menu(campaign_store.empty_book(), None, 0)
    assert [key for key, _label in options] == ["setup", "sample", "blank", "quit"]
    assert prompt == "Open your DM folio"
    assert subtitle == "Track initiative, HP, conditions, and campaign notes in one place."

    options, _prompt, _subtitle = BattleApp()._startup_menu(campaign_store.empty_book(), None, 2)
    assert [key for key, _label in options] == ["setup", "sample", "blank", "data", "quit"]


def test_returning_startup_prioritizes_resume_and_hides_empty_prepared_action():
    from app import BattleApp

    data = campaign_store.normalize_book({
        "active": "Lost Mine",
        "campaigns": {
            "Lost Mine": {"party": [{"name": "Borin"}], "ruleset": "2024"},
        },
    })
    current = {
        "id": "abc",
        "name": "Cragmaw Hideout",
        "campaign": "Lost Mine",
        "snapshot": {"round": 3, "combatants": [{}, {}]},
    }
    app = BattleApp()
    with mock.patch.object(app, "_encounter_records", return_value=[current]):
        options, prompt, subtitle = app._startup_menu(data, current, 0)
    keys = [key for key, _label in options]
    assert keys[0] == "resume"
    assert "run:Lost Mine" in keys and "prepare:Lost Mine" in keys
    assert "prepared" not in keys and "campaigns" not in keys
    assert prompt == "Resume, run, or prepare"
    assert "1 adventurer" in subtitle


def test_manual_campaign_member_builds_a_fresh_default_pc():
    from app import BattleApp

    pc = BattleApp()._manual_pc("Borin")
    assert (pc.name, pc.kind, pc.hp, pc.max_hp, pc.ac, pc.ddb_id) == ("Borin", "PC", 10, 10, 10, None)


def test_campaign_created_from_table_keeps_imported_and_manual_party_members():
    from app import BattleApp

    refs = BattleApp._party_refs_from_combatants([
        Combatant("Lyra", "PC", hp=20, max_hp=20, ac=15, ddb_id=123),
        Combatant("Borin", "PC", hp=10, max_hp=10, ac=10),
        Combatant("Goblin", "monster", hp=7, max_hp=7, ac=15),
    ])
    assert refs == [{"name": "Lyra", "ddb_id": 123}, {"name": "Borin"}]


def test_live_encounter_is_remembered_with_campaign_context():
    import app as appmod
    from app import BattleApp

    app = BattleApp()
    app._session_started = True
    app._session_campaign = "Lost Mine"
    app._session_encounter_name = "Goblin Cave"
    app.combatants = [Combatant("Goblin", "monster", hp=7, max_hp=7, ac=15)]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "campaign-encounters.json")
        legacy_path = os.path.join(tmp, "missing-legacy.json")
        with mock.patch.object(appmod, "CAMPAIGN_ENCOUNTERS_PATH", path), mock.patch.object(appmod, "SAVE_PATH", legacy_path):
            assert app._remember_current_encounter()
            remembered = app._current_encounter_read()
            store = encounter_store.read_store(path)
    assert remembered is not None
    assert remembered["version"] == 3
    assert remembered["campaign"] == "Lost Mine"
    assert remembered["encounter_name"] == "Goblin Cave"
    assert remembered["combatants"][0]["name"] == "Goblin"
    assert len(store["encounters"]) == 1


def test_encounter_store_keeps_many_fights_per_campaign_and_one_current():
    data = encounter_store.empty_store()
    records = []
    for i in range(10):
        records.append(encounter_store.create_record(
            data,
            "Lost Mine",
            f"Encounter {i + 1}",
            {"combatants": [], "round": i + 1},
        ))
    assert len(data["encounters"]) == 10
    assert encounter_store.current_for(data, "Lost Mine")["name"] == "Encounter 10"
    assert sum(record["status"] == "active" for record in records) == 1
    assert all(record["status"] == "paused" for record in records[:-1])
    ordered = encounter_store.records_for(data, "Lost Mine")
    assert ordered[0]["name"] == "Encounter 10"


def test_encounter_store_tracks_current_fight_per_campaign():
    data = encounter_store.empty_store()
    lost = encounter_store.create_record(data, "Lost Mine", "Cragmaw", {"combatants": [], "round": 2})
    curse = encounter_store.create_record(data, "Curse of Strahd", "Death House", {"combatants": [], "round": 1})
    assert encounter_store.current_for(data, "Lost Mine")["id"] == lost["id"]
    assert encounter_store.current_for(data, "Curse of Strahd")["id"] == curse["id"]
    assert lost["status"] == "active" and curse["status"] == "active"


def test_encounter_store_repairs_malformed_state():
    snapshot = {"combatants": [], "round": 2}
    assert encounter_store.normalize_store(None) == encounter_store.empty_store()
    data = encounter_store.normalize_store({
        "last_active": "missing",
        "current": {encounter_store.NO_CAMPAIGN: "kept", "bad": "missing"},
        "encounters": {
            "": {"snapshot": snapshot},
            "kept": {
                "campaign": 42,
                "name": "  ",
                "status": "unexpected",
                "snapshot": snapshot,
                "source_template": 99,
            },
            "stray": {"campaign": "Keepers", "status": "active", "snapshot": snapshot},
            "broken": {"snapshot": "not a snapshot"},
            "missing-fields": {"snapshot": {"combatants": [{"name": "Goblin"}]}},
        },
    })
    assert set(data["encounters"]) == {"kept", "stray"}
    assert data["current"] == {encounter_store.NO_CAMPAIGN: "kept"}
    assert data["last_active"] == "kept"
    assert data["encounters"]["kept"]["snapshot"] == snapshot
    assert data["encounters"]["kept"]["name"] == "Untitled encounter"
    assert data["encounters"]["kept"]["campaign"] is None
    assert data["encounters"]["kept"]["status"] == "active"
    assert data["encounters"]["kept"]["source_template"] == "99"
    assert data["encounters"]["stray"]["status"] == "paused"


def test_encounter_store_repairs_current_scope_from_record_ownership():
    snapshot = {"combatants": [], "round": 1}
    data = encounter_store.normalize_store({
        "current": {"Wrong Campaign": "right-fight"},
        "encounters": {
            "right-fight": {
                "campaign": "Right Campaign",
                "status": "active",
                "updated_at": "2026-08-17T12:00:00+00:00",
                "snapshot": snapshot,
            },
        },
    })
    assert encounter_store.current_for(data, "Wrong Campaign") is None
    assert encounter_store.current_for(data, "Right Campaign")["id"] == "right-fight"


def test_encounter_store_collapses_blank_campaign_ownership():
    snapshot = {"combatants": [], "round": 1}
    data = encounter_store.normalize_store({
        "current": {"": "loose-fight"},
        "encounters": {
            "loose-fight": {"campaign": "", "status": "active", "snapshot": snapshot},
            "named-fight": {"campaign": "  Keepers  ", "status": "paused", "snapshot": snapshot},
        },
    })
    assert data["encounters"]["loose-fight"]["campaign"] is None
    assert encounter_store.current_for(data, None)["id"] == "loose-fight"
    assert encounter_store.records_for(data, None)[0]["id"] == "loose-fight"
    assert data["encounters"]["named-fight"]["campaign"] == "Keepers"

    created = encounter_store.create_record(data, "   ", "Another", snapshot)
    assert created["campaign"] is None


def test_encounter_store_updates_and_rejects_missing_records():
    data = encounter_store.empty_store()
    record = encounter_store.create_record(
        data, "Keepers", "Goblin Road", {"combatants": [], "round": 1}, source_template="Road Ambush",
    )
    updated = {"combatants": [{"name": "Goblin"}], "round": 3}
    assert record["source_template"] == "Road Ambush"
    assert encounter_store.update_record(data, record["id"], updated)
    assert record["snapshot"] == updated
    assert encounter_store.activate_record(data, "missing") is None
    assert not encounter_store.update_record(data, "missing", updated)
    assert not encounter_store.complete_record(data, "missing")
    assert not encounter_store.rename_record(data, "missing", "Name")
    assert not encounter_store.move_record(data, "missing", None)


def test_completed_encounter_stays_archived_and_can_be_reactivated():
    data = encounter_store.empty_store()
    record = encounter_store.create_record(data, "Lost Mine", "Goblin Ambush", {"combatants": [], "round": 4})
    assert encounter_store.complete_record(data, record["id"])
    assert record["status"] == "complete"
    assert encounter_store.current_for(data, "Lost Mine") is None
    encounter_store.activate_record(data, record["id"])
    assert record["status"] == "active"


def test_encounter_can_be_renamed_and_moved_into_a_campaign():
    data = encounter_store.empty_store()
    record = encounter_store.create_record(data, None, "Loose Fight", {"combatants": [], "round": 1})
    assert encounter_store.rename_record(data, record["id"], "Session Zero")
    assert encounter_store.move_record(data, record["id"], "Lost Mine")
    assert record["name"] == "Session Zero"
    assert record["campaign"] == "Lost Mine"
    assert encounter_store.current_for(data, None) is None
    assert encounter_store.current_for(data, "Lost Mine")["id"] == record["id"]


def test_legacy_resume_point_migrates_into_encounter_store():
    import app as appmod
    from app import BattleApp

    legacy = {
        "version": 2,
        "campaign": "Lost Mine",
        "combatants": [{"name": "Goblin", "kind": "monster", "hp": 7, "max_hp": 7, "ac": 15}],
        "round": 3,
    }
    with tempfile.TemporaryDirectory() as tmp:
        legacy_path = os.path.join(tmp, "encounter.json")
        store_path = os.path.join(tmp, "campaign-encounters.json")
        with open(legacy_path, "w", encoding="utf-8") as legacy_file:
            json.dump(legacy, legacy_file)
        with mock.patch.object(appmod, "SAVE_PATH", legacy_path), mock.patch.object(appmod, "CAMPAIGN_ENCOUNTERS_PATH", store_path):
            record = BattleApp()._last_encounter_record()
    assert record is not None
    assert record["name"] == "Recovered encounter"
    assert record["campaign"] == "Lost Mine"
    assert record["snapshot"]["round"] == 3


def test_removing_active_combatant_advances_to_the_actual_successor():
    from app import BattleApp

    def remove_at(index: int):
        app = BattleApp()
        app.combatants = [
            Combatant(name, "monster", hp=5, max_hp=5, ac=10)
            for name in ("A", "B", "C")
        ]
        app.round = 4
        app._turn = app.combatants[index]
        app._sel = app._turn
        app._log = lambda *_args, **_kwargs: None
        app._rebuild_rows = lambda: None
        app._remove_combatant(app._turn)
        return [c.name for c in app.combatants], app._turn.name, app.round

    assert remove_at(0) == (["B", "C"], "B", 4)
    assert remove_at(1) == (["A", "C"], "C", 4)
    assert remove_at(2) == (["A", "B"], "A", 5)


def test_removing_combatant_outside_turn_order_does_not_start_combat():
    from app import BattleApp

    app = BattleApp()
    app.combatants = [
        Combatant(name, "monster", hp=5, max_hp=5, ac=10)
        for name in ("A", "B", "C")
    ]
    app._sel = app.combatants[1]
    app._log = lambda *_args, **_kwargs: None
    app._rebuild_rows = lambda: None
    app._remove_combatant(app._sel)
    assert app._turn is None
    assert app._sel.name == "C"


def test_unknown_restored_condition_remains_renderable():
    from app import BattleApp

    app = BattleApp()
    app.combatants = [Combatant(
        "Scout", "PC", hp=8, max_hp=10, ac=14,
        conditions={"future-condition"},
    )]
    app._sel = app.combatants[0]
    markup = app._detail_markup()
    assert "? future-condition" in markup


def test_ward_backup_roundtrip_restores_all_user_data():
    campaigns = campaign_store.normalize_book({
        "active": "Keepers",
        "campaigns": {"Keepers": {"party": [{"name": "Borin"}], "notes": "Gate code", "ruleset": "2014"}},
    })
    encounters = encounter_store.empty_store()
    encounter_store.create_record(encounters, "Keepers", "North Gate", {"combatants": [], "round": 3})
    templates = {"templates": {"Road Ambush": {"snapshot": {"combatants": []}}}}

    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = os.path.join(tmp, "backups")
        backup_path = ward_backup.write_backup(backup_dir, campaigns, encounters, templates)
        assert ward_backup.list_backups(backup_dir) == [backup_path]

        campaign_path = os.path.join(tmp, "campaigns.json")
        encounter_path = os.path.join(tmp, "campaign-encounters.json")
        template_path = os.path.join(tmp, "encounters.json")
        restored = ward_backup.restore_backup(backup_path, campaign_path, encounter_path, template_path)
        assert restored["format"] == "ward-data-backup"
        assert campaign_store.read_book(campaign_path) == campaigns
        assert encounter_store.read_store(encounter_path) == encounter_store.normalize_store(encounters)
        with open(template_path, encoding="utf-8") as template_file:
            assert json.load(template_file) == templates


def test_ward_backup_rejects_unrelated_json():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "not-ward.json")
        with open(path, "w", encoding="utf-8") as backup_file:
            json.dump({"version": 1}, backup_file)
        try:
            ward_backup.read_backup(path)
        except ValueError as exc:
            assert "not a Ward data backup" in str(exc)
        else:
            raise AssertionError("unrelated JSON should not be restored")


# ---------------------------------------------------------------------------
# Open5e SRD integration
# ---------------------------------------------------------------------------

import srd as srd_client

GOBLIN_SRD = {
    "name": "Goblin",
    "size": "Small",
    "type": "humanoid",
    "armor_class": 15,
    "hit_points": 7,
    "hit_dice": "2d6",
    "ability_scores": {"strength": 8, "dexterity": 14, "constitution": 10,
                       "intelligence": 10, "wisdom": 8, "charisma": 8},
    "initiative_bonus": 2,
    "saving_throws": {},
    "skill_bonuses": {"stealth": 6},
    "speed": {"walk": 30, "unit": "feet"},
    "proficiency_bonus": None,
    "passive_perception": None,
    "challenge_rating": 0.25,
    "desc": "A small humanoid that hates sunlight. It scuttles in the dark.",
    "actions": [
        {"name": "Scimitar",
         "desc": "Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage."},
        {"name": "Shortbow",
         "desc": "Ranged Weapon Attack: +4 to hit, range 80 ft., one target. Hit: 5 (1d6 + 2) piercing damage."},
        {"name": "Fire Breath",
         "desc": "The goblin exhales fire. Each creature in a 15-foot cone must make a DC 13 Dexterity saving throw, taking 21 (6d6) fire damage on a failed save."},
        {"name": "Multiattack",
         "desc": "The goblin makes two attacks."},
    ],
    "traits": ["Nimble Escape"],
}


def test_srd_monster_to_fields():
    f = srd_client.srd_monster_to_fields(GOBLIN_SRD)
    assert f["ac"] == 15 and f["max_hp"] == 7 and f["hp"] == 7
    assert f["stats"][2] == 14 and f["init_mod"] == 2
    assert f["role"] == "Small humanoid"
    assert f["proficiency"] == 2  # CR 0.25 -> +2
    assert any(a.startswith("Scimitar +4 · 1d6+2 sl") for a in f["attacks"]), f["attacks"]
    assert any(a.startswith("Shortbow +4 · 1d6+2 pi") for a in f["attacks"]), f["attacks"]
    # save-DC spell-like action -> spell line with a save hint
    assert any("Fire Breath" in a and "fire" in a and "dex DC 13" in a for a in f["attacks"]), f["attacks"]
    # plain ability (Multiattack) falls through to traits
    assert any("Multiattack" in t for t in f["traits"]), f["traits"]
    assert "Nimble Escape" in f["traits"]
    assert f["saves"] == []  # no saving throws on the goblin


def test_srd_action_parser_preserves_negative_damage_modifiers():
    parsed = srd_client._parse_action(
        "Weak Claw",
        "Melee Weapon Attack: +1 to hit. Hit: 1 (1d4 - 1) slashing damage.",
    )
    assert parsed == "Weak Claw +1 · 1d4-1 sl"


def test_srd_fetch_and_cache():
    page = {"next": None, "results": [
        {"name": "Goblin", "document": {"key": "srd-2014"}, **GOBLIN_SRD},
        {"name": "Homebrew Thing", "document": {"key": "not-srd"}, "armor_class": 10},
    ]}
    calls = []

    def fake_get(url):
        calls.append(url)
        return page

    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(srd_client, "_http_get_json", fake_get), \
             mock.patch.object(srd_client, "CACHE_DIR", tmp):
            out = srd_client.get_srd_monsters(force=True)
            # non-SRD document excluded
            assert [m["name"] for m in out] == ["Goblin"], [m["name"] for m in out]
            assert os.path.exists(os.path.join(tmp, "monsters.json"))
            # second call reads the cache, no network (cached keys are JSON
            # strings, so compare on stable identity fields, not raw equality)
            calls.clear()
            out2 = srd_client.get_srd_monsters(force=False)
            assert [m["name"] for m in out2] == [m["name"] for m in out]
            assert calls == []


def test_srd_offline_no_cache():
    def fake_get(url):
        raise ValueError("Could not reach Open5e: offline")

    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(srd_client, "_http_get_json", fake_get), \
             mock.patch.object(srd_client, "CACHE_DIR", tmp):
            assert srd_client.load_cache("monsters") is None
            try:
                srd_client.get_srd_monsters(force=True)
            except ValueError:
                pass
            else:
                raise AssertionError("offline fetch should raise ValueError")


def test_srd_combatant_resolves():
    """An SRD field dict builds a real Combatant whose weapon lines the engine
    actually resolves (the contract _spawn_srd relies on)."""
    from battle import Combatant, resolve_attack, _ATK_RE

    f = srd_client.srd_monster_to_fields(GOBLIN_SRD)
    c = Combatant(**f)
    c.conditions = set(c.conditions or [])
    c.saves = set(c.saves or [])
    c.stats = {int(k): v for k, v in (c.stats or {}).items()}

    weapon = next(a for a in c.attacks if a.startswith("Scimitar"))
    assert _ATK_RE.match(weapon), weapon
    target = Combatant("Dummy", "PC", hp=10, max_hp=10, ac=10)
    # d20 rolls 10 (a hit, not a crit) then 1d6 -> 4
    res = resolve_attack(c, weapon, target, Seq([10, 4]))
    assert res["kind"] == "attack" and res["hit"] and res["damage"] == 6  # 4 + 2


# -- SRD spell conversion ---------------------------------------------------

FIREBALL = {
    "name": "Fireball", "level": 3, "school": {"name": "Evocation", "key": "evocation"},
    "casting_time": "action", "range": 150, "range_text": "150 feet",
    "components": "V, S, M", "duration": "instantaneous",
    "damage_roll": "8d6", "damage_types": ["fire"], "saving_throw_ability": "dexterity",
    "desc": "A bright streak flashes and then explodes. Each creature in a 20-foot-radius sphere must make a Dexterity saving throw. A target takes 8d6 fire damage on a failed save.",
    "document": {"key": "srd-2014"},
}
CURE = {
    "name": "Cure Wounds", "level": 1, "school": {"name": "Evocation", "key": "evocation"},
    "casting_time": "action", "range": 0, "range_text": "touch",
    "components": "V, S", "duration": "instantaneous",
    "damage_roll": "", "damage_types": [], "saving_throw_ability": None,
    "desc": "A creature you touch regains 1d8 + 2 hit points for each spell slot level above 1st.",
    "document": {"key": "srd-2014"},
}
HOLD = {
    "name": "Hold Person", "level": 2, "school": {"name": "Enchantment", "key": "enchantment"},
    "casting_time": "action", "range": 60, "range_text": "60 feet",
    "components": "V, S, M", "duration": "1 minute",
    "damage_roll": "", "damage_types": [], "saving_throw_ability": "wisdom",
    "desc": "Choose a humanoid that you can see. The target must succeed on a Wisdom saving throw or be paralyzed.",
    "document": {"key": "srd-2014"},
}
MMISSILE = {
    "name": "Magic Missile", "level": 1, "school": {"name": "Evocation", "key": "evocation"},
    "casting_time": "action", "range": 120, "range_text": "120 feet",
    "components": "V, S", "duration": "instantaneous",
    "damage_roll": "", "damage_types": [], "saving_throw_ability": None,
    "desc": "You create three glowing darts of force. Each dart hits a creature of your choice for 1d4 + 1 force damage.",
    "document": {"key": "srd-2014"},
}


def test_srd_spell_to_fields():
    f = srd_client.spell_to_fields(FIREBALL)
    assert f["name"] == "Fireball" and f["level"] == 3 and f["school"] == "Evocation"
    # damage spell with a save -> engine-ready string with default DC 13
    assert f["cast"] == "Fireball — 8d6 fire (dex DC 13)", f["cast"]
    assert srd_client.spell_to_fields(CURE)["cast"] == "Cure Wounds — 1d8+2 HP"
    assert srd_client.spell_to_fields(HOLD)["cast"] == "Hold Person — (wis DC 13)"
    # "three darts" word form is caught and multiplied
    assert srd_client.spell_to_fields(MMISSILE)["cast"] == "Magic Missile — 3 darts, 1d4+1 force", \
        srd_client.spell_to_fields(MMISSILE)["cast"]


def test_srd_spell_resolves():
    """An SRD spell string resolves in the engine (damage + heal contracts)."""
    from battle import Combatant, resolve_attack

    dmg = srd_client.spell_to_fields(FIREBALL)["cast"]
    target = Combatant("Dummy", "PC", hp=50, max_hp=50, ac=10, stats={3: 10})
    # all dice roll 1 (8d6 -> 8); CON save roll (1) + mod (2) = 3 < 13 -> not saved
    res = resolve_attack(Combatant("Caster", "monster", hp=1, max_hp=1, ac=10), dmg, target, Seq([1] * 10))
    assert res["kind"] == "spell" and res["damage"] == 8
    # The spell branch skips the d20, so the die roll consumes the first RNG
    # value: 1d8+2 -> 7+2 = 9 (resolver returns the heal in `damage`; the app
    # applies it via _apply_attack_result)
    heal = srd_client.spell_to_fields(CURE)["cast"]
    wounded = Combatant("Ally", "PC", hp=3, max_hp=10, ac=10)
    res = resolve_attack(Combatant("Healer", "monster", hp=1, max_hp=1, ac=10), heal, wounded, Seq([7]))
    assert res["heal"] and res["damage"] == 9


def test_srd_spells_fetch_and_cache():
    page = {"next": None, "results": [
        {"name": "Fireball", "document": {"key": "srd-2014"}, **FIREBALL},
        {"name": "Homebrew Spell", "document": {"key": "not-srd"}},
    ]}
    calls = []

    def fake_get(url):
        calls.append(url)
        return page

    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(srd_client, "_http_get_json", fake_get), \
             mock.patch.object(srd_client, "CACHE_DIR", tmp):
            out = srd_client.get_srd_spells(force=True)
            assert [m["name"] for m in out] == ["Fireball"]
            assert os.path.exists(os.path.join(tmp, "spells.json"))
            calls.clear()
            out2 = srd_client.get_srd_spells(force=False)
            assert [m["name"] for m in out2] == [m["name"] for m in out]
            assert calls == []


def main() -> None:
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"TESTS OK ({len(tests)} passed)")


if __name__ == "__main__":
    main()
