"""D&D Beyond import — pull a character off the (unofficial) character service.

The service endpoint is internal and unsupported; treat everything here as
best-effort parsing that should fail gracefully into a usable Combatant.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from battle import Combatant

ABILITY_NAMES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

_ABILITY_NAME_TO_ID = {
    "strength": 1, "dexterity": 2, "constitution": 3,
    "intelligence": 4, "wisdom": 5, "charisma": 6,
}

_SKILL_ABILITY = {
    "acrobatics": 2, "animal handling": 5, "arcana": 4, "athletics": 1,
    "deception": 6, "history": 4, "insight": 5, "intimidation": 6,
    "investigation": 4, "medicine": 5, "nature": 4, "perception": 5,
    "performance": 6, "persuasion": 6, "religion": 4, "sleight of hand": 2,
    "stealth": 2, "survival": 5,
}


def parse_ddb_url(url: str) -> int | None:
    """Pull a character id out of a D&D Beyond character URL (or a bare id)."""
    m = re.search(r"characters/(\d+)", url)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\s*(\d+)\s*", url)
    if m:
        return int(m.group(1))
    return None


def _iter_modifiers(character: dict):
    mods = character.get("modifiers") or {}
    if isinstance(mods, dict):
        for group in mods.values():
            if isinstance(group, list):
                yield from group
    elif isinstance(mods, list):
        yield from mods


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_character_data(character_id: int) -> dict:
    """Fetch a character from D&D Beyond's (unofficial) character service.

    This is an internal endpoint, not a supported API contract — treat it
    as best-effort and expect it to change.
    """
    url = f"https://character-service.dndbeyond.com/character/v5/character/{character_id}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "battle-tracker/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except ValueError as exc:
        if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
            raise ValueError(f"D&D Beyond returned a non-JSON body: {exc}") from exc
        raise
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            data = detail.get("data") if isinstance(detail, dict) else None
            message = (
                detail.get("message")
                or (data.get("serverMessage") if isinstance(data, dict) else None)
                or str(exc)
            )
            code = data.get("errorCode") if isinstance(data, dict) else None
            if code:
                message = f"{message} ({code})"
        except Exception:
            message = str(exc)
        raise ValueError(f"D&D Beyond returned {exc.code}: {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Could not reach D&D Beyond: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("D&D Beyond returned an unexpected response")
    data = payload.get("data") or {}
    if data.get("character") is None and not payload.get("success", True):
        raise ValueError(payload.get("message", "character not found"))
    return data


def extract_combatant(character_id: int, data: dict) -> Combatant:
    character = data.get("character")
    if not isinstance(character, dict) or not character:
        character = data if isinstance(data, dict) else {}
    name = character.get("name") or f"Char {character_id}"

    total_level = 0
    parts = []
    classes = _as_list(character.get("classes"))
    for cls in classes:
        if not isinstance(cls, dict):
            continue
        definition = cls.get("definition")
        if isinstance(definition, str):
            definition = {"name": definition}
        elif not isinstance(definition, dict):
            definition = {}
        cname = definition.get("name") or cls.get("name") or "?"
        level = _int(cls.get("level"), 1)
        total_level += level
        parts.append(f"{cname} {level}")
    role = " / ".join(parts) if parts else f"Level {max(total_level, 1)} Adventurer"
    if not total_level:
        total_level = 1

    # ability scores (ids: 1 STR, 2 DEX, 3 CON, 4 INT, 5 WIS, 6 CHA)
    dex_mod = con_mod = 0
    stats = character.get("stats")
    if isinstance(stats, dict):
        # dict form may arrive with string keys in any order — sort by id
        stats = [stats[k] for k in sorted(stats, key=_int)]
    if isinstance(stats, list) and stats and isinstance(stats[0], dict):
        for stat in stats:
            s_id = _int(stat.get("id"))
            value = _int(stat.get("value"), 10)
            if s_id == 2:
                dex_mod = (value - 10) // 2
            elif s_id == 3:
                con_mod = (value - 10) // 2
    elif isinstance(stats, list) and stats and isinstance(stats[0], int) and len(stats) >= 3:
        dex_mod = (int(stats[1]) - 10) // 2
        con_mod = (int(stats[2]) - 10) // 2

    # hit points: hit dice base + CON per level (+ any flat bonus)
    max_hp = None
    override = character.get("overrideHitPoints")
    if isinstance(override, dict):
        max_hp = _int(override.get("value") or override.get("max"), 0) or None
    if max_hp is None:
        base = _int(character.get("baseHitPoints"))
        bonus = _int(character.get("bonusHitPoints"))
        max_hp = base + bonus + con_mod * total_level
        if max_hp <= 0:
            max_hp = 10 + total_level * 5
    current = max(0, min(max_hp, max_hp - _int(character.get("removedHitPoints"))))

    # armor class: armor base + dex (capped by armor type) + shield + AC bonuses
    ac = 10
    dex_cap = None
    wearing_armor = False
    shield_bonus = 0
    inventory = _as_list(character.get("inventory"))
    for item in inventory:
        if not item.get("equipped"):
            continue
        defn = item.get("definition")
        if not isinstance(defn, dict):
            continue
        item_ac = defn.get("armorClass")
        atype = _int(defn.get("armorTypeId"), -1)
        if atype in (1, 2, 3) and item_ac:
            ac = _int(item_ac)
            dex_cap = {1: None, 2: 2, 3: 0}[atype]
            wearing_armor = True
    for item in inventory:
        if not item.get("equipped"):
            continue
        defn = item.get("definition")
        if not isinstance(defn, dict):
            continue
        item_ac = defn.get("armorClass")
        atype = _int(defn.get("armorTypeId"), -1)
        iname = (defn.get("name") or "").lower()
        if (atype == 4 or "shield" in iname) and item_ac:
            shield_bonus += _int(item_ac)
    ac += shield_bonus
    for mod in _iter_modifiers(character):
        if mod.get("type") == "bonus" and mod.get("subType") in ("armor-class", "armored-armor-class"):
            value = mod.get("fixedValue")
            if value is None:
                value = mod.get("value")
            if value:
                ac += _int(value)
    # heavy armour ignores the DEX modifier entirely (5e); light/moderate cap it
    if not wearing_armor:
        ac += dex_mod
    elif dex_cap == 0:
        ac += 0
    else:
        ac += dex_mod if dex_cap is None else min(dex_mod, dex_cap)

    race = ""
    race_obj = character.get("race")
    if isinstance(race_obj, str):
        race = f"{race_obj} "
    elif isinstance(race_obj, dict):
        rname = race_obj.get("fullName") or race_obj.get("baseRaceName")
        if rname:
            race = f"{rname} "

    stat_values = {}
    if isinstance(stats, list) and stats and isinstance(stats[0], dict):
        for stat in stats:
            stat_values[_int(stat.get("id"))] = _int(stat.get("value"))
    elif isinstance(stats, list) and stats and isinstance(stats[0], int):
        for i, value in enumerate(stats[:6]):
            stat_values[i + 1] = int(value)
    note = f"{race}{role}. Imported from D&D Beyond."

    def _stat_mod(aid: int) -> int:
        return (int(stat_values.get(aid, 10)) - 10) // 2

    prof = character.get("proficiencyBonus")
    prof = int(prof) if isinstance(prof, int) else 2 + (total_level - 1) // 4

    saves: set[int] = set()
    for cls in classes:
        definition = cls.get("definition")
        if not isinstance(definition, dict):
            continue
        st = definition.get("savingThrows")
        if isinstance(st, list):
            for s in st:
                aid = _ABILITY_NAME_TO_ID.get(str(s).lower())
                if aid:
                    saves.add(aid)
        elif isinstance(st, dict):
            for k, v in st.items():
                if v and _ABILITY_NAME_TO_ID.get(str(k).lower()):
                    saves.add(_ABILITY_NAME_TO_ID[str(k).lower()])

    skill_ranks: dict[str, int] = {}
    for mod in _iter_modifiers(character):
        mtype = mod.get("type")
        if mtype not in ("proficiency", "expertise"):
            continue
        sub = (mod.get("subType") or "").strip().lower()
        if sub in _SKILL_ABILITY:
            skill_ranks[sub] = 2 if mtype == "expertise" else 1
    skills = {
        name: _stat_mod(_SKILL_ABILITY[name]) + prof * rank
        for name, rank in skill_ranks.items()
    }
    perception = skills.get("perception")
    passive_perception = 10 + (perception if perception is not None else _stat_mod(5))

    speed = character.get("speed")
    if isinstance(speed, dict):
        speed = speed.get("walk")
    speed = int(speed) if isinstance(speed, (int, float)) else None

    hd = character.get("hitPointDice")
    if isinstance(hd, dict):
        # keep only numeric die-size keys, largest first
        hd = ", ".join(
            f"{v}d{k}"
            for k, v in sorted(hd.items(), key=lambda kv: -_int(kv[0]))
            if re.fullmatch(r"\d+", str(k))
        )
    hit_dice = hd if isinstance(hd, str) else ""

    attacks: list[str] = []
    str_mod = _stat_mod(1)
    for item in inventory:
        if not item.get("equipped") or len(attacks) >= 4:
            continue
        defn = item.get("definition")
        if not isinstance(defn, dict):
            continue
        dmg = defn.get("damage")
        if not dmg:
            continue
        if isinstance(dmg, dict):
            dmg = dmg.get("diceString") or dmg.get("dice")
        if not isinstance(dmg, str) or not dmg:
            continue
        if defn.get("attackType") is None and not defn.get("weaponDefinition") \
                and not defn.get("range") and not defn.get("damageType"):
            continue
        stat_mod = dex_mod if defn.get("range") else str_mod
        dmg_bonus = _int(defn.get("damageBonus"))
        dtype = str(defn.get("damageType") or "")
        # when DDB reports an explicit attack bonus (magic weapons etc.) trust it;
        # otherwise the flat damage bonus does not help you hit (5e)
        to_hit = _int(defn.get("attackBonus"), stat_mod + prof)
        attacks.append(
            f"{(defn.get('name') or '?')} {to_hit:+d} · {dmg}{stat_mod + dmg_bonus:+d} {dtype.lower()}"
        )

    traits: list[str] = []
    if race:
        traits.append(f"{race.strip()} racial traits")
    for f in _as_list(character.get("classFeatures"))[:2]:
        if isinstance(f, dict) and f.get("name"):
            traits.append(f["name"])

    spells: list[str] = []
    spell_items: list = []
    for item in _as_list(character.get("spells")):
        if isinstance(item, list):
            spell_items.extend(item)
        else:
            spell_items.append(item)
    for spell in spell_items[:8]:
        defn = spell.get("definition") if isinstance(spell, dict) else None
        if isinstance(defn, dict) and defn.get("name"):
            spells.append(defn["name"])

    return Combatant(
        name=name,
        kind="PC",
        hp=current,
        max_hp=max_hp,
        ac=ac,
        init=None,
        init_mod=dex_mod,
        role=role,
        note=note,
        stats={aid: stat_values.get(aid, 10) for aid in range(1, 7)},
        saves=saves,
        speed=speed,
        proficiency=prof,
        hit_dice=hit_dice,
        skills=skills,
        passive_perception=passive_perception,
        attacks=attacks,
        traits=traits,
        spells=spells,
    )
