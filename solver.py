"""Double-dummy solver: exact minimax over a fully specified deal.

Given both hands face up, the play phase of a round is a small zero-sum perfect-information
game, and this solves it exactly. Everything above it — PIMC bidding, PIMC play, the
best-response oracle — is some way of sampling the hands this solver then treats as known.

Hands are 18-bit masks so the transposition-table key is a tuple of ints. The tree is small
enough that exhaustive minimax would terminate, but not fast enough to run hundreds of times
per decision, so this is alpha-beta with a proper bounded transposition table: entries carry
an EXACT/LOWER/UPPER flag and are only reused when the stored bound resolves the current
window. Reusing raw alpha-beta values as if they were exact is the classic way to get a
solver that is wrong only sometimes, so the flag is not optional.

The table is keyed on position alone, which means it is only valid for a fixed trump and a
fixed payoff function. :class:`DoubleDummy` therefore owns one table per (trump, payoff)
configuration and is meant to be reused across the determinizations of a single decision,
where those are constant and the subproblems genuinely overlap.
"""
from __future__ import annotations

from engine import (DECK_SIZE, FIRST_JESTER, FIRST_WIZARD, NUM_NORMAL, NUM_RANKS,
                    NUM_SUITS, round_score)

EXACT, LOWER, UPPER = 0, 1, 2

