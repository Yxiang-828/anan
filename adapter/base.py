"""Base primitives shared by the chat adapters.

ContractError carries (code, message); atomic_write_json
writes tmp-then-rename so a crash never leaves a half-written offset file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """A typed contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def atomic_write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                      allow_nan=False).encode("utf-8") + b"\n"
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
