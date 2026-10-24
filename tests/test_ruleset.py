# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Loading the rules data file: the packaged ruleset is complete, and a broken one is refused clearly."""

from __future__ import annotations

import copy
import dataclasses
import tomllib
from pathlib import Path

import pytest

from green_oaks_bot.ruleset import (
    CATEGORIES,
    DEFAULT_RULES_FILE,
    HINT_FIELDS,
    RedrawOption,
    RulesetError,
    default_ruleset,
    load_ruleset,
    ruleset_from_dict,
)

PACKAGED = tomllib.loads(DEFAULT_RULES_FILE.read_text("utf-8"))
SECTIONS = [(is_trump, cat) for is_trump in (True, False) for cat in CATEGORIES]


def section_name(is_trump: bool, cat: str) -> str:
    return f"{'trump' if is_trump else 'non_trump'}.{cat}"


def broken(mutate) -> dict:
    data = copy.deepcopy(PACKAGED)
    mutate(data)
    return data


def test_packaged_ruleset_loads_every_card_category():
    ruleset = default_ruleset()
    assert len(ruleset.cells) == 8
    for is_trump, cat in SECTIONS:
        assert ruleset.cell(is_trump, cat).points >= 0


def test_packaged_ruleset_labels_and_upgrade_are_present():
    ruleset = default_ruleset()
    for field in dataclasses.fields(ruleset.labels):
        assert getattr(ruleset.labels, field.name).strip()
    assert ruleset.upgrade_points == 3


def test_packaged_ruleset_is_immutable():
    ruleset = default_ruleset()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ruleset.upgrade_points = 9  # type: ignore[misc]
    with pytest.raises(TypeError):
        ruleset.cells[(True, "ace")] = ruleset.cell(False, "ace")  # type: ignore[index]


def test_load_ruleset_reads_a_file_and_matches_the_packaged_one(tmp_path: Path):
    copy_path = tmp_path / "rules.toml"
    copy_path.write_text(DEFAULT_RULES_FILE.read_text("utf-8"), "utf-8")
    loaded, packaged = load_ruleset(copy_path), default_ruleset()
    assert loaded.labels == packaged.labels
    assert loaded.upgrade_points == packaged.upgrade_points
    assert dict(loaded.cells) == dict(packaged.cells)


def test_missing_rules_file_is_a_ruleset_error(tmp_path: Path):
    with pytest.raises(RulesetError, match="cannot read rules file"):
        load_ruleset(tmp_path / "absent.toml")


def test_malformed_toml_is_a_ruleset_error(tmp_path: Path):
    path = tmp_path / "rules.toml"
    path.write_text("[labels\nsuccess = ", "utf-8")
    with pytest.raises(RulesetError, match="not valid TOML"):
        load_ruleset(path)


@pytest.mark.parametrize("is_trump, cat", SECTIONS, ids=[section_name(*s) for s in SECTIONS])
def test_a_missing_category_is_named_in_the_error(is_trump, cat):
    name = section_name(is_trump, cat)
    data = broken(lambda d: d[name.split(".")[0]].pop(cat))
    with pytest.raises(RulesetError, match=rf"\[{name}\]"):
        ruleset_from_dict(data, source="rules.toml")


@pytest.mark.parametrize("section", ["labels", "redraw", "help", "hints"])
def test_a_missing_section_is_refused(section):
    data = broken(lambda d: d.pop(section))
    with pytest.raises(RulesetError, match=section):
        ruleset_from_dict(data, source="rules.toml")


@pytest.mark.parametrize("key", ["success", "failure", "success_points", "failure_points", "redraw"])
def test_a_missing_label_is_refused(key):
    data = broken(lambda d: d["labels"].pop(key))
    with pytest.raises(RulesetError, match=key):
        ruleset_from_dict(data, source="rules.toml")


@pytest.mark.parametrize("value", ["5", 5.0, True, -1])
def test_points_must_be_a_non_negative_int(value):
    data = broken(lambda d: d["trump"]["ace"].__setitem__("points", value))
    with pytest.raises(RulesetError, match=r"\[trump\.ace\] points"):
        ruleset_from_dict(data, source="rules.toml")


def test_upgrade_points_must_be_an_int():
    data = broken(lambda d: d["redraw"].__setitem__("upgrade_points", "3"))
    with pytest.raises(RulesetError, match="upgrade_points"):
        ruleset_from_dict(data, source="rules.toml")


