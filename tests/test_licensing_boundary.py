# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AC13.1: no published text file in the project names a rules expression.

The scanned set is every published text file under the project root: an allowlist of suffixes and
names, found with rglob so it also works from an sdist. It excludes the rules data file itself and
the LICENSES/ directory, and skips files that do not decode as UTF-8. A guard test runs `git ls-files`
when a git index is present and fails on any tracked file that the allowlist neither covers nor
explicitly excludes, so a new file type cannot slip past the allowlist unnoticed. Secret files
(`.env` and similar) are never opened. The expressions are read from the rules data file (its
keywords and its two points terms), so this file never spells them out. A term matches
case-insensitively, as a whole
word or as a token between underscores or spaces, with an optional plural `s`, and at camelCase
boundaries (a term after a lower-case word, or before an upper-case one). Matches are found anywhere
in a file: code, strings, comments and names. The samples below are built from the rules file's
terms at run time, so this file never spells them out either.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RULES_FILE = REPO / "src" / "green_oaks_bot" / "rulesets" / "green_oaks.toml"
EXPECTED_TERM_COUNT = 6  # four keywords and the two points terms
PRUNED_DIR_NAMES = {".venv", ".git", "data", "build", "dist", "__pycache__"}  # plus any *_cache
SCANNED_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".sh", ".txt", ".example"}
SCANNED_NAMES = {"Dockerfile", ".dockerignore", ".gitignore"}
EXCLUDED_ROOT_DIRS = {"LICENSES"}
EXCLUDED_SUFFIXES = {".png"}  # binary card art, licensed in REUSE.toml; never decoded as text
# Secret files are never opened, whatever the allowlist says: a .env file usually holds a real token,
# and a later allowlist edit must not make the scan read it. The denylist is checked before the
# allowlist and before any read. ".env.example" is the committed template and is scanned like any
# text file. The globs also cover key material, which must never be published either.
SECRET_NAMES = {".env"}
SECRET_GLOBS = (".env.*", "*.pem", "*.key", "id_rsa*")
SECRET_EXEMPT_NAMES = {".env.example"}

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


def _pruned(rel: Path) -> bool:
    return any(part in PRUNED_DIR_NAMES or part.endswith("_cache") for part in rel.parts[:-1])


def is_secret(path: Path) -> bool:
    name = path.name
    if name in SECRET_EXEMPT_NAMES:
        return False
    return name in SECRET_NAMES or any(fnmatch.fnmatchcase(name, glob) for glob in SECRET_GLOBS)


def scanned_files(root: Path = REPO) -> list[Path]:
    """Every published text file under `root`, excluding the rules file and LICENSES/."""
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or _pruned(rel):
            continue
        if is_secret(path):
            continue  # before the allowlist and before any read
        if rel.parts[0] in EXCLUDED_ROOT_DIRS or path.resolve() == RULES_FILE.resolve():
            continue
        if path.name not in SCANNED_NAMES and path.suffix not in SCANNED_SUFFIXES:
            continue
        try:
            path.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        files.append(path)
    return files


def git_tracked_files(root: Path = REPO) -> list[Path] | None:
    """Files git tracks under `root` (paths relative to `root`), or None without a usable index."""
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [root / name for name in listing.decode("utf-8", "surrogateescape").split("\0") if name]


def unrecognised_files(tracked: list[Path], root: Path = REPO) -> list[Path]:
    """Tracked files that the scan neither covers nor explicitly excludes."""
    scanned = set(scanned_files(root))
    rules = RULES_FILE.resolve()
    unrecognised = []
    for path in tracked:
        if path in scanned or not path.is_file() or is_secret(path):
            continue
        if path.resolve() == rules or path.relative_to(root).parts[0] in EXCLUDED_ROOT_DIRS:
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        unrecognised.append(path)
    return unrecognised


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


def test_scan_covers_all_published_text_and_excludes_the_rules_file_and_licences():
    scanned = scanned_files()
    assert scanned, "no published text files to scan"
    assert REPO / "README.md" in scanned
    assert REPO / "CLAUDE.md" in scanned
    assert REPO / "src" / "green_oaks_bot" / "fluxer" / "rest.py" in scanned
    assert REPO / "tests" / "test_licensing_boundary.py" in scanned
    assert RULES_FILE not in scanned
    assert not [p for p in scanned if "LICENSES" in p.relative_to(REPO).parts]
    assert not [p for p in scanned if ".venv" in p.relative_to(REPO).parts]
    assert not [p for p in scanned if p.name.endswith(".png") or p.suffix == ".png"]


