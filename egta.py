"""Empirical game-theoretic analysis: payoff matrix, dominance, Nash averaging, Bradley-Terry.

Taken unchanged from the GOPS strategy-search project (``ddx/EvolutionaryApproach/egta.py``).
Nothing in here knows what game produced the numbers — it consumes a win-count matrix and a
game-count matrix and returns a ranking — so it ports to Up the River verbatim. Kept byte-for
-byte identical to its source so improvements can be moved between the two projects freely.

This module replaces Elo as the evaluation stage. The pipeline is:

    round robin  ->  payoff_matrix (3.1)  ->  iterated_dominance (3.2)
                 ->  nash_average (3.3)   ->  bradley_terry on S x S (3.4)

Three properties are worth stating up front because they drive every design choice here:

* ``M`` is **exactly** antisymmetric. Beta smoothing preserves this — ``(w+0.5)/(n+1)`` and
  ``(n-w+0.5)/(n+1)`` sum to exactly 1 — so the game value is exactly 0 and the Nash
  polytope is ``{p >= 0 : 1'p = 1, Mp <= 0}``. Every solver below relies on that.
* The reported per-strategy score is ``v = M @ p*``, never ``p*`` itself. ``p*`` is a
  distribution and splits its mass across near-duplicates; ``v`` is a payoff and gives each
  duplicate the full score. That invariance-to-redundancy is the whole point.
* The Bradley–Terry fit in 3.4 is restricted to the dominance survivors, so a strategy
  cannot buy rank by beating strategies that were already eliminated.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linprog, minimize

ELO_SCALE = 400.0 / math.log(10.0)


# --------------------------------------------------------------------------- 3.1

def payoff_matrix(wins: np.ndarray, counts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Beta-smoothed win probabilities and the antisymmetric payoff matrix.

    ``P_hat[i,j] = (w[i,j] + 0.5) / (n[i,j] + 1)`` — the smoothing is applied before any
    log transform so an undefeated strategy yields a finite estimate rather than an
    infinite one. ``M = P_hat - 0.5``.

    Self-play is defined as 0.5 (a symmetric game against yourself), not simulated.

    Returns:
        ``(P_hat, M)``, both ``k x k``. ``M`` is symmetrized to kill float asymmetry, and
        ``P_hat`` is rebuilt from it so the two never disagree.
    """
    counts = np.asarray(counts, dtype=float)
    wins = np.asarray(wins, dtype=float)
    p = (wins + 0.5) / (counts + 1.0)
    np.fill_diagonal(p, 0.5)

    m = p - 0.5
    m = 0.5 * (m - m.T)
    np.fill_diagonal(m, 0.0)
    return m + 0.5, m


# --------------------------------------------------------------------------- 3.2

def iterated_dominance(m: np.ndarray, tol: float = 0.0) -> list[int]:
    """Iterated elimination of dominated strategies; returns the survivor set ``S``.

    Removes ``i`` whenever some surviving ``j`` satisfies ``M[j,k] >= M[i,k]`` for every
    surviving ``k``, strictly for at least one. Repeats to a fixed point.

    Columns are restricted to the *current* survivors each pass — that is what makes the
    elimination iterated rather than a single sweep, and it is why a strategy that only
    looked competitive against already-eliminated junk eventually falls out too.

    Args:
        m: Antisymmetric payoff matrix.
        tol: Slack on the "at least as good against every opponent" side only: ``j`` may be
            worse than ``i`` by up to ``tol`` on any single column and still dominate. The
            strictness requirement stays exact, so raising ``tol`` monotonically eliminates
            more — if the slack applied to both sides they would cancel and the knob would
            do nothing. ``0.0`` is the literal spec: exact domination only. Set it to a
            fraction of an entry's standard error when games-per-pair is low.

    Returns:
        Sorted indices of the survivors.
    """
    alive = list(range(m.shape[0]))
    removed = True
    while removed and len(alive) > 1:
        removed = False
        for i in alive:
            for j in alive:
                if i == j:
                    continue
                diff = m[j, alive] - m[i, alive]
                if np.all(diff >= -tol) and np.any(diff > 1e-12):
                    alive.remove(i)
                    removed = True
                    break
            if removed:
                break
    return sorted(alive)


