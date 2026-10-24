# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rules data: loaded once from a TOML file and handed to the engine as an immutable Ruleset.

The engine is game-neutral. Every word that names a result (the outcome words, the points
terms, the keywords, which card category gives what) comes from the rules file, and so does
every sentence that restates a result: the game half of the help text and the hints (prompts,
redraw narration and redraw refusals). The file's schema is described in its own header comment.
"""

from __future__ import annotations

import string
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

# The command players type to redraw. It stays `grumble` (user decision, phase 5 addendum 3).
REDRAW_COMMAND = "grumble"

_TOP_KEYS = frozenset({"labels", "redraw", "trump", "non_trump", "help", "hints"})
_LABEL_KEYS = frozenset({"success", "failure", "success_points", "failure_points", "redraw"})
_CELL_KEYS = frozenset({"success", "points", "keyword", "redraw", "changes_trump", "special"})
_HELP_KEYS = frozenset({"title", "lines", "credit"})
# Fields every text may use; see Ruleset.text.
_COMMON_FIELDS = frozenset({"p", "redraw_cmd", "trump_cmd", "upgrade_points", *_LABEL_KEYS})
# Each hint and the extra fields the engine passes it.
HINT_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType({
    "choose_trump": frozenset({"name", "suits"}),
    "choose_trump_unavailable": frozenset({"name"}),
    "may_replace": frozenset({"name"}),
    "may_upgrade": frozenset({"name"}),
    "replaced": frozenset({"name", "card", "result"}),
    "upgraded": frozenset({"name", "card", "result"}),
    "nothing_to_redraw": frozenset(),
    "not_your_redraw": frozenset(),
    "redraw_empty_draw": frozenset(),
})


class RulesetError(ValueError):
    """The rules file is missing, unreadable, or does not describe a complete ruleset."""


class RedrawOption(Enum):
    NONE = "none"
    REPLACE = "replace"  # a failure: flip a replacement card
    UPGRADE = "upgrade"  # a failure: becomes a success worth the upgrade points


@dataclass(frozen=True)
class Cell:
    """One of the eight card categories: (trump or not) x (ace, two, face, pip)."""
    success: bool
    points: int
    keyword: str | None
    redraw: RedrawOption
    changes_trump: bool
    special: bool


@dataclass(frozen=True)
class Labels:
    success: str
    failure: str
    success_points: str
    failure_points: str
    redraw: str


@dataclass(frozen=True)
class Help:
    """The game half of the help text. Templates, filled in by Ruleset.text."""
    title: str
    lines: tuple[str, ...]
    credit: str


@dataclass(frozen=True)
class Ruleset:
    labels: Labels
    upgrade_points: int
    cells: Mapping[tuple[bool, Category], Cell]  # keyed by (is_trump, category)
    help: Help
    hints: Mapping[str, str]  # keyed by the names in HINT_FIELDS

    def cell(self, is_trump: bool, category: Category) -> Cell:
        return self.cells[(is_trump, category)]

    def text(self, template: str, prefix: str, **fields: object) -> str:
        """Fill a template from the rules file: the common fields plus the caller's own."""
        common = {
            "p": prefix,
            "redraw_cmd": f"`{prefix}{REDRAW_COMMAND}`",
            "trump_cmd": f"`{prefix}trump <suit>`",
            "upgrade_points": self.upgrade_points,
            **{key: getattr(self.labels, key) for key in _LABEL_KEYS},
        }
        return template.format_map({**common, **fields})

    def hint(self, key: str, prefix: str, **fields: object) -> str:
        return self.text(self.hints[key], prefix, **fields)


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


def _template(d: Mapping[str, Any], key: str, where: str, source: str,
              allowed: frozenset[str] = frozenset()) -> str:
    """A non-empty format string that uses only the common fields and `allowed`."""
    value = _text(d, key, where, source)
    try:
        names = [name for _, name, _, _ in string.Formatter().parse(value) if name is not None]
    except ValueError as exc:
        raise _fail(source, f"[{where}] {key} is not a valid template: {exc}") from None
    unknown = sorted(set(names) - _COMMON_FIELDS - allowed)
    if unknown:
        raise _fail(source, f"[{where}] {key} uses unknown field(s): {', '.join(unknown)}")
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
    redraw_name = _text(d, "redraw", where, source)
    try:
        redraw = RedrawOption(redraw_name)
    except ValueError:
        raise _fail(source, f"[{where}] redraw must be none, replace or upgrade, not {redraw_name!r}") from None
    if success and redraw is not RedrawOption.NONE:
        raise _fail(source, f"[{where}] redraw must be \"none\" on a success cell")
    return Cell(
        success=success,
        points=points,
        keyword=keyword,
        redraw=redraw,
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

    redraw_d = _section(data, "redraw", source)
    _no_extra_keys(redraw_d, frozenset({"upgrade_points"}), "redraw", source)
    upgrade_points = _int(redraw_d, "upgrade_points", "redraw", source)

    cells: dict[tuple[bool, Category], Cell] = {}
    for is_trump, section in ((True, "trump"), (False, "non_trump")):
        group = _section(data, section, source)
        _no_extra_keys(group, frozenset(CATEGORIES), section, source)
        for category in CATEGORIES:
            if category not in group:
                raise _fail(source, f"missing [{section}.{category}] section")
            cells[(is_trump, category)] = _cell(_section(group, category, source), is_trump, category, source)

    help_d = _section(data, "help", source)
    _no_extra_keys(help_d, _HELP_KEYS, "help", source)
    lines = help_d.get("lines")
    if not isinstance(lines, list) or not lines:
        raise _fail(source, "[help] lines must be a non-empty list of strings")
    help_ = Help(
        title=_template(help_d, "title", "help", source),
        lines=tuple(_template({"line": line}, "line", f"help.lines[{i}]", source)
                    for i, line in enumerate(lines)),
        credit=_template(help_d, "credit", "help", source),
    )

    hints_d = _section(data, "hints", source)
    _no_extra_keys(hints_d, frozenset(HINT_FIELDS), "hints", source)
    hints = {key: _template(hints_d, key, "hints", source, allowed)
             for key, allowed in HINT_FIELDS.items()}

    return Ruleset(labels=labels, upgrade_points=upgrade_points, cells=MappingProxyType(cells),
                   help=help_, hints=MappingProxyType(hints))


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
