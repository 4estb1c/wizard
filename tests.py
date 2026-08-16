"""Validation suite. Run with ``python tests.py``.

Two kinds of test live here. The first kind checks the engine against results derived by
hand away from the code, which is the only way to catch a rule that is implemented
self-consistently but wrong. The second checks the optimized solver against a deliberately
naive one, because alpha-beta with a transposition table is exactly the sort of code that is
correct on most positions and silently wrong on a few.

The deck carries two of each special, which is what makes the first section interesting: the
Wizard and Jester are no longer unconditional, and the tests pin down exactly which half of
each one survives.
"""
from __future__ import annotations

import random
import sys

from agents import ROSTER
from agents.base import count_specials
from engine import (DECK, DECK_SIZE, JESTERS, LADDER, NO_TRUMP, NUM_NORMAL, NUM_RANKS,
                    PEAK, WIZARDS, card_name, is_jester, is_wizard, legal_bids,
                    legal_plays, play_match, round_score, trick_winner)
from solver import DoubleDummy, legal_mask, tricks_payoff

C10 = 3 * NUM_RANKS + 0   # the ten of clubs — weakest normal card in the deck
DIAMONDS = 2
TRUMPS = (NO_TRUMP, 0, 1, 2, 3)

_failures: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        print(f"  pass  {label}")
    else:
        print(f"  FAIL  {label}   {detail}")
        _failures.append(label)


# --------------------------------------------------------------------------- the specials

def test_specials_are_conditional():
    """Two of each special makes both cards position-dependent, in mirrored ways."""
    wizard, other_wizard = WIZARDS
    jester, other_jester = JESTERS

    check(all(trick_winner(wizard, x, t) == 0
              for x in DECK if x != wizard for t in TRUMPS),
          "a Wizard LED always wins — the first Wizard played takes the trick")

    beaten = [x for x in DECK if x != wizard
              and any(trick_winner(x, wizard, t) == 0 for t in TRUMPS)]
    check(beaten == [other_wizard],
          "a Wizard FOLLOWED wins against everything except the other Wizard",
          f"also lost to {[card_name(c) for c in beaten]}")

    check(all(trick_winner(x, jester, t) == 0
              for x in DECK if x != jester for t in TRUMPS),
          "a Jester FOLLOWED always loses")

    survives = [x for x in DECK if x != jester
                and any(trick_winner(jester, x, t) == 0 for t in TRUMPS)]
    check(survives == [other_jester],
          "a Jester LED loses to everything except the other Jester",
          f"also won against {[card_name(c) for c in survives]}")


def test_specials_always_legal():
    """Wizards and Jesters are exempt from following suit, so they are never excluded."""
    hand = [0, 1, WIZARDS[0], JESTERS[0]]  # two spades plus one of each special
    legal = legal_plays(hand, lead_card=2)  # a spade led, so spades must be followed
    check(WIZARDS[0] in legal and JESTERS[0] in legal,
          "specials stay legal when holding the led suit")
    check(set(legal) == {0, 1, WIZARDS[0], JESTERS[0]},
          "off-suit normal cards are excluded when the led suit is held")
    check(set(legal_plays(hand, JESTERS[0])) == set(hand),
          "a Jester lead establishes no suit, so the follower is unconstrained")
    check(set(legal_plays(hand, WIZARDS[0])) == set(hand),
          "a Wizard lead establishes no suit either")


# --------------------------------------------------------------------------- round 1, exact

def _trump_of(flip: int) -> int:
    if is_jester(flip):
        return NO_TRUMP
    return flip // NUM_RANKS if flip < NUM_NORMAL else 0


def _lead_win_probability(card: int, flip: int) -> float:
    trump = _trump_of(flip)
    unseen = [c for c in DECK if c not in (card, flip)]
    return sum(1 for x in unseen if trick_winner(card, x, trump) == 0) / len(unseen)


def _follow_win_probability(card: int, flip: int) -> float:
    trump = _trump_of(flip)
    unseen = [c for c in DECK if c not in (card, flip)]
    return sum(1 for x in unseen if trick_winner(x, card, trump) == 1) / len(unseen)


def test_lowest_card_positional_value():
    """The weakest normal card is still a favourite on lead and nearly dead as a follower."""
    flip = DIAMONDS * NUM_RANKS + 1
    lead = _lead_win_probability(C10, flip)
    follow = _follow_win_probability(C10, flip)
    check(abs(lead - 12 / 22) < 1e-12,
          f"{card_name(C10)} led wins exactly 12/22", f"got {lead:.4f}")
    check(abs(follow - 2 / 22) < 1e-12,
          f"{card_name(C10)} as follower wins exactly 2/22 (only against a Jester lead)",
          f"got {follow:.4f}")