# --------------------------------------------------------------------------- 3.3

@dataclass
class NashResult:
    """Output of Nash averaging."""
    p_star: np.ndarray       # the max-entropy Nash mixture — mixture composition, NOT a score
    v: np.ndarray            # v[i] = (M @ p_star)[i] — the per-strategy score
    value: float             # game value; ~0 for an antisymmetric M
    support: list[int]       # indices with positive mass in p_star
    max_entropy: bool        # False if the entropy refinement fell back to the raw LP vertex


def _maximin_lp(m: np.ndarray) -> tuple[np.ndarray, float]:
    """Solve ``max_p min_j (M^T p)_j`` by linear program. Returns ``(p, value)``."""
    k = m.shape[0]
    # Variables [p (k), t]. Our payoff against pure column j is (M^T p)_j = -(M p)_j,
    # so requiring it to be >= t is the constraint (M p)_j + t <= 0.
    c = np.zeros(k + 1)
    c[-1] = -1.0
    a_ub = np.hstack([m, np.ones((k, 1))])
    b_ub = np.zeros(k)
    a_eq = np.zeros((1, k + 1))
    a_eq[0, :k] = 1.0
    bounds = [(0.0, 1.0)] * k + [(None, None)]

    res = linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=[1.0], bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"maximin LP failed: {res.message}")
    p = np.clip(res.x[:k], 0.0, None)
    p = p / p.sum()
    return p, float(res.x[k])


def _essential_support(
    m: np.ndarray, value: float, feas_tol: float, support_tol: float
) -> tuple[list[int], float]:
    """Indices that can carry positive mass in *some* Nash equilibrium, plus its width.

    Two LPs per candidate: maximize and minimize ``p_i`` over the Nash polytope. The
    maxima give the essential support — the set the max-entropy equilibrium has full
    support on — so the entropy program below runs over a handful of variables instead of
    the whole population. The spread ``max p_i - min p_i`` gives the polytope's width: when
    it is zero the equilibrium is unique and there is nothing for entropy to choose
    between, which is the common case and worth detecting rather than solving.

    ``support_tol`` must sit well above ``feas_tol``: the slack in the Nash constraints
    lets a strategy that belongs to *no* equilibrium reach a mass on the order of
    ``feas_tol / min|M|``, and admitting those makes the entropy program hand back an
    infeasible point.
    """
    k = m.shape[0]
    a_ub = m
    b_ub = np.full(k, -value + feas_tol)
    a_eq = np.ones((1, k))
    bounds = [(0.0, 1.0)] * k

    def solve(objective):
        return linprog(objective, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=[1.0],
                       bounds=bounds, method="highs")

    support, width = [], 0.0
    for i in range(k):
        c = np.zeros(k)
        c[i] = -1.0
        hi = solve(c)
        if not (hi.success and -hi.fun > support_tol):
            continue
        support.append(i)
        lo = solve(-c)
        if lo.success:
            width = max(width, -hi.fun - lo.fun)
    return support, width


