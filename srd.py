"""Open5e SRD client — pull official D&D 5e content into the tracker.

This module is the integration point for Open5e (https://open5e.com), a free,
OGL-licensed mirror of the 5e System Reference Document. It is built to grow:
`fetch_raw` / `get_collection` are generic, so future content (spells, magic
items, conditions, …) slots in by adding an endpoint + a transform — the
monster path below is just the first consumer.

Everything is cached to `.cache/open5e/<name>.json` so a session only hits the
network once. Monsters are converted into the same field dicts the rest of the
tracker feeds to `Combatant`, so an SRD creature is indistinguishable in play
from one of the hand-authored templates.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from persistence import write_json_atomic

# Open5e v2 API. v1's `actions` left `damage` null; v2 carries the full
# statblock text we parse below.
BASE = "https://api.open5e.com/v2/"
HEADERS = {"User-Agent": "ward-dm/1.0"}

# The freely redistributable SRD documents (2014 + 2024 rules). Other documents
# in the API are third-party/homebrew and intentionally excluded.
SRD_DOC_KEYS = ("srd-2014", "srd-2024")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "open5e")

_ABILITY_ID = {
    "strength": 1,
    "dexterity": 2,
    "constitution": 3,
    "intelligence": 4,
    "wisdom": 5,
    "charisma": 6,
}
_ABILITY_NAMES = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]

# Map full damage-type words to the short tags the attack resolver logs.
_DTYPE_ABBR = {
    "piercing": "pi",
    "slashing": "sl",
    "bludgeoning": "bl",
    "fire": "fire",
    "cold": "cold",
    "lightning": "light",
    "thunder": "thun",
    "acid": "acid",
    "poison": "pois",
    "necrotic": "necr",
    "radiant": "rad",
    "force": "force",
    "psychic": "psy",
}

# Full ability names -> the short codes the attack resolver's save regex uses.
_ABILITY_SHORT = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
}

# Heal detection (mirrors battle.py's _HEAL_RE) so SRD heal spells resolve as
# heals in the attack engine.
_HEAL_RE = re.compile(
    r"\b(heal\w*|cure\w*|restore\w*|mend\w*|regain\w*|regenerat\w*)\b",
    re.IGNORECASE,
)

# "N darts" multiplier (mirrors battle.py's _DARTS_RE).
_DARTS_RE = re.compile(r"(\d+)\s+darts?\b", re.IGNORECASE)

# Bare dice expression finder (mirrors battle.py's _DICE_RE) for scraping
# damage out of a spell description when `damage_roll` is empty.
_DICE_RE = re.compile(r"\d*d\d+(?:[+-]\d+)?")

_TO_HIT = re.compile(r"([+-]?\d+)\s+to\s+hit", re.IGNORECASE)
# Matches both "Hit: 5 (1d6 + 2) slashing damage" and
# "taking 21 (6d6) fire damage …" (save-based breath weapons).
_HIT_DMG = re.compile(
    r"(?:Hit:|taking\s+\d+)\s*(?:\d+\s*)?\(\s*([0-9d+\s]+?)\s*\)\s*([A-Za-z ]+?)\s+damage",
    re.IGNORECASE,
)
_DC = re.compile(r"DC\s+(\d+)\s+([A-Za-z]+)\s+saving throw", re.IGNORECASE)
_INNER = re.compile(r"(\d*)d(\d+)(?:\s*\+\s*(\d+))?")


def _abbr(damage_type: str) -> str:
    dt = damage_type.strip().lower()
    return _DTYPE_ABBR.get(dt, dt[:3])


def _as_text(value) -> str:
    """Coerce an Open5e field that may be a string, a {"name": ...} dict, or a
    list of such into a plain string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or value.get("key") or "")
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    return str(value)


