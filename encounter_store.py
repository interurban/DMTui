"""Persistence for campaign-owned encounter instances.

Encounter instances retain live fight state and belong to one campaign (or to
the explicit campaign-free scope). Prepared encounters are intentionally not
stored here: they are reusable monster templates, not played fights.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from typing import Any

from persistence import write_json_atomic


STORE_VERSION = 1
NO_CAMPAIGN = "__campaign_free__"
VALID_STATUSES = {"active", "paused", "complete"}
SNAPSHOT_REQUIRED_FIELDS = {"name", "kind", "hp", "max_hp", "ac"}
SNAPSHOT_INT_FIELDS = {"hp", "max_hp", "ac", "init_mod", "x", "y"}
SNAPSHOT_OPTIONAL_INT_FIELDS = {
    "init", "speed", "proficiency", "passive_perception", "spell_dc", "ddb_id", "level",
}
SNAPSHOT_STRING_FIELDS = {"name", "kind", "role", "note", "hit_dice", "reminder"}
SNAPSHOT_STRING_LIST_FIELDS = {"conditions", "attacks", "traits", "spells"}


def empty_store() -> dict:
    return {"version": STORE_VERSION, "last_active": None, "current": {}, "encounters": {}}


def scope_key(campaign: str | None) -> str:
    return campaign if campaign else NO_CAMPAIGN


def normalize_campaign(campaign: Any) -> str | None:
    """Collapse invalid and blank ownership values into campaign-free scope."""
    return campaign.strip() if isinstance(campaign, str) and campaign.strip() else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def valid_snapshot(snapshot: Any) -> bool:
    """Return whether a snapshot has enough structure to be resumed safely."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("combatants"), list):
        return False
    for creature in snapshot["combatants"]:
        if not isinstance(creature, dict) or not SNAPSHOT_REQUIRED_FIELDS.issubset(creature):
            return False
        if any(
            field in creature and not isinstance(creature[field], str)
            for field in SNAPSHOT_STRING_FIELDS
        ):
            return False
        if any(
            field in creature
            and (not isinstance(creature[field], int) or isinstance(creature[field], bool))
            for field in SNAPSHOT_INT_FIELDS
        ):
            return False
        if any(
            field in creature
            and creature[field] is not None
            and (not isinstance(creature[field], int) or isinstance(creature[field], bool))
            for field in SNAPSHOT_OPTIONAL_INT_FIELDS
        ):
            return False
        for field in SNAPSHOT_STRING_LIST_FIELDS:
            value = creature.get(field, [])
            if not isinstance(value, (list, tuple, set)) or not all(isinstance(item, str) for item in value):
                return False
        stats = creature.get("stats", {})
        if not isinstance(stats, dict):
            return False
        try:
            if any(
                not 1 <= int(key) <= 6
                or not isinstance(value, int)
                or isinstance(value, bool)
                for key, value in stats.items()
            ):
                return False
        except (TypeError, ValueError):
            return False
        saves = creature.get("saves", [])
        if not isinstance(saves, (list, tuple, set)) or any(
            not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 6
            for value in saves
        ):
            return False
        skills = creature.get("skills", {})
        if not isinstance(skills, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            for key, value in skills.items()
        ):
            return False
    return True


def normalize_store(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("encounters"), dict):
        return empty_store()
    encounters: dict[str, dict] = {}
    for raw_id, raw_record in raw["encounters"].items():
        encounter_id = str(raw_id).strip()
        if not encounter_id or not isinstance(raw_record, dict):
            continue
        snapshot = raw_record.get("snapshot")
        if not valid_snapshot(snapshot):
            continue
        campaign = normalize_campaign(raw_record.get("campaign"))
        status = str(raw_record.get("status") or "paused")
        if status not in VALID_STATUSES:
            status = "paused"
        created = str(raw_record.get("created_at") or raw_record.get("updated_at") or now_iso())
        updated = str(raw_record.get("updated_at") or created)
        encounters[encounter_id] = {
            "id": encounter_id,
            "campaign": campaign,
            "name": str(raw_record.get("name") or "Untitled encounter").strip() or "Untitled encounter",
            "status": status,
            "created_at": created,
            "updated_at": updated,
            "snapshot": snapshot,
        }
        if raw_record.get("source_template"):
            encounters[encounter_id]["source_template"] = str(raw_record["source_template"])

    current_candidates: dict[str, list[str]] = {}
    raw_current = raw.get("current")
    if isinstance(raw_current, dict):
        for raw_id in raw_current.values():
            encounter_id = str(raw_id)
            if encounter_id in encounters:
                campaign = encounters[encounter_id]["campaign"]
                canonical_scope = scope_key(campaign)
                current_candidates.setdefault(canonical_scope, []).append(encounter_id)
    current = {
        scope: max(ids, key=lambda encounter_id: encounters[encounter_id]["updated_at"])
        for scope, ids in current_candidates.items()
    }
    current_ids = set(current.values())
    for encounter_id, record in encounters.items():
        if record["status"] == "active" and encounter_id not in current_ids:
            record["status"] = "paused"
    for encounter_id in current_ids:
        encounters[encounter_id]["status"] = "active"
    last_active = raw.get("last_active")
    if not isinstance(last_active, str) or last_active not in encounters:
        last_active = next(iter(current.values()), None)
    return {
        "version": STORE_VERSION,
        "last_active": last_active,
        "current": current,
        "encounters": encounters,
    }


