# Up the River — heads-up strategy search

A two-player Wizard variant on a stripped 24-card deck ([`RULES.md`](RULES.md)), a set of
bots that try to play it well, and the evaluation harness from the
[GOPS strategy-search project](../ddx) reused to rank them.

```
RULES.md            the game
engine.py           deck, trick resolution, the dealer hook, the 16-round ladder, scoring
solver.py           double-dummy solver: exact alpha-beta over a fully specified deal
agents/             the Agent interface and the ranked roster
oracle.py           perfect-information oracle — a measuring instrument, never a competitor
sim.py              common-random-number round robin      (ported from ddx/sim.py)
egta.py             dominance, Nash averaging, Bradley-Terry  (verbatim from ddx/egta.py)
run_tournament.py   the driver
analysis.py         properties of the game itself, independent of any strategy
tests.py            validation, including the round-1 solve done by hand

play.py             play against a bot from the terminal
explain.py          generates the reasons behind each verdict
review.py           post-game analysis of a logged game
games/              one JSONL log per game played
runs/               recorded output from every tournament below
```

```bash
python tests.py
python run_tournament.py --matches 24 --workers 12 --gap
```

## Playing it in a browser

Open [`play.html`](play.html). One self-contained file — no build, no server, no
dependencies. The engine, the double-dummy solver and the PIMC bot are all ported to JS and
run locally.

It is markedly faster than the Python: an 8-card solve takes **3.1 ms** (4,590 nodes) against
~49 ms in CPython, so even the hardest setting answers in about a tenth of a second. Three
opponents — Easy plays on hand evaluation alone, Normal and Hard determinize and solve, with
Hard simply sampling more. (Per the tournament results below, more samples stop helping around
24, so the honest difficulty ladder here is short.)

The port was checked against the same invariants as `tests.py` by simulating 48 rounds in the
page: no illegal bids or plays, the hook never violated, trick counts always summing, and
never once did both players make their bid.

## Playing it in the terminal

```bash
python play.py                      # quick game: ladder to 4, 8 rounds
python play.py --peak 8             # the full 16-round game
python play.py --opponent pimc-24   # a harder bot
```

Every decision is written to `games/*.jsonl` as it happens, straight from the engine's own
`on_event` hook, so a log cannot drift from what was actually played. The log records both
hands, which is what lets the review solve each position exactly — during play you only ever
see your own.

The review runs automatically at the end, or later with
`python review.py games/<file>.jsonl`. Every decision is scored against the best action
available **on the information you had** — your hand, the trump card, the bids, the cards
played, and the suits the opponent has shown a void in. Opponent hands are sampled from
everything consistent with that, and each candidate is scored as its average over those
samples.

It deliberately does **not** use the double-dummy optimum. Both hands are in the log, so the
exact best line is computable after the fact, but marking you down for not seeing through the
back of the cards produces advice you could never have followed. The opponent's real cards
are read for exactly one thing: how many of them there were.

Costs are therefore averages carrying sampling noise. Every candidate is evaluated on the
*same* sampled hands, making the comparison paired, and a decision is only reported when its
cost clears twice the standard error of that paired difference — so "too close to call" is a
category, not a rounding artifact.

```
  round 2, bid: played 0, best 2   cost 4.4 +/- 0.2
        across 150 deals consistent with what you could see, this hand averaged 1.7 tricks,
        most often 2 (74%); you bid 0; bidding 2 was worth 4.4 points more.

  round 3, bid: played 0, best 2   cost 2.0 +/- 0.0
        ...most often 3 (100%); the hook denied you 3, the most likely count; bidding 2 was
        worth 2.0 points more, judged on the score differential.

  round 2, trick 1: played Wz, best QH   cost 0.6 +/- 0.1
        you had your 0 and needed to duck all 2 remaining; you led Wz and a Wizard lead
        always takes the trick; because 3 unseen cards beat QH where only 0 beat Wz.
```

This is still not GTO — averaging over determinizations has its own blind spot, described
below — but it is at least a reference a player could have reached from the table.

The deck is parameterized at the top of `engine.py` — suits, ranks, Wizard and Jester counts,
and the peak hand size. Everything downstream derives from those, so a rule change is a
one-line edit plus a rerun.

