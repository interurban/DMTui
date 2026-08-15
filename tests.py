"""Unit tests for the pure battle logic. Run: .venv/bin/python tests.py"""

import urllib.error
import urllib.request
from unittest import mock

from battle import (
    Combatant,
    coord_name,
    find_free_spot,
    resolve_attack,
    roll_dice,
    short_label,
)
from ddb import extract_combatant, fetch_character_data, parse_ddb_url


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


def test_resolve_spell_heals():
    atk, tgt = dent(), hobgoblin()
    res = resolve_attack(atk, "Cure Wounds — 1d8+2 HP", tgt, Seq([5]))
    assert res["kind"] == "spell" and res["heal"] is True
    assert res["damage"] == 7


def test_resolve_spell_magic_missile():
    atk, tgt = dent(), hobgoblin()
    # '3 darts' rolls 1d4+1 three times: (2, 3, 1) -> 3 + 4 + 2 = 9
    res = resolve_attack(atk, "Magic Missile — 3 darts, 1d4+1 force each", tgt, Seq([2, 3, 1]))
    assert res["kind"] == "spell" and res["damage"] == 9
    assert res["dice"] == [2, 3, 1] and not res["heal"]


def test_resolve_spell_without_dice():
    atk, tgt = dent(), hobgoblin()
    res = resolve_attack(atk, "Word of Censure", tgt, Seq([1]))
    assert res["kind"] == "spell" and res["damage"] == 0 and res["hit"]


def test_resolve_spell_healing_word():
    atk, tgt = dent(), hobgoblin()
    # 'Healing Word' must be detected as a heal (regression: \bheal\b missed
    # the 'healing' word prefix and dealt damage instead)
    res = resolve_attack(atk, "Healing Word — 1d4+3 HP", tgt, Seq([4]))
    assert res["kind"] == "spell" and res["heal"] is True
    assert res["damage"] == 7


def test_resolve_crit_zero_bonus():
    atk, tgt = dent(), hobgoblin()
    # the crit re-roll strips the flat bonus ('+0' included) so it is added once
    res = resolve_attack(atk, "Longsword +7 · 1d8+0 sl", tgt, Seq([20, 3, 5]))
    assert res["crit"] and res["damage"] == 3 + 5 + 0 == 8
    assert res["dice"] == [3, 5]


def test_resolve_crit_negative_bonus():
    atk, tgt = dent(), hobgoblin()
    res = resolve_attack(atk, "Longsword +5 · 1d8-1 sl", tgt, Seq([20, 3, 5]))
    assert res["crit"] and res["damage"] == 3 + 5 - 1 == 7
    assert res["dice"] == [3, 5]


def test_resolve_heal_with_save_hint_not_halved():
    atk, tgt = dent(), hobgoblin()
    # a heal that also carries a (Con DC N) hint must NOT be halved by a save;
    # the save is reported but ignored for healing spells
    res = resolve_attack(atk, "Regenerate — 4d8 HP (Con DC 12)", tgt, Seq([1, 2, 3, 4, 20]))
    assert res["kind"] == "spell" and res["heal"] is True
    assert res["damage"] == 10
    assert res.get("save") is None


def test_resolve_spell_save_without_dice():
    atk, tgt = dent(), hobgoblin()
    # control spells with a save hint but no dice still roll the save
    res = resolve_attack(atk, "Hold Person — (Wis DC 15)", tgt, Seq([3]))
    assert res["kind"] == "spell" and res["damage"] == 0
    assert res["save"]["dc"] == 15 and res["save"]["saved"] is False


def test_resolve_spell_times_not_multiplied():
    atk, tgt = dent(), hobgoblin()
    # only an explicit 'N darts' keyword multiplies (regression: '3 ×' used to
    # multiply every damage spell that mentioned a number + times sign)
    res = resolve_attack(atk, "Magic Missile — 3 × 1d4+1 force", tgt, Seq([2]))
    assert res["kind"] == "spell" and not res["heal"]
    assert res["damage"] == 3 and res["dice"] == [2]


def test_resolve_spell_regenerate_without_hp():
    atk, tgt = dent(), hobgoblin()
    # 'Regenerate' is caught by its own keyword — not by a trailing 'HP' token
    # (regression: the heal regex matched 'regains' but not 'Regenerate', and
    # only the 'HP' suffix was masking it in the tests)
    res = resolve_attack(atk, "Regenerate — 4d8 (Con DC 12)", tgt, Seq([1, 2, 3, 4, 20]))
    assert res["kind"] == "spell" and res["heal"] is True
    assert res["damage"] == 10 and res.get("save") is None


