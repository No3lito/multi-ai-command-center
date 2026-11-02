"""Prefixed random identifiers, e.g. msg_3f2a... (32 hex chars)."""

from __future__ import annotations

import uuid
from typing import Literal

Prefix = Literal["msg", "room", "usr", "agt", "ext", "sys", "ses", "run", "res"]


def new_id(prefix: Prefix) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