def test_round_one_is_solved():
    """Round 1 as non-dealer: bid 1 with everything except a Jester.

    The hook forces the dealer to copy the bid, so the round is a choice of polarity.
    Bidding 1 is worth ``8p - 4`` and bidding 0 is worth ``3 - 6p``, crossing at exactly
    p = 1/2 — the made-bid bonus cancels. Every normal card clears that bar, though by less
    than it did on the old 18-card deck.
    """
    worst, worst_case, exceptions = 1.0, None, []
    for flip in DECK:
        if is_wizard(flip):
            continue  # dealer names trump: a tell, not a fixed suit
        for card in DECK:
            if card == flip:
                continue
            p = _lead_win_probability(card, flip)
            if is_jester(card):
                if p > 2 / 22 + 1e-12:
                    exceptions.append((card, flip, p))
                continue
            if not (8 * p - 4 > 3 - 6 * p):
                exceptions.append((card, flip, p))
            if p < worst:
                worst, worst_case = p, (card, flip)

    check(not exceptions, "non-dealer prefers bid 1 with every card but a Jester",
          f"{len(exceptions)} exceptions")
    check(abs(worst - 12 / 22) < 1e-12,
          f"the worst round-1 lead still wins 12/22 "
          f"({card_name(worst_case[0])}, trump {card_name(worst_case[1])})",
          f"got {worst:.4f}")


# --------------------------------------------------------------------------- solver

def _brute_force(a, b, trump, a_to_move, lead, at, bt):
    """Plain minimax: no pruning, no table, no move ordering. Slow and obviously right."""
    if not a and not b:
        return float(at)
    hand = a if a_to_move else b
    mask = sum(1 << x for x in hand)
    options = [c for c in hand if legal_mask(mask, lead) >> c & 1]
    results = []
    for card in options:
        rest = tuple(c for c in hand if c != card)
        if lead is None:
            if a_to_move:
                results.append(_brute_force(rest, b, trump, False, card, at, bt))
            else:
                results.append(_brute_force(a, rest, trump, True, card, at, bt))
        else:
            won = trick_winner(lead, card, trump) == 1
            if a_to_move:
                results.append(_brute_force(rest, b, trump, won, None,
                                            at + won, bt + (not won)))
            else:
                results.append(_brute_force(a, rest, trump, not won, None,
                                            at + (not won), bt + won))
    return max(results) if a_to_move else min(results)


def test_solver_matches_brute_force():
    """Alpha-beta plus a bounded transposition table must agree with naive minimax."""
    rng = random.Random(20240815)
    mismatches = trials = 0
    for size in (2, 3, 4):
        for _ in range(30):
            cards = list(DECK)
            rng.shuffle(cards)
            a, b, flip = cards[:size], cards[size:2 * size], cards[2 * size]
            trump = _trump_of(flip)
            for leads in (True, False):
                fast = DoubleDummy(trump, tricks_payoff).value(a, b, a_to_move=leads)
                slow = _brute_force(tuple(a), tuple(b), trump, leads, None, 0, 0)
                trials += 1
                mismatches += abs(fast - slow) > 1e-9
    check(mismatches == 0,
          f"solver agrees with brute force on {trials} positions (sizes 2-4)",
          f"{mismatches} mismatches")


def test_only_pairs_are_guaranteed():
    """Holding both copies restores certainty; holding one does not.

    A lone Wizard can be met by the other Wizard on lead, and a lone Jester can be met by
    the other Jester. Holding the pair removes the only card that could answer it, which is
    why :func:`agents.base.hard_bid_bounds` only tightens at two of a kind.
    """
    rng = random.Random(11)
    plain = [c for c in DECK if c < NUM_NORMAL]
    pair_floor = pair_ceiling = True
    for _ in range(30):
        rng.shuffle(plain)
        dd = DoubleDummy(0, tricks_payoff)
        # Both Wizards, defending: the opponent cannot have a Wizard to lead.
        if dd.value(list(WIZARDS) + plain[:3], plain[3:8], a_to_move=False) < 2:
            pair_floor = False
        # Both Jesters, on lead: neither can meet a Jester, so both must lose.
        if dd.value(list(JESTERS) + plain[8:11], plain[11:16], a_to_move=True) > 3:
            pair_ceiling = False
    check(pair_floor, "both Wizards guarantee at least 2 tricks, even on defence")
    check(pair_ceiling, "both Jesters guarantee at least 2 tricks lost, even on lead")

    check(count_specials(list(WIZARDS) + [0, 1]) == (2, 0), "count_specials counts Wizards")
    check(count_specials(list(JESTERS) + [WIZARDS[0]]) == (1, 2),
          "count_specials counts Jesters")


