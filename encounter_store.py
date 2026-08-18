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


def empty_store() -> dict:
    return {"version": STORE_VERSION, "last_active": None, "current": {}, "encounters": {}}


def scope_key(campaign: str | None) -> str:
    return campaign if campaign else NO_CAMPAIGN


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_store(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("encounters"), dict):
        return empty_store()
    encounters: dict[str, dict] = {}
    for raw_id, raw_record in raw["encounters"].items():
        encounter_id = str(raw_id).strip()
        if not encounter_id or not isinstance(raw_record, dict):
            continue
        snapshot = raw_record.get("snapshot")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("combatants"), list):
            continue
        campaign = raw_record.get("campaign")
        if not isinstance(campaign, str):
            campaign = None
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

    current: dict[str, str] = {}
    raw_current = raw.get("current")
    if isinstance(raw_current, dict):
        for raw_scope, raw_id in raw_current.items():
            encounter_id = str(raw_id)
            if encounter_id in encounters:
                current[str(raw_scope)] = encounter_id
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
    records = [
        record for record in data.get("encounters", {}).values()
        if isinstance(record, dict) and record.get("campaign") == campaign
    ]
    rank = {"active": 0, "paused": 1, "complete": 2}
    records.sort(key=lambda record: str(record.get("updated_at", "")), reverse=True)
    records.sort(key=lambda record: rank.get(str(record.get("status")), 3))
    return records


def current_for(data: dict, campaign: str | None) -> dict | None:
    encounter_id = data.get("current", {}).get(scope_key(campaign))
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
        "campaign": campaign,
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
    record["campaign"] = campaign
    record["updated_at"] = now_iso()
    activate_record(data, encounter_id)
    return True
