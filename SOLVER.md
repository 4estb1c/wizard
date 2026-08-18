# How the EV numbers are produced, and how far to trust them

Every figure in the solver panel is in **round points** — the same units as the scoring rule
(`made = 2 + tricks`, `missed = −|tricks − bid|`). This document says exactly how each one is
computed, which parts are exact, which are approximations, and what the approximations cost.
Every number quoted below is measured by a script in this repo, named at the end of its
section, so you can re-run any claim rather than take it on faith.

---

## 1. The pipeline

Both the bid panel and the card panel do the same three things.

**Sample.** Your opponent's hand is unknown. Take the set of cards you have not seen — the deck
minus your hand, minus the turned-up trump card, minus everything already played, minus their
card if it is already on the table — and draw a hand for them at random from it. That single
guess is called a *determinization*: a complete, fully specified deal.

**Solve.** With both hands known, the round is a finite two-player zero-sum game with no
hidden information, so it has an exact value. `DoubleDummy` computes it with alpha-beta over
bitmask hands and a transposition table. This step involves no estimation at all; it is the
true value of that deal under optimal play by both sides.

**Average.** Repeat over many determinizations and average per option.

This is **Perfect-Information Monte Carlo** (PIMC). It is the standard approach for
trick-taking games and it is what the bot uses to choose its own moves.

Two things are conditioned on beyond raw card counting:

- Suits the opponent has shown out of. Once they fail to follow a suit, samples that give them
  a card in that suit are rejected.
- The trump card and every played card are removed from the pool, so late-round samples are
  drawn from a genuinely small space and get sharper as the round goes on.

---

## 2. Card EV — what the panel means

For a card decision the payoff handed to the solver is the **score differential under the
contracts actually in force**:

```
payoff(myTricks, theirTricks) = roundScore(myBid, myTricks) − roundScore(theirBid, theirTricks)
```

So the solver is not counting tricks. It is playing the rest of the round to maximise your
score minus theirs, given both bids. That is why the same card can be worth +4 in one round
and −5 in another: winning a trick is good or bad purely relative to your contract.

Each root move gets a **full alpha-beta window**. This matters and is easy to get wrong:
alpha-beta returns exact values only for the best move and mere bounds for the rest. Averaging
bounds across determinizations would quietly corrupt the comparison between cards, so every
root move is searched independently on `(−∞, +∞)`.

### Win probability

The `%` column beside each card is not from the sampler. It is exact arithmetic:

- **Following** — their card is already down, so the outcome is settled. 0% or 100%.
- **Leading** — the chance that none of the cards which would beat yours is in their hand.
  Their hand is a uniform random subset of the unseen cards, so this is a hypergeometric draw:

  ```
  P(they hold none of the m beaters) = C(u−m, h) / C(u, h)
  ```

  with `u` unseen cards and `h` in their hand. Computed as a running product, no sampling.

Worth knowing: a card can have a high survival chance and a bad EV. Once you are at your bid,
winning is the thing you are trying to avoid.

---

## 3. Bid EV — why it is a band, not a number

This is the part that was wrong for a long time and is worth explaining properly.

The obvious approach is to solve each determinization once for the number of tricks you can
force, then score every candidate bid against that number. **It does not work**, because it
asserts that your hand takes a fixed number of tricks regardless of what you bid. Under that
model bidding away from `T` can only lose, so the EV column comes out as a rigid ±1 ladder
around `T` and tells you nothing you did not already know.

A hand does not take a fixed number of tricks. It takes however many you play for.

So each determinization is solved **twice**:

- `hi` — maximise your tricks against best defence. The most you can *force*.
- `lo` — minimise your tricks while they push tricks onto you. The fewest you can *hold
  yourself to*.

Note these are two different games, not a sign flip of one another: playing to duck is not the
reverse of playing to win. Every bid in `[lo, hi]` is makeable, so a bid scores `2 + b` when it
falls inside the band and `−(distance to the nearest end)` when it falls outside.

**Measured** (`bandcheck.js`, both seats playing their own contracts with the real bot):

| | matches the real outcome |
|---|---|
| single "tricks you can force" number | 44–57% |
| the band `[lo, hi]` | **78–84%** |

Mean band width is **0.92 tricks** — so the band is far more honest without becoming vague.
Its width distribution over 600 rounds (`casework.js`):

| band width | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| share of hands | 35% | 43% | 17% | 4% |

A third of hands are pinned to one number. Most of the rest give you a real choice, and among
makeable bids the **highest** pays best, because a made bid scores `2 + tricks`.

One consequence of the hook, also measured: it forbids your best bid in **35%** of rounds, and
costs about **2.9 points** when it does.

---

## 4. What is exact and what is not

**Exact, no approximation:**

- The rules, trick resolution and scoring.
- The value of any single determinization. Verified against a plain minimax with no
  transposition table and no pruning: **900 solves compared across three payoff functions and
  every trump setting, all values identical** (`correct.js`).
- The win-probability column (hypergeometric, closed form).
- The sampler itself. Against exhaustive enumeration of all 1140 possible opponent hands in a
  size-3 round, the sampled means land within **±0.02 points** of exact.

**Approximate, and here is the honest accounting:**

### 4a. Sampling noise

The panel runs 80 determinizations at every hand size. It used to slide down to 14 at eight
cards, because a solve there cost 21ms; after the search rewrite one costs 0.83ms and there is
no reason to be stingy at exactly the size where the estimate was noisiest.

Measured against a 300-determinization run (`noise.js`):

| hand size | samples | std error per card | picks the same best card | true gap, best vs second | **cost of following the short run** | wrong by >0.5 pt |
|---|---|---|---|---|---|---|
| 6 | 80 | 0.26 | 78% | 0.20 | **0.036 pts** | 0% |
| 7 | 80 | 0.25 | 68% | 0.12 | **0.026 pts** | 0% |
| 8 | 80 | 0.24 | 85% | 0.15 | **0.009 pts** | 0% |

