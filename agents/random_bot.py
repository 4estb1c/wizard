"""Uniform random play — the floor every other strategy has to beat."""
from __future__ import annotations

from agents.base import Agent


class RandomBot(Agent):
    """Picks uniformly among legal bids and legal cards.

    Deliberately does not use the Wizard/Jester bid bounds, so it bids guaranteed misses
    reasonably often. That is the point: it calibrates how much the trivially-known facts are
    worth before any search enters the picture.
    """

    def bid(self, view, legal):
        return self.rng.choice(legal)

    def play(self, view, legal):
        return self.rng.choice(legal)
