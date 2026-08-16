"""Common-random-number round robin over the roster.

Ported from the GOPS harness (``ddx/EvolutionaryApproach/sim.py``); the variance-reduction
design is the same and the mapping is:

* **Prize deck -> deal seed.** A GOPS game is pinned by its prize order; a match here is
  pinned by a seed that generates all fourteen deals. Every pairing plays the same bank of
  seeds, so pairings stay correlated even when they are allotted different sample counts.
* **Seat swap -> mirrored match.** :func:`engine.play_match` derives each round's deal from
  ``(seed, round_index)`` alone, so calling it with the agents swapped replays the exact
  same cards with the roles reversed. Both orders of a seed are always played, which cancels
  the deal advantage rather than relying on it averaging out — and because the ladder plays
  its peak twice, the two orders are genuinely symmetric to begin with.
* **RNG streams.** Each strategy gets its own ``random.Random`` per (strategy, deal), so a
  randomizing strategy sees the identical draws whichever seat it sits in. GOPS did this by
  swapping the global ``random`` state around every call; agents here take their stream as
  ``self.rng`` instead, which gets the same guarantee without the global juggling.

The population is passed around as a list of roster *names* rather than factories, because
worker processes have to be able to pickle it. Workers rebuild the agents from
:data:`agents.ROSTER` themselves.
"""
from __future__ import annotations

import multiprocessing
import os
import sys
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents import ROSTER  # noqa: E402
from engine import LADDER, play_match  # noqa: E402

_MASK = 0xFFFFFFFF

#: Ceiling on simulation processes — each worker holds the whole roster.
MAX_WORKERS = 6


def make_seeds(count: int, seed: int) -> list[int]:
    """The bank of deal seeds, reproducible from `seed`."""
    rng = np.random.default_rng(seed)
    return [int(v) for v in rng.integers(1, _MASK, size=count)]


def stream_seed(strategy_seed: int, deal_index: int) -> int:
    """Per-(strategy, deal) RNG stream seed — identical across the two seat orders."""
    return ((strategy_seed * 1000003) ^ (deal_index * 2654435761)) & _MASK


@dataclass
class PairOutcome:
    """Aggregated result of every match played between one unordered pair."""
    i: int
    j: int
    wins_i: float      # draws counted as half, so wins_i + wins_j == games
    wins_j: float
    games: int
    margin_i: float    # mean (score_i - score_j), a finer signal than the win rate


def play_pair(factory_i, factory_j, seeds, seed_i: int, seed_j: int, *,
              first: int = 0, ladder=LADDER) -> PairOutcome:
    """Play both orders of every deal seed between two strategies.

    Args:
        seeds: The slice of the seed bank this pairing plays.
        first: Index of ``seeds[0]`` in the full bank, so a pairing given a short slice sees
            the same streams it would have seen as a prefix of a long one. That is what keeps
            common random numbers intact under an uneven allocation.
    """
    wins_i = wins_j = 0.0
    margin = 0.0
    games = 0

    for offset, deal in enumerate(seeds):
        index = first + offset
        stream_i, stream_j = stream_seed(seed_i, index), stream_seed(seed_j, index)

        for forward in (True, False):
            a, b = (factory_i(), factory_j()) if forward else (factory_j(), factory_i())
            sa, sb = (stream_i, stream_j) if forward else (stream_j, stream_i)
            a.seed(sa)
            b.seed(sb)
            result = play_match(a, b, deal, ladder=ladder)

            # Normalize back to i's point of view regardless of which seat i took.
            margin_i = result.margin if forward else -result.margin
            margin += margin_i
            wins_i += 1.0 if margin_i > 0 else 0.5 if margin_i == 0 else 0.0
            wins_j += 1.0 if margin_i < 0 else 0.5 if margin_i == 0 else 0.0
            games += 1

    return PairOutcome(0, 0, wins_i, wins_j, games, margin / games if games else 0.0)


# --------------------------------------------------------------------------- parallel driver