def test_resolve_damage_spell_mentioning_hp_is_not_heal():
    atk, tgt = dent(), hobgoblin()
    # a damage spell whose description happens to mention 'hp' must not flip
    # into a heal (regression: the bare 'hp'/'hit points' tokens did)
    res = resolve_attack(atk, "Inflict Wounds — 2d8 necrotic, reduces max hp", tgt, Seq([5, 6]))
    assert res["kind"] == "spell" and res["heal"] is False
    assert res["damage"] == 11


def test_resolve_spell_zero_darts_not_multiplied():
    atk, tgt = dent(), hobgoblin()
    res = resolve_attack(atk, "Magic Missile — 0 darts, 1d4+1 force each", tgt, Seq([2]))
    assert res["kind"] == "spell" and not res["heal"]
    assert res["damage"] == 3 and res["dice"] == [2]


def test_resolve_crit_multi_die_no_bonus():
    atk, tgt = dent(), hobgoblin()
    # '2d6' with no flat bonus — the crit re-roll must still strip '+0'/nothing
    res = resolve_attack(atk, "Maul +5 · 2d6 bl", tgt, Seq([20, 2, 3, 4, 1]))
    assert res["crit"] and res["damage"] == 2 + 3 + 4 + 1 == 10
    assert res["dice"] == [2, 3, 4, 1] and res["dice_bonus"] == 0


def test_short_label():
    assert short_label("Goblin 2") == "G2"
    assert short_label("Syrva") == "Syr"
    assert short_label("Ogre") == "Ogr"
    assert short_label("Goblin Boss") == "Gob"
    assert short_label("") == "?"


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


def test_build_encounter_returns_fresh_clones():
    """build_encounter must not hand back the shared module singletons —
    mutating one call's result must not leak into the next (reset regression)."""
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
    data = {
        "character": {
            "name": "Hasty",
            "stats": [15, 14, 13, 12, 10, 8],
            "baseHitPoints": 10,
            "inventory": [],
            "modifiers": {},
        }
    }
    c = extract_combatant(1, data)
    assert c.init_mod == 2 and c.stats[1] == 15 and c.stats[6] == 8


