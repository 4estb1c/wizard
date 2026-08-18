"""Exact enumeration behind CASEBOOK.md — every number in that document is produced here.

Nothing in this file samples, apart from the hand-generation loop in Case G, which says so.
The opponent's hand is always a uniform random subset of the unseen cards, and those subsets
are small enough to enumerate exhaustively at every hand size (C(15,8) = 6435 at the peak),
so each probability below is an exact count and each expectation an exact average.

Where a number depends on how the opponent *plays* it comes from the double-dummy solver run
over every one of those hands, which makes it a statement about an opponent who can see your
cards. That cuts in different directions and is noted case by case: when the opponent is the
one who benefits from the extra sight, the number is a lower bound on how you would really do.

Run with no arguments to check every closed form in CASEBOOK.md against the enumeration.
"""
from __future__ import annotations

import random
from fractions import Fraction
from itertools import combinations
from math import comb

from engine import (DECK, DECK_SIZE, JESTERS, NO_TRUMP, NUM_RANKS, WIZARDS, card_name,
                    hand_str, is_jester, is_wizard, legal_bids, suit_of, trick_winner)
from solver import DoubleDummy, score_payoff, tricks_payoff

# Card indices, spelled out so the scenarios read like cards rather than integers.
S, H, D, C = 0, 1, 2, 3
T, J, Q, K, A = 0, 1, 2, 3, 4


def card(suit: int, rank: int) -> int:
    return suit * NUM_RANKS + rank


WZ, WZ2 = WIZARDS
JE, JE2 = JESTERS

_FAILURES: list[str] = []


def check(label: str, got, want, tol: float = 1e-9) -> None:
    """Record a comparison between the enumeration and the closed form."""
    ok = abs(float(got) - float(want)) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    print(f"       enumerated {float(got):.6f}   closed form {float(want):.6f}")
    if not ok:
        _FAILURES.append(label.strip())


def unseen_for(hand, trump_card: int) -> tuple[int, ...]:
    """Cards whose location you do not know: everything but your hand and the trump card."""
    known = set(hand) | {trump_card}
    return tuple(c for c in DECK if c not in known)


def beaters_of(lead_card: int, pool, trump: int) -> tuple[int, ...]:
    """Cards in `pool` that would take the trick from `lead_card`."""
    return tuple(c for c in pool if trick_winner(lead_card, c, trump) == 1)


def p_none_of(n_unseen: int, n_special: int, hand_size: int) -> Fraction:
    """P(a random `hand_size`-subset of `n_unseen` cards contains none of `n_special`).

    Written as one factor per card the opponent holds, so a size-3 hand is three
    multiplications rather than four binomials — the form to use at the table.
    """
    p = Fraction(1)
    for j in range(hand_size):
        p *= Fraction(n_unseen - n_special - j, n_unseen - j)
    return p


def p_all_of(n_unseen: int, n_special: int, hand_size: int) -> Fraction:
    """P(every card of a random `hand_size`-subset of `n_unseen` is one of `n_special`)."""
    p = Fraction(1)
    for j in range(hand_size):
        p *= Fraction(n_special - j, n_unseen - j)
    return p


# --------------------------------------------------------------------------- case A

