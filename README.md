# Green Oaks Bot

A Fluxer chat bot that resolves Green Oaks "ArterioscleroSys" card checks with one shared 40-card deck per channel.

Status: the bot is deployable with the Pterodactyl egg or Docker Compose.

## Commands

| Command | Who | What it does |
| --- | --- | --- |
| `!flip` (`!f`) | Anyone | Flips the top card of the deck. |
| `!adv` (`!advantage`) / `!dis` (`!disadvantage`) | Anyone | Flips two cards and keeps one. |
| `!grumble` | The player with a pending redraw | Redraws the card. |
| `!trump [suit]` | Anyone shows; the GM, or the player who flipped the trump Ace, sets | Shows the trump, or sets it to a suit (`clubs`, `diamonds`, `hearts`, `spades`, or `c`, `d`, `h`, `s`). |
| `!shuffle` | GM only | Shuffles all 40 cards and turns up a new trump. |
| `!status` | Anyone | Shows the trump, the pile counts and the Aces drawn. |
| `!style emoji\|short\|long` | Anyone | Sets how card names are written. |
| `!images large\|small\|off` | Anyone | Sets the card image size. |
| `!help` | Anyone | Lists the commands. |

A channel starts with no deck. `!flip`, `!adv`, `!dis` and the GM's `!shuffle` start one. Other commands in a fresh channel reply with a hint and create nothing.

The results of each card are not written in this README. They are in the rules file, `src/green_oaks_bot/rulesets/green_oaks.toml`, and in the publisher's text named under Licensing. Read those for what a card does.

## Fluxer bot setup

- Create an application on your instance (Settings → Applications, or `POST /v1/oauth2/applications`) and copy the bot token (shown once).
- Invite the bot with View Channel, Send Messages, Embed Links, Attach Files and Read Message History.
- Create a role whose name matches `GM_ROLE_NAME`.

## Configuration

Set these as environment variables (in the `.env` file for Docker Compose, or as egg variables on Pterodactyl).

| Variable | Default | Meaning |
| --- | --- | --- |
| `FLUXER_TOKEN` | required | The bot token from your Fluxer instance. |
| `FLUXER_INSTANCE_URL` | required unless `FLUXER_API_URL` is set | Base URL of your Fluxer instance, e.g. `https://chat.example.org`. |
| `FLUXER_API_URL` | discovered | Fluxer public API base (without `/v1`). Overrides discovery from the instance. |
| `FLUXER_GATEWAY_URL` | discovered | Fluxer gateway websocket URL. Overrides the gateway lookup. |
| `GM_ROLE_NAME` | `GM` | Members with a role of this name (case-insensitive) can shuffle and set trump. |
| `COMMAND_PREFIX` | `!` | Prefix for bot commands. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |
| `DATA_DIR` | `data` | Where channel state is stored. |
| `CARD_ASSETS_DIR` | the packaged `assets/cards` | Directory of card images. |
| `RULES_FILE` | the packaged `src/green_oaks_bot/rulesets/green_oaks.toml` | The rules file to load. |
| `SOURCE_URL` | `https://github.com/tznkai/green-oaks-bot` | Shown in `!help` as the `Source:` line. Set it to your fork's URL if you run a modified bot, per AGPL-3.0 §13. Must be an `http://` or `https://` URL. |

Set `RULES_FILE` only to load a different rules file. It must have the same structure. A missing or malformed file stops startup with a clear message.

## Pterodactyl

- Admin → Nests → Import Egg → `egg-green-oaks-bot.json`.
- Create a server with the egg; no ports are needed. Wings may still require an allocation, so assign any free one.
- Set the token in the admin server view (it is hidden from users). The egg has nine variables: the token, the instance URL, the API and gateway overrides, the GM role, the prefix, the log level, the source URL, and the optional rules file (blank = packaged).
- Start the server. It shows "running" once `Green Oaks bot ready` is logged.
- The image is `ghcr.io/tznkai/green-oaks-bot:latest`. Make the GHCR package public, or configure registry credentials on the Wings node.
- State lives in the server's `data/` folder.

## Docker Compose

    cp .env.example .env
    # fill in .env, then:
    docker compose up -d --build

State lives in `./data`. The container runs as your UID and GID (default 1000), so `./data` must be writable by that user.

## Development

    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -e '.[dev]'
    .venv/bin/python -m pytest

Run these from `green-oaks-bot/`. To check the licence headers, run `uvx reuse --root . lint` from the same folder.

## Smoke-test checklist

Run this manually after any deploy.

- Server reaches "running".
- `!help` lists the commands and ends with the rules credit and the `Source:` line.
- The first `!flip` (or GM `!shuffle`) in a fresh channel announces a new deck and trump. `!status` in a fresh channel only gives a hint and creates nothing.
- `!flip` shows a card image and result.
- `!adv` shows two cards with the kept one marked.
- `!images small` shrinks the image, and `!images off` removes it.
- `!shuffle` as a non-GM is refused; as GM it turns up a new trump.
- Restart the server; `!status` shows the same counts as before the restart.
- A DM to the bot gets "server channels only" once.

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
  and `assets/cards/ATTRIBUTION.md`). They are not part of the Python package. One centre pip on `ace_of_spades.png` was
  replaced by a copy of a pip from another of his images, and needs no separate licence.

**The non-commercial restriction applies to any distribution that includes the rules file.** The engine's AGPL terms
do not remove the CC BY-NC-SA 4.0 terms on the rules file. A copy of this project that contains the rules file may be
shared and changed only non-commercially, under share-alike terms; a copy built without it (the engine alone, with its
own rules file written from scratch) is under the AGPL alone. The Python package's `license` field records the combined
expression, `AGPL-3.0-or-later AND CC-BY-NC-SA-4.0`, and describes the installed package (engine and rules file). The wheel
and the source distribution share that metadata and carry the two licence texts it names. The source distribution and
the repository also carry the public-domain card images under `LicenseRef-PublicDomain-vector-playing-cards`; that
licence is not in the package metadata, because the wheel does not ship the images. Its text is in `LICENSES/`, and
`REUSE.toml` and `assets/cards/ATTRIBUTION.md` say which files it covers.

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