def _max_entropy_on_support(
    m: np.ndarray, support: list[int], value: float, feas_tol: float, warm: np.ndarray
) -> np.ndarray | None:
    """Maximize entropy over the Nash polytope, restricted to `support`.

    The Nash set is a polytope, so multiple equilibria are the norm and an LP returns an
    arbitrary vertex of it — which makes ``p*`` (and any diagnostic keyed on its support)
    jump between runs. Maximizing entropy picks a unique interior point, which is what
    makes the reported mixture deterministic.
    """
    idx = np.array(support, dtype=int)
    # Columns, not rows: with p supported on `idx`, (M p)_j = sum_i M[j, i] q_i, so the
    # Nash constraint M p <= -value is `sub @ q <= -value`. Taking rows here would encode
    # M^T p >= -value, which is the same constraint with its sign flipped.
    sub = m[:, idx]  # k x |support|

    def neg_entropy(q):
        qc = np.clip(q, 1e-15, None)
        return float(np.sum(qc * np.log(qc)))

    def neg_entropy_grad(q):
        qc = np.clip(q, 1e-15, None)
        return 1.0 + np.log(qc)

    constraints = [
        {"type": "eq", "fun": lambda q: np.sum(q) - 1.0, "jac": lambda q: np.ones_like(q)},
        {
            "type": "ineq",
            "fun": lambda q: (-value + feas_tol) - sub @ q,
            "jac": lambda q: -sub,
        },
    ]
    uniform = np.full(len(idx), 1.0 / len(idx))
    x0 = 0.5 * uniform + 0.5 * np.clip(warm[idx], 0.0, None)
    x0 = x0 / x0.sum() if x0.sum() > 0 else uniform

    res = minimize(neg_entropy, x0, jac=neg_entropy_grad, method="SLSQP",
                   constraints=constraints, bounds=[(1e-12, 1.0)] * len(idx),
                   options={"maxiter": 500, "ftol": 1e-12})
    q = np.clip(res.x, 0.0, None)
    if not res.success or q.sum() <= 0:
        return None

    full = np.zeros(m.shape[0])
    full[idx] = q / q.sum()
    # SLSQP can report success at a point that violates the constraints, so verify the
    # result really is an equilibrium before accepting it.
    if float(np.max(m @ full)) > -value + 1e-6:
        return None
    return full


def nash_average(
    m: np.ndarray,
    *,
    feas_tol: float = 1e-9,
    support_tol: float = 1e-6,
    max_support_lps: int = 400,
) -> NashResult:
    """Nash-average the payoff matrix: max-entropy equilibrium and per-strategy scores.

    Args:
        m: Antisymmetric payoff matrix over the full population.
        feas_tol: Slack when re-expressing the Nash constraints for the support and entropy
            programs. Without it, a vertex that is feasible only to LP tolerance can make
            the entropy program infeasible.
        support_tol: Minimum equilibrium mass for a strategy to count as being in the
            essential support. Keep it several orders of magnitude above ``feas_tol``.
        max_support_lps: Above this population size, skip the per-strategy support LPs and
            take the support of the LP solution instead. The mixture is then an arbitrary
            equilibrium rather than the max-entropy one; ``max_entropy`` reports which.

    Returns:
        A :class:`NashResult`. Score strategies by ``v``; ``p_star`` is mixture composition
        and must never be presented as a per-strategy score.
    """
    p_lp, value = _maximin_lp(m)

    if m.shape[0] <= max_support_lps:
        support, width = _essential_support(m, value, feas_tol, support_tol)
    else:
        support, width = [i for i in range(m.shape[0]) if p_lp[i] > support_tol], float("inf")

    p_star, max_ent = None, True
    if support and width <= support_tol:
        # The Nash set is a single point, so the LP answer is already the unique — and
        # therefore the maximum-entropy — equilibrium. No program to solve.
        p_star = np.zeros(m.shape[0])
        p_star[support] = p_lp[support]
        p_star = p_star / p_star.sum()
    elif support:
        p_star = _max_entropy_on_support(m, support, value, feas_tol, p_lp)
    if p_star is None:
        p_star, max_ent = p_lp, False

    v = m @ p_star
    return NashResult(
        p_star=p_star,
        v=v,
        value=value,
        support=[i for i in range(len(p_star)) if p_star[i] > support_tol],
        max_entropy=max_ent,
    )