def test_extract_combatant_weapon_without_attack_fields_skipped():
    data = {
        "character": {
            "name": "Plain",
            "stats": {"1": 10, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "inventory": [{"equipped": True, "definition": {"name": "Lantern", "damage": None}}],
            "modifiers": {},
        }
    }
    c = extract_combatant(2, data)
    assert c.attacks == []


def test_extract_combatant_spell_without_definition():
    data = {
        "character": {
            "name": "Sparrow",
            "stats": {"1": 10, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "spells": {"0": [{"definition": None}, {"definition": {"name": "Cure Wounds"}}]},
            "modifiers": {},
        }
    }
    c = extract_combatant(3, data)
    assert c.spells == ["Cure Wounds"]


def test_extract_combatant_multi_hit_dice():
    data = {
        "character": {
            "name": "Dicey",
            "stats": {"1": 10, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "hitPointDice": {"8": 3, "6": 2},
            "modifiers": {},
        }
    }
    c = extract_combatant(4, data)
    assert c.hit_dice == "3d8, 2d6"


def test_extract_combatant_hit_dice_sorted_descending():
    data = {
        "character": {
            "name": "Dicey",
            "stats": {"1": 10, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            # inserted smallest-first; output must still be largest-die-first
            "hitPointDice": {"6": 2, "8": 3},
            "modifiers": {},
        }
    }
    c = extract_combatant(4, data)
    assert c.hit_dice == "3d8, 2d6"


def test_extract_combatant_stats_dict_unordered():
    data = {
        "character": {
            "name": "Muddled",
            "stats": {"6": 8, "1": 15, "3": 12, "5": 10, "4": 10, "2": 14},
            "baseHitPoints": 10,
            "inventory": [],
            "modifiers": {},
        }
    }
    c = extract_combatant(5, data)
    assert c.init_mod == 2 and c.stats[1] == 15 and c.stats[6] == 8
    assert c.stats == {1: 15, 2: 14, 3: 12, 4: 10, 5: 10, 6: 8}


def test_extract_combatant_armor_type_id_as_string():
    data = {
        "character": {
            "name": "Bouncy",
            "stats": {"1": 10, "2": 12, "3": 10, "4": 10, "5": 10, "6": 10},
            "baseHitPoints": 10,
            "inventory": [
                {"equipped": True, "definition": {"name": "Shield", "armorClass": 2, "armorTypeId": "4"}},
            ],
            "modifiers": {},
        }
    }
    c = extract_combatant(6, data)
    assert c.ac == 10 + 1 + 2  # 10 + DEX + shield (armorTypeId came back as a string)


def test_extract_combatant_attack_bonus_trusted():
    data = {
        "character": {
            "name": "Vexed",
            "stats": {"1": 10, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "baseHitPoints": 10,
            "inventory": [
                {"equipped": True, "definition": {
                    "name": "Flame Tongue", "damage": {"diceString": "2d6"}, "damageType": "Fire",
                    "attackBonus": 9,
                }},
            ],
            "modifiers": {},
        }
    }
    c = extract_combatant(7, data)
    assert c.attacks[0].startswith("Flame Tongue +9 · 2d6"), c.attacks


def test_extract_combatant_negative_attack_bonus_renders():
    data = {
        "character": {
            "name": "Vexed",
            "stats": {"1": 16, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "baseHitPoints": 10,
            "inventory": [
                {"equipped": True, "definition": {
                    "name": "Cursed Blade", "damage": {"diceString": "1d8"}, "damageType": "Slashing",
                    "attackBonus": -2,
                }},
            ],
            "modifiers": {},
        }
    }
    c = extract_combatant(7, data)
    assert c.attacks[0].startswith("Cursed Blade -2 · 1d8"), c.attacks


def test_extract_combatant_damage_bonus_not_double_counted_to_hit():
    data = {
        "character": {
            "name": "Smash",
            "stats": {"1": 16, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "baseHitPoints": 10,
            "proficiencyBonus": 2,
            "inventory": [
                {"equipped": True, "definition": {
                    "name": "Greataxe", "damage": {"diceString": "1d12"}, "damageType": "Slashing",
                    "damageBonus": 3,
                }},
            ],
            "modifiers": {},
        }
    }
    c = extract_combatant(7, data)
    # the flat +3 damage bonus helps damage, not the to-hit roll
    assert c.attacks[0].startswith("Greataxe +5 · 1d12+6"), c.attacks


def test_extract_combatant_explicit_zero_attack_bonus_trusted():
    data = {
        "character": {
            "name": "Weird",
            "stats": {"1": 16, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "baseHitPoints": 10,
            "proficiencyBonus": 2,
            "inventory": [
                {"equipped": True, "definition": {
                    "name": "Weapon", "damage": {"diceString": "1d6"}, "damageType": "Bludgeoning",
                    "attackBonus": 0,
                }},
            ],
            "modifiers": {},
        }
    }
    c = extract_combatant(9, data)
    assert c.attacks[0].startswith("Weapon +0 · 1d6"), c.attacks


def test_extract_combatant_heavy_armor_ignores_negative_dex():
    data = {
        "character": {
            "name": "Plod",
            "stats": {"1": 10, "2": 6, "3": 10, "4": 10, "5": 10, "6": 10},
            "baseHitPoints": 10,
            "inventory": [
                {"equipped": True, "definition": {"name": "Plate", "armorClass": 18, "armorTypeId": 3}},
            ],
            "modifiers": {},
        }
    }
    c = extract_combatant(9, data)
    assert c.ac == 18, c.ac  # heavy armour ignores DEX entirely, even a -2 penalty


def test_extract_combatant_hit_dice_non_numeric_keys_filtered():
    data = {
        "character": {
            "name": "Dicey",
            "stats": {"1": 10, "2": 10, "3": 10, "4": 10, "5": 10, "6": 10},
            "hitPointDice": {"8": 3, "6": 2, "foo": 2, "d10": 1},
            "modifiers": {},
        }
    }
    c = extract_combatant(4, data)
    assert c.hit_dice == "3d8, 2d6"


def test_extract_combatant_negative_removed_hp_clamped():
    data = {
        "character": {
            "name": "Hearty",
            "stats": {"1": 16, "2": 10, "3": 14, "4": 10, "5": 10, "6": 10},
            "baseHitPoints": 10,
            "removedHitPoints": -5,
            "inventory": [],
            "modifiers": {},
        }
    }
    c = extract_combatant(8, data)
    assert c.hp == c.max_hp  # a negative 'removed' value must not push hp above max


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


def main() -> None:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"TESTS OK ({len(fns)} passed)")


# ---------------------------------------------------------------------------
# Open5e SRD integration
# ---------------------------------------------------------------------------

import os
import srd as srd_client
import tempfile

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


if __name__ == "__main__":
    main()