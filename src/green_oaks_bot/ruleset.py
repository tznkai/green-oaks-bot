# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rules data: loaded once from a TOML file and handed to the engine as an immutable Ruleset.

The engine is game-neutral. Every word that names a result (the outcome words, the points
terms, the keywords, which card category gives what) comes from the rules file. The file's
schema is described in its own header comment.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

Category = Literal["ace", "two", "face", "pip"]
CATEGORIES: tuple[Category, ...] = ("ace", "two", "face", "pip")
DEFAULT_RULES_FILE = Path(__file__).resolve().parent / "rulesets" / "green_oaks.toml"

_TOP_KEYS = frozenset({"labels", "grumble", "trump", "non_trump"})
_LABEL_KEYS = frozenset({"success", "failure", "success_points", "failure_points"})
_CELL_KEYS = frozenset({"success", "points", "keyword", "grumble", "changes_trump", "special"})


class RulesetError(ValueError):
    """The rules file is missing, unreadable, or does not describe a complete ruleset."""


class GrumbleOption(Enum):
    NONE = "none"
    REDRAW = "redraw"    # a failure: flip a replacement card
    UPGRADE = "upgrade"  # a failure: becomes a success worth the upgrade points


@dataclass(frozen=True)
class Cell:
    """One of the eight card categories: (trump or not) x (ace, two, face, pip)."""
    success: bool
    points: int
    keyword: str | None
    grumble: GrumbleOption
    changes_trump: bool
    special: bool


@dataclass(frozen=True)
class Labels:
    success: str
    failure: str
    success_points: str
    failure_points: str


@dataclass(frozen=True)
class Ruleset:
    labels: Labels
    upgrade_points: int
    cells: Mapping[tuple[bool, Category], Cell]  # keyed by (is_trump, category)

    def cell(self, is_trump: bool, category: Category) -> Cell:
        return self.cells[(is_trump, category)]


def _fail(source: str, message: str) -> RulesetError:
    return RulesetError(f"{source}: {message}")


def _section(data: Mapping[str, Any], name: str, source: str) -> Mapping[str, Any]:
    value = data.get(name)
    if not isinstance(value, Mapping):
        raise _fail(source, f"missing [{name}] section")
    return value


def _text(d: Mapping[str, Any], key: str, where: str, source: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(source, f"[{where}] {key} must be a non-empty string")
    return value


def _int(d: Mapping[str, Any], key: str, where: str, source: str) -> int:
    value = d.get(key)
    if type(value) is not int or value < 0:  # bool is a subclass of int, so type() is exact
        raise _fail(source, f"[{where}] {key} must be a non-negative integer")
    return value


def _bool(d: Mapping[str, Any], key: str, where: str, source: str) -> bool:
    value = d.get(key)
    if type(value) is not bool:
        raise _fail(source, f"[{where}] {key} must be true or false")
    return value


def _no_extra_keys(d: Mapping[str, Any], allowed: frozenset[str], where: str, source: str) -> None:
    extra = sorted(set(d) - allowed)
    if extra:
        raise _fail(source, f"[{where}] has unknown key(s): {', '.join(extra)}")


def _cell(d: Mapping[str, Any], is_trump: bool, category: str, source: str) -> Cell:
    where = f"{'trump' if is_trump else 'non_trump'}.{category}"
    _no_extra_keys(d, _CELL_KEYS, where, source)
    success = _bool(d, "success", where, source)
    points = _int(d, "points", where, source)
    keyword = None
    if "keyword" in d:
        keyword = _text(d, "keyword", where, source)
    grumble_name = _text(d, "grumble", where, source)
    try:
        grumble = GrumbleOption(grumble_name)
    except ValueError:
        raise _fail(source, f"[{where}] grumble must be none, redraw or upgrade, not {grumble_name!r}") from None
    if success and grumble is not GrumbleOption.NONE:
        raise _fail(source, f"[{where}] grumble must be \"none\" on a success cell")
    return Cell(
        success=success,
        points=points,
        keyword=keyword,
        grumble=grumble,
        changes_trump=_bool(d, "changes_trump", where, source),
        special=_bool(d, "special", where, source),
    )


def ruleset_from_dict(data: Mapping[str, Any], source: str = "rules file") -> Ruleset:
    """Validate parsed TOML and build the Ruleset. Every problem found is a RulesetError naming it."""
    extra = sorted(set(data) - _TOP_KEYS)
    if extra:
        raise _fail(source, f"unknown section(s): {', '.join(extra)}")

    labels_d = _section(data, "labels", source)
    _no_extra_keys(labels_d, _LABEL_KEYS, "labels", source)
    labels = Labels(**{key: _text(labels_d, key, "labels", source) for key in sorted(_LABEL_KEYS)})

    grumble_d = _section(data, "grumble", source)
    _no_extra_keys(grumble_d, frozenset({"upgrade_points"}), "grumble", source)
    upgrade_points = _int(grumble_d, "upgrade_points", "grumble", source)

    cells: dict[tuple[bool, Category], Cell] = {}
    for is_trump, section in ((True, "trump"), (False, "non_trump")):
        group = _section(data, section, source)
        _no_extra_keys(group, frozenset(CATEGORIES), section, source)
        for category in CATEGORIES:
            if category not in group:
                raise _fail(source, f"missing [{section}.{category}] section")
            cells[(is_trump, category)] = _cell(_section(group, category, source), is_trump, category, source)

    return Ruleset(labels=labels, upgrade_points=upgrade_points, cells=MappingProxyType(cells))


def load_ruleset(path: Path = DEFAULT_RULES_FILE) -> Ruleset:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise RulesetError(f"cannot read rules file {path}: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RulesetError(f"rules file {path} is not valid TOML: {exc}") from exc
    return ruleset_from_dict(data, source=str(path))


@lru_cache(maxsize=1)
def default_ruleset() -> Ruleset:
    """The packaged rules file, loaded once. Production passes the configured ruleset explicitly."""
    return load_ruleset(DEFAULT_RULES_FILE)