def test_scan_skips_files_that_do_not_decode_as_utf8_and_pruned_dirs(tmp_path):
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00 not utf-8 \x89PNG")
    (tmp_path / "good.md").write_text("plain text", "utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "inside.py").write_text("x = 1", "utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "inside.md").write_text("x", "utf-8")
    assert {p.name for p in scanned_files(tmp_path)} == {"good.md"}


# The last two have allowlisted suffixes, so only the denylist keeps them out of the scan.
SECRET_FILES = [".env", ".env.local", ".env.production", ".env.production.json", ".env.local.toml"]


def test_secret_files_are_never_opened_or_scanned(tmp_path, monkeypatch):
    # Each secret holds a rules term, so a read that reached the scan would also be an offence.
    leaked = f"TOKEN = '{rules_terms()[0]}'\n"
    for name in SECRET_FILES:
        (tmp_path / name).write_text(leaked, "utf-8")
    (tmp_path / ".env.example").write_text("FLUXER_TOKEN=\n", "utf-8")

    opened: list[str] = []

    def recording(real):
        def wrapper(self, *args, **kwargs):
            opened.append(self.name)
            return real(self, *args, **kwargs)
        return wrapper

    for method in ("open", "read_text", "read_bytes"):
        monkeypatch.setattr(Path, method, recording(getattr(Path, method)))

    scanned = scanned_files(tmp_path)
    assert tmp_path / ".env.example" in scanned
    for name in SECRET_FILES:
        assert tmp_path / name not in scanned, name
    secret_opens = sorted(set(opened) & set(SECRET_FILES))
    assert not secret_opens, f"secret files were opened: {secret_opens}"


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.production", "server.pem", "deploy.key",
                                  "id_rsa", "id_rsa.pub"])
def test_secret_names_are_denied(name):
    assert is_secret(Path(name))


@pytest.mark.parametrize("name", [".env.example", "README.md", "config.toml"])
def test_templates_and_ordinary_files_are_not_secret(name):
    assert not is_secret(Path(name))


def test_guard_flags_tracked_files_of_unrecognised_types(tmp_path):
    (tmp_path / "notes.md").write_text("plain", "utf-8")
    (tmp_path / "card.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "logo.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.md").write_text("pruned, so never scanned", "utf-8")
    tracked = [tmp_path / name for name in ["notes.md", "card.png", "logo.bin", "data/x.md"]]
    assert {p.name for p in unrecognised_files(tracked, tmp_path)} == {"logo.bin", "x.md"}


def test_every_tracked_file_is_scanned_or_explicitly_excluded():
    tracked = git_tracked_files()
    if not tracked:
        pytest.skip("no git index under the project root (an sdist or export); the guard runs in a checkout")
    unrecognised = unrecognised_files(tracked)
    assert not unrecognised, (
        "tracked files the licensing scan neither covers nor excludes. Add the suffix or name to "
        "SCANNED_SUFFIXES / SCANNED_NAMES in tests/test_licensing_boundary.py, or to EXCLUDED_SUFFIXES / "
        "EXCLUDED_ROOT_DIRS there if it is binary or licensed elsewhere:\n"
        + "\n".join(str(p.relative_to(REPO)) for p in unrecognised)
    )
    secrets = [str(p.relative_to(REPO)) for p in tracked if is_secret(p)]
    assert not secrets, f"secret files must not be tracked by git: {secrets}"


def test_no_rules_expression_in_any_published_text():
    terms = rules_terms()
    assert len(terms) == EXPECTED_TERM_COUNT
    patterns = [pattern_for(term) for term in terms]
    offences = []
    for path in scanned_files():
        for lineno, line in offences_in(path.read_text("utf-8"), patterns):
            offences.append(f"{path.relative_to(REPO)}:{lineno}: {line}")
    assert not offences, "rules expressions belong only in the rules data file:\n" + "\n".join(offences)
