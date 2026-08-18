"""Portable backup and recovery for Ward's user-owned campaign data."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any

import campaigns as campaign_store
import encounter_store
from persistence import write_json_atomic


BACKUP_FORMAT = "ward-data-backup"
BACKUP_VERSION = 1


def normalize_templates(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("templates"), dict):
        return {"templates": {}}
    return {
        "templates": {
            str(name): snapshot
            for name, snapshot in raw["templates"].items()
            if str(name).strip() and isinstance(snapshot, dict)
        }
    }


def build_bundle(campaigns: dict, encounters: dict, templates: dict, *, created_at: str | None = None) -> dict:
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "campaigns": campaign_store.normalize_book(campaigns),
        "encounters": encounter_store.normalize_store(encounters),
        "prepared_encounters": normalize_templates(templates),
    }


def normalize_bundle(raw: Any) -> dict:
    if not isinstance(raw, dict) or raw.get("format") != BACKUP_FORMAT:
        raise ValueError("This is not a Ward data backup")
    if raw.get("version") != BACKUP_VERSION:
        raise ValueError("This Ward backup version is not supported")
    return build_bundle(
        raw.get("campaigns"),
        raw.get("encounters"),
        raw.get("prepared_encounters"),
        created_at=str(raw.get("created_at") or "unknown"),
    )


def read_backup(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as backup_file:
            return normalize_bundle(json.load(backup_file))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Ward backup could not be read: {exc}") from exc


def write_backup(directory: str, campaigns: dict, encounters: dict, templates: dict) -> str:
    os.makedirs(directory, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    bundle = build_bundle(campaigns, encounters, templates, created_at=timestamp.isoformat(timespec="seconds"))
    filename = f"ward-backup-{timestamp.strftime('%Y%m%d-%H%M%S-%f')}.json"
    path = os.path.join(directory, filename)
    write_json_atomic(path, bundle, indent=2)
    return path


def list_backups(directory: str) -> list[str]:
    try:
        names = [
            name for name in os.listdir(directory)
            if name.startswith("ward-backup-") and name.endswith(".json")
            and os.path.isfile(os.path.join(directory, name))
        ]
    except OSError:
        return []
    return [os.path.join(directory, name) for name in sorted(names, reverse=True)]


def write_templates(path: str, templates: dict) -> None:
    write_json_atomic(path, normalize_templates(templates), indent=2)


def restore_backup(path: str, campaign_path: str, encounter_path: str, template_path: str) -> dict:
    """Validate the complete bundle before replacing any live Ward data."""
    bundle = read_backup(path)
    campaign_store.write_book(campaign_path, bundle["campaigns"])
    encounter_store.write_store(encounter_path, bundle["encounters"])
    write_templates(template_path, bundle["prepared_encounters"])
    return bundle
