"""AC11.1: no Python file under src/ or tests/ names a rules expression.

The expressions are read from the rules data file (its keywords and its two points terms), so
this file never spells them out. A term matches as a whole word or as a token between
underscores or spaces, case-insensitively, anywhere in the file: code, strings, comments and names.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RULES_FILE = REPO / "src" / "green_oaks_bot" / "rulesets" / "green_oaks.toml"
SCANNED_DIRS = (REPO / "src", REPO / "tests")
EXPECTED_TERM_COUNT = 6  # four keywords and the two points terms


def rules_terms() -> list[str]:
    data = tomllib.loads(RULES_FILE.read_text("utf-8"))
    raw = [cell["keyword"] for section in ("trump", "non_trump")
           for cell in data[section].values() if "keyword" in cell]
    raw += [data["labels"]["success_points"], data["labels"]["failure_points"]]
    # Punctuation is dropped, so a trailing exclamation mark goes; a multi-word term stays whole.
    return [re.sub(r"[^A-Za-z ]", "", term).strip() for term in raw]


def pattern_for(term: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in term.split()]
    return re.compile(r"(?<![a-z])" + r"[\s_]+".join(words) + r"(?![a-z])", re.IGNORECASE)


def offences_in(text: str, patterns: list[re.Pattern[str]]) -> list[tuple[int, str]]:
    found = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if pattern.search(line):
                found.append((lineno, line.strip()))
    return found


def test_scan_matcher_catches_identifiers_and_strings_but_not_substrings():
    patterns = [pattern_for(term) for term in rules_terms()]
    term = rules_terms()[0]
    assert offences_in(f"x = '{term}'", patterns)
    assert offences_in(f"def test_{term.lower()}_case():", patterns)
    assert offences_in(f"# {term.upper()}", patterns)
    assert not offences_in("the restaurant and the transact helper", patterns)


def test_no_rules_expression_in_python_source_or_tests():
    terms = rules_terms()
    assert len(terms) == EXPECTED_TERM_COUNT
    patterns = [pattern_for(term) for term in terms]
    offences = []
    for root in SCANNED_DIRS:
        for path in sorted(root.rglob("*.py")):
            for lineno, line in offences_in(path.read_text("utf-8"), patterns):
                offences.append(f"{path.relative_to(REPO)}:{lineno}: {line}")
    assert not offences, "rules expressions belong only in the rules data file:\n" + "\n".join(offences)