def allocate_decks(
    p: np.ndarray, total: int, *, floor: int = 8, blend: float = 0.25,
    cap: int | None = None
) -> np.ndarray:
    """Deck counts per pairing that minimise the variance of ``v`` at a fixed budget.

    The reported score is ``v_i = sum_j M[i,j] p_j``, so a pairing ``{i,j}`` only enters
    the score through ``p_i`` and ``p_j``. Writing the per-entry sampling variance as
    ``sigma^2 / n_ij``, the total variance of ``v`` is ``sum_{i<j} (p_i^2 + p_j^2) /
    n_ij`` up to a constant, and minimising that subject to ``sum n_ij = total`` gives

        n_ij  proportional to  sqrt(p_i^2 + p_j^2).

    Since the equilibrium is typically supported on a handful of strategies, the great
    majority of pairings cannot move any score at all and need only the ``floor`` that
    keeps the §3.2 dominance filter and the next round's mixture estimate honest. The
    budget freed that way goes to the pairings that do move it.

    Args:
        p: Equilibrium mixture over the population (the bagged mixture, in practice).
        total: Total decks to distribute over all unordered pairs.
        floor: Minimum decks per pairing. This is what pays for the dominance filter, the
            net-win-rate column, and the estimate of ``p`` itself on the next pass, none of
            which are covered by the objective above.
        blend: Floor on the *relative* share a pairing receives, as a fraction of the
            busiest pairing's share. The variance objective above is indifferent to
            everything outside the equilibrium support, but §3.2, the net-win-rate column,
            and the next generation's estimate of ``p`` are not — and when the equilibrium
            concentrates on one strategy, which happens the moment something beats the
            whole population, the pure rule drives every other pairing to ``floor``.
            Blending in weight space rather than mixing ``p`` toward uniform is what makes
            the guarantee hold at any support size: at ``blend=0.25`` no pairing is sampled
            less than a quarter as often as the busiest one, whether the support has two
            members or twenty. ``0.0`` recovers the pure variance-minimising split.
        cap: Optional per-pairing ceiling.

    Returns:
        A symmetric ``k x k`` integer matrix with a zero diagonal.
    """
    p = np.clip(np.asarray(p, dtype=float), 0.0, None)
    k = len(p)
    if p.sum() > 0:
        p = p / p.sum()
    weight = np.sqrt(p[:, None] ** 2 + p[None, :] ** 2)
    np.fill_diagonal(weight, 0.0)

    peak = weight.max()
    if peak > 0 and blend > 0:
        weight = blend * peak + (1.0 - blend) * weight
    np.fill_diagonal(weight, 0.0)

    pairs = k * (k - 1) // 2
    if weight.sum() <= 0 or total <= pairs * floor:
        alloc = np.full((k, k), floor, dtype=int)
        np.fill_diagonal(alloc, 0)
        return alloc

    # Bisect the scale so the floors and the ceiling are both respected exactly.
    ceiling = cap if cap is not None else total
    lo, hi = 0.0, float(total)
    for _ in range(60):
        scale = 0.5 * (lo + hi)
        alloc = np.clip(np.rint(scale * weight), floor, ceiling)
        np.fill_diagonal(alloc, 0)
        if alloc[np.triu_indices(k, 1)].sum() > total:
            hi = scale
        else:
            lo = scale
    alloc = np.clip(np.rint(lo * weight), floor, ceiling).astype(int)
    np.fill_diagonal(alloc, 0)
    return alloc


def bagged_mixture(
    wins: np.ndarray, counts: np.ndarray, *, trials: int = 40, seed: int = 0
) -> np.ndarray:
    """Equilibrium mixture averaged over bootstrap resamples of the win counts.

    The map from payoff matrix to equilibrium is discontinuous: the support changes
    identity at the boundaries between equilibrium regions, so a point estimate inherits
    every wobble of the underlying counts and ``v = M @ p*`` inherits it too. Each trial
    redraws every pairing as ``Binomial(n_ij, P_hat[i,j])`` with antisymmetry imposed by
    construction, re-solves the maximin LP, and the mixtures are averaged.

    The average of equilibria of nearby games is not itself an equilibrium of any one of
    them, and is not claimed to be. It is an estimator of the mixture the population would
    produce with unlimited simulation, and it measurably beats the point estimate at that
    job — which is the only property ``v`` needs from it. The entropy refinement is skipped
    inside the loop because averaging already selects an interior point, and running it per
    trial costs 40x for no measurable accuracy.
    """
    rng = np.random.default_rng(seed)
    p_hat, _ = payoff_matrix(wins, counts)
    k = p_hat.shape[0]
    upper = np.triu_indices(k, 1)
    n_upper = np.rint(counts[upper]).astype(int)
    p_upper = np.clip(p_hat[upper], 0.0, 1.0)

    total = np.zeros(k)
    for _ in range(max(1, trials)):
        drawn = rng.binomial(np.maximum(n_upper, 0), p_upper)
        w = np.zeros((k, k))
        w[upper] = drawn
        w.T[upper] = n_upper - drawn
        _, m_b = payoff_matrix(w, counts)
        p, _ = _maximin_lp(m_b)
        total += p
    return total / max(1, trials)


