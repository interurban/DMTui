"""Encounter data for the battle tracker demo.

Simulated-but-real data: a level-3 party ambushed by goblins on the old
toll road. Health values, initiative, and conditions are hand-tuned to make
the demo interesting.
"""

from __future__ import annotations

import random
import re
from copy import deepcopy
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Conditions — glyph + colour used for the little chips in the initiative list
# ---------------------------------------------------------------------------

CONDITIONS: dict[str, dict[str, str]] = {
    "blinded":       {"glyph": "◉", "color": "#9a8fb0"},
    "charmed":       {"glyph": "♥", "color": "#d953a8"},
    "deafened":      {"glyph": "✖", "color": "#8a93a3"},
    "exhaustion":    {"glyph": "▽", "color": "#d9a441"},
    "frightened":    {"glyph": "!", "color": "#6aa6d9"},
    "grappled":      {"glyph": "⚓", "color": "#b08968"},
    "incapacitated": {"glyph": "∅", "color": "#8a93a3"},
    "invisible":     {"glyph": "…", "color": "#cfcfd6"},
    "paralyzed":     {"glyph": "✣", "color": "#5fc4c4"},
    "petrified":     {"glyph": "⛰", "color": "#9aa4b3"},
    "poisoned":      {"glyph": "☠", "color": "#6fd97a"},
    "prone":         {"glyph": "⬇", "color": "#d9a441"},
    "restrained":    {"glyph": "⛓", "color": "#b08968"},
    "stunned":       {"glyph": "✷", "color": "#e0c04c"},
    "unconscious":   {"glyph": "○", "color": "#7d8591"},
    "concentrating": {"glyph": "✧", "color": "#c678dd"},
}

# ---------------------------------------------------------------------------
# Combatant
# ---------------------------------------------------------------------------


@dataclass
class Combatant:
    name: str
    kind: str              # "PC" | "monster"
    hp: int
    max_hp: int
    ac: int
    init: int | None = None   # None = not yet rolled / set
    init_mod: int = 0         # initiative modifier, used when rolling
    conditions: set[str] = field(default_factory=set)
    role: str = ""         # class / creature tag, shown in the detail card
    note: str = ""         # flavour line for the detail card
    x: int = 0             # battle-map grid position
    y: int = 0
    stats: dict[int, int] = field(default_factory=dict)  # 1 STR .. 6 CHA
    saves: set[int] = field(default_factory=set)         # ability ids proficient in saving throws
    speed: int | None = None
    proficiency: int | None = None
    hit_dice: str = ""
    skills: dict[str, int] = field(default_factory=dict)  # skill name -> total bonus
    passive_perception: int | None = None
    attacks: list[str] = field(default_factory=list)       # e.g. "Longsword +7 · 1d8+4 sl"
    traits: list[str] = field(default_factory=list)        # special abilities
    spells: list[str] = field(default_factory=list)        # spellcaster spells

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def hp_frac(self) -> float:
        if self.max_hp <= 0:
            return 0.0
        return max(0.0, min(1.0, self.hp / self.max_hp))

    def stat(self, aid: int) -> int | None:
        return self.stats.get(aid)

    def mod(self, aid: int) -> int | None:
        s = self.stats.get(aid)
        return None if s is None else (s - 10) // 2

    def save(self, aid: int) -> int | None:
        m = self.mod(aid)
        if m is None:
            return None
        prof = self.proficiency if self.proficiency is not None else 2
        return m + (prof if aid in self.saves else 0)


# ---------------------------------------------------------------------------
# Battle map
# ---------------------------------------------------------------------------

MAP_COLS = 13
MAP_ROWS = 20


def short_label(name: str) -> str:
    """Compact token label: 'Goblin 2' -> 'G2', 'Syrva' -> 'Syr', 'Ogre' -> 'Ogr'."""
    if not name:
        return "?"
    m = re.search(r"\s+(\d+)$", name)
    if m:
        base = name[: m.start()].strip()
        return (base[:1] + m.group(1)).upper()
    return name.split()[0][:3].capitalize()


# ---------------------------------------------------------------------------
# Dice + attack resolution
# ---------------------------------------------------------------------------

