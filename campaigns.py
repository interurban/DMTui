"""Campaign persistence and roster normalization.

A campaign is the long-lived container: it owns a party roster, lookup-reference
preference, and notes. A live encounter points at a campaign by name and
snapshots the party at the moment the encounter starts. Prepared encounters
remain party-free monster setups so they can be reused with any campaign.
"""

from __future__ import annotations

import json
import os
from typing import Any


BOOK_VERSION = 2
DEFAULT_RULESET = "2014"


def empty_book() -> dict:
    return {"version": BOOK_VERSION, "active": None, "campaigns": {}}


def normalize_member(value: Any) -> dict | None:
    """Normalize a saved party member into a small, stable roster reference."""
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        raw_id = value.get("ddb_id")
    elif isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        name = ""
        raw_id = value
    elif isinstance(value, str):
        name = value.strip()
        raw_id = None
    else:
        return None

    ddb_id = None
    if isinstance(raw_id, int) or (isinstance(raw_id, str) and raw_id.strip().isdigit()):
        ddb_id = int(raw_id)
    if not name and ddb_id is None:
        return None

    member: dict[str, object] = {}
    if name:
        member["name"] = name
    if ddb_id is not None:
        member["ddb_id"] = ddb_id
    return member


def normalize_book(raw: Any) -> dict:
    """Return the current schema while accepting legacy ``character_ids``."""
    if not isinstance(raw, dict):
        return empty_book()
    raw_campaigns = raw.get("campaigns")
    if not isinstance(raw_campaigns, dict):
        return empty_book()

    normalized: dict[str, dict] = {}
    for raw_name, raw_campaign in raw_campaigns.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_campaign, dict):
            continue
        campaign = dict(raw_campaign)
        roster = campaign.get("party")
        if not isinstance(roster, list):
            roster = campaign.get("character_ids") or []
        party: list[dict] = []
        seen: set[tuple[str, object]] = set()
        for value in roster:
            member = normalize_member(value)
            if member is None:
                continue
            identity = (
                ("ddb", member["ddb_id"])
                if "ddb_id" in member
                else ("name", str(member["name"]).casefold())
            )
            if identity in seen:
                continue
            seen.add(identity)
            party.append(member)
        campaign.pop("character_ids", None)
        campaign["party"] = party
        campaign["ruleset"] = str(campaign.get("ruleset") or DEFAULT_RULESET)
        campaign["notes"] = str(campaign.get("notes") or "")
        normalized[name] = campaign

    active = raw.get("active")
    if not isinstance(active, str) or active not in normalized:
        active = next(iter(normalized), None)
    return {"version": BOOK_VERSION, "active": active, "campaigns": normalized}


def read_book(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as campaign_file:
            return normalize_book(json.load(campaign_file))
    except (OSError, ValueError, TypeError):
        return empty_book()


def write_book(path: str, data: dict) -> None:
    """Atomically persist normalized campaign data."""
    normalized = normalize_book(data)
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as campaign_file:
            json.dump(normalized, campaign_file, indent=2)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def party_for(data: dict, name: str | None) -> list[dict]:
    campaign = data.get("campaigns", {}).get(name) if name else None
    if not isinstance(campaign, dict):
        return []
    party = campaign.get("party")
    return [dict(member) for member in party if isinstance(member, dict)] if isinstance(party, list) else []