def case_a_size_one() -> None:
    """Size 1 is a solved game: the dealer's bid is forced, so the non-dealer picks the duel.

    Both bids necessarily end up equal, so the round has exactly two shapes. Writing p for
    the probability the non-dealer's card takes the trick:

        both bid 0:  margin = 3 - 6p          both bid 1:  margin = 8p - 4

    which cross at p = 1/2. Maximizing your own score rather than the margin crosses at
    p = 3/7, so the two objectives genuinely disagree on a band of hands.
    """
    print("\nCASE A - size 1, non-dealer")

    forced = all(len(legal_bids(1, True, b)) == 1 for b in (0, 1))
    print(f"  ok   the dealer's bid is forced for every opponent bid: {forced}")
    if not forced:
        _FAILURES.append("size-1 dealer forced")

    rows = []
    for trump_card in DECK:
        if is_wizard(trump_card):
            continue  # dealer names trump before bidding; a separate branch
        trump = NO_TRUMP if is_jester(trump_card) else trump_card // NUM_RANKS
        for mine in DECK:
            if mine == trump_card:
                continue
            pool = unseen_for([mine], trump_card)
            losers = len(pool) - len(beaters_of(mine, pool, trump))
            rows.append((mine, trump_card, Fraction(losers, len(pool))))

    # The stated policy, checked hand by hand against the two payoff lines.
    for mine, trump_card, p in rows:
        margin_0, margin_1 = 3 - 6 * p, 8 * p - 4
        best = 1 if margin_1 > margin_0 else 0
        if p != Fraction(1, 2) and best != (1 if p > Fraction(1, 2) else 0):
            _FAILURES.append(f"threshold at {card_name(mine)}")
    print("  ok   'bid 1 iff p > 1/2' agrees with the payoff lines on all "
          f"{len(rows)} (card, trump) pairs")

    normals = [(m, tc, p) for m, tc, p in rows if m < DECK_SIZE - 4]
    mine, tcard, worst_p = min(normals, key=lambda r: r[2])
    print(f"  ok   the worst normal card is {card_name(mine)} with {card_name(tcard)} up")
    check("       worst normal card p", worst_p, Fraction(12, 22))
    print(f"  ok   12/22 = {float(Fraction(12,22)):.4f} > 1/2, so every normal card bids 1")

    # A Jester led wins only when the opponent is holding its twin - unless the twin is the
    # card flipped for trump, in which case a led Jester is a certain loser.
    twin_out = [p for m, tc, p in rows if is_jester(m) and is_jester(tc)]
    twin_live = [p for m, tc, p in rows if is_jester(m) and not is_jester(tc)]
    check("       Jester lead, twin unseen", min(twin_live), Fraction(1, 22))
    check("       Jester lead, twin is the trump card", max(twin_out), 0)
    check("       Wizard lead", min(p for m, _, p in rows if is_wizard(m)), 1)

    # Maximizing your own score rather than the margin moves the threshold to 3/7, which
    # would flip the bid at 11 or 12 beaters. No single card gets there: the most beaters a
    # normal card can face is 2 Wizards + 4 unseen trumps + 4 higher cards of its own suit.
    most = max(len(unseen_for([m], tc)) - int(p * len(unseen_for([m], tc)))
               for m, tc, p in normals)
    print(f"  ok   own-score threshold is p > 3/7 = {float(Fraction(3, 7)):.4f}, which flips "
          f"the bid at 11-12 beaters;")
    check("       most beaters any one card faces", most, 10)


# --------------------------------------------------------------------------- case B

def case_b_ace_decay() -> None:
    """How long a bare off-suit Ace survives, as a function of hand size.

    Your Ace is beaten by the two Wizards and by any trump, and with the flipped trump card
    itself a trump that is six beaters no matter how big the hand is. But the opponent draws
    more cards as the hand grows, so the Ace decays fast — and the decay is the whole story,
    since nothing about the Ace changes.
    """
    print("\nCASE B - will the Ace hold?  (A of hearts, K of spades up, spades trump)")
    mine, trump_card, trump = card(H, A), card(S, K), S

    print(f"  {'n':>2} {'unseen':>7} {'beaters':>8} {'enumerated':>11} {'closed form':>12}")
    for n in range(1, 9):
        pool = [c for c in DECK if c not in (trump_card, mine)]
        # Fill the rest of your hand with cards that cannot beat the Ace, so the beater count
        # stays fixed at six and hand size is the only thing varying down the column.
        filler = [c for c in pool if c not in beaters_of(mine, pool, trump)][:n - 1]
        unseen = unseen_for([mine] + filler, trump_card)
        beat = set(beaters_of(mine, unseen, trump))
        hits = sum(1 for opp in combinations(unseen, n) if not set(opp) & beat)
        exact = Fraction(hits, comb(len(unseen), n))
        formula = p_none_of(len(unseen), len(beat), n)
        print(f"  {n:>2} {len(unseen):>7} {len(beat):>8} {float(exact):>11.4f} "
              f"{float(formula):>12.4f}")
        if exact != formula:
            _FAILURES.append(f"ace decay n={n}")
    print("  ok   the enumeration matches the closed form at every hand size")

    # What one more beater costs, in closed form. Not a constant: the same extra beater bites
    # harder as the hand grows, which is the shrinking-pool effect seen from the other side.
    bad = [(u, n, b)
           for u in range(10, 23) for n in range(1, 9) for b in range(u - n)
           if p_none_of(u, b + 1, n) != p_none_of(u, b, n) * Fraction(u - b - n, u - b)]
    print(f"  ok   P(B+1)/P(B) == (U-B-n)/(U-B) over every (U, n, B): "
          f"{'clean' if not bad else bad[:3]}")
    if bad:
        _FAILURES.append("beater-ratio identity")