# --------------------------------------------------------------------------- 3.4

def smoothed_counts(
    wins: np.ndarray, counts: np.ndarray, indices: list[int]
) -> tuple[np.ndarray, np.ndarray]:
    """Beta-smoothed win and game counts restricted to `indices`, diagonals zeroed."""
    idx = np.array(indices, dtype=int)
    w = wins[np.ix_(idx, idx)] + 0.5
    n = counts[np.ix_(idx, idx)] + 1.0
    np.fill_diagonal(w, 0.0)
    np.fill_diagonal(n, 0.0)
    return w, n


def bradley_terry(
    w: np.ndarray, n: np.ndarray, *, max_iter: int = 10_000, tol: float = 1e-12
) -> np.ndarray:
    """Batch maximum-likelihood Bradley–Terry strengths by minorization-maximization.

    Iterates ``s_i <- W_i / sum_j n[i,j] / (s_i + s_j)`` to convergence — the stationarity
    condition that actual wins equal expected wins for every player. This is the batch fit,
    not the online Elo update: the full matrix is available, so there is no reason to use a
    stochastic approximation whose answer depends on the order matches were played.

    Args:
        w: Smoothed win counts, diagonal zero.
        n: Smoothed game counts, diagonal zero.

    Returns:
        Strengths normalized so mean log-strength is zero.
    """
    m = w.shape[0]
    strengths = np.ones(m)
    wins_total = w.sum(axis=1)

    for _ in range(max_iter):
        denom = np.zeros(m)
        for i in range(m):
            pair = strengths[i] + strengths
            denom[i] = np.sum(n[i] / np.where(pair > 0, pair, 1.0))
        new = np.where(denom > 0, wins_total / np.where(denom > 0, denom, 1.0), strengths)
        new = np.clip(new, 1e-12, 1e12)
        new = new / math.exp(float(np.mean(np.log(new))))
        if np.max(np.abs(np.log(new) - np.log(strengths))) < tol:
            strengths = new
            break
        strengths = new
    return strengths


def provisional_strength(
    wins: np.ndarray,
    counts: np.ndarray,
    target: int,
    indices: list[int],
    strengths: np.ndarray,
    *,
    max_iter: int = 500,
    tol: float = 1e-12,
) -> float:
    """Rate `target` against a frozen pool without letting it influence the pool's ratings.

    Used only for the anchor. If the permanent GTO seed does not survive the dominance
    filter it cannot be fitted jointly — adding it back to the matrix would reintroduce
    exactly the farmable opponent §3.2 removed. Instead its rating is the one-dimensional
    MLE against fixed survivor strengths, which keeps the reported scale anchored across
    generations without contaminating the ranking.
    """
    idx = np.array(indices, dtype=int)
    w = float(np.sum(wins[target, idx] + 0.5))
    n = counts[target, idx] + 1.0

    s = 1.0
    for _ in range(max_iter):
        denom = float(np.sum(n / (s + strengths)))
        new = w / denom if denom > 0 else s
        new = min(max(new, 1e-12), 1e12)
        if abs(math.log(new) - math.log(s)) < tol:
            return new
        s = new
    return s


def to_elo(strengths: np.ndarray, anchor: float = 1.0) -> np.ndarray:
    """Convert strengths to Elo points, anchored so ``anchor`` maps to 1500."""
    return 1500.0 + ELO_SCALE * (np.log(np.clip(strengths, 1e-12, None)) - math.log(anchor))


