<!-- SPDX-FileCopyrightText: 2026 K. Chen -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Green Oaks Bot

Last verified: 2026-10-25

Fluxer chat bot that resolves card checks with one shared 40-card deck per channel.
User-facing docs (commands, config, deploy) are in `README.md`; Fluxer API notes in `docs/fluxer-notes.md`.

## Commands (run from this directory)

- Tests: `.venv/bin/python -m pytest -q -W error` (warnings are errors)
- Lint: `.venv/bin/ruff check src tests tools`
- Licensing: `.venv/bin/reuse --root . lint`
- CI (`.github/workflows/image.yml`) runs these three on every push/PR; the image is built every run
  but pushed to GHCR only on `v*` tags. CI installs with `-c requirements.txt` (the image's pinned
  runtime deps, compiled by uv from `pyproject.toml`); regenerate it when runtime deps change.

## Licensing boundary (read before editing any text)

- Engine (Python, build files, docs): AGPL-3.0-or-later. Rules data
  `src/green_oaks_bot/rulesets/green_oaks.toml`: CC BY-NC-SA 4.0. Card art `assets/cards/`: public domain.
- All rules expressions (card results, points terms, keywords, game half of `!help`, redraw/prompt
  lines) live ONLY in the TOML. Never restate them in Python, tests, tools, README or this file;
  refer to the rules file instead. `tests/test_licensing_boundary.py` scans every published text file in
  the project (README, this file, docs, build files, `src/`, `tests/`, `tools/`; excludes the TOML and `LICENSES/`)
  for the TOML's terms and fails on any match (it builds samples from the TOML at run time).
  It never opens secret files (`.env`, `.env.*` except `.env.example`, keys). With a git index, a
  guard test fails on any tracked file type the scan neither covers nor explicitly excludes: a new
  file type means extending its allowlist or exclusions.
- Every new file needs an SPDX header or a `REUSE.toml` entry, or `reuse lint` fails.

## Architecture

Functional core (no I/O, deterministic given an injected `random.Random`):
- `deck.py` - cards, suits, ranks, `Deck`
- `ruleset.py` - `load_ruleset(path)` / `ruleset_from_dict` parse and strictly validate the TOML
  (unknown keys, bad templates raise `RulesetError`); `Ruleset` is immutable
- `rules.py` - resolves a card against a `Ruleset` into an `Outcome`
- `table.py` - `Table` (per-channel game state), `Actor`, `Reply`, `Pending`
- `commands.py` - `parse`, `execute`, `standalone_reply`, `creates_deck`, `no_deck`, `help_text`
- `ids.py` - `is_snowflake` / `require_snowflake` (digits only, 1-25 chars)

Imperative shell:
- `store.py` - JSON persistence, per-channel locking
- `render.py` - card images (Pillow)
- `fluxer/` - `rest.py` (HTTP, endpoint discovery), `gateway.py` (websocket), `roles.py` (GM lookup)
- `bot.py` - wires a message to parse -> store.transact -> execute -> reply
- `config.py` - env vars to `Config` (the only place defaults like `SOURCE_URL` live); `token` is
  `repr=False` so a logged `Config` never shows it; `COMMAND_PREFIX` is stripped, blank means `!`
- `__main__.py` - loads config and ruleset (fails fast with a clear message), runs the bot

## Contracts

- `Ruleset` and `source_url` are required keyword arguments everywhere they are used (`Table`,
  `Table.new`, `Store`, `Bot`, `execute`, `help_text`, `standalone_reply`). The engine has no default
  ruleset or URL; `__main__` loads one `Ruleset` and threads it through. `Bot` raises `ValueError` if
  `store.ruleset is not ruleset`.
- Only `!flip`, `!adv`, `!dis` and a GM `!shuffle` create a deck (`creates_deck`). Any other command
  in a deckless channel gets `no_deck` and writes nothing (`Store.transact(..., create=False)`).
- `!help` and unknown commands need no table (`standalone_reply`).
- Guild/channel ids are validated as snowflakes before they become paths (`Store.path`) and at the
  bot boundary.

## Store invariants (`store.py`)

- State file: `<DATA_DIR>/guilds/<guild>/<channel>.json`, `FORMAT_VERSION = 3`; any other version or
  malformed data is treated as corrupt.
- `transact(guild, channel, fn, *, create=True)` holds the channel's `asyncio.Lock` across load, `fn`,
  and save, and keeps holding it until worker threads finish even if the task is cancelled.
- If `fn` or the write fails (or is cancelled before the write lands), in-memory state is rolled back
  to the pre-command snapshot; a write that completed stays.
- Writes are atomic: temp file + fsync + `os.replace` + directory fsync.
- A corrupt file is moved aside to `<name>.corrupt` (then `.corrupt.1`, ...), never overwritten.
- `create=False`: a missing deck yields `fn(None, notice)`; nothing written or cached.

## Gotchas

- Do not read or print `.env` (holds `FLUXER_TOKEN`); `.env.example` is the template.
- `RULES_FILE` may point at another TOML of the same structure; startup rejects malformed files.
- The egg (`egg-green-oaks-bot.json`) validation rules must match `config.py` (e.g. `SOURCE_URL`), and
  the egg must pass the panel's model validation (`tests/test_egg.py`): e.g. `author` must be an email
  address, or import fails with a bare HTTP 500.
- This directory is published as https://github.com/tznkai/green-oaks-bot (git subtree split);
  everything here is public.
