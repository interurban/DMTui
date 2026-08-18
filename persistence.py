"""Small persistence primitives shared by Ward's JSON stores."""

from __future__ import annotations

import json
import os
from typing import Any


def write_json_atomic(path: str, data: Any, *, indent: int | None = None) -> None:
    """Write JSON beside its destination, then atomically replace the old file."""
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=indent)
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