# --------------------------------------------------------------------------- orchestration

@dataclass
class EGTAResult:
    """Everything §3.1–§3.4 produces for one population snapshot."""
    names: list[str]
    p_hat: np.ndarray
    m: np.ndarray
    survivors: list[int]
    nash: NashResult
    ratings: dict[int, float] = field(default_factory=dict)      # index -> BT strength, S only
    elo: dict[int, float] = field(default_factory=dict)          # index -> anchored Elo, S only
    anchor_name: str | None = None
    anchor_in_frontier: bool = True
    net_win_rate: np.ndarray = None
    frontier_win_rate: np.ndarray = None
    v: np.ndarray = None            # the reported score: bagged when bagging is on
    p_bagged: np.ndarray = None     # bagged mixture, or None when bagging is off

    @property
    def survivor_names(self) -> list[str]:
        return [self.names[i] for i in self.survivors]

    @property
    def bagged(self) -> bool:
        return self.p_bagged is not None


def evaluate(
    rr,
    *,
    anchor: str | None = None,
    dominance_tol: float = 0.0,
    bag_trials: int = 40,
    bag_seed: int = 0,
) -> EGTAResult:
    """Run §3.1–§3.4 over a completed round robin.

    Args:
        rr: A :class:`sim.RoundRobin`.
        anchor: Name of the permanent baseline the Elo scale is pinned to (the ``GTO``
            seed). ``None`` leaves the scale at mean-log-strength zero, which is *not*
            comparable across generations.
        dominance_tol: Passed to :func:`iterated_dominance`.
        bag_trials: Bootstrap resamples behind the reported score (see
            :func:`bagged_mixture`). ``0`` reports the point equilibrium's ``v`` instead,
            which is the literal §3.3 definition and a measurably noisier estimate of it.
        bag_seed: Seed for those resamples, so the reported score is reproducible.

    Returns:
        An :class:`EGTAResult`. Score by ``result.v``; ``result.nash.v`` is the point
        estimate, kept for comparison.
    """
    p_hat, m = payoff_matrix(rr.wins, rr.counts)
    survivors = iterated_dominance(m, tol=dominance_tol)
    nash = nash_average(m)

    p_bagged = None
    v = nash.v
    if bag_trials > 0:
        p_bagged = bagged_mixture(rr.wins, rr.counts, trials=bag_trials, seed=bag_seed)
        v = m @ p_bagged

    w, n = smoothed_counts(rr.wins, rr.counts, survivors)
    strengths = bradley_terry(w, n)
    ratings = {idx: float(strengths[pos]) for pos, idx in enumerate(survivors)}

    anchor_strength, anchor_in_s = 1.0, True
    if anchor is not None and anchor in rr.names:
        a_idx = rr.names.index(anchor)
        if a_idx in ratings:
            anchor_strength = ratings[a_idx]
        else:
            anchor_in_s = False
            anchor_strength = provisional_strength(
                rr.wins, rr.counts, a_idx, survivors, strengths
            )

    elo_values = to_elo(np.array([ratings[i] for i in survivors]), anchor_strength)
    elo = {idx: float(elo_values[pos]) for pos, idx in enumerate(survivors)}

    k = len(rr.names)
    off_diagonal = ~np.eye(k, dtype=bool)
    net = np.array([p_hat[i][off_diagonal[i]].mean() for i in range(k)])
    # "vs frontier" excludes self so a survivor is not credited with its own 0.5.
    frontier = np.full(k, np.nan)
    for i in range(k):
        opponents = [j for j in survivors if j != i]
        if opponents:
            frontier[i] = float(np.mean(p_hat[i, opponents]))

    return EGTAResult(
        names=list(rr.names),
        p_hat=p_hat,
        m=m,
        survivors=survivors,
        nash=nash,
        ratings=ratings,
        elo=elo,
        anchor_name=anchor,
        anchor_in_frontier=anchor_in_s,
        net_win_rate=net,
        frontier_win_rate=frontier,
        v=v,
        p_bagged=p_bagged,
    )
