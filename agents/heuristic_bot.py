"""Hand-evaluation baseline: no search, just the reads a decent human would make.

The bid is the sum, over the cards held, of the exact probability that each one beats a
single uniformly random unseen card *when led*. That is not an arbitrary weighting — it is
exactly right in round 1, and it automatically captures the fact that leading is worth far
more than raw rank, because an off-suit, non-trump card cannot win at all. A low club led
into a likely void beats most of the deck.

Its known bias is over-weighting the lead: across a seven-card round you lead roughly half
the tricks, not all of them, so the estimate drifts high at the peak. Left in on purpose —
this bot exists to show what the positional insight alone is worth before search is added.
"""
from __future__ import annotations

from agents.base import Agent, card_power, practical_bid_bounds
from engine import is_jester, trick_winner


class HeuristicBot(Agent):
    """Sum-of-lead-win-probabilities bidding, need-driven play."""

    @staticmethod
    def _lead_win_prob(card: int, unseen, trump: int) -> float:
        """Exact probability `card` takes the trick when led against one random unseen card."""
        if not unseen:
            return 0.0
        beats = sum(1 for other in unseen if trick_winner(card, other, trump) == 0)
        return beats / len(unseen)

    def bid(self, view, legal):
        unseen = view.unseen
        estimate = sum(self._lead_win_prob(c, unseen, view.trump) for c in view.hand)
        low, high = practical_bid_bounds(view.hand, view.hand_size)
        target = min(max(estimate, low), high)
        # Ties break toward the larger bid: making a bid pays 2 + tricks, so when two bids
        # look equally reachable the bigger one is worth more.
        return min(legal, key=lambda b: (abs(b - target), -b))

    def play(self, view, legal):
        if len(legal) == 1:
            return legal[0]

        trump = view.trump
        wants_trick = (view.my_bid - view.my_tricks) > 0

        if view.lead_card is not None:
            # Following: whether each card wins is a fact, not an estimate.
            winners = [c for c in legal if trick_winner(view.lead_card, c, trump) == 1]
            losers = [c for c in legal if c not in winners]
            if wants_trick:
                if winners:
                    return min(winners, key=lambda c: card_power(c, trump))  # cheapest win
                return min(losers, key=lambda c: card_power(c, trump))       # keep the good cards
            if losers:
                # Dump the highest card that still loses. Against a Wizard lead nothing wins,
                # so this sheds our own Wizard — which is right: when we want no more tricks
                # a Wizard is a liability, and their Wizard lead is the one safe place to
                # be rid of it.
                return max(losers, key=lambda c: card_power(c, trump))
            return min(winners, key=lambda c: card_power(c, trump))          # forced to take it

        # Leading.
        if wants_trick:
            return max(legal, key=lambda c: card_power(c, trump))
        jesters = [c for c in legal if is_jester(c)]
        if jesters:
            # Still the best way to shed the trick and the lead, but no longer certain: if
            # the opponent holds the other Jester they can answer with it and the trick
            # comes back to us. They only do that when they also want to shed.
            return jesters[0]
        return min(legal, key=lambda c: self._lead_win_prob(c, view.unseen, trump))