# --------------------------------------------------------------------------- match rules

def test_ladder_deal_balance():
    """Playing the peak twice makes strict alternation exactly fair."""
    dealt = ({}, {})
    for index, size in enumerate(LADDER):
        dealt[index % 2][size] = dealt[index % 2].get(size, 0) + 1
    check(len(LADDER) == 2 * PEAK and sum(LADDER) == PEAK * (PEAK + 1),
          f"{2 * PEAK} rounds, {PEAK * (PEAK + 1)} tricks")
    check(dealt[0] == dealt[1] == {s: 1 for s in range(1, PEAK + 1)},
          "each player deals each hand size exactly once",
          f"{dealt[0]} vs {dealt[1]}")
    check(2 * PEAK < DECK_SIZE,
          f"the peak leaves {DECK_SIZE - 2 * PEAK - 1} cards dead behind the trump flip")


def test_hook_and_duel_property():
    """The hook holds, and it forces at most one player to make their bid each round."""
    both_made = hook_violations = rounds = 0
    for seed in range(10):
        a, b = ROSTER["heuristic"](), ROSTER["pimc-8"]()
        a.seed(seed * 2 + 1)
        b.seed(seed * 2 + 2)
        for result in play_match(a, b, seed).rounds:
            rounds += 1
            hook_violations += sum(result.bids) == result.hand_size
            both_made += (result.tricks[0] == result.bids[0]
                          and result.tricks[1] == result.bids[1])
    check(hook_violations == 0, f"bids never total the hand size across {rounds} rounds",
          f"{hook_violations} violations")
    check(both_made == 0, "at most one player makes their bid in any round",
          f"{both_made} rounds where both did")


def test_scoring():
    check(round_score(0, 0) == 2 and round_score(PEAK, PEAK) == 2 + PEAK,
          "a made bid pays 2 + tricks")
    check(round_score(3, 5) == -2 and round_score(4, 0) == -4,
          "a missed bid costs the size of the miss")


def test_mirrored_matches_use_identical_deals():
    """Seat-swapping a pairing must replay the same cards, or the pairing is not paired."""
    a, b = ROSTER["heuristic"](), ROSTER["random"]()
    a.seed(1)
    b.seed(2)
    forward = play_match(a, b, 4242)
    c, d = ROSTER["random"](), ROSTER["heuristic"]()
    c.seed(2)
    d.seed(1)
    reverse = play_match(c, d, 4242)
    check(all(sorted(f.hands_dealt) == sorted(r.hands_dealt) and f.trump_card == r.trump_card
              for f, r in zip(forward.rounds, reverse.rounds)),
          "mirrored match deals the identical cards to the swapped seats")


def test_bots_respect_the_hard_bounds():
    """A searching bot should never bid an impossible number when a possible one is legal.

    The caveat is a real property of the rules, not a hedge: the hook removes one bid from
    the dealer, and in the smallest rounds it can remove the only one the special-card bounds
    leave.
    """
    violations = forced = checked = 0
    for seed in range(6):
        a, b = ROSTER["pimc-24"](), ROSTER["pimc-8"]()
        a.seed(seed + 100)
        b.seed(seed + 200)
        for result in play_match(a, b, seed + 900).rounds:
            size = result.hand_size
            for seat in (0, 1):
                wizards, jesters = count_specials(result.hands_dealt[seat])
                low = 2 if wizards == 2 else 0
                high = size - (2 if jesters == 2 else 0)
                legal = legal_bids(size, seat == result.dealer, result.bids[1 - seat])
                checked += 1
                if not [x for x in legal if low <= x <= high]:
                    forced += 1
                elif not low <= result.bids[seat] <= high:
                    violations += 1
    check(violations == 0,
          f"PIMC never bids an impossible number when a possible one exists "
          f"({checked} bids checked)", f"{violations} violations")
    print(f"        (the hook forced an impossible bid {forced} times in {checked})")


def main() -> int:
    for test in (
        test_specials_are_conditional,
        test_specials_always_legal,
        test_lowest_card_positional_value,
        test_round_one_is_solved,
        test_solver_matches_brute_force,
        test_only_pairs_are_guaranteed,
        test_ladder_deal_balance,
        test_hook_and_duel_property,
        test_scoring,
        test_mirrored_matches_use_identical_deals,
        test_bots_respect_the_hard_bounds,
    ):
        print(f"\n{test.__name__}")
        test()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
