"""Rules you could state in one sentence each.

Every strategy here is deliberately crude and isolates exactly one idea, so the tournament
answers a specific question rather than a vague one. Read as a group they form a ladder:

    duck / grab    what a fixed policy is worth when it ignores the contract entirely
    specials       what the four special cards alone are worth
    count          what counting your own winners is worth
    contract       what "win it only when you still need it" adds on top of counting

The two bid policies and the three play policies are written as free functions rather than
methods so a strategy is just a pairing of the two. That is the point of the file: it makes
the comparison between neighbouring rows a controlled experiment, with exactly one thing
different, instead of two whole agents that happen to differ in several ways at once.
"""
from __future__ import annotations

from agents.base import Agent, card_power, count_specials, practical_bid_bounds
from engine import NUM_RANKS, is_jester, is_wizard, suit_of, trick_winner


# --------------------------------------------------------------------------- bidding

def _nearest(legal, target: int) -> int:
    """The legal bid closest to `target`, breaking ties upward.

    Upward because a made bid pays ``2 + tricks``: when two bids look equally reachable the
    larger one is worth more, and the hook regularly makes the obvious number illegal.
    """
    return min(legal, key=lambda b: (abs(b - target), -b))


def bid_extreme(view, legal, high: bool) -> int:
    """Bid the top or the bottom of what the specials make possible, ignoring everything else."""
    low, top = practical_bid_bounds(view.hand, view.hand_size)
    return _nearest(legal, top if high else low)


def bid_count(view, legal) -> int:
    """Count your own likely winners: every Wizard, plus every high trump, plus bare aces.

    No probability, no search — the arithmetic a beginner does on their first hand. Jesters
    count against, since a Jester played second can never win.
    """
    wizards, jesters = count_specials(view.hand)
    trump = view.trump
    winners = wizards
    for card in view.hand:
        if is_wizard(card) or is_jester(card):
            continue
        rank, suit = card % NUM_RANKS, suit_of(card)
        if trump >= 0 and suit == trump:
            winners += 1 if rank >= NUM_RANKS - 3 else 0      # Q, K, A of trumps
        elif rank == NUM_RANKS - 1:
            winners += 1                                      # a bare ace off-suit
    low, top = practical_bid_bounds(view.hand, view.hand_size)
    return _nearest(legal, min(max(winners, low), top))


# --------------------------------------------------------------------------- play

def play_extreme(view, legal, high: bool) -> int:
    """Always the strongest, or always the weakest. Never looks at the contract."""
    return max(legal, key=lambda c: card_power(c, view.trump)) if high \
        else min(legal, key=lambda c: card_power(c, view.trump))


def play_specials(view, legal) -> int:
    """Spend the special cards on purpose; play any other card blind.

    Wizards when a trick is still wanted, Jesters when it is not. This is the whole strategy,
    so what it measures is how much of the game the four odd cards decide on their own.
    """
    wants = (view.my_bid - view.my_tricks) > 0
    if wants:
        wizards = [c for c in legal if is_wizard(c)]
        if wizards:
            return wizards[0]
    else:
        jesters = [c for c in legal if is_jester(c)]
        if jesters:
            return jesters[0]
    return play_extreme(view, legal, high=wants)


def play_contract(view, legal) -> int:
    """Win the trick exactly when you still need it, and spend as little as possible doing it.

    Following, whether a card wins is a fact rather than a guess, so the rule is exact: take
    it with the cheapest winner, or shed the dearest loser. Leading is the guess — lead high
    when chasing tricks, low when avoiding them.
    """
    trump = view.trump
    wants = (view.my_bid - view.my_tricks) > 0

    if view.lead_card is None:
        return play_extreme(view, legal, high=wants)

    winners = [c for c in legal if trick_winner(view.lead_card, c, trump) == 1]
    losers = [c for c in legal if c not in winners]
    if wants:
        pool = winners or losers            # cheapest win, else cheapest discard
        return min(pool, key=lambda c: card_power(c, trump))
    pool = losers or winners                # dearest safe discard, else forced to take it
    return max(pool, key=lambda c: card_power(c, trump)) if losers \
        else min(pool, key=lambda c: card_power(c, trump))


# --------------------------------------------------------------------------- strategies

class DuckBot(Agent):
    """Bid as low as the specials allow, then never try to win a trick."""

    def bid(self, view, legal):
        return bid_extreme(view, legal, high=False)

    def play(self, view, legal):
        return play_extreme(view, legal, high=False)


class GrabBot(Agent):
    """Bid as high as the specials allow, then take every trick it can."""

    def bid(self, view, legal):
        return bid_extreme(view, legal, high=True)

    def play(self, view, legal):
        return play_extreme(view, legal, high=True)


class SpecialsBot(Agent):
    """Bid the Wizards it holds; play the specials deliberately and everything else blind."""

    def bid(self, view, legal):
        wizards, _ = count_specials(view.hand)
        return _nearest(legal, wizards)

    def play(self, view, legal):
        return play_specials(view, legal)


class CountBot(Agent):
    """Counts its winners to bid, but still plays a fixed high/low policy.

    Paired with ContractBot below this isolates the value of the play rule alone: the two bid
    identically and differ only in what they do with a card once the bidding is over.
    """

    def bid(self, view, legal):
        return bid_count(view, legal)

    def play(self, view, legal):
        wants = (view.my_bid - view.my_tricks) > 0
        return play_extreme(view, legal, high=wants)


class ContractBot(Agent):
    """Counts its winners to bid, then wins a trick exactly when it still needs one."""

    def bid(self, view, legal):
        return bid_count(view, legal)

    def play(self, view, legal):
        return play_contract(view, legal)
