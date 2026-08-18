"""Small persistence primitives shared by Ward's JSON stores."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any


def _stage_json(path: str, data: Any, *, indent: int | None = None) -> str:
    """Serialize JSON to a unique temporary file beside its destination."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=indent)
        return temp_path
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def write_json_atomic(path: str, data: Any, *, indent: int | None = None) -> None:
    """Write JSON beside its destination, then atomically replace the old file."""
    temp_path = _stage_json(path, data, indent=indent)
    try:
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def write_json_group_atomic(items: list[tuple[str, Any, int | None]]) -> None:
    """Replace several JSON files as one recoverable operation.

    Every new file and every rollback copy is staged before the first live file
    changes. If a later replace fails, files already replaced are restored.
    """
    staged: list[tuple[str, str]] = []
    rollbacks: dict[str, str | None] = {}
    committed: list[str] = []
    try:
        for path, data, indent in items:
            staged.append((path, _stage_json(path, data, indent=indent)))
        for path, _temp_path in staged:
            if os.path.exists(path):
                directory = os.path.dirname(os.path.abspath(path))
                descriptor, rollback_path = tempfile.mkstemp(
                    prefix=f".{os.path.basename(path)}.",
                    suffix=".rollback",
                    dir=directory,
                )
                os.close(descriptor)
                rollbacks[path] = rollback_path
                shutil.copyfile(path, rollback_path)
            else:
                rollbacks[path] = None
        for path, temp_path in staged:
            os.replace(temp_path, path)
            committed.append(path)
    except BaseException as exc:
        rollback_error: OSError | None = None
        for path in reversed(committed):
            rollback_path = rollbacks.get(path)
            try:
                if rollback_path is None:
                    os.unlink(path)
                else:
                    os.replace(rollback_path, path)
                    rollbacks[path] = None
            except OSError as restore_exc:
                rollback_error = rollback_error or restore_exc
        if rollback_error is not None:
            raise OSError(
                f"JSON group write failed and rollback was incomplete: {rollback_error}"
            ) from exc
        raise
    finally:
        for _path, temp_path in staged:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        for rollback_path in rollbacks.values():
            if rollback_path is not None:
                try:
                    os.unlink(rollback_path)
                except OSError:
                    pass
