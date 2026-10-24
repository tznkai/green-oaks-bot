# Green Oaks Bot

A Fluxer chat bot that resolves Green Oaks "ArterioscleroSys" card checks with one shared 40-card deck per channel.

Status: under construction. Setup, deployment and the command reference arrive in later phases.

## Development

    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -e '.[dev]'
    .venv/bin/python -m pytest

## Licensing

This project is split into two licensed parts, so that the engine can be reused without the game's rules text.

- **The engine** (all Python under `src/`, `tests/` and `tools/`, the Docker and build files) is licensed under the
  **GNU Affero General Public License v3.0 or later** (`AGPL-3.0-or-later`). Full text: `LICENSES/AGPL-3.0-or-later.txt`.
- **The rules data** (`src/green_oaks_bot/rulesets/green_oaks.toml`) is licensed under the
  **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International** licence (`CC-BY-NC-SA-4.0`), because it
  restates the results of *Green Oaks*. It also holds the game half of the `!help` text and the lines that follow a
  result (prompts, and what a Grumble does), because those restate the results too. Full text: `LICENSES/CC-BY-NC-SA-4.0.txt`. Note that the publisher's notice
  says "4.0 IT": there is no ported 4.0 version of this licence, so the IT refers to the Italian-language legal code
  and this is the international 4.0 licence.
- **The card images** (`assets/cards/`) are public domain, by Byron Knoll (see `LICENSES/LicenseRef-PublicDomain-vector-playing-cards.txt`
  and `assets/cards/ATTRIBUTION.md`). One centre pip on `ace_of_spades.png` was replaced by a copy from another of his images.

**The non-commercial restriction applies to any distribution that includes the rules file.** The engine's AGPL terms
do not remove the CC BY-NC-SA 4.0 terms on the rules file. A copy of this project that contains the rules file may be
shared and changed only non-commercially, under share-alike terms; a copy built without it (the engine alone, with its
own rules file written from scratch) is under the AGPL alone. The Python package's `license` field records the combined
expression, `AGPL-3.0-or-later AND CC-BY-NC-SA-4.0 AND LicenseRef-PublicDomain-vector-playing-cards`.

### Attribution: *Green Oaks* (MS Edizioni)

> *Green Oaks* by Roberto de Luca, Claudio Pustorino and Claudio Serena. Published by MS Edizioni / Magic Store srl —
> https://www.msedizioni.it, https://fumblegdr.it. English translation by Leonardo Abate; English editing by Jessica
> Collins; final editing by Giacomo Gentile. Licensed under CC BY-NC-SA 4.0
> (https://creativecommons.org/licenses/by-nc-sa/4.0/). Adapted: the card-resolution results are restated as structured
> data, with interpretations of unclear wording by K. Chen.

The bot's `!help` output carries a one-line credit that points here.

### Checking the licences

The project follows the [REUSE specification](https://reuse.software). Each file carries its licence in an SPDX header,
or in `REUSE.toml` where a header is not possible. To check:

    uvx reuse --root . lint