Read the last two columns together with the fourth. The panel disagrees with a long run about
which card is "best" between 15% and a third of the time — which sounds alarming until you notice
the true gap between best and second is only **0.12–0.20 points**. The top options are
genuinely near-tied, so relabelling them is almost free: following the short run costs
**0.01–0.04 points per decision**, and it is
never wrong by as much as half a point.

Set that against the size of a real mistake. Over 600 rounds, decisions where the choice
actually mattered cost **7.5 points** on average to get wrong (`casework.js`). The noise is
roughly **1% of the signal**. The solver is unreliable about the exact ordering of options that
are nearly equal, and reliable about the ones that are not — which is the behaviour you want.

**So: do not read a 0.2-point difference as meaningful. Do read a 2-point difference as real.**

### 4b. Strategy fusion — the real limitation

This is inherent to PIMC and no amount of extra sampling fixes it.

Each determinization is solved as though both players can see all the cards. That lets the
solver play a *different* line in each imagined world. You cannot: you have to commit to one
line that works across every hand they might hold. PIMC therefore overvalues plays that only
pay off if you already know which world you are in, and correspondingly undervalues plays
whose merit is that they work everywhere.

Practically, it means the solver is slightly too optimistic about finesses and guesses, and
slightly too pessimistic about safe plays. It is at its most misleading when a decision hinges
on information you do not have and cannot get.

### 4c. Non-locality

The sampler draws the opponent's hand uniformly from the unseen cards, conditioned only on
suits they have shown out of. It does not reason backwards from their earlier choices — a bold
bid or an odd lead tells you something about their hand, and none of that is used. A strong
human reads those signals; this solver does not.

### 4d. The opponent model

Each determinization assumes the opponent plays the remainder **perfectly** against your
contract. They will not. The bot is itself a PIMC player with the same blind spots, and a human
is neither perfect nor PIMC. So the EVs are closer to "value against a strong opponent" than
"expected value against this particular opponent". Against a weak opponent the true value of
aggressive lines is higher than shown.

### 4e. The band's own assumption

`[lo, hi]` is the range you can *force* against best defence. Since the opponent is chasing
their own contract rather than fighting yours, both ends are conservative. That is why the band
contains the real outcome 80% of the time rather than 100%: the remaining 20% is mostly
outcomes outside the band that occurred because the opponent was not playing to constrain you.

---

## 5. Determinism

The panel is seeded from a hash of the position — your hand, the trump card, everything played,
both bids, the card on the table, the trick counts. So the same position always produces the
same numbers: closing and reopening the panel, or the board re-rendering, cannot make the
figures shuffle. Verified as 1 distinct result from 8 identical runs.

The bot keeps genuine randomness. Only the read-out is pinned.

The pacing is deliberately *not* part of the seed. The solver yields control back to the
browser once it has spent about half a frame, so the animations keep running while it thinks;
how many times it yields depends on machine speed, but the sample sequence and therefore the
result do not.

---

## 6. Performance

A determinization is straight-line search with no I/O, so cost is dominated by node count.
After optimising the hot path — numeric transposition keys instead of built-up strings, entries
packed into one integer instead of a two-element array, and the move loop walking a fixed power
order in place rather than allocating a legal-move array per node:

| hand size | nodes per determinization | per determinization | full panel (80 samples) |
|---|---|---|---|
| 6 | 360 | 0.5 ms | 42 ms |
| 7 | 876 | 0.6 ms | 48 ms |
| 8 | 1501 | 1.2 ms | 97 ms |

An eight-card determinization started at 21.5ms and 13,300 nodes, so this is **26× faster on
time and 9× fewer nodes**, with every value still provably identical (`correct.js`). Four
changes got it there:

- numeric transposition keys instead of built-up strings, and entries packed into one integer
  rather than a two-element array, so a node neither builds a string nor allocates;
- the entry also stores the move that was best last time, and trying it first is what makes
  alpha-beta cut early — the single largest saving;
- **indistinguishable cards are collapsed to one move**. If two of the mover's legal cards are
  in the same suit with every rank between them already gone from both hands, they beat the
  same cards, lose to the same cards, and leave positions identical up to renaming. Searching
  both doubles the work for the same answer. Same for the two Wizards and the two Jesters;
- trick outcomes come from a precomputed 24x24 table instead of a branchy comparison.

The collapsing rule has one trap worth recording. "Already gone" has to include the card
currently on the table, not just the cards missing from both hands. Treating a led J as gone
made the 10 and the Q either side of it look interchangeable — when one loses to it and the
other beats it. That produced 17 wrong values in 360 before `correct.js` caught it.

One bug worth recording, since it was invisible and badly distorted the numbers for a while:
the node budget was shared across all determinizations of a single decision instead of being
reset per determinization. At eight cards it was exhausted by the twenty-sixth of sixty
samples, and every sample after that returned the current score without searching at all — a
constant that dragged every option's average toward the same value, with no error and nothing
on screen to suggest anything was wrong.

---

## 7. Re-running the evidence

```bash
node correct.js 150      # optimised solver vs plain minimax, exact agreement
node bandcheck.js 6 80   # band vs single number, against real played-out rounds
node noise.js 40         # sampling error, and what it actually costs
node casework.js 600     # decision statistics behind the explanation text
```

`casework.js` is also where the constants quoted in the game's own explanation lines come
from — the 79% tie rate, the 7.5-point cost of a real mistake, the 83%/80% duck-or-take splits.
Re-run it and the constants in `play.html` can be updated to match.
