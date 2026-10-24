# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-channel game table: every game action returns a Reply."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from green_oaks_bot.deck import Card, Deck, Rank, Suit, TextStyle
from green_oaks_bot.rules import (
    Outcome,
    describe,
    resolve,
    upgrade,
)
from green_oaks_bot.ruleset import RedrawOption, Ruleset

Tone = Literal["success", "failure", "special", "info", "error"]
ImageMode = Literal["large", "small", "off"]
PendingKind = Literal["redraw_replace", "redraw_upgrade", "choose_trump"]

STYLES: tuple[TextStyle, ...] = ("emoji", "short", "long")
IMAGE_MODES: tuple[ImageMode, ...] = ("large", "small", "off")


@dataclass(frozen=True)
class Actor:
    user_id: str
    display_name: str
    is_gm: bool


@dataclass(frozen=True)
class Pending:
    user_id: str
    kind: PendingKind


@dataclass(frozen=True)
class Reply:
    text: str
    cards: tuple[Card, ...] = ()
    kept_index: int | None = None
    tone: Tone = "info"
    hints: tuple[str, ...] = ()


def _suit_label(suit: Suit) -> str:
    return f"{suit.long_name} {suit.symbol}"


class Table:
    """One per (guild_id, channel_id)."""

    def __init__(self, deck: Deck, trump: Suit, rng: random.Random, *, prefix: str = "!",
                 aces_drawn: int = 0, pending: Pending | None = None,
                 last_outcome: Outcome | None = None, style: TextStyle = "long",
                 images: ImageMode = "large", ruleset: Ruleset) -> None:
        self.deck = deck
        self.trump = trump
        self.rng = rng
        self.ruleset = ruleset
        self.prefix = prefix
        self.aces_drawn = aces_drawn
        self.pending = pending
        self.last_outcome = last_outcome
        self.style: TextStyle = style
        self.images: ImageMode = images

    @classmethod
    def new(cls, rng: random.Random, *, prefix: str = "!", ruleset: Ruleset) -> Table:
        table = cls(Deck.fresh(), Suit.CLUBS, rng, prefix=prefix, ruleset=ruleset)
        table._shuffle_and_turn_trump()
        return table

    # ---- helpers -------------------------------------------------------

    @property
    def shuffle_hint(self) -> str:
        return f"GM: time to `{self.prefix}shuffle`"

    def needs_shuffle(self) -> bool:
        return not self.deck.draw or self.aces_drawn >= 4

    def finish(self, reply: Reply) -> Reply:
        if self.needs_shuffle() and self.shuffle_hint not in reply.hints:
            return Reply(reply.text, reply.cards, reply.kept_index, reply.tone,
                         reply.hints + (self.shuffle_hint,))
        return reply

    def _error(self, text: str) -> Reply:
        return self.finish(Reply(text, tone="error"))

    def _name(self, card: Card) -> str:
        return card.text(self.style)

    def _take(self) -> Card:
        card = self.deck.flip()
        assert card is not None  # callers check the draw count first
        if card.rank is Rank.ACE:
            self.aces_drawn += 1
        return card

    def _shuffle_and_turn_trump(self) -> Card:
        self.deck.shuffle(self.rng)
        self.aces_drawn = 0
        card = self._take()
        self.trump = card.suit
        self.pending = None
        self.last_outcome = None
        return card

    def valid_trump_choices(self) -> list[Suit]:
        """Suits in the discards other than the current trump. A hint only: set_trump accepts any suit."""
        present = {c.suit for c in self.deck.discards}
        return [s for s in Suit if s in present and s is not self.trump]

    @staticmethod
    def _tone(outcome: Outcome) -> Tone:
        if outcome.special:
            return "special"
        return "success" if outcome.success else "failure"

    def _hint(self, key: str, **fields: object) -> str:
        return self.ruleset.hint(key, self.prefix, **fields)

    def _apply(self, actor: Actor, outcome: Outcome) -> list[str]:
        """Record a kept outcome; set pending; return prompt lines."""
        self.last_outcome = outcome
        self.pending = None
        name = actor.display_name
        if outcome.changes_trump:
            self.pending = Pending(actor.user_id, "choose_trump")
            suits = ", ".join(_suit_label(s) for s in self.valid_trump_choices())
            if not suits:
                return [self._hint("choose_trump_unavailable", name=name)]
            return [self._hint("choose_trump", name=name, suits=suits)]
        if outcome.redraw is RedrawOption.REPLACE:
            self.pending = Pending(actor.user_id, "redraw_replace")
            return [self._hint("may_replace", name=name)]
        if outcome.redraw is RedrawOption.UPGRADE:
            self.pending = Pending(actor.user_id, "redraw_upgrade")
            return [self._hint("may_upgrade", name=name)]
        return []

    # ---- actions -------------------------------------------------------

    def flip(self, actor: Actor) -> Reply:
        if not self.deck.draw:
            return self._error("The draw pile is empty.")
        card = self._take()
        outcome = resolve(card, self.trump, self.ruleset)
        prompts = self._apply(actor, outcome)
        text = "\n".join([(f"{actor.display_name} flips **{self._name(card)}**: "
                           f"{describe(outcome, self.ruleset)}."),
                          *prompts])
        return self.finish(Reply(text, (card,), None, self._tone(outcome)))

    def advantage(self, actor: Actor) -> Reply:
        return self._two(actor, keep_higher=True)

    def disadvantage(self, actor: Actor) -> Reply:
        return self._two(actor, keep_higher=False)

    def _two(self, actor: Actor, *, keep_higher: bool) -> Reply:
        if len(self.deck.draw) < 2:
            # Carry the hint explicitly: with one card left, finish() would not add it.
            return Reply("Not enough cards in the draw pile to flip two.",
                         tone="error", hints=(self.shuffle_hint,))
        c1, c2 = self._take(), self._take()
        o1, o2 = resolve(c1, self.trump, self.ruleset), resolve(c2, self.trump, self.ruleset)
        better = o2.score > o1.score if keep_higher else o2.score < o1.score
        kept_index = 1 if better else 0
        kept = (o1, o2)[kept_index]
        prompts = self._apply(actor, kept)
        label = "advantage" if keep_higher else "disadvantage"
        text = "\n".join([
            f"{actor.display_name} flips with {label}: **{self._name(c1)}** and **{self._name(c2)}**.",
            f"Kept **{self._name(kept.card)}**: {describe(kept, self.ruleset)}.",
            *prompts,
        ])
        return self.finish(Reply(text, (c1, c2), kept_index, self._tone(kept)))

    def redraw(self, actor: Actor) -> Reply:
        pending = self.pending
        if pending is None or pending.kind == "choose_trump":
            return self._error(self._hint("nothing_to_redraw"))
        if pending.user_id != actor.user_id:
            return self._error(self._hint("not_your_redraw"))
        if pending.kind == "redraw_upgrade":
            assert self.last_outcome is not None
            outcome = upgrade(self.last_outcome, self.ruleset)
            self.last_outcome = outcome
            self.pending = None
            text = self._hint("upgraded", name=actor.display_name, card=self._name(outcome.card),
                              result=describe(outcome, self.ruleset))
            return self.finish(Reply(text, (outcome.card,), None, "success"))
        if not self.deck.draw:
            return self._error(self._hint("redraw_empty_draw"))
        card = self._take()
        outcome = resolve(card, self.trump, self.ruleset)
        prompts = self._apply(actor, outcome)
        flip_line = self._hint("replaced", name=actor.display_name, card=self._name(card),
                               result=describe(outcome, self.ruleset))
        text = "\n".join([flip_line, *prompts])
        return self.finish(Reply(text, (card,), None, self._tone(outcome)))

    def show_trump(self, actor: Actor) -> Reply:
        return self.finish(Reply(f"Trump is {_suit_label(self.trump)}."))

    def set_trump(self, actor: Actor, suit: Suit) -> Reply:
        choosing = (self.pending is not None and self.pending.kind == "choose_trump"
                    and self.pending.user_id == actor.user_id)
        if not actor.is_gm and not choosing:
            return self._error("Only the GM can set trump.")
        self.trump = suit
        if self.pending is not None and self.pending.kind == "choose_trump":
            self.pending = None
        return self.finish(Reply(f"{actor.display_name} sets trump to {_suit_label(suit)}."))

    def shuffle(self, actor: Actor) -> Reply:
        if not actor.is_gm:
            return self._error("Only the GM can shuffle.")
        card = self._shuffle_and_turn_trump()
        text = (f"{actor.display_name} shuffles all 40 cards. **{self._name(card)}** is turned up: "
                f"trump is {_suit_label(self.trump)}.")
        return self.finish(Reply(text, (card,)))

    def status(self, actor: Actor) -> Reply:
        text = (f"Trump: {_suit_label(self.trump)} | Draw: {len(self.deck.draw)} | "
                f"Discards: {len(self.deck.discards)} | Aces drawn: {self.aces_drawn}/4")
        return self.finish(Reply(text))

    def set_style(self, actor: Actor, style: TextStyle) -> Reply:
        self.style = style
        return self.finish(Reply(f"Card names now use the {style} style."))

    def set_images(self, actor: Actor, mode: ImageMode) -> Reply:
        self.images = mode
        return self.finish(Reply(f"Card images set to {mode}."))


def new_table_notice(table: Table) -> str:
    card = table.deck.discards[0]
    return (f"New deck for this channel. **{card.text(table.style)}** is turned up: "
            f"trump is {_suit_label(table.trump)}.")