_WORKER: dict = {}


def _init_worker(names, seeds, strategy_seeds, ladder):
    _WORKER["names"] = names
    _WORKER["seeds"] = seeds
    _WORKER["strategy_seeds"] = strategy_seeds
    _WORKER["ladder"] = ladder


def _pair_worker(task):
    i, j, lo, hi = task
    names = _WORKER["names"]
    outcome = play_pair(
        ROSTER[names[i]], ROSTER[names[j]], _WORKER["seeds"][lo:hi],
        _WORKER["strategy_seeds"][i], _WORKER["strategy_seeds"][j],
        first=lo, ladder=_WORKER["ladder"],
    )
    outcome.i, outcome.j = i, j
    return outcome


@dataclass
class RoundRobin:
    """Raw output: fractional win counts, game counts, and mean score margins."""
    names: list[str]
    wins: np.ndarray      # wins[i, j] = fractional wins of i over j (draws = 0.5)
    counts: np.ndarray    # counts[i, j] = matches played between i and j
    margins: np.ndarray   # margins[i, j] = mean score margin of i over j
    matches: int
    generation_seed: int


def round_robin(names: list[str], *, matches_per_pair: int = 16, generation_seed: int = 0,
                workers: int | None = None, ladder=LADDER,
                deal_lo: np.ndarray | None = None,
                deal_hi: np.ndarray | None = None) -> RoundRobin:
    """Play every unordered pair, both orders of every deal, under common random numbers.

    Args:
        names: Roster keys to compete.
        matches_per_pair: Deal seeds per pairing. Each yields two matches (mirrored), so
            ``counts[i, j] == 2 * matches_per_pair``.
        generation_seed: Rotates both the seed bank and the per-strategy streams, so no
            strategy can be tuned to a fixed sample.
        deal_lo, deal_hi: Optional per-pairing slices of the seed bank, for spending more
            samples where they change the ranking (see :func:`egta.allocate_decks`).
    """
    k = len(names)
    if k < 2:
        raise ValueError("round robin needs at least two strategies")

    if deal_hi is None:
        deal_hi = np.full((k, k), matches_per_pair, dtype=int)
    if deal_lo is None:
        deal_lo = np.zeros((k, k), dtype=int)

    seeds = make_seeds(int(np.max(deal_hi)), generation_seed)
    rng = np.random.default_rng(generation_seed ^ 0xA5A5A5)
    strategy_seeds = [int(v) for v in rng.integers(1, _MASK, size=k)]

    tasks = [
        (i, j, int(deal_lo[i, j]), int(deal_hi[i, j]))
        for i in range(k) for j in range(i + 1, k)
        if deal_hi[i, j] > deal_lo[i, j]
    ]

    wins = np.zeros((k, k))
    counts = np.zeros((k, k))
    margins = np.zeros((k, k))
    if not tasks:
        return RoundRobin(list(names), wins, counts, margins, 0, generation_seed)

    if workers is None:
        workers = max(1, min(multiprocessing.cpu_count() - 2, MAX_WORKERS))

    args = (list(names), seeds, strategy_seeds, ladder)
    if workers > 1 and len(tasks) > 1:
        chunk = max(1, len(tasks) // (workers * 4))
        with multiprocessing.Pool(workers, initializer=_init_worker, initargs=args) as pool:
            outcomes = pool.map(_pair_worker, tasks, chunksize=chunk)
    else:
        _init_worker(*args)
        outcomes = [_pair_worker(t) for t in tasks]

    for out in outcomes:
        wins[out.i, out.j] = out.wins_i
        wins[out.j, out.i] = out.wins_j
        counts[out.i, out.j] = counts[out.j, out.i] = out.games
        margins[out.i, out.j] = out.margin_i
        margins[out.j, out.i] = -out.margin_i

    return RoundRobin(
        names=list(names), wins=wins, counts=counts, margins=margins,
        matches=int(np.max(deal_hi)), generation_seed=generation_seed,
    )
