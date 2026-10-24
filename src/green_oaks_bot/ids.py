"""Snowflake id validation, shared by the bot, the REST path builders and the Store."""

from __future__ import annotations

import re

# fullmatch: "$" would accept a trailing newline
_SNOWFLAKE = re.compile(r"[0-9]{1,25}")


def is_snowflake(value: object) -> bool:
    return isinstance(value, str) and _SNOWFLAKE.fullmatch(value) is not None


def require_snowflake(value: str) -> str:
    """Return `value` unchanged, or raise ValueError: ids are interpolated into URL paths."""
    if not is_snowflake(value):
        raise ValueError(f"not a snowflake id: {value!r}")
    return value