# --------------------------------------------------------------------------- case C

def case_c_specials_mirror() -> None:
    """The Wizard and the Jester are each certain in one seat and a coin flip in the other.

    A Wizard led always wins; a Wizard followed loses to a Wizard lead. A Jester followed
    always loses; a Jester led loses unless answered by the other Jester. Both exceptions
    need the same thing — the opponent holding the *other* copy — so both carry the same
    probability, n / (23 - n), and the two cards are exact mirrors of each other.
    """
    print("\nCASE C - when the specials stop being special")
    print(f"  {'n':>2} {'unseen':>7} {'P(twin opposite)':>18}")
    for n in range(1, 9):
        unseen = DECK_SIZE - 1 - n          # your n cards and the trump card are known
        shortcut = Fraction(n, unseen)
        hits = sum(1 for opp in combinations(range(unseen), n) if 0 in opp)
        if shortcut != Fraction(hits, comb(unseen, n)):
            _FAILURES.append(f"twin probability n={n}")
        print(f"  {n:>2} {unseen:>7} {float(shortcut):>18.4f}")
    print("  ok   n / (23 - n) matches the exact count at every hand size")


# --------------------------------------------------------------------------- case D

def case_d_exit_card() -> None:
    """Size 2 holding a Wizard: the second card decides the contract, and it reverses the lead.

    You bid 1 and lead; the dealer is barred from 1 and bids 0. Your Wizard is a trick you
    cannot avoid taking, so the entire round is the question of whether you can *lose* the
    other one. The answer flips depending on what your second card is, which is the point.
    """
    print("\nCASE D - the exit card  (size 2, you bid 1, they bid 0, spades trump)")
    trump_card, trump = card(S, K), S
    dd = DoubleDummy(trump, score_payoff(1, 0))

    for hand in ((WZ, JE), (WZ, card(D, T))):
        partner = hand[1]
        unseen = unseen_for(hand, trump_card)
        total = comb(len(unseen), 2)
        made = {WZ: 0, partner: 0}
        for opp in combinations(unseen, 2):
            values = dd.root_values(list(hand), list(opp), lead=None)
            for first in (WZ, partner):
                # +4 is the only branch in which you take exactly one trick.
                made[first] += abs(values[first] - 4) < 1e-9

        print(f"\n  holding {hand_str(hand)}:")
        for first in (WZ, partner):
            print(f"    lead {card_name(first):>2} first -> make the bid "
                  f"{made[first] / total:.4f}   ({made[first]}/{total})")
        print(f"    -> lead {card_name(max(made, key=made.get))}")

        n_wiz = sum(1 for c in unseen if is_wizard(c))
        n_jes = sum(1 for c in unseen if is_jester(c))

        if partner == JE:
            # Wizard first, then exit with the Jester: a led Jester loses to everything but
            # the other Jester, so you make the bid unless they are holding it.
            check("    Wz then Je == P(no Jester opposite)",
                  Fraction(made[WZ], total), p_none_of(len(unseen), n_jes, 2))
            # Jester first: a Jester answer hands you the trick you did not want, and a
            # Wizard led back on trick 2 kills your Wizard. You need them to hold neither.
            check("    Je then Wz == P(no Jester and no Wizard opposite)",
                  Fraction(made[JE], total), p_none_of(len(unseen), n_jes + n_wiz, 2))
        else:
            # Wizard first, then lead the ten: they keep whichever card ducks, so you make
            # the bid only when *both* of their cards are forced to beat it.
            beat = beaters_of(partner, unseen, trump)
            check(f"    Wz then {card_name(partner)} == P(both their cards beat it)",
                  Fraction(made[WZ], total), p_all_of(len(unseen), len(beat), 2))

            # Ten first: you need them unable to duck, and then unable to lead a Wizard back.
            # They can duck with a Jester always, or with any losing card when they are void
            # in the led suit — so "cannot duck" is: no special, and either they hold the led
            # suit (every higher card of it wins) or their whole hand is trump.
            led_suit = suit_of(partner)
            plain = [c for c in unseen if not is_wizard(c) and not is_jester(c)]
            stuck = sum(
                1 for opp in combinations(plain, 2)
                if any(suit_of(c) == led_suit for c in opp)
                or all(suit_of(c) == trump for c in opp)
            )
            check(f"    {card_name(partner)} then Wz == P(no special, and cannot duck)",
                  Fraction(made[partner], total), Fraction(stuck, total))


