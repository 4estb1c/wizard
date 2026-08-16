"""Rank the roster: round robin, then empirical game-theoretic analysis.

    python run_tournament.py --matches 32
    python run_tournament.py --matches 64 --gap --strategies pimc-24 pimc-24-infer

The ranking column to read is ``v``, the Nash-averaged score. Net win rate is reported
alongside it precisely so the two can disagree: a strategy can post a fine net rate by
crushing the weak end of the roster while losing every match that decides anything, and
Nash averaging is what refuses to reward that.
"""
from __future__ import annotations

import argparse
import time

import numpy as np

import egta
from agents import ROSTER
from sim import round_robin


def _matrix(names, values, title, fmt="{:6.3f}", diagonal="  --  "):
    width = max(len(n) for n in names)
    head = " " * (width + 2) + " ".join(f"{n[:6]:>6}" for n in names)
    lines = [title, head]
    for i, name in enumerate(names):
        cells = []
        for j in range(len(names)):
            cells.append(diagonal if i == j else fmt.format(values[i, j]))
        lines.append(f"  {name:<{width}} " + " ".join(cells))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matches", type=int, default=24,
                        help="deal seeds per pairing; each is played mirrored (default 24)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--strategies", nargs="*", default=None,
                        help=f"subset of: {' '.join(ROSTER)}")
    parser.add_argument("--anchor", default="heuristic",
                        help="strategy the Elo scale is pinned to (default heuristic)")
    parser.add_argument("--gap", action="store_true",
                        help="also measure each strategy's double-dummy gap (slow)")
    parser.add_argument("--gap-matches", type=int, default=16)
    args = parser.parse_args()

    names = args.strategies or list(ROSTER)
    unknown = [n for n in names if n not in ROSTER]
    if unknown:
        parser.error(f"unknown strategies {unknown}; available: {sorted(ROSTER)}")

    print(f"roster: {len(names)}   matches/pair: {args.matches} x2 mirrored   "
          f"seed: {args.seed}")
    print("strategies: " + ", ".join(names))

    start = time.perf_counter()
    rr = round_robin(names, matches_per_pair=args.matches, generation_seed=args.seed,
                     workers=args.workers)
    elapsed = time.perf_counter() - start
    total = int(rr.counts[np.triu_indices(len(names), 1)].sum())
    print(f"\nplayed {total} matches in {elapsed:.1f}s "
          f"({elapsed / max(total, 1) * 1000:.0f} ms/match)")

    result = egta.evaluate(rr, anchor=args.anchor if args.anchor in names else None)

    print()
    print(_matrix(names, result.p_hat, "Win rate, row vs column"))
    print()
    print(_matrix(names, rr.margins, "Mean score margin, row vs column", fmt="{:+6.1f}"))

    order = sorted(range(len(names)), key=lambda i: -result.v[i])
    survivors = set(result.survivors)
    print("\nRanking by Nash-averaged score")
    print(f"  {'strategy':<16}{'v':>8}{'net':>8}{'vs front':>10}{'margin':>9}"
          f"{'Elo':>9}  frontier")
    for i in order:
        elo = f"{result.elo[i]:8.0f}" if i in result.elo else "       -"
        margin = np.mean([rr.margins[i, j] for j in range(len(names)) if j != i])
        print(f"  {names[i]:<16}{result.v[i]:+8.3f}{result.net_win_rate[i]:8.3f}"
              f"{result.frontier_win_rate[i]:10.3f}{margin:+9.1f}{elo}"
              f"  {'yes' if i in survivors else 'no'}")

    eliminated = [names[i] for i in range(len(names)) if i not in survivors]
    if eliminated:
        print(f"\n  dominated and eliminated: {', '.join(eliminated)}")
    support = ", ".join(f"{names[i]} {result.nash.p_star[i]:.2f}"
                        for i in result.nash.support)
    print(f"  Nash mixture: {support}")
    if not result.nash.max_entropy:
        print("  (equilibrium is an arbitrary LP vertex, not the max-entropy one)")

    if args.gap:
        from oracle import double_dummy_gap
        # ASCII only: the default Windows console codepage mangles em-dashes.
        print("\nDouble-dummy gap - margin conceded to a perfect-information opponent")
        print("  (a ceiling on exploitation, not Nash exploitability; lower is better)")
        rows = []
        for name in names:
            outcome = double_dummy_gap(ROSTER[name], matches=args.gap_matches,
                                       seed=args.seed)
            rows.append((outcome["margin"], name, outcome))
        for margin, name, outcome in sorted(rows):
            print(f"  {name:<16}{margin:+8.1f} pts/match   "
                  f"oracle win rate {outcome['win_rate']:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
