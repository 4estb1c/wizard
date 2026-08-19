"""Seven-card hand evaluation, and the exact equity that everything else rests on.

Hold'em is not solvable the way a small trick-taking game is, so this module is deliberately
confined to the parts that *are* exact: which of two hands wins, and how often one hand beats
another over every runout. Both are settled by enumeration, not estimation. Everything
approximate in this project is built on top of these two functions and is labelled as such.

Cards are ints 0..51 with ``rank = c >> 2`` (0 = deuce, 12 = ace) and ``suit = c & 3``, so a
hand is a list of small ints and the hot loops stay in integer arithmetic.

A hand's strength is one integer, larger is better, laid out base-13:

    category * 13^5 + k1 * 13^4 + k2 * 13^3 + k3 * 13^2 + k4 * 13 + k5

so two hands compare with a single ``<``. The five kickers are always written even when the
category does not need all of them, which is what makes ties between, say, two identical
two-pair holdings resolve on the fifth card rather than silently comparing short tuples.
"""
from __future__ import annotations

from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "cdhs"

HIGH, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, BOAT, QUADS, STRAIGHT_FLUSH = range(9)
CATEGORY_NAMES = ("high card", "a pair", "two pair", "three of a kind", "a straight",
                  "a flush", "a full house", "four of a kind", "a straight flush")

_B = 13


def card(text: str) -> int:
    """Parse ``"As"`` or ``"7h"`` into a card int."""
    return RANKS.index(text[0].upper()) * 4 + SUITS.index(text[1].lower())


def hand(text: str) -> list[int]:
    """Parse ``"As Kd 7h"`` into card ints."""
    return [card(t) for t in text.split()]


def card_name(c: int) -> str:
    return RANKS[c >> 2] + SUITS[c & 3]


def cards_name(cs) -> str:
    return " ".join(card_name(c) for c in cs)


def _pack(category: int, kickers) -> int:
    v = category
    for k in kickers:
        v = v * _B + k
    return v


# Straight lookup: for each 13-bit rank mask, the high rank of the best straight, or -1.
# The wheel is folded in by treating an ace as also sitting below the deuce.
# Straight lookup: for each 13-bit rank mask, the high rank of the best straight, or -1.
# Scanned high to low, because a seven-card hand can contain two straights and the higher one
# is the hand. (Five cards can only ever contain one, so this is invisible to a 5-card census.)
_STRAIGHT = [-1] * (1 << 13)
for _mask in range(1 << 13):
    _hi = -1
    for _top in range(12, 3, -1):
        if all(_mask & (1 << (_top - i)) for i in range(5)):
            _hi = _top
            break
    # The wheel is the one straight the ace plays low in, and it is the lowest of all, so it
    # only counts when nothing above it matched.
    if _hi < 0 and (_mask & (1 << 12)) and (_mask & 0b1111) == 0b1111:
        _hi = 3
    _STRAIGHT[_mask] = _hi


def evaluate(cards) -> int:
    """Strength of the best five-card hand inside `cards` (five to seven of them)."""
    rank_count = [0] * 13
    suit_count = [0] * 4
    suit_mask = [0] * 4
    mask = 0
    for c in cards:
        r, s = c >> 2, c & 3
        rank_count[r] += 1
        suit_count[s] += 1
        suit_mask[s] |= 1 << r
        mask |= 1 << r

    # Flushes first: a flush and a straight flush can only live in the one suit with five.
    for s in range(4):
        if suit_count[s] >= 5:
            sm = suit_mask[s]
            sf = _STRAIGHT[sm]
            if sf >= 0:
                return _pack(STRAIGHT_FLUSH, (sf, 0, 0, 0, 0))
            top = []
            for r in range(12, -1, -1):
                if sm & (1 << r):
                    top.append(r)
                    if len(top) == 5:
                        break
            return _pack(FLUSH, top)

    # Rank-count shapes, strongest first.
    quads = [r for r in range(12, -1, -1) if rank_count[r] == 4]
    trips = [r for r in range(12, -1, -1) if rank_count[r] == 3]
    pairs = [r for r in range(12, -1, -1) if rank_count[r] == 2]
    singles = [r for r in range(12, -1, -1) if rank_count[r] == 1]

    if quads:
        q = quads[0]
        kicker = max(r for r in range(13) if rank_count[r] and r != q)
        return _pack(QUADS, (q, kicker, 0, 0, 0))
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        pair = trips[1] if len(trips) > 1 else pairs[0]
        if pairs and pairs[0] > pair:
            pair = pairs[0]
        return _pack(BOAT, (t, pair, 0, 0, 0))

    straight = _STRAIGHT[mask]
    if straight >= 0:
        return _pack(STRAIGHT, (straight, 0, 0, 0, 0))

    if trips:
        t = trips[0]
        return _pack(TRIPS, [t] + singles[:2] + [0, 0])
    if len(pairs) >= 2:
        rest = [r for r in range(12, -1, -1) if rank_count[r] and r not in pairs[:2]]
        return _pack(TWO_PAIR, [pairs[0], pairs[1], rest[0], 0, 0])
    if pairs:
        return _pack(PAIR, [pairs[0]] + singles[:3] + [0])
    return _pack(HIGH, singles[:5])


def category_of(score: int) -> int:
    return score // (_B ** 5)


def describe(score: int) -> str:
    return CATEGORY_NAMES[category_of(score)]


# --------------------------------------------------------------------------- equity

def equity(hero, villain, board=(), deck=None) -> tuple[float, int]:
    """Exact equity for `hero` against `villain`, enumerating every remaining runout.

    Returns ``(share, runouts)`` where share counts a tie as half. This is enumeration over
    the complete set of boards, so the number is exact rather than sampled: there is no
    variance to quote and no seed to record.
    """
    known = set(hero) | set(villain) | set(board)
    if deck is None:
        deck = [c for c in range(52) if c not in known]
    need = 5 - len(board)
    won = tied = total = 0
    board = list(board)
    for extra in combinations(deck, need):
        full = board + list(extra)
        h = evaluate(hero + full)
        v = evaluate(villain + full)
        total += 1
        if h > v:
            won += 1
        elif h == v:
            tied += 1
    return (won + tied / 2) / total, total
