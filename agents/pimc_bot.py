"""Perfect-Information Monte Carlo — the strongest thing here that is still a legal player.

The idea is the standard one from strong bridge and skat engines. The hard part of this game
is that the opponent's hand is hidden; so guess it, many times, consistently with everything
observed, and solve each guess exactly with the double-dummy solver. Average the value of
each candidate action over the guesses and take the best.

**This is not GTO and should not be sold as it.** PIMC has two documented pathologies:

* *Strategy fusion* — it may pick an action justified by playing differently in two
  determinizations it cannot actually tell apart, since in the real game one policy has to
  serve both.
* *Non-locality* — it samples hands from the observation-consistent set without conditioning
  on the fact that a rational opponent's earlier choices were informative about their hand.
  The ``infer`` variant below claws back part of this by rejecting hands from which the
  opponent could never still make the bid they made, but it is a patch, not a fix.

What PIMC does have is the right treatment of everything downstream of the guess: once the
hands are fixed, its play is exactly optimal. In practice that dominates in trick-taking
games, which is why the bots below are expected to win the tournament even though a genuine
equilibrium strategy would beat all of them.
"""
from __future__ import annotations

from agents.base import Agent, infer_voids, sample_opponent_hand
from engine import round_score
from solver import DoubleDummy, score_payoff, tricks_payoff


class PIMCBot(Agent):
    """Determinize, solve exactly, average.

    Args:
        samples: Determinizations per play decision.
        bid_samples: Determinizations per bid. Defaults to ``samples``.
        infer: Reject determinizations from which the opponent could not still make the bid
            they actually made. Costs a second solve per sample; whether it pays for itself
            is exactly the sort of question the tournament is here to answer.
        veto: Weight on the denial term when bidding first (see :meth:`_bid_value`).
    """

    def __init__(self, samples: int = 24, bid_samples: int | None = None,
                 infer: bool = False, veto: float = 0.0, name: str | None = None):
        super().__init__(name)
        self.samples = samples
        self.bid_samples = bid_samples if bid_samples is not None else samples
        self.infer = infer
        self.veto = veto

    # -- bidding --------------------------------------------------------------

    def _trick_distribution(self, view) -> list[int]:
        """Sample hands and double-dummy each one for the tricks we would take."""
        # trump and payoff are constant across these, so one table serves every sample and
        # later samples ride on the subtrees earlier ones already resolved.
        dd = DoubleDummy(view.trump, tricks_payoff)
        counts = []
        for _ in range(self.bid_samples):
            opponent = sample_opponent_hand(view, self.rng)
            counts.append(int(round(dd.value(view.hand, opponent, a_to_move=view.i_lead))))
        return counts

    def _bid_value(self, bid: int, counts: list[int], view) -> float:
        """Expected value of `bid` over the sampled trick distribution.

        As dealer the opponent's bid is already on the table, so the objective is the true
        score differential. As non-dealer it is our own expected score, optionally plus a
        denial term.

        The denial term is worth a note. Our bid forbids the dealer from bidding
        ``hand_size - bid``, and their honest bid is their own trick count, which is
        ``hand_size - t``. So we deny them exactly when ``t == bid`` — the same event as
        making our own bid. Accuracy and denial are the same objective here, and ``veto``
        only shifts weight from *expected score* (which favours bidding big, since a made bid
        pays ``2 + tricks``) toward *probability of hitting* (which favours the mode).
        """
        n = len(counts)
        if view.opp_bid is not None:
            other = view.opp_bid
            size = view.hand_size
            return sum(round_score(bid, t) - round_score(other, size - t)
                       for t in counts) / n
        value = sum(round_score(bid, t) for t in counts) / n
        if self.veto:
            value += self.veto * sum(1 for t in counts if t == bid) / n
        return value

    def bid(self, view, legal):
        counts = self._trick_distribution(view)
        return max(legal, key=lambda b: (self._bid_value(b, counts, view), b))

    # -- play -----------------------------------------------------------------

    def _consistent(self, view, opponent, probe: DoubleDummy) -> bool:
        """Could the opponent still make the bid they made, holding this hand?

        Uses the minimax trick count rather than their best case, so the test asks whether
        the bid survives our best defence. Strict, but it is the assumption a strong player
        makes about a strong opponent.
        """
        needed = view.opp_bid - view.opp_tricks
        if needed <= 0:
            return True
        reachable = probe.value(
            opponent, view.hand, a_to_move=False, lead=view.lead_card,
            a_tricks=view.opp_tricks, b_tricks=view.my_tricks,
        )
        return reachable >= view.opp_bid - 1e-9

    def play(self, view, legal):
        if len(legal) == 1:
            return legal[0]

        voids = infer_voids(view)
        dd = DoubleDummy(view.trump, score_payoff(view.my_bid, view.opp_bid))
        probe = DoubleDummy(view.trump, tricks_payoff) if self.infer else None

        totals = dict.fromkeys(legal, 0.0)
        used = 0
        # Rejection sampling needs a ceiling: late in a round the consistent set can be
        # empty, and an unbounded loop would hang rather than degrade.
        for _ in range(self.samples * 6):
            if used >= self.samples:
                break
            opponent = sample_opponent_hand(view, self.rng, voids)
            if probe is not None and not self._consistent(view, opponent, probe):
                continue
            values = dd.root_values(
                view.hand, opponent, lead=view.lead_card,
                a_tricks=view.my_tricks, b_tricks=view.opp_tricks,
            )
            for card in legal:
                if card in values:
                    totals[card] += values[card]
            used += 1

        if used == 0:
            # Every consistent hand was rejected — fall back to the unfiltered set rather
            # than returning an arbitrary card.
            for _ in range(self.samples):
                opponent = sample_opponent_hand(view, self.rng)
                values = dd.root_values(
                    view.hand, opponent, lead=view.lead_card,
                    a_tricks=view.my_tricks, b_tricks=view.opp_tricks,
                )
                for card in legal:
                    if card in values:
                        totals[card] += values[card]

        return max(legal, key=lambda c: totals[c])