# --------------------------------------------------------------------------- case E

def case_e_bid_up_ratio() -> None:
    """When is one more trick worth bidding?

    Making bid b scores 2 + b, and a typical miss is by one and costs 1. So bid b is worth
    p_b (3 + b) - 1, and bidding one higher pays exactly when

        p_(b+1) / p_b  >  (b + 3) / (b + 4)

    The bar rises with b. A speculative low bid is cheap; a speculative high bid is not.
    """
    print("\nCASE E - the bid-up ratio")
    print(f"  {'b':>2} {'ratio needed':>13} {'(if a miss were free)':>23}")
    for b in range(0, 7):
        with_cost, free = Fraction(b + 3, b + 4), Fraction(b + 2, b + 3)
        print(f"  {b:>2} {float(with_cost):>13.4f} {float(free):>23.4f}")
        # The two expectations must coincide exactly at the crossing ratio.
        p_lo = Fraction(1, 2)
        if p_lo * (3 + b) - 1 != p_lo * with_cost * (4 + b) - 1:
            _FAILURES.append(f"bid-up ratio b={b}")
    print("  ok   the two expectations are equal exactly at (b+3)/(b+4)")


# --------------------------------------------------------------------------- case F

def case_f_floor_and_ceiling() -> None:
    """A Wizard is a floor under your bid; a Jester is a ceiling over it. Both are provable.

    On lead a Wizard cannot be beaten, and the winner of a trick leads the next one — so w
    Wizards plus the opening lead force w tricks, cashed back to back. Mirror image: a Jester
    played as follower always loses, and losing leaves the lead where it was, so j Jesters
    while the opponent leads shed j tricks. Any bid outside [w, n - j] is a certain miss.
    """
    print("\nCASE F - the Wizard floor and the Jester ceiling  (size 3, spades trump)")
    trump_card, trump = card(S, K), S
    rag_d, rag_c = card(D, T), card(C, T)

    # A maximizes its own tricks; the minimum over every opponent hand is what A can force.
    grab = DoubleDummy(trump, tricks_payoff)
    for label, hand, floor in (("one Wizard", (WZ, rag_d, rag_c), 1),
                               ("both Wizards", (WZ, WZ2, rag_d), 2)):
        unseen = unseen_for(hand, trump_card)
        worst = min(grab.value(list(hand), list(opp), a_to_move=True)
                    for opp in combinations(unseen, 3))
        print(f"  {label} on lead, over all {comb(len(unseen), 3)} opponent hands:")
        check(f"    fewest tricks A can be held to", worst, floor)

    # Flip the objective so A minimizes its own tricks and B tries to force them on it; the
    # maximum over opponent hands is then the most A can be made to take.
    shed = DoubleDummy(trump, lambda at, _bt: -float(at))
    for label, hand, ceiling in (("one Jester", (JE, card(S, A), card(S, K)), 2),
                                 ("both Jesters", (JE, JE2, card(S, A)), 1)):
        unseen = unseen_for(hand, trump_card)
        worst = max(-shed.value(list(hand), list(opp), a_to_move=False)
                    for opp in combinations(unseen, 3))
        print(f"  {label} while following, over all {comb(len(unseen), 3)} opponent hands:")
        check(f"    most tricks A can be forced to take", worst, ceiling)


