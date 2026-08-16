"""The one interface every strategy implements, plus the inferences they all share.

An agent is asked for three things: a trump suit (only when the flipped card is the Wizard),
a bid, and a card. It is handed a :class:`engine.View` containing exactly what it may
legally know, and a tuple of legal choices — so a strategy can never accidentally cheat by
reading a field that should have been hidden, and never has to re-derive legality.

Randomness comes from ``self.rng``, seeded by the harness, never from the global ``random``
module. That is what lets the two seat orders of a pairing replay identical draws.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod

from engine import (FIRST_JESTER, FIRST_WIZARD, NUM_NORMAL, NUM_RANKS, NUM_SUITS,
                    is_jester, is_wizard, suit_of)


class Agent(ABC):
    """Base class for every strategy in the roster."""

    def __init__(self, name: str | None = None):
        self._name = name
        self.rng = random.Random(0)

    def seed(self, value: int) -> None:
        """Give this agent its own reproducible RNG stream."""
        self.rng = random.Random(value)

    def reset(self) -> None:
        """Called once at the start of each match."""

    def choose_trump(self, view) -> int:
        """Name trump after a flipped Wizard. Default: longest suit, strongest as tiebreak.

        Worth remembering that this choice is public and, heads-up, is a tell — the only
        opponent there is learns roughly where your strength sits before either bid.
        """
        length = [0] * NUM_SUITS
        power = [0] * NUM_SUITS
        for card in view.hand:
            s = suit_of(card)
            if s >= 0:
                length[s] += 1
                power[s] += (card % NUM_RANKS) + 1
        return max(range(NUM_SUITS), key=lambda s: (length[s], power[s]))

    @abstractmethod
    def bid(self, view, legal: tuple[int, ...]) -> int:
        """Return one of `legal`. The dealer's forbidden bid is already excluded."""

    @abstractmethod
    def play(self, view, legal: tuple[int, ...]) -> int:
        """Return one of `legal`. Follow-suit obligations are already applied."""

    @property
    def name(self) -> str:
        return self._name or type(self).__name__

    def __repr__(self) -> str:
        return f"<{self.name}>"


# --------------------------------------------------------------------------- shared reads

def count_specials(hand) -> tuple[int, int]:
    """``(wizards, jesters)`` held."""
    return (sum(1 for c in hand if is_wizard(c)),
            sum(1 for c in hand if is_jester(c)))


def hard_bid_bounds(hand, hand_size: int) -> tuple[int, int]:
    """Bids that are impossible to make whatever the opponent does.

    With two of each special these are weaker than they look. One Wizard is *not* a
    guaranteed trick: the opponent can lead the other Wizard onto it, and if it is your last
    card you have to play it. Symmetrically one Jester is not a guaranteed lost trick, since
    leading it into the other Jester wins.

    Holding *both* copies is what restores certainty — nobody can outrank a Wizard you both
    hold, and neither of your Jesters can meet a Jester. So the only unconditional bounds are
    at two of a kind.
    """
    wizards, jesters = count_specials(hand)
    return (2 if wizards == 2 else 0,
            hand_size - (2 if jesters == 2 else 0))


def practical_bid_bounds(hand, hand_size: int) -> tuple[int, int]:
    """Bounds that hold unless the opponent spends a special of their own to break them.

    A single Wizard wins every trick it is played in except against a Wizard *lead*, and a
    single Jester loses every trick except against a Jester *lead* by you. Both exceptions
    cost the opponent their own special card, so these bounds are the ones worth bidding on
    even though :func:`hard_bid_bounds` is what is actually guaranteed.
    """
    wizards, jesters = count_specials(hand)
    return (wizards, hand_size - jesters)


def infer_voids(view) -> set[int]:
    """Suits the opponent is known to be void in, from their failures to follow.

    Only tricks *we* led carry this information, and only when they answered with a normal
    card: the Wizard and Jester are legal at any time, so discarding one reveals nothing.
    """
    voids: set[int] = set()
    for i_led, my_card, their_card in view.history:
        if not i_led:
            continue
        led = suit_of(my_card)
        if led < 0 or their_card >= NUM_NORMAL:
            continue
        if suit_of(their_card) != led:
            voids.add(led)
    return voids


def sample_opponent_hand(view, rng: random.Random, voids: set[int] | None = None):
    """Draw one opponent hand consistent with everything we have observed.

    Consistency here means the right number of cards, drawn from the cards we have not seen,
    avoiding any suit they have shown a void in. The remaining unseen cards are the dead
    stock, which is never revealed — so unlike most trick-taking games there is no round in
    which this collapses to certainty.
    """
    unseen = view.unseen
    size = view.opp_hand_size
    if size <= 0:
        return ()
    if voids:
        allowed = [c for c in unseen if suit_of(c) not in voids]
        if len(allowed) >= size:
            return tuple(rng.sample(allowed, size))
    return tuple(rng.sample(unseen, size))


def card_power(card: int, trump: int) -> int:
    """Crude strength ordering used for move preference, never for legality."""
    if card >= FIRST_JESTER:
        return -1
    if card >= FIRST_WIZARD:
        return 100
    rank = card % NUM_RANKS
    return rank + 50 if (trump >= 0 and (card // NUM_RANKS) == trump) else rank
