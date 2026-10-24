# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AC13.1: no Python file under src/, tests/ or tools/ names a rules expression.

The expressions are read from the rules data file (its keywords and its two points terms), so
this file never spells them out. A term matches case-insensitively, as a whole word or as a
token between underscores or spaces, with an optional plural `s`, and at camelCase boundaries
(a term after a lower-case word, or before an upper-case one). Matches are found anywhere in a file:
code, strings, comments and names. The samples below are built from the rules file's terms at run
time, so this file never spells them out either.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RULES_FILE = REPO / "src" / "green_oaks_bot" / "rulesets" / "green_oaks.toml"
SCANNED_DIRS = (REPO / "src", REPO / "tests", REPO / "tools")
EXPECTED_TERM_COUNT = 6  # four keywords and the two points terms

# A term starts and ends at a non-letter, or at a lower-to-upper camelCase boundary.
_WORD_START = r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
_WORD_END = r"(?:(?![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
# Words of a multi-word term are joined by spaces or underscores, or by a camelCase boundary.
_BETWEEN_WORDS = r"(?:[\s_]+|(?<=[a-z])(?=[A-Z]))"


def rules_terms() -> list[str]:
    data = tomllib.loads(RULES_FILE.read_text("utf-8"))
    raw = [cell["keyword"] for section in ("trump", "non_trump")
           for cell in data[section].values() if "keyword" in cell]
    raw += [data["labels"]["success_points"], data["labels"]["failure_points"]]
    # Punctuation is dropped, so a trailing exclamation mark goes; a multi-word term stays whole.
    return [re.sub(r"[^A-Za-z ]", "", term).strip() for term in raw]


def _either_case(char: str) -> str:
    return f"[{char.lower()}{char.upper()}]" if char.isalpha() else re.escape(char)


def pattern_for(term: str) -> re.Pattern[str]:
    """Case-insensitive without re.IGNORECASE, which would hide camelCase boundaries."""
    words = ["".join(_either_case(c) for c in word) for word in term.split()]
    return re.compile(_WORD_START + _BETWEEN_WORDS.join(words) + "[Ss]?" + _WORD_END)


def offences_in(text: str, patterns: list[re.Pattern[str]]) -> list[tuple[int, str]]:
    found = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if pattern.search(line):
                found.append((lineno, line.strip()))
    return found


def all_patterns() -> list[re.Pattern[str]]:
    return [pattern_for(term) for term in rules_terms()]


def test_scan_matcher_catches_identifiers_and_strings_but_not_substrings():
    patterns = all_patterns()
    term = rules_terms()[0]
    assert offences_in(f"x = '{term}'", patterns)
    assert offences_in(f"def test_{term.lower()}_case():", patterns)
    assert offences_in(f"# {term.upper()}", patterns)
    assert not offences_in("the restaurant and the transact helper", patterns)


def samples(term: str) -> list[str]:
    """Spellings of one term that must be caught: camelCase on either side, plural, separators, case."""
    joined = term.replace(" ", "")
    words = term.split()
    camel = words[0].lower() + "".join(w.capitalize() for w in words[1:])
    return [
        f"outcome{joined}",                       # a term after a lower-case word
        f"{joined}Total",                         # a term before an upper-case word
        f"{joined}s",                             # optional plural s
        f"{camel}",                               # camelCase between the words of a term
        term.upper().replace(" ", "_"),           # upper case, underscores between the words
        term.lower().replace(" ", "_") + "_count",
        term.lower(),
    ]


@pytest.mark.parametrize("term", rules_terms())
def test_matcher_catches_plurals_and_camel_case(term):
    patterns = all_patterns()
    for text in samples(term):
        assert offences_in(f"x = '{text}'", patterns), text


@pytest.mark.parametrize("text", [
    "restaurant", "transact", "grant", "bothered", "BOTHERED", "rumored", "Rumoring", "Bothersome",
])
def test_matcher_ignores_words_that_only_contain_a_term(text):
    # Only words that merely begin with a term are listed; none of them is a term or its plural.
    assert not offences_in(f"x = '{text}'", all_patterns())


def test_scan_covers_src_tests_and_tools():
    assert set(SCANNED_DIRS) == {REPO / "src", REPO / "tests", REPO / "tools"}
    for root in SCANNED_DIRS:
        assert any(root.rglob("*.py")), f"{root} has no Python files to scan"


def test_no_rules_expression_in_python_source_tests_or_tools():
    terms = rules_terms()
    assert len(terms) == EXPECTED_TERM_COUNT
    patterns = [pattern_for(term) for term in terms]
    offences = []
    for root in SCANNED_DIRS:
        for path in sorted(root.rglob("*.py")):
            for lineno, line in offences_in(path.read_text("utf-8"), patterns):
                offences.append(f"{path.relative_to(REPO)}:{lineno}: {line}")
    assert not offences, "rules expressions belong only in the rules data file:\n" + "\n".join(offences)