_SUIT_MASK = tuple(
    sum(1 << c for c in range(NUM_NORMAL) if (c // NUM_RANKS) == s)
    for s in range(NUM_SUITS)
)
_SPECIALS = sum(1 << c for c in range(NUM_NORMAL, DECK_SIZE))

INF = float("inf")


def mask_of(cards) -> int:
    """Pack an iterable of card ints into a bitmask."""
    m = 0
    for c in cards:
        m |= 1 << c
    return m


def cards_of(mask: int) -> tuple[int, ...]:
    """Unpack a bitmask back into sorted card ints."""
    out = []
    while mask:
        low = mask & -mask
        out.append(low.bit_length() - 1)
        mask ^= low
    return tuple(out)


def legal_mask(hand: int, lead_card: int | None) -> int:
    """Bitmask of legal plays — the mask form of :func:`engine.legal_plays`."""
    if lead_card is None or lead_card >= NUM_NORMAL:
        return hand
    follow = hand & _SUIT_MASK[lead_card // NUM_RANKS]
    if not follow:
        return hand
    return follow | (hand & _SPECIALS)


def _wins(lead_card: int, follow_card: int, trump: int) -> bool:
    """True if the follower takes the trick. Mirrors :func:`engine.trick_winner` exactly.

    The test order carries the duplicate-card rules: a Wizard *lead* is checked before a
    Wizard *follow* (first Wizard played wins), and a Jester *follow* before a Jester *lead*
    (two Jesters go to the leader). Reordering these silently changes the game.
    """
    if lead_card >= FIRST_WIZARD and lead_card < FIRST_JESTER:
        return False
    if follow_card >= FIRST_WIZARD and follow_card < FIRST_JESTER:
        return True
    if follow_card >= FIRST_JESTER:
        return False
    if lead_card >= FIRST_JESTER:
        return True
    led, fol = lead_card // NUM_RANKS, follow_card // NUM_RANKS
    if trump >= 0:
        if fol == trump and led != trump:
            return True
        if led == trump and fol != trump:
            return False
    return fol == led and (follow_card % NUM_RANKS) > (lead_card % NUM_RANKS)


def tricks_payoff(a_tricks: int, _b_tricks: int) -> float:
    """Payoff for the bidding phase: A maximizes tricks taken, B minimizes them.

    Valid as a zero-sum objective because trick counts always sum to the hand size, so
    minimizing A's tricks is exactly maximizing B's.
    """
    return float(a_tricks)


def score_payoff(bid_a: int, bid_b: int):
    """Payoff for the play phase: the round's score differential under the real scoring.

    Returns ``score_a - score_b``, which is a genuine zero-sum objective even though the
    scores themselves are not — B minimizing the difference is B maximizing their own score
    net of A's, which is what a match-winning opponent actually wants.
    """
    def payoff(a_tricks: int, b_tricks: int) -> float:
        return float(round_score(bid_a, a_tricks) - round_score(bid_b, b_tricks))
    return payoff


class DoubleDummy:
    """Exact alpha-beta over one deal, with a transposition table across determinizations.

    Args:
        trump: Trump suit index, or :data:`engine.NO_TRUMP`.
        payoff: ``(a_tricks, b_tricks) -> float``, maximized by A and minimized by B.
        budget: Node ceiling. On exhaustion the search stops deepening and falls back to the
            payoff of the position as it stands, so a pathological call degrades to a weak
            answer instead of hanging. :attr:`exhausted` reports whether this happened.
    """

    def __init__(self, trump: int, payoff=tricks_payoff, budget: int = 2_000_000):
        self.trump = trump
        self.payoff = payoff
        self.budget = budget
        self.nodes = 0
        self.exhausted = False
        self._tt: dict[tuple, tuple[float, int]] = {}
        self._order = self._build_order(trump)

    @staticmethod
    def _build_order(trump: int) -> list[int]:
        """Cards sorted strongest first, for move ordering only — never for legality."""
        def power(card: int) -> int:
            if card >= FIRST_JESTER:
                return -1
            if card >= FIRST_WIZARD:
                return 100
            base = card % NUM_RANKS
            return base + 50 if (trump >= 0 and (card // NUM_RANKS) == trump) else base
        return sorted(range(DECK_SIZE), key=power, reverse=True)

    # -- search ---------------------------------------------------------------

    def _moves(self, hand: int, lead_card: int | None):
        """Legal plays, strongest first. Ordering drives cutoffs and nothing else."""
        allowed = legal_mask(hand, lead_card)
        return [c for c in self._order if allowed >> c & 1]

    def _search(self, a: int, b: int, a_to_move: bool, lead: int | None,
                at: int, bt: int, alpha: float, beta: float) -> float:
        if a == 0 and b == 0:
            return self.payoff(at, bt)
        if self.nodes >= self.budget:
            self.exhausted = True
            return self.payoff(at, bt)

        key = (a, b, a_to_move, lead, at)
        cached = self._tt.get(key)
        if cached is not None:
            value, flag = cached
            if flag == EXACT:
                return value
            if flag == LOWER and value >= beta:
                return value
            if flag == UPPER and value <= alpha:
                return value

        self.nodes += 1
        alpha_orig, beta_orig = alpha, beta
        hand = a if a_to_move else b

        if lead is None:
            # Leading: every card is legal, and the follower answers.
            best = -INF if a_to_move else INF
            for card in self._moves(hand, None):
                if a_to_move:
                    value = self._search(a ^ (1 << card), b, False, card, at, bt, alpha, beta)
                    if value > best:
                        best = value
                    if best > alpha:
                        alpha = best
                else:
                    value = self._search(a, b ^ (1 << card), True, card, at, bt, alpha, beta)
                    if value < best:
                        best = value
                    if best < beta:
                        beta = best
                if alpha >= beta:
                    break
        else:
            # Following: resolve the trick, then the winner leads the next one.
            best = -INF if a_to_move else INF
            for card in self._moves(hand, lead):
                if a_to_move:
                    follower_won = _wins(lead, card, self.trump)
                    value = self._search(
                        a ^ (1 << card), b, follower_won, None,
                        at + follower_won, bt + (not follower_won), alpha, beta,
                    )
                    if value > best:
                        best = value
                    if best > alpha:
                        alpha = best
                else:
                    follower_won = _wins(lead, card, self.trump)
                    value = self._search(
                        a, b ^ (1 << card), not follower_won, None,
                        at + (not follower_won), bt + follower_won, alpha, beta,
                    )
                    if value < best:
                        best = value
                    if best < beta:
                        beta = best
                if alpha >= beta:
                    break

        if best <= alpha_orig:
            flag = UPPER
        elif best >= beta_orig:
            flag = LOWER
        else:
            flag = EXACT
        self._tt[key] = (best, flag)
        return best

    # -- public API -----------------------------------------------------------

    def _begin(self) -> None:
        """Start a fresh determinization.

        One instance is deliberately reused across all the determinizations of a single
        decision so the table can carry subtrees between them, but the node budget must not
        be carried with it. Left cumulative, a large enough sample count exhausts the budget
        partway through and every determinization after that returns ``payoff(a, b)`` without
        searching at all — a constant that silently drags every option's average toward the
        same number, with no error and no sign that it happened.
        """
        self.nodes = 0
        # A tuple-keyed dict entry costs a few hundred bytes here, so this cap is a memory
        # budget rather than a nicety: a round robin runs several PIMC agents inside each of
        # several worker processes, and at 400k the pool ran the machine out of memory
        # mid-tournament. 40k keeps a solver near ten megabytes while still carrying the
        # table across the determinizations of one decision, which is where it pays.
        if len(self._tt) > 40_000:
            self._tt.clear()

    def value(self, a_hand, b_hand, *, a_to_move: bool = True, lead: int | None = None,
              a_tricks: int = 0, b_tricks: int = 0) -> float:
        """Exact minimax value of the position, from A's point of view."""
        self._begin()
        a = a_hand if isinstance(a_hand, int) else mask_of(a_hand)
        b = b_hand if isinstance(b_hand, int) else mask_of(b_hand)
        return self._search(a, b, a_to_move, lead, a_tricks, b_tricks, -INF, INF)

    def root_values(self, a_hand, b_hand, *, lead: int | None = None,
                    a_tricks: int = 0, b_tricks: int = 0) -> dict[int, float]:
        """Value of every legal move for A at this position.

        Each root move is searched on a full window rather than a narrowing one. Alpha-beta
        would return a bound for every move except the best, and PIMC averages these values
        across determinizations — averaging bounds would quietly corrupt the comparison
        between moves.
        """
        self._begin()
        a = a_hand if isinstance(a_hand, int) else mask_of(a_hand)
        b = b_hand if isinstance(b_hand, int) else mask_of(b_hand)
        out: dict[int, float] = {}
        for card in self._moves(a, lead):
            bit = 1 << card
            if lead is None:
                out[card] = self._search(a ^ bit, b, False, card, a_tricks, b_tricks, -INF, INF)
            else:
                won = _wins(lead, card, self.trump)
                out[card] = self._search(
                    a ^ bit, b, won, None, a_tricks + won, b_tricks + (not won), -INF, INF,
                )
        return out


# --------------------------------------------------------------------------- helpers

def optimal_tricks(a_hand, b_hand, trump: int, a_leads: bool = True) -> int:
    """Tricks A takes when both sides play perfectly to maximize their own trick count.

    This is the quantity a bid is a guess at, which is why the bidding bots sample hands and
    call this rather than trying to evaluate a hand by features.
    """
    dd = DoubleDummy(trump, tricks_payoff)
    return int(round(dd.value(a_hand, b_hand, a_to_move=a_leads)))