def test_an_unknown_redraw_option_is_refused():
    data = broken(lambda d: d["non_trump"]["pip"].__setitem__("redraw", "reroll"))
    with pytest.raises(RulesetError, match="redraw"):
        ruleset_from_dict(data, source="rules.toml")


def test_a_success_cell_may_not_offer_a_redraw():
    data = broken(lambda d: d["trump"]["pip"].__setitem__("redraw", "replace"))
    with pytest.raises(RulesetError, match=r"\[trump\.pip\] redraw"):
        ruleset_from_dict(data, source="rules.toml")


def test_a_misspelt_cell_key_is_refused():
    data = broken(lambda d: d["trump"]["two"].__setitem__("pointz", 4))
    with pytest.raises(RulesetError, match="pointz"):
        ruleset_from_dict(data, source="rules.toml")


def test_an_empty_keyword_is_refused():
    data = broken(lambda d: d["trump"]["two"].__setitem__("keyword", ""))
    with pytest.raises(RulesetError, match=r"\[trump\.two\] keyword"):
        ruleset_from_dict(data, source="rules.toml")


def test_redraw_option_values_are_the_three_engine_options():
    assert {g.value for g in RedrawOption} == {"none", "replace", "upgrade"}


def test_the_old_grumble_vocabulary_is_refused():
    data = broken(lambda d: d.__setitem__("grumble", d.pop("redraw")))
    with pytest.raises(RulesetError, match="grumble"):
        ruleset_from_dict(data, source="rules.toml")


# AC12.3 – AC12.5: help and hints come from the rules file and are checked at load

def test_packaged_help_and_every_hint_are_present():
    ruleset = default_ruleset()
    assert ruleset.help.title and ruleset.help.lines and ruleset.help.credit
    assert set(ruleset.hints) == set(HINT_FIELDS)


@pytest.mark.parametrize("key", sorted(HINT_FIELDS))
def test_a_missing_hint_is_refused(key):
    data = broken(lambda d: d["hints"].pop(key))
    with pytest.raises(RulesetError, match=rf"\[hints\] {key}"):
        ruleset_from_dict(data, source="rules.toml")


def test_an_unknown_hint_is_refused():
    data = broken(lambda d: d["hints"].__setitem__("may_reroll", "x"))
    with pytest.raises(RulesetError, match="may_reroll"):
        ruleset_from_dict(data, source="rules.toml")


def test_a_hint_may_not_use_a_field_the_engine_does_not_pass_it():
    # `suits` is passed only to choose_trump.
    data = broken(lambda d: d["hints"].__setitem__("may_replace", "{name} {suits}"))
    with pytest.raises(RulesetError, match=r"\[hints\] may_replace uses unknown field\(s\): suits"):
        ruleset_from_dict(data, source="rules.toml")


@pytest.mark.parametrize("template", ["{nmae}", "{labels.success}", "{name[0]}"])
def test_a_misspelt_or_dotted_field_is_refused(template):
    data = broken(lambda d: d["hints"].__setitem__("replaced", template))
    with pytest.raises(RulesetError, match="unknown field"):
        ruleset_from_dict(data, source="rules.toml")


def test_an_unbalanced_brace_is_refused():
    data = broken(lambda d: d["help"].__setitem__("title", "Commands {"))
    with pytest.raises(RulesetError, match=r"\[help\] title is not a valid template"):
        ruleset_from_dict(data, source="rules.toml")


def test_a_help_line_with_an_unknown_field_is_named_by_index():
    data = broken(lambda d: d["help"]["lines"].__setitem__(1, "{prefix}flip"))
    with pytest.raises(RulesetError, match=r"\[help\.lines\[1\]\].*prefix"):
        ruleset_from_dict(data, source="rules.toml")


@pytest.mark.parametrize("lines", [[], "one line", None])
def test_help_lines_must_be_a_non_empty_list(lines):
    data = broken(lambda d: d["help"].__setitem__("lines", lines))
    with pytest.raises(RulesetError, match=r"\[help\] lines"):
        ruleset_from_dict(data, source="rules.toml")


def test_escaped_braces_are_literal():
    data = broken(lambda d: d["hints"].__setitem__("nothing_to_redraw", "{{none}} for {redraw}"))
    ruleset = ruleset_from_dict(data, source="rules.toml")
    assert ruleset.hint("nothing_to_redraw", "!") == f"{{none}} for {ruleset.labels.redraw}"


def test_text_fills_the_common_fields():
    ruleset = default_ruleset()
    assert ruleset.text("{redraw_cmd} {trump_cmd} {p}", "?") == "`?grumble` `?trump <suit>` ?"
