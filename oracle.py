"""The double-dummy oracle — a ceiling, not a competitor.

This player is handed the opponent's hand through :meth:`reveal` and then plays the exact
minimax line. Running a strategy against it measures the **double-dummy gap**: how much a
strategy concedes to somebody who has perfect information and never misplays.

**What this is not.** It is not Nash exploitability. The oracle uses information no legal
player has, so its margin is an *upper* bound on what any real opponent could extract, not
the lower bound a best-response oracle would give. In GOPS both hands are public, so a
best-response oracle there is a legal construction; here hidden information is the entire
game, and there is no cheap legal equivalent. A true exploitability figure would need a
best response computed over information sets — worth building, not built here, and it would
be dishonest to print this number under that label.

What the gap is good for is the property that made exploitability worth measuring in the
first place: it is **population-independent**. Every number the tournament produces is
relative to the roster, so a roster can churn while all its internal statistics look
healthy. The gap does not care what else exists.
"""
from __future__ import annotations

from agents.base import Agent
from engine import LADDER, play_match, round_score
from solver import DoubleDummy, score_payoff, tricks_payoff


class OracleBot(Agent):
    """Perfect-information minimax. Excluded from :data:`agents.ROSTER` by design."""

    def __init__(self, name: str = "oracle"):
        super().__init__(name)
        self._opponent: tuple[int, ...] = ()
        self._trump = 0

    def reveal(self, _my_hand, opponent_hand, trump) -> None:
        self._opponent = opponent_hand
        self._trump = trump

    def _opponent_now(self, view) -> tuple[int, ...]:
        """Their remaining cards: the revealed hand minus everything they have played."""
        played = {theirs for _, _, theirs in view.history}
        if view.lead_card is not None:
            played.add(view.lead_card)
        return tuple(c for c in self._opponent if c not in played)

    def bid(self, view, legal):
        opponent = self._opponent_now(view)
        if view.opp_bid is not None:
            # Their bid is already on the table, so the whole round is a solved
            # perfect-information game: pick the bid whose play phase is worth the most.
            best, best_value = legal[0], None
            for candidate in legal:
                dd = DoubleDummy(view.trump, score_payoff(candidate, view.opp_bid))
                value = dd.value(view.hand, opponent, a_to_move=view.i_lead)
                if best_value is None or value > best_value:
                    best, best_value = candidate, value
            return best

        # Bidding first, so their bid is unknown. Bid the trick count both sides get under
        # trick-maximizing play — the honest number, which is also the one most likely to
        # deny the dealer theirs.
        dd = DoubleDummy(view.trump, tricks_payoff)
        exact = int(round(dd.value(view.hand, opponent, a_to_move=view.i_lead)))
        return min(legal, key=lambda b: (abs(b - exact), -b))

    def play(self, view, legal):
        if len(legal) == 1:
            return legal[0]
        dd = DoubleDummy(view.trump, score_payoff(view.my_bid, view.opp_bid))
        values = dd.root_values(
            view.hand, self._opponent_now(view), lead=view.lead_card,
            a_tricks=view.my_tricks, b_tricks=view.opp_tricks,
        )
        return max(legal, key=lambda c: values.get(c, -1e9))


def double_dummy_gap(factory, *, matches: int = 24, seed: int = 0, ladder=LADDER) -> dict:
    """Mean margin the oracle takes off `factory()` over mirrored matches.

    Both orders of every deal are played, so the result is not contaminated by the deal.

    Returns:
        ``{"margin", "win_rate", "matches"}`` — margin in match points per match, from the
        oracle's side. Lower is better for the strategy under test.
    """
    from sim import make_seeds, stream_seed

    total_margin = 0.0
    oracle_wins = 0.0
    played = 0

    for index, deal in enumerate(make_seeds(matches, seed)):
        for forward in (True, False):
            victim = factory()
            oracle = OracleBot()
            victim.seed(stream_seed(0xBEEF, index))
            oracle.seed(stream_seed(0xFEED, index))
            a, b = (oracle, victim) if forward else (victim, oracle)
            result = play_match(a, b, deal, ladder=ladder)
            margin = result.margin if forward else -result.margin
            total_margin += margin
            oracle_wins += 1.0 if margin > 0 else 0.5 if margin == 0 else 0.0
            played += 1

    return {
        "margin": total_margin / played,
        "win_rate": oracle_wins / played,
        "matches": played,
    }


__all__ = ["OracleBot", "double_dummy_gap", "round_score"]