## What is borrowed and what is new

`egta.py` arrives unchanged. It never learns what game produced its inputs — it consumes a
win-count matrix and returns a ranking — so the whole evaluation stage ports for free:
iterated elimination of dominated strategies, then Nash averaging, then Bradley–Terry
restricted to the survivors. The reason that pipeline is worth carrying over is the same here
as there: a strategy can post a strong net win rate by beating the weak end of the roster
decisively while losing every match that decides anything, and Nash averaging refuses to
reward it.

`sim.py` is a port rather than a copy, but the variance-reduction design is identical:

| GOPS | Up the River |
|---|---|
| prize deck order | deal seed generating all 16 rounds |
| seat swap on the same deck | mirrored match on the same seed |
| per-strategy RNG stream, stable across seats | same, via `agent.seed()` |

The mirror is exact. `engine.play_match` derives each round's deal from `(seed,
round_index)` and nothing else, so calling it with the agents swapped replays the identical
cards with the roles reversed. Because the ladder plays its peak twice, each player also
deals each hand size exactly once, so the two orders are symmetric before the pairing starts.

## The solver

Everything that plays well sits on `solver.py`. Once both hands are known, a round is a small
zero-sum perfect-information game, and this solves it exactly — alpha-beta with a
transposition table whose entries carry EXACT/LOWER/UPPER bound flags. The flags are not
optional: reusing raw alpha-beta values as though they were exact produces a solver that is
right on most positions and quietly wrong on a few. `tests.py` checks it against a naive
minimax with no pruning and no table.

A full 8-card solve runs in about 49 ms — roughly 14k nodes where the raw tree is orders of
magnitude larger. The table is shared across the determinizations of a single decision, where
trump and the payoff are constant, so later samples ride on subtrees earlier ones resolved.

One detail worth guarding: the order of tests in `trick_winner` and `solver._wins` is what
encodes the duplicate-card rules. A Wizard *lead* is checked before a Wizard *follow* (first
Wizard played wins), and a Jester *follow* before a Jester *lead* (two Jesters go to the
leader). Reordering them silently changes the game.

## The bots

| name | what it does |
|---|---|
| `random` | uniform legal choices — the floor |
| `heuristic` | no search; bids the summed probability that each card wins *when led* |
| `pimc-8` / `pimc-24` / `pimc-64` | determinize the opponent's hand, solve each exactly, average |
| `pimc-24-veto` | as above, but bids partly to deny the dealer their number |
| `pimc-24-infer` | rejects hands from which the opponent could not still make their bid |

### These are not GTO, and the code says so

PIMC is the standard strong approach for trick-taking games, and it has two documented
pathologies that keep it away from equilibrium:

- **Strategy fusion** — it can choose an action justified by playing differently in two
  determinizations it cannot actually distinguish, when in the real game one policy has to
  serve both.
- **Non-locality** — it samples from the observation-consistent set without conditioning on a
  rational opponent's earlier choices being informative. `pimc-24-infer` tries to patch this
  and makes things much worse; see below.

A genuine equilibrium would need counterfactual regret minimization over the information
sets, which this repo does not attempt. Round 1 *is* solved exactly, by hand and by
enumeration in `tests.py`, and it is the only round that gets that treatment.

## Exploitability, honestly

`oracle.py` measures the **double-dummy gap**: the margin a strategy concedes to an opponent
who has been shown its hand and never misplays.

This is not Nash exploitability, and is not labelled as such. In GOPS both hands are public,
so a best-response oracle is a legal construction; here hidden information is the whole game,
and the oracle has to cheat to function. Its margin is therefore an *upper* bound on what any
real opponent could extract, where exploitability is a lower bound. What it does keep is the
property that made exploitability worth measuring: it is population-independent, so it cannot
be flattered by a roster that is churning without improving.

## Results

Raw output for every run is in [`runs/`](runs/). Each pairing plays every deal seed twice
with the seats mirrored, so "48 matches" is 24 seeds played both ways.

### The roster — 24 seeds per pairing, 24-card deck

| strategy | v (Nash) | net win | margin/match | double-dummy gap |
|---|---|---|---|---|
| pimc-24-veto | +0.021 | 0.780 | +21.0 | +41.5 |
| pimc-24 | −0.021 | 0.759 | +20.9 | +40.9 |
| pimc-8 | −0.135 | 0.686 | +15.5 | +49.8 |
| pimc-24-infer | −0.309 | 0.369 | −1.6 | +37.7 |
| heuristic | −0.412 | 0.388 | −11.4 | +68.9 |
| random | −0.490 | 0.018 | −44.4 | +78.4 |

At 48 matches per pairing a win rate carries about ±0.14 at 95%. **`pimc-24-veto` and
`pimc-24` are tied** (0.541, well under one standard error), and `pimc-24` over `pimc-8`
(0.582) is only ~1.1 SE here — though it agrees in sign with three larger runs on the
18-card deck, where the same comparison came out 0.567 pooled over 620 matches.

### The inference variant got worse, not better

`pimc-24-infer` now **loses to the no-search heuristic** (0.235), having been roughly even
with it on the old deck. Its filter rejects determinizations from which the opponent could no
longer make their bid — and the guarantees that test leans on stopped being guarantees when
the deck went to two of each special. Instrumenting it on the old deck showed 33% acceptance
with the bot still landing 20 of its 24 requested samples, so this was never sample
starvation; it is **selection bias**, and a bigger hidden stock makes it bite harder. Keeping
only hands from which the opponent can still make their bid over-represents strong opponent
hands, so the bot plays every position as though it is facing a monster.

The general lesson is the one PIMC's literature already warns about: patching non-locality by
filtering the sample distorts it, and a distorted belief is worse than a naive one.

### The bigger deck moved everything further from optimal

| | 18-card deck | 24-card deck |
|---|---|---|
| best bot's double-dummy gap | +31.2 /match (2.2 /round) | **+40.9** /match (2.6 /round) |
| oracle win rate vs best bot | 0.979 | **1.000** |
| P(opponent holds an unseen card), peak | 0.70 | **0.53** |

These move together and the mechanism is direct: the dead stock grew from 3 cards to 7, the
endgame no longer converges toward certainty, and perfect information is worth
correspondingly more. The 24-card game is *harder*, not just bigger.

### The game itself

From `analysis.py`, by double-dummy solving 300 random deals per hand size — properties of
the game, not of any bot:

| hand size | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| leader's edge (tricks) | +0.147 | +0.207 | +0.160 | −0.010 | +0.017 | +0.010 | +0.083 | −0.010 |

**The lead is worth something real at sizes 1–3 (3–5 SE clear) and nothing measurable from 4
up.** Five ranks per suit instead of four makes voids rarer, so the "an off-suit non-trump
card cannot win at all" effect that makes leading strong dies out sooner than it did on the
18-card deck, where the edge persisted at roughly +0.1 throughout.

At the peak, double-dummy trick counts land on 3, 4 or 5 in 74% of deals. Taking nothing
(0.3%, pays +2) is three times *rarer* than taking everything (1.0%, pays +10) — the
scoring's sharpest asymmetry, and sharper than it was on the old deck.

### A caveat on the ranking

The dominance filter runs at `tol=0.0` — exact domination — and eliminates every non-winner
in every run, returning a pure Nash mixture each time. It crowned `pimc-24` and eliminated
`pimc-24-veto` on the 18-card deck, then crowned `pimc-24-veto` and eliminated `pimc-24` on
the 24-card deck, with the two statistically tied both times. **That flip is direct evidence
the filter is over-confident on noisy entries.** `egta.py` documents the `tol` knob for
exactly this case and recommends a fraction of an entry's standard error; it is left at the
literal spec here and should not be.

Resolving the top two properly would need roughly 1,500 matches per pairing at a plausible
true edge, which is about five hours at the current ~13 s per match. The honest reading is
that the top of the table is a tie.

## Where this could go next

- Set `dominance_tol` from the measured standard error, which is the one clearly wrong knob.
- Exact equilibria for rounds 1–2 by linear programming over the bid-then-play tree, giving
  the roster a true GTO anchor at the small end of the ladder.
- CFR with an information-set abstraction for the larger rounds.
- The LLM-driven evolutionary generator from `ddx/EvolutionaryApproach`, which was written
  against exactly this evaluation interface and needs only a new strategy prompt.
