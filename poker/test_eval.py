"""Verification for eval7. The five-card census is the real proof: if any hand shape were
misclassified the counts could not come out right, because they are fixed by combinatorics
and not by anything this code believes."""
import random
from itertools import combinations
from eval7 import *

EXPECTED = {          # the standard five-card census, summing to C(52,5) = 2,598,960
    STRAIGHT_FLUSH: 40, QUADS: 624, BOAT: 3744, FLUSH: 5108, STRAIGHT: 10200,
    TRIPS: 54912, TWO_PAIR: 123552, PAIR: 1098240, HIGH: 1302540,
}

def census():
    counts = {k: 0 for k in EXPECTED}
    for five in combinations(range(52), 5):
        counts[category_of(evaluate(five))] += 1
    return counts

def seven_matches_best_five(trials=25000, seed=1):
    """evaluate() on seven cards must equal the best of its twenty-one five-card subsets."""
    rng = random.Random(seed)
    bad = 0
    for _ in range(trials):
        seven = rng.sample(range(52), 7)
        if evaluate(seven) != max(evaluate(f) for f in combinations(seven, 5)):
            bad += 1
    return bad

def ordering_sanity():
    """Spot checks that no census can catch, because they are about ordering within a category."""
    cases = [
        ("A5432 wheel under 65432", hand("As 5c 4d 3h 2s"), hand("6s 5c 4d 3h 2s"), False),
        ("boat beats flush", hand("As Ac Ad Ks Kc"), hand("Ah Qh Th 8h 6h"), True),
        ("kicker decides", hand("As Ac Kd 7h 5s"), hand("Ah Ad Qc 7s 5d"), True),
        ("fifth card decides two pair", hand("As Ac Kd Kh 9s"), hand("Ah Ad Kc Ks 8d"), True),
        ("wheel SF is lowest SF", hand("5s 4s 3s 2s As"), hand("6h 5h 4h 3h 2h"), False),
        ("quads kicker", hand("9s 9c 9d 9h As"), hand("9s 9c 9d 9h Ks"), True),
    ]
    out = []
    for label, a, b, want_a_bigger in cases:
        got = evaluate(a) > evaluate(b)
        out.append((label, got == want_a_bigger))
    return out

if __name__ == "__main__":
    print("five-card census over all 2,598,960 hands:")
    got = census()
    ok = True
    for k in sorted(EXPECTED, reverse=True):
        hit = got[k] == EXPECTED[k]
        ok &= hit
        print(f"  {'ok  ' if hit else 'FAIL'} {CATEGORY_NAMES[k]:<17} {got[k]:>9,}  expected {EXPECTED[k]:>9,}")
    print(f"  total {sum(got.values()):,}")

    bad = seven_matches_best_five()
    print(f"\n{'ok  ' if not bad else 'FAIL'} seven-card = best of its 21 five-card subsets "
          f"({25000 - bad:,}/25,000 random hands)")
    ok &= not bad

    print("\nordering checks:")
    for label, hit in ordering_sanity():
        print(f"  {'ok  ' if hit else 'FAIL'} {label}")
        ok &= hit

    print("\nall checks passed" if ok else "\nFAILURES ABOVE")