_ATK_RE = re.compile(
    r"^(?P<name>.*?)\s*(?P<bonus>[+-]\d+)\s*·\s*(?P<dice>\d*d\d+(?:[+-]\d+)?)\s*(?P<dtype>\w+)?$"
)
_DICE_RE = re.compile(r"\d*d\d+(?:[+-]\d+)?")
_HEAL_RE = re.compile(r"\b(heal\w*|cure\w*|restore\w*|mend\w*|regain\w*|hit points|hp)\b", re.IGNORECASE)
_SAVE_RE = re.compile(r"\(([a-z]+)\s+dc\s*(\d+)\)", re.IGNORECASE)
_DARTS_RE = re.compile(r"(\d+)\s*darts?\b", re.IGNORECASE)
_SAVE_ABILITY_ID = {"str": 1, "dex": 2, "con": 3, "int": 4, "wis": 5, "cha": 6}


def roll_dice(spec: str, rng=random) -> tuple[int, list[int], int]:
    """Roll a dice expression like '2d6+3' -> (total, [each die], bonus)."""
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", spec.strip())
    if not m:
        raise ValueError(f"bad dice expression: {spec!r}")
    n = int(m.group(1) or 1)
    d = int(m.group(2))
    bonus = int(m.group(3) or 0)
    if n < 1 or d < 1:
        raise ValueError(f"bad dice expression: {spec!r}")
    rolls = [rng.randint(1, d) for _ in range(n)]
    return sum(rolls) + bonus, rolls, bonus


