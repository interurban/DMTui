"""Unit tests for the pure battle logic. Run: .venv/bin/python tests.py"""

from battle import (
    Combatant,
    coord_name,
    find_free_spot,
    resolve_attack,
    roll_dice,
    short_label,
)
from app import parse_ddb_url


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
    # nat 20 always hits and doubles the damage dice (d8=3 then d8=5)
    res = resolve_attack(atk, "Longsword +7 · 1d8+4 sl", tgt, Seq([20, 3, 5]))
    assert res["hit"] and res["crit"]
    assert res["damage"] == (3 + 4) + (5 + 4) == 16
    assert res["dice"] == [3, 5]


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
    res = resolve_attack(atk, "Burning Hands — 15 ft. cone, 3d6 fire (Dex DC 12)", tgt, Seq([2, 4, 5]))
    assert res["kind"] == "spell" and res["damage"] == 11
    assert res["dice"] == [2, 4, 5] and res["dice_bonus"] == 0


def test_resolve_spell_without_dice():
    atk, tgt = dent(), hobgoblin()
    res = resolve_attack(atk, "Word of Censure", tgt, Seq([1]))
    assert res["kind"] == "spell" and res["damage"] == 0 and res["hit"]


def test_short_label():
    assert short_label("Goblin 2") == "G2"
    assert short_label("Syrva") == "Syr"
    assert short_label("Ogre") == "Ogr"
    assert short_label("Goblin Boss") == "Gob"


def test_coord_name():
    assert coord_name(0, 0) == "A1"
    assert coord_name(13, 7) == "N8"


def test_find_free_spot():
    a = Combatant("A", "monster", hp=1, max_hp=1, ac=10, x=2, y=0)
    b = Combatant("B", "monster", hp=1, max_hp=1, ac=10, x=1, y=0)
    # scans top-right inward, so (3,0) is free first
    assert find_free_spot([a, b], cols=4, rows=2) == (3, 0)


def test_parse_ddb_url():
    assert parse_ddb_url("https://www.dndbeyond.com/characters/9876543") == 9876543
    assert parse_ddb_url("9876543") == 9876543
    assert parse_ddb_url("https://example.com/other") is None
    assert parse_ddb_url("") is None


def test_combatant_snap_json_roundtrip():
    """Snapshots survive a JSON save/load: ability-score keys come back as
    strings and must be re-normalised to ints before use (regression)."""
    import json

    from app import BattleApp

    app = BattleApp()
    c = app.combatants[0]
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


if __name__ == "__main__":
    main()