def read_store(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as encounter_file:
            return normalize_store(json.load(encounter_file))
    except (OSError, ValueError, TypeError):
        return empty_store()


def write_store(path: str, data: dict) -> None:
    write_json_atomic(path, normalize_store(data), indent=2)


def records_for(data: dict, campaign: str | None) -> list[dict]:
    campaign = normalize_campaign(campaign)
    records = [
        record for record in data.get("encounters", {}).values()
        if isinstance(record, dict) and normalize_campaign(record.get("campaign")) == campaign
    ]
    rank = {"active": 0, "paused": 1, "complete": 2}
    records.sort(key=lambda record: str(record.get("updated_at", "")), reverse=True)
    records.sort(key=lambda record: rank.get(str(record.get("status")), 3))
    return records


def current_for(data: dict, campaign: str | None) -> dict | None:
    encounter_id = data.get("current", {}).get(scope_key(normalize_campaign(campaign)))
    record = data.get("encounters", {}).get(encounter_id)
    return record if isinstance(record, dict) else None


def last_active(data: dict) -> dict | None:
    encounter_id = data.get("last_active")
    record = data.get("encounters", {}).get(encounter_id)
    return record if isinstance(record, dict) else None


def create_record(
    data: dict,
    campaign: str | None,
    name: str,
    snapshot: dict,
    *,
    source_template: str | None = None,
) -> dict:
    encounter_id = new_id()
    timestamp = now_iso()
    record = {
        "id": encounter_id,
        "campaign": normalize_campaign(campaign),
        "name": name.strip() or "Untitled encounter",
        "status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "snapshot": snapshot,
    }
    if source_template:
        record["source_template"] = source_template
    data.setdefault("encounters", {})[encounter_id] = record
    activate_record(data, encounter_id)
    return record


def activate_record(data: dict, encounter_id: str) -> dict | None:
    record = data.get("encounters", {}).get(encounter_id)
    if not isinstance(record, dict):
        return None
    scope = scope_key(record.get("campaign") if isinstance(record.get("campaign"), str) else None)
    previous_id = data.setdefault("current", {}).get(scope)
    if previous_id != encounter_id:
        previous = data.get("encounters", {}).get(previous_id)
        if isinstance(previous, dict) and previous.get("status") == "active":
            previous["status"] = "paused"
    data["current"][scope] = encounter_id
    data["last_active"] = encounter_id
    record["status"] = "active"
    record["updated_at"] = now_iso()
    return record


def update_record(data: dict, encounter_id: str, snapshot: dict) -> bool:
    record = data.get("encounters", {}).get(encounter_id)
    if not isinstance(record, dict):
        return False
    record["snapshot"] = snapshot
    record["updated_at"] = now_iso()
    return True


def complete_record(data: dict, encounter_id: str) -> bool:
    record = data.get("encounters", {}).get(encounter_id)
    if not isinstance(record, dict):
        return False
    record["status"] = "complete"
    record["updated_at"] = now_iso()
    scope = scope_key(record.get("campaign") if isinstance(record.get("campaign"), str) else None)
    if data.get("current", {}).get(scope) == encounter_id:
        data["current"].pop(scope, None)
    if data.get("last_active") == encounter_id:
        data["last_active"] = next(iter(data.get("current", {}).values()), None)
    return True


def rename_record(data: dict, encounter_id: str, name: str) -> bool:
    record = data.get("encounters", {}).get(encounter_id)
    if not isinstance(record, dict) or not name.strip():
        return False
    record["name"] = name.strip()
    record["updated_at"] = now_iso()
    return True


def move_record(data: dict, encounter_id: str, campaign: str | None) -> bool:
    """Move a live encounter into a campaign, preserving its independent state."""
    record = data.get("encounters", {}).get(encounter_id)
    if not isinstance(record, dict):
        return False
    old_scope = scope_key(record.get("campaign") if isinstance(record.get("campaign"), str) else None)
    if data.get("current", {}).get(old_scope) == encounter_id:
        data["current"].pop(old_scope, None)
    record["campaign"] = normalize_campaign(campaign)
    record["updated_at"] = now_iso()
    activate_record(data, encounter_id)
    return True