def resolve_attack(attacker: Combatant, action: str, target: Combatant, rng=random) -> dict:
    """Resolve a weapon attack or spell string against a target.

    Weapon lines look like 'Longsword +7 · 1d8+4 sl' and roll d20+bonus vs the
    target's AC (nat 20 crits and doubles the damage dice, nat 1 always misses).
    Spells are best-effort: the first dice expression found is rolled as damage,
    a '(Dex DC 12)' hint grants the target a saving throw (half damage on a
    success), heal/cure/regain spells restore HP instead of dealing damage, and
    'N darts' lines (Magic Missile) roll the dice expression N times.
    Returns a plain dict describing the outcome for the caller to log/apply.
    """
    m = _ATK_RE.match(action)
    if m is not None:
        name = m.group("name")
        bonus = int(m.group("bonus"))
        dice = m.group("dice")
        dtype = m.group("dtype") or ""
        d20 = rng.randint(1, 20)
        roll = d20 + bonus
        crit = d20 == 20
        miss = d20 == 1
        hit = crit or (not miss and roll >= target.ac)
        if hit:
            total, rolls, dmg_bonus = roll_dice(dice, rng)
            if crit:
                # doubling the dice means rolling them again — the flat +N
                # bonus is added once, not twice
                extra, extra_rolls, _ = roll_dice(dice.replace(f"{dmg_bonus:+d}", ""), rng)
                total += extra
                rolls = rolls + extra_rolls
        else:
            total, rolls, dmg_bonus = 0, [], 0
        return {
            "kind": "attack", "name": name, "d20": d20, "bonus": bonus, "roll": roll,
            "ac": target.ac, "hit": hit, "crit": crit, "damage": total,
            "dice": rolls, "dice_bonus": dmg_bonus, "dtype": dtype,
        }
    dm = _DICE_RE.search(action)
    healing = bool(_HEAL_RE.search(action))
    save_m = _SAVE_RE.search(action)
    total, rolls, dmg_bonus = 0, [], 0
    if dm is not None:
        total, rolls, dmg_bonus = roll_dice(dm.group(0), rng)
        darts_m = _DARTS_RE.search(action)
        if darts_m is not None and not healing and int(darts_m.group(1)) > 1:
            for _ in range(int(darts_m.group(1)) - 1):
                extra, extra_rolls, _ = roll_dice(dm.group(0), rng)
                total += extra
                rolls = rolls + extra_rolls
    if save_m is not None and not healing:
        ability = save_m.group(1).lower()
        aid = _SAVE_ABILITY_ID.get(ability)
        dc = int(save_m.group(2))
        save_mod = target.save(aid) if aid is not None else None
        save_roll = rng.randint(1, 20) + (save_mod if save_mod is not None else 0)
        saved = save_roll >= dc
        if saved:
            total = max(0, total // 2)
        return {
            "kind": "spell", "name": action, "hit": True, "crit": False,
            "damage": total, "dice": rolls, "dice_bonus": dmg_bonus, "heal": healing,
            "save": {"ability": ability, "dc": dc, "roll": save_roll, "saved": saved},
        }
    return {"kind": "spell", "name": action, "hit": True, "crit": False,
            "damage": total, "dice": rolls, "dice_bonus": dmg_bonus, "heal": healing}


def coord_name(x: int, y: int) -> str:
    """Grid coordinate label, e.g. (13, 7) -> 'N8'. Columns past 'Z' continue
    Excel-style: (26, 0) -> 'AA1'."""
    x = int(x)
    label = ""
    while True:
        label = chr(ord("A") + x % 26) + label
        x = x // 26 - 1
        if x < 0:
            break
    return f"{label}{y + 1}"


def find_free_spot(combatants: list[Combatant], cols: int = MAP_COLS, rows: int = MAP_ROWS) -> tuple[int, int] | None:
    """Pick the first empty cell, scanning from the top-right inward. Returns
    None when the map is completely full."""
    occupied = {(c.x, c.y) for c in combatants}
    for y in range(rows):
        for x in range(cols - 1, -1, -1):
            if (x, y) not in occupied:
                return x, y
    return None


# ---------------------------------------------------------------------------
# Monster templates — pick from the "add monster" dialog
# ---------------------------------------------------------------------------

MONSTERS: dict[str, dict] = {
    "Goblin": {
        "max_hp": 14, "ac": 15, "init": 2, "role": "Small humanoid",
        "stats": {1: 8, 2: 14, 3: 10, 4: 10, 5: 8, 6: 8},
        "saves": {2}, "speed": 30, "proficiency": 2,
        "skills": {"stealth": 6}, "passive_perception": 9,
        "attacks": ["Scimitar +4 · 1d6+2 sl", "Shortbow +4 · 1d6+2 pi"],
        "traits": ["Nimble Escape — disengage or hide as a bonus action."],
        "note": "Scurries and stabs. Courage comes in numbers.",
    },
    "Hobgoblin": {
        "max_hp": 28, "ac": 18, "init": 2, "role": "Medium humanoid",
        "stats": {1: 13, 2: 12, 3: 12, 4: 10, 5: 10, 6: 9},
        "saves": set(), "speed": 30, "proficiency": 2,
        "skills": {"intimidation": 2}, "passive_perception": 10,
        "attacks": ["Longsword +3 · 1d8+1 sl", "Longbow +3 · 1d8+1 pi"],
        "traits": ["Martial Advantage — +2d6 when an ally is adjacent."],
        "note": "Disciplined. Calls out battle plans in Goblin.",
    },
    "Bugbear": {
        "max_hp": 27, "ac": 16, "init": 2, "role": "Medium humanoid",
        "stats": {1: 15, 2: 14, 3: 13, 4: 8, 5: 11, 6: 9},
        "saves": {1, 2, 3}, "speed": 30, "proficiency": 2,
        "skills": {"stealth": 6}, "passive_perception": 10,
        "attacks": ["Morningstar +4 · 2d8+2 pi", "Javelin +4 · 2d6+2 pi"],
        "traits": ["Brute — melee weapons deal one extra die."],
        "note": "Sneaky ambusher. Brute force when cornered.",
    },
    "Orc": {
        "max_hp": 30, "ac": 13, "init": 0, "role": "Medium humanoid",
        "stats": {1: 16, 2: 12, 3: 16, 4: 7, 5: 11, 6: 10},
        "saves": {1}, "speed": 30, "proficiency": 2,
        "skills": {"intimidation": 2}, "passive_perception": 10,
        "attacks": ["Greataxe +5 · 1d12+3 sl", "Javelin +5 · 1d6+3 pi"],
        "traits": ["Aggressive — move toward a foe as a bonus action."],
        "note": "Slaughters, then howls.",
    },
    "Goblin Boss": {
        "max_hp": 39, "ac": 17, "init": 2, "role": "Small humanoid",
        "stats": {1: 10, 2: 14, 3: 10, 4: 10, 5: 8, 6: 10},
        "saves": {2}, "speed": 30, "proficiency": 2,
        "skills": {"stealth": 6}, "passive_perception": 9,
        "attacks": ["Scimitar +4 · 1d6+2 sl", "Shortbow +4 · 1d6+2 pi"],
        "traits": ["Rally — goblins within 30 ft. get +1 to attacks."],
        "note": "Raises a war-horn to his lips…",
    },
    "Goblin Shaman": {
        "max_hp": 17, "ac": 13, "init": 2, "role": "Small humanoid",
        "stats": {1: 8, 2: 14, 3: 12, 4: 10, 5: 13, 6: 10},
        "saves": {5}, "speed": 30, "proficiency": 2,
        "skills": {"arcana": 2, "perception": 3}, "passive_perception": 13,
        "attacks": ["Scimitar +4 · 1d6+2 sl"],
        "traits": ["Nimble Escape — disengage or hide as a bonus action."],
        "spells": [
            "Magic Missile — 3 darts, 1d4+1 force each",
            "Burning Hands — 15 ft. cone, 3d6 fire (Dex DC 12)",
            "Bane — three creatures, −1d4 to attacks and saves",
            "Cure Wounds — 1d8+2 HP",
        ],
        "note": "Rattles bones and cackles. Covets the party's spellcasters.",
    },
    "Ogre": {
        "max_hp": 59, "ac": 11, "init": -1, "role": "Large giant",
        "stats": {1: 19, 2: 8, 3: 16, 4: 5, 5: 7, 6: 7},
        "saves": set(), "speed": 40, "proficiency": 2,
        "skills": {}, "passive_perception": 8,
        "attacks": ["Greatclub +6 · 2d8+4 bl"],
        "traits": ["Enormous — 15 ft. reach, smashes doors."],
        "note": "Slow, devastating.",
    },
    "Dire Wolf": {
        "max_hp": 37, "ac": 14, "init": 2, "role": "Large beast",
        "stats": {1: 17, 2: 15, 3: 15, 4: 3, 5: 12, 6: 7},
        "saves": {1, 2}, "speed": 50, "proficiency": 2,
        "skills": {"perception": 3, "stealth": 4}, "passive_perception": 13,
        "attacks": ["Bite +5 · 2d6+3 pi"],
        "traits": ["Pack Tactics — advantage when an ally is adjacent."],
        "note": "Hunts in a bloodthirsty pack.",
    },
    "Worg": {
        "max_hp": 26, "ac": 13, "init": 1, "role": "Large monstrosity",
        "stats": {1: 16, 2: 13, 3: 13, 4: 7, 5: 11, 6: 8},
        "saves": set(), "speed": 50, "proficiency": 2,
        "skills": {"perception": 4}, "passive_perception": 14,
        "attacks": ["Bite +5 · 1d10+3 pi"],
        "traits": ["Keen Hearing & Smell — advantage on perception."],
        "note": "Rides as a goblin mount.",
    },
    "Skeleton": {
        "max_hp": 13, "ac": 13, "init": 1, "role": "Medium undead",
        "stats": {1: 10, 2: 14, 3: 15, 4: 6, 5: 8, 6: 5},
        "saves": {2}, "speed": 30, "proficiency": 2,
        "skills": {}, "passive_perception": 9,
        "attacks": ["Shortsword +4 · 1d6+2 sl", "Shortbow +4 · 1d6+2 pi"],
        "traits": ["Undead Fortitude — may survive at 0 HP (DC 10+damage)."],
        "note": "Shortbow volley. Shatters at 0 HP.",
    },
    "Bandit": {
        "max_hp": 11, "ac": 12, "init": 1, "role": "Medium humanoid",
        "stats": {1: 11, 2: 12, 3: 12, 4: 10, 5: 10, 6: 10},
        "saves": set(), "speed": 30, "proficiency": 2,
        "skills": {}, "passive_perception": 10,
        "attacks": ["Scimitar +3 · 1d6+1 sl", "Light Crossbow +3 · 1d8+1 pi"],
        "traits": [],
        "note": "Preys on the road. Greedy, cowardly.",
    },
    "Bandit Captain": {
        "max_hp": 65, "ac": 15, "init": 3, "role": "Medium humanoid",
        "stats": {1: 15, 2: 16, 3: 14, 4: 14, 5: 11, 6: 14},
        "saves": {1, 2, 5}, "speed": 30, "proficiency": 2,
        "skills": {"deception": 4, "intimidation": 4, "perception": 2}, "passive_perception": 12,
        "attacks": ["Scimitar +5 · 1d6+3 sl", "Dagger +5 · 1d4+3 pi"],
        "traits": ["Parry — reaction, +2 AC against one attack."],
        "note": "Leads from the front. Bounty on his head.",
    },
    "Giant Rat": {
        "max_hp": 7, "ac": 12, "init": 2, "role": "Small beast",
        "stats": {1: 7, 2: 15, 3: 11, 4: 2, 5: 10, 6: 4},
        "saves": set(), "speed": 30, "proficiency": 2,
        "skills": {}, "passive_perception": 10,
        "attacks": ["Bite +4 · 1d4+2 pi"],
        "traits": ["Pack Tactics — advantage when an ally is adjacent."],
        "note": "Scuttles in swarms beneath the floorboards.",
    },
    "Gnoll": {
        "max_hp": 22, "ac": 15, "init": 1, "role": "Medium humanoid",
        "stats": {1: 14, 2: 12, 3: 11, 4: 6, 5: 10, 6: 7},
        "saves": set(), "speed": 30, "proficiency": 2,
        "skills": {}, "passive_perception": 10,
        "attacks": ["Bite +4 · 1d4+2 pi", "Spear +4 · 1d6+2 pi"],
        "traits": ["Rampage — extra move and bite after bringing a foe down."],
        "note": "Gnashes and howls for the hunt.",
    },
    "Harpy": {
        "max_hp": 38, "ac": 11, "init": 1, "role": "Medium monstrosity",
        "stats": {1: 12, 2: 13, 3: 12, 4: 7, 5: 10, 6: 13},
        "saves": set(), "speed": 20, "proficiency": 2,
        "skills": {}, "passive_perception": 10,
        "attacks": ["Claws +3 · 2d4+1 sl", "Club +3 · 1d4+1 bl"],
        "traits": ["Luring Song — a charm that draws victims closer (DC 11)."],
        "note": "Sings sailors to their doom.",
    },
    "Kobold": {
        "max_hp": 5, "ac": 12, "init": 2, "role": "Small humanoid",
        "stats": {1: 7, 2: 15, 3: 9, 4: 8, 5: 7, 6: 8},
        "saves": {2}, "speed": 30, "proficiency": 2,
        "skills": {"stealth": 4}, "passive_perception": 8,
        "attacks": ["Dagger +4 · 1d4+2 pi", "Sling +4 · 1d4+2 bl"],
        "traits": ["Pack Tactics — advantage when an ally is adjacent."],
        "note": "Traps, ambushes, and swarms.",
    },
    "Owlbear": {
        "max_hp": 59, "ac": 13, "init": 1, "role": "Large monstrosity",
        "stats": {1: 20, 2: 12, 3: 17, 4: 3, 5: 12, 6: 7},
        "saves": {1, 3, 5}, "speed": 40, "proficiency": 2,
        "skills": {}, "passive_perception": 11,
        "attacks": ["Beak +7 · 1d10+5 pi", "Claws +7 · 2d8+5 sl"],
        "traits": ["Keen Sight & Smell — advantage on perception."],
        "note": "A furious, hungry amalgam. Hisses like a cat.",
    },
    "Specter": {
        "max_hp": 22, "ac": 12, "init": 2, "role": "Medium undead",
        "stats": {1: 1, 2: 14, 3: 11, 4: 10, 5: 10, 6: 11},
        "saves": {5}, "speed": 50, "proficiency": 2,
        "skills": {}, "passive_perception": 10,
        "attacks": ["Life Drain +4 · 3d6 ne"],
        "traits": ["Incorporeal Movement — passes through walls."],
        "note": "A vengeful wraith that drains the living.",
    },
    "Troll": {
        "max_hp": 84, "ac": 15, "init": 1, "role": "Large giant",
        "stats": {1: 18, 2: 13, 3: 20, 4: 7, 5: 9, 6: 7},
        "saves": {1, 2, 3, 5}, "speed": 30, "proficiency": 3,
        "skills": {}, "passive_perception": 9,
        "attacks": ["Bite +7 · 1d6+4 pi", "Claws +7 · 2d6+4 sl"],
        "traits": ["Regeneration — regains 10 HP at the top of its turn."],
        "note": "Keep it down — fire or acid to stop the regen.",
    },
    "Zombie": {
        "max_hp": 22, "ac": 8, "init": -2, "role": "Medium undead",
        "stats": {1: 13, 2: 6, 3: 16, 4: 3, 5: 6, 6: 5},
        "saves": {5}, "speed": 20, "proficiency": 2,
        "skills": {}, "passive_perception": 8,
        "attacks": ["Slam +3 · 1d6+1 bl"],
        "traits": ["Undead Fortitude — may survive at 0 HP (DC 5+damage)."],
        "note": "Shuffles, groans, keeps coming.",
    },
}

# ---------------------------------------------------------------------------
# The party + starting encounter
# ---------------------------------------------------------------------------

PARTY = [
    Combatant("Dent", "PC", hp=60, max_hp=60, ac=22, init=None, init_mod=2,
              role="Human Fighter 7",
              note="Imported from D&D Beyond — plate armour and shield, standing guard.",
              stats={1: 19, 2: 14, 3: 15, 4: 9, 5: 12, 6: 12},
              saves={1, 3}, speed=30, proficiency=3, hit_dice="7d10",
              skills={"athletics": 7, "insight": 4, "perception": 4, "survival": 4},
              passive_perception=14,
              attacks=["Longsword +7 · 1d8+4 sl", "Javelin +7 · 1d6+4 pi"],
              traits=["Second Wind — bonus action, regain 1d10+7 HP once per short rest."]),
]


def encounter_monster(template: str, name: str, **over) -> Combatant:
    """Build an encounter monster from a template, overriding hp/conditions/note/etc."""
    t = MONSTERS[template]
    hp = over.pop("hp", t["max_hp"])
    base = dict(
        name=name, kind="monster",
        hp=hp, max_hp=t["max_hp"], ac=t["ac"],
        init=None, init_mod=t["init"],
        role=t["role"], note=t["note"],
        stats=dict(t["stats"]), saves=set(t["saves"]),
        speed=t["speed"], proficiency=t["proficiency"],
        skills=dict(t["skills"]), passive_perception=t["passive_perception"],
        attacks=list(t["attacks"]), traits=list(t["traits"]),
        spells=list(t.get("spells", [])),
    )
    base.update(over)
    if isinstance(base.get("conditions"), (list, set)):
        base["conditions"] = set(base["conditions"])
    if isinstance(base.get("stats"), dict):
        base["stats"] = dict(base["stats"])
    if isinstance(base.get("skills"), dict):
        base["skills"] = dict(base["skills"])
    if isinstance(base.get("saves"), (list, set)):
        base["saves"] = set(base["saves"])
    for key in ("attacks", "traits", "spells"):
        if isinstance(base.get(key), list):
            base[key] = list(base[key])
    return Combatant(**base)


ENCOUNTER_MONSTERS = [
    encounter_monster("Hobgoblin", "Hobgoblin",
                      note="Shouts orders in Goblin. Wary of the heavy plate."),
    encounter_monster("Goblin", "Goblin 1", hp=7, conditions={"frightened"},
                      note="Wounded and nervous — may flee."),
    encounter_monster("Goblin", "Goblin 2", hp=3, conditions={"poisoned"},
                      note="Backed into the ditch. Throwing daggers."),
    encounter_monster("Goblin Boss", "Grish",
                      note="Raises a war-horn to his lips…"),
    encounter_monster("Goblin", "Goblin 3",
                      note="Scrambling around the treeline."),
    encounter_monster("Goblin Shaman", "Mog", hp=13,
                      note="His voice crackles with stolen magic."),
]


START_POSITIONS: dict[str, tuple[int, int]] = {
    "Dent": (3, 7),
    "Hobgoblin": (10, 4),
    "Goblin 1": (11, 6),
    "Goblin 2": (10, 6),
    "Grish": (9, 3),
    "Goblin 3": (11, 8),
    "Mog": (8, 5),
}


def build_encounter() -> list[Combatant]:
    """Return the starting encounter in encounter order (initiative is blank).

    PARTY / ENCOUNTER_MONSTERS are shared module-level singletons, so every
    call clones them — otherwise 'reset' would hand back the same objects the
    player has been damaging (regression from the code-review pass)."""
    combatants = [deepcopy(c) for c in (PARTY + ENCOUNTER_MONSTERS)]
    for c in combatants:
        spot = START_POSITIONS.get(c.name)
        if spot is None:
            spot = find_free_spot(combatants)
        if spot is None:
            spot = (0, 0)
        c.x, c.y = spot
    return combatants


# ---------------------------------------------------------------------------
# A little narrative colour for the message bar
# ---------------------------------------------------------------------------

DEATH_LINES = [
    "{name} drops!", "{name} hits the dirt.", "{name} crumples.", "{name} goes limp.",
    "{name} is taken down.",
]
DAMAGE_LINES = [
    "{name} takes {amount} damage.", "{name} is hit for {amount} damage.",
    "{name} reels — {amount} damage.", "{name} staggers under {amount} damage.",
]
HEAL_LINES = [
    "{name} recovers {amount} HP.", "{name} is healed for {amount} HP.",
    "{name} mends — {amount} HP.", "{name} patches up for {amount} HP.",
]