# --------------------------------------------------------------------------- case G

def case_g_additive_estimate(trials: int = 40, seed: int = 7) -> None:
    """The additive winner count: add up P(this card wins) and call the sum your bid.

    This is the closed-form approximation you can run in your head — one hypergeometric per
    card, summed. Done naively it prices every card as though it had to win *the first*
    trick, against a full opponent hand, and that is badly pessimistic: your worst card is
    played on the last trick, when the opponent holds exactly one card and almost nothing
    can beat it.

    The fix costs nothing. Sort your hand strongest first and price the k-th card against an
    opponent hand of n - k + 1 cards. Both versions are compared here against the exact
    double-dummy mean over every opponent hand.
    """
    print(f"\nCASE G - the additive winner count  ({trials} random hands per size, "
          "each against every opponent hand)")
    rng = random.Random(seed)
    trump_card, trump = card(S, K), S
    dd = DoubleDummy(trump, tricks_payoff)

    print(f"  {'n':>2} {'exact':>7} {'flat':>7} {'staged':>7}    "
          f"{'|err| flat':>10} {'|err| staged':>12}")
    for n in (2, 3, 4, 5):
        pool = [c for c in DECK if c != trump_card]
        totals = [0.0, 0.0, 0.0]
        errors = [0.0, 0.0]
        runs = trials if n < 5 else trials // 2
        for _ in range(runs):
            hand = tuple(rng.sample(pool, n))
            unseen = unseen_for(hand, trump_card)
            width = len(unseen)
            exact = sum(dd.value(list(hand), list(opp), a_to_move=True)
                        for opp in combinations(unseen, n)) / comb(width, n)
            # Strongest card first: fewest beaters is strongest.
            beats = sorted(len(beaters_of(c, unseen, trump)) for c in hand)
            flat = float(sum(p_none_of(width, b, n) for b in beats))
            staged = float(sum(p_none_of(width, b, n - k) for k, b in enumerate(beats)))
            for i, v in enumerate((exact, flat, staged)):
                totals[i] += v
            errors[0] += abs(flat - exact)
            errors[1] += abs(staged - exact)
        print(f"  {n:>2} {totals[0] / runs:>7.3f} {totals[1] / runs:>7.3f} "
              f"{totals[2] / runs:>7.3f}    {errors[0] / runs:>10.3f} "
              f"{errors[1] / runs:>12.3f}")
        if errors[1] > errors[0]:
            _FAILURES.append(f"staged estimate no better than flat at n={n}")
    print("  ok   staging the hand beats the flat count at every size tested")


# --------------------------------------------------------------------------- main

def main() -> int:
    case_a_size_one()
    case_b_ace_decay()
    case_c_specials_mirror()
    case_d_exit_card()
    case_e_bid_up_ratio()
    case_f_floor_and_ceiling()
    case_g_additive_estimate()

    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} closed form(s) disagree with the enumeration:")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("every closed form matches the exact enumeration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