def _http_get_json(url: str):
    """GET a URL and parse JSON, wrapping failures in a friendly ValueError."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Open5e request failed ({exc.code}) for {url}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ValueError(f"Could not reach Open5e: {exc}") from exc


def fetch_raw(endpoint: str, document_keys=None, limit: int = 200) -> list[dict]:
    """Page through an Open5e v2 collection, optionally keeping only results
    from the given document keys. Returns the raw result dicts.

    SRD content ships under both `srd-2014` and `srd-2024`, so the same creature
    or spell appears twice; we dedupe by name, preferring `srd-2014`."""
    best: dict[str, tuple[int, dict]] = {}
    prio = {"srd-2014": 0, "srd-2024": 1}
    url = f"{BASE}{endpoint.rstrip('/')}/?limit={limit}"
    while url:
        data = _http_get_json(url)
        for row in data.get("results", []):
            doc_key = (row.get("document") or {}).get("key")
            if document_keys is not None and doc_key not in document_keys:
                continue
            name = row.get("name")
            p = prio.get(doc_key, 2)
            if name not in best or p < best[name][0]:
                best[name] = (p, row)
        url = data.get("next")
    return [v[1] for v in best.values()]


def cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.json")


def load_cache(name: str):
    """Return cached collection data, or None if missing/corrupt."""
    path = cache_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_cache(name: str, data) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    write_json_atomic(cache_path(name), data)


def get_collection(name: str, endpoint: str, transform, document_keys=None, force: bool = False):
    """Fetch a collection, transform each result, and cache it.

    Future content types just call this with their own endpoint + transform,
    e.g. `get_collection("spells", "spells", spell_to_fields)`.
    """
    if not force:
        cached = load_cache(name)
        if cached is not None:
            return cached
    raw = fetch_raw(endpoint, document_keys=document_keys)
    out = [transform(r) for r in raw]
    save_cache(name, out)
    return out


# ---------------------------------------------------------------------------
# Monster conversion
# ---------------------------------------------------------------------------


def _parse_action(name: str, desc: str | None) -> str | None:
    """Turn a statblock action into an attack line the resolver understands.

    Returns a weapon line ("Scimitar +4 · 1d6+2 sl"), a spell line
    ("Fireball — 8d6 fire (dex DC 15)"), or None when the action is a plain
    trait/ability (Multiattack, Nimble Escape, …)."""
    if not desc:
        return None
    to_hit = _TO_HIT.search(desc)
    hit = _HIT_DMG.search(desc)
    dc = _DC.search(desc)
    if hit:
        inner = _INNER.search(hit.group(1))
        if inner:
            n = inner.group(1) or "1"
            die = inner.group(2)
            bonus = inner.group(3)
            dice = f"{n}d{die}" + (f"+{bonus}" if bonus else "")
            dtype = _abbr(hit.group(2))
            if to_hit:
                return f"{name} {int(to_hit.group(1)):+d} · {dice} {dtype}"
            if dc:
                ab = _ABILITY_SHORT.get(dc.group(2).lower(), dc.group(2).lower())
                return f"{name} — {dice} {dtype} ({ab} DC {dc.group(1)})"
            return f"{name} — {dice} {dtype}"
    if dc:
        ab = _ABILITY_SHORT.get(dc.group(2).lower(), dc.group(2).lower())
        return f"{name} — ({ab} DC {dc.group(1)})"
    return None


def srd_monster_to_fields(mon: dict) -> dict:
    """Convert a raw Open5e v2 creature into the field dict the tracker feeds
    to `Combatant`. Conditions/saves are stored as lists so the result is
    JSON-serialisable for the cache."""
    ab = mon.get("ability_scores") or {}
    stats = {i: int(ab.get(name, 10)) for i, name in enumerate(_ABILITY_NAMES, start=1)}

    init_mod = mon.get("initiative_bonus")
    if init_mod is None:
        dex = stats.get(2)
        init_mod = (dex - 10) // 2 if dex is not None else 0
    else:
        init_mod = int(init_mod)

    saves = set()
    for aname, aid in _ABILITY_ID.items():
        if (mon.get("saving_throws") or {}).get(aname) is not None:
            saves.add(aid)

    speed = mon.get("speed")
    if isinstance(speed, dict):
        walk = speed.get("walk") or next(iter(speed.values()), None)
        speed = int(walk) if walk is not None else None
    elif isinstance(speed, (int, float)):
        speed = int(speed)
    else:
        speed = None

    cr = mon.get("challenge_rating") or 0
    pb = mon.get("proficiency_bonus")
    pb = int(pb) if pb is not None else 2 + int(float(cr)) // 4

    size = _as_text(mon.get("size")).capitalize()
    mtype = _as_text(mon.get("type")).lower()
    role = f"{size} {mtype}".strip()

    skills = {k: int(v) for k, v in (mon.get("skill_bonuses") or {}).items()}
    pp = mon.get("passive_perception")
    pp = int(pp) if pp is not None else None
    hd = mon.get("hit_dice") or ""
    ac = mon.get("armor_class")
    ac = int(ac) if isinstance(ac, (int, float)) else 10
    hp = int(mon.get("hit_points") or 10)

    desc = _as_text(mon.get("desc"))
    note = desc.split(". ")[0][:160] if desc else role

    attacks: list[str] = []
    traits: list[str] = []
    for action in mon.get("actions", []):
        line = _parse_action(action.get("name", ""), action.get("desc", ""))
        if line:
            attacks.append(line)
        else:
            nm = action.get("name", "")
            d = action.get("desc", "")
            traits.append(f"{nm} — {d}" if d else nm)
    for t in mon.get("traits", []):
        if isinstance(t, str):
            traits.append(t)

    return {
        "name": _as_text(mon.get("name")) or "Monster",
        "kind": "monster",
        "hp": hp,
        "max_hp": hp,
        "ac": ac,
        "init": None,
        "init_mod": init_mod,
        "conditions": [],
        "role": role,
        "note": note,
        "x": 0,
        "y": 0,
        "stats": stats,
        "saves": sorted(saves),
        "speed": speed,
        "proficiency": int(pb),
        "hit_dice": hd,
        "skills": skills,
        "passive_perception": pp,
        "attacks": attacks,
        "traits": traits,
        "spells": [],
        "ddb_id": None,
    }


def get_srd_monsters(force: bool = False) -> list[dict]:
    """Fetch + cache the SRD monster library as field dicts."""
    return get_collection("monsters", "creatures", srd_monster_to_fields, document_keys=SRD_DOC_KEYS, force=force)


# ---------------------------------------------------------------------------
# Spell conversion
# ---------------------------------------------------------------------------

# Spell save/heal parsing reuses the monster attack regexes; add word->digit so
# "three darts" (Magic Missile) is caught the same way "3 darts" is.
_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_WORD_DARTS = re.compile(r"\b(" + "|".join(_WORD_NUM) + r")\b.{0,30}?\bdarts?\b", re.IGNORECASE)


def _spell_cast_string(spell: dict) -> str:
    """Build the engine-ready attack string for an SRD spell so it can be slotted
    straight into a creature's `spells` list and resolved by `resolve_attack`.

    Damage comes from `damage_roll` when present, else the spell description.
    Save-based and heal spells are tagged the same way the hand-authored
    templates are; SRD spells carry no caster DC, so save spells fall back to a
    default DC 13 (cosmetic — the tracker doesn't actually apply the effect)."""
    name = _as_text(spell.get("name")) or "Spell"
    heal = bool(_HEAL_RE.search(name))

    dice = (spell.get("damage_roll") or "").strip()
    if not dice:
        # SRD descriptions space out the bonus ("1d8 + 2"); strip whitespace so
        # the dice regex captures the full expression.
        m = _DICE_RE.search(re.sub(r"\s+", "", spell.get("desc") or ""))
        if m:
            dice = m.group(0)
    dice = re.sub(r"\s+", "", dice)

    dtypes = spell.get("damage_types") or []
    if dtypes:
        dtype = _abbr(_as_text(dtypes[0]))
    else:
        dm = re.search(r"([A-Za-z ]+?)\s+damage", spell.get("desc") or "", re.IGNORECASE)
        dtype = _abbr(dm.group(1)) if dm else ""

    darts_m = _DARTS_RE.search(spell.get("desc") or "")
    if not darts_m:
        darts_m = _WORD_DARTS.search(spell.get("desc") or "")
    darts = None
    if darts_m:
        n = _WORD_NUM.get(darts_m.group(1).lower(), None)
        if n is None:
            try:
                n = int(darts_m.group(1))
            except ValueError:
                n = None
        if n is not None and n > 1:
            darts = n

    save = spell.get("saving_throw_ability")
    save = _ABILITY_SHORT.get(save, save) if save else None

    if heal:
        return f"{name} — {dice or '1d8'} HP"
    if darts:
        base = f"{darts} darts, {dice} {dtype}".rstrip()
        return f"{name} — {base} ({save} DC 13)" if save else f"{name} — {base}"
    if dice:
        return f"{name} — {dice} {dtype} ({save} DC 13)" if save else f"{name} — {dice} {dtype}"
    if save:
        return f"{name} — ({save} DC 13)"
    return name


def spell_to_fields(spell: dict) -> dict:
    """Convert a raw Open5e v2 spell into a field dict for the library browser."""
    rng = spell.get("range_text") or spell.get("range")
    return {
        "name": _as_text(spell.get("name")) or "Spell",
        "level": spell["level"] if isinstance(spell.get("level"), int) else 0,
        "school": _as_text(spell.get("school")),
        "casting_time": _as_text(spell.get("casting_time")),
        "range": _as_text(rng),
        "components": _as_text(spell.get("components")) or "",
        "duration": _as_text(spell.get("duration")),
        "desc": _as_text(spell.get("desc")),
        "cast": _spell_cast_string(spell),
    }


def get_srd_spells(force: bool = False) -> list[dict]:
    """Fetch + cache the SRD spell library as field dicts."""
    return get_collection("spells", "spells", spell_to_fields, document_keys=SRD_DOC_KEYS, force=force)
