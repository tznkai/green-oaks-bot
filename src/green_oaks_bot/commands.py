# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prefix command parsing and dispatch to Table methods."""

from __future__ import annotations

from dataclasses import dataclass, replace

from green_oaks_bot.deck import Suit
from green_oaks_bot.ruleset import Ruleset, default_ruleset
from green_oaks_bot.table import IMAGE_MODES, STYLES, Actor, Reply, Table

ALIASES = {
    "flip": "flip", "f": "flip",
    "adv": "adv", "advantage": "adv",
    "dis": "dis", "disadvantage": "dis",
    "grumble": "grumble",
    "trump": "trump",
    "shuffle": "shuffle",
    "status": "status",
    "style": "style",
    "images": "images",
    "help": "help",
}

_SUIT_WORDS = {
    "clubs": Suit.CLUBS, "club": Suit.CLUBS, "c": Suit.CLUBS, "♣": Suit.CLUBS, "♧": Suit.CLUBS,
    "diamonds": Suit.DIAMONDS, "diamond": Suit.DIAMONDS, "d": Suit.DIAMONDS,
    "♦": Suit.DIAMONDS, "♢": Suit.DIAMONDS,
    "hearts": Suit.HEARTS, "heart": Suit.HEARTS, "h": Suit.HEARTS, "♥": Suit.HEARTS, "♡": Suit.HEARTS,
    "spades": Suit.SPADES, "spade": Suit.SPADES, "s": Suit.SPADES, "♠": Suit.SPADES, "♤": Suit.SPADES,
}
SUIT_OPTIONS = "clubs, diamonds, hearts, spades (or c, d, h, s, or ♣ ♦ ♥ ♠)"


@dataclass(frozen=True)
class Command:
    name: str           # canonical name, or the raw lowercased word if unknown
    args: tuple[str, ...]


def parse(text: str, prefix: str) -> Command | None:
    text = text.strip()
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix):].strip()
    if not rest:
        return None
    word, *args = rest.split()
    word = word.lower()
    return Command(ALIASES.get(word, word), tuple(args))


def parse_suit(token: str) -> Suit | None:
    return _SUIT_WORDS.get(token.strip().replace("\ufe0f", "").lower())


def help_text(prefix: str, ruleset: Ruleset | None = None) -> str:
    p = prefix
    rules = ruleset if ruleset is not None else default_ruleset()
    labels, upgrade_points = rules.labels, rules.upgrade_points
    return "\n".join([
        "**Green Oaks Bot commands**",
        f"`{p}flip` (`{p}f`): flip a card and resolve it against trump",
        f"`{p}adv` / `{p}dis`: flip two, keep the better / worse result",
        (f"`{p}grumble`: after a non-trump 3–7 flip a replacement; after a non-trump face card make it "
         f"{labels.success}, {labels.success_points} {upgrade_points}"),
        f"`{p}trump`: show trump. `{p}trump <suit>`: set trump (GM, or the player who flipped the trump Ace)",
        f"`{p}shuffle`: GM only. Shuffle all 40 cards and turn up a new trump",
        f"`{p}status`: trump, pile counts, Aces drawn",
        f"`{p}style emoji|short|long`: how card names are written",
        f"`{p}images large|small|off`: card image size",
        f"`{p}help`: this list",
        # Rules-neutral credit line; the full attribution is in the README's Licensing section.
        "Rules: Green Oaks © MS Edizioni / Magic Store srl, CC BY-NC-SA 4.0. See the README, Licensing.",
    ])


_DECK_STARTERS = frozenset({"flip", "adv", "dis"})
_STANDALONE = frozenset({"help"})


def creates_deck(cmd: Command, is_gm: bool) -> bool:
    """Whether this command may start a channel's deck when none exists yet.

    Only a flip, an advantage/disadvantage flip, or a GM shuffle does. Everything else is
    answered with `no_deck` and writes nothing.
    """
    return cmd.name in _DECK_STARTERS or (cmd.name == "shuffle" and is_gm)


def standalone_reply(cmd: Command, prefix: str, ruleset: Ruleset | None = None) -> Reply | None:
    """The reply for `help` and unknown commands, which need no table. None for table commands."""
    if cmd.name == "help":
        return Reply(help_text(prefix, ruleset))
    if cmd.name in ALIASES.values():
        return None
    return Reply(f"Unknown command `{prefix}{cmd.name}`. Try `{prefix}help`.", tone="error")


def no_deck(cmd: Command, actor: Actor, prefix: str, notice: str | None = None) -> Reply:
    """The reply for a command in a channel with no deck, when the command may not start one."""
    hint = (f"This channel has no deck yet. Start one with `{prefix}flip`, `{prefix}adv`, "
            f"`{prefix}dis`, or `{prefix}shuffle` (GM).")
    if cmd.name == "shuffle" and not actor.is_gm:
        reply = Reply(f"Only the GM can shuffle. {hint}", tone="error")
    else:
        reply = Reply(hint)
    if notice:
        reply = replace(reply, text=f"{notice}\n{reply.text}")
    return reply


def execute(cmd: Command, table: Table, actor: Actor, notice: str | None = None) -> Reply:
    if cmd.name == "shuffle" and actor.is_gm and notice is not None:
        # The store has just made and shuffled this deck for this very command. The notice already
        # announces the turned-up trump (and any reset warning), so shuffling again would be a second shuffle.
        return table.finish(Reply(notice, (table.deck.discards[0],)))
    reply = _dispatch(cmd, table, actor)
    reply = table.finish(reply)
    if notice:
        reply = replace(reply, text=f"{notice}\n{reply.text}")
    return reply


def _dispatch(cmd: Command, table: Table, actor: Actor) -> Reply:
    p = table.prefix
    match cmd.name:
        case "flip":
            return table.flip(actor)
        case "adv":
            return table.advantage(actor)
        case "dis":
            return table.disadvantage(actor)
        case "grumble":
            return table.grumble(actor)
        case "trump":
            if not cmd.args:
                return table.show_trump(actor)
            suit = parse_suit(cmd.args[0])
            if suit is None:
                return Reply(f"Unknown suit `{cmd.args[0]}`. Use {SUIT_OPTIONS}.", tone="error")
            return table.set_trump(actor, suit)
        case "shuffle":
            return table.shuffle(actor)
        case "status":
            return table.status(actor)
        case "style":
            value = cmd.args[0].lower() if cmd.args else ""
            if value not in STYLES:
                return Reply(f"Usage: `{p}style {'|'.join(STYLES)}`", tone="error")
            return table.set_style(actor, value)
        case "images":
            value = cmd.args[0].lower() if cmd.args else ""
            if value not in IMAGE_MODES:
                return Reply(f"Usage: `{p}images {'|'.join(IMAGE_MODES)}`", tone="error")
            return table.set_images(actor, value)
        case "help":
            return Reply(help_text(p, table.ruleset))
        case _:
            return Reply(f"Unknown command `{p}{cmd.name}`. Try `{p}help`.", tone="error")
