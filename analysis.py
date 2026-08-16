"""Measure properties of the game itself, independent of any strategy.

    python analysis.py --deals 400

Everything here is computed by double-dummy solving random deals, so the numbers describe
the game under perfect play rather than the habits of the bots in the roster.
"""
from __future__ import annotations

import argparse
import random
from collections import Counter

from engine import (DECK, DECK_SIZE, NO_TRUMP, NUM_NORMAL, NUM_RANKS, PEAK, WIZARDS,
                    is_jester, round_score)
from solver import DoubleDummy, tricks_payoff


def _deal(rng: random.Random, size: int):
    cards = list(DECK)
    rng.shuffle(cards)
    flip = cards[2 * size]
    trump = NO_TRUMP if is_jester(flip) else (
        flip // NUM_RANKS if flip < NUM_NORMAL else 0)
    return cards[:size], cards[size:2 * size], flip, trump


def value_of_the_lead(deals: int, seed: int) -> None:
    """How much is leading the first trick worth, as a function of hand size?

    Round 1 says a great deal: an off-suit non-trump card cannot win, so leading anything
    beats roughly half the deck outright. The open question is whether that survives to the
    peak, where both players hold most of the suits and voids are rare.
    """
    # ASCII only in printed output: the default Windows console codepage mangles em-dashes.
    print("\nValue of the lead - double-dummy tricks for the player on lead")
    print(f"  {'size':>4}{'leader':>9}{'even split':>12}{'edge':>8}   edge as % of a trick")
    rng = random.Random(seed)
    for size in range(1, PEAK + 1):
        total = 0.0
        for _ in range(deals):
            mine, theirs, _flip, trump = _deal(rng, size)
            dd = DoubleDummy(trump, tricks_payoff)
            total += dd.value(mine, theirs, a_to_move=True)
        mean = total / deals
        edge = mean - size / 2
        bar = "#" * max(0, int(round(edge * 40)))
        print(f"  {size:>4}{mean:9.3f}{size / 2:12.1f}{edge:+8.3f}   {bar}")


def unseen_card_location(deals: int, seed: int) -> None:
    """Given you cannot see a card, how often does the opponent hold it rather than the stock?

    ``size / (DECK_SIZE - 1 - size)`` — you hold `size`, one card is face up as trump, and
    the opponent holds `size` of the rest. On the 24-card deck this tops out near half, well
    below the 70% the old 18-card deck reached, because the dead stock grew from 3 cards to 7.
    """
    print("\nWhere the unseen cards are - P(opponent holds it | you cannot see it)")
    print(f"  {'size':>4}{'formula':>10}{'measured':>10}")
    rng = random.Random(seed + 1)
    target = WIZARDS[0]
    for size in range(1, PEAK + 1):
        held = seen = 0
        for _ in range(deals):
            mine, theirs, flip, _trump = _deal(rng, size)
            if target in mine or flip == target:
                continue
            seen += 1
            held += target in theirs
        formula = size / (DECK_SIZE - 1 - size)
        measured = held / seen if seen else float("nan")
        print(f"  {size:>4}{formula:10.3f}{measured:10.3f}")


def bid_distribution(deals: int, seed: int) -> None:
    """What does a perfectly informed player actually bid, and what is a round worth?"""
    print(f"\nDouble-dummy trick counts at the peak (size {PEAK}), leader's perspective")
    rng = random.Random(seed + 2)
    counts = Counter()
    for _ in range(deals):
        mine, theirs, _flip, trump = _deal(rng, PEAK)
        dd = DoubleDummy(trump, tricks_payoff)
        counts[int(round(dd.value(mine, theirs, a_to_move=True)))] += 1
    total = sum(counts.values())
    for tricks in sorted(counts):
        share = counts[tricks] / total
        print(f"  {tricks} tricks  {share:6.1%}  {'#' * int(share * 120)}"
              f"   (worth {round_score(tricks, tricks):+d} if bid exactly)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deals", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    value_of_the_lead(args.deals, args.seed)
    unseen_card_location(args.deals * 4, args.seed)
    bid_distribution(args.deals, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
