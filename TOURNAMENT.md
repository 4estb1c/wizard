# What the simple rules are worth

Five one-sentence strategies in `agents/simple_bots.py`, run through the EGTA harness
(`run_tournament.py`) against the existing roster. Each isolates one idea, and neighbouring
rows differ by exactly one thing, so the gap between two rows is the price of that idea.

| name | the whole strategy |
|---|---|
| `duck` | Bid as low as the specials allow, then never try to win a trick. |
| `grab` | Bid as high as the specials allow, then take every trick it can. |
| `specials` | Bid the Wizards it holds; play the four special cards deliberately, everything else blind. |
| `count` | Count your winners (Wizards, high trumps, bare aces) to bid; play high when chasing tricks, low when not. |
| `contract` | Same bid as `count`; win a trick exactly when you still need one, with the cheapest card that does it. |

---

## Rules only

2520 matches, mirrored, 60 deal seeds per pairing.

| strategy | net | margin | frontier |
|---|---|---|---|
| heuristic | 0.809 | **+22.1** | yes |
| count | 0.722 | +15.5 | yes |
| contract | 0.771 | +15.0 | yes |
| grab | 0.466 | −3.4 | no |
| random | 0.375 | −8.4 | no |
| specials | 0.200 | −18.5 | no |
| duck | 0.157 | **−22.3** | no |

Three things stand out, and two of them are backwards from what you would guess.

**Counting is the whole game.** The step from `grab` to `count` is worth about **19 points a
match** — far larger than any other single step on the ladder. Everything below that line is
within a few points of random; everything above it is not. Simply totting up your own likely
winners before bidding is worth more than every play refinement combined.

**`specials` is worse than random.** Playing the four odd cards deliberately and everything
else blind scores 0.200 against random's 0.375. The reason is instructive: bidding the number
of Wizards you hold means bidding 0 or 1 nearly always, which then makes the bot want no
tricks, which makes it play its lowest card every time. It collapses into `duck`, and `duck`
is the worst strategy on the board. A good idea applied to four cards out of twenty-four
cannot rescue a bad bid.

**`duck` is the floor, not `random`.** Bidding low and never contesting is the single worst
policy tested, ten points below random. You cannot decline tricks you are forced to win, so a
low bid you make no effort to protect is a bid you miss.

---

## The rock-paper-scissors cycle

The three frontier strategies do not form a ranking. Re-run at 800 matches per pairing to be
sure it was not noise:

```
count      beats  contract    0.722     (+10.0)
contract   beats  heuristic   0.628      (+5.5)
heuristic  beats  count       0.623      (+5.9)
```

At n = 800 the standard error on a win rate is about 0.018, so each of these sits between six
and twelve standard errors from an even split. The cycle is real.

This is exactly the situation Nash averaging exists for, and it shows: all three land at
`v ≈ 0.000` with a near-even mixture of **count 0.27 / contract 0.26 / heuristic 0.47**. Read
as a plain ranking the table is meaningless; read as a mixture it says there is no single best
simple rule, only a best *blend*.

The `count` / `contract` pair is the sharpest illustration. They **bid identically** and differ
only in what they do with a card once bidding is over. `contract` has the better record against
the field (0.771 vs 0.722) — and loses to `count` head to head, 0.278. The more careful play
rule is better against everyone except the opponent it most resembles.

---

## Against search

12 deal seeds per pairing, mirrored — PIMC is slow in Python.

| | vs contract | vs count | vs heuristic |
|---|---|---|---|
| `pimc-8` win rate | 0.880 | 0.940 | 0.980 |
| margin | +30.3 | +33.3 | +29.0 |

Elo 2176 against roughly 1500 for the rules, and the dominance filter eliminates every rule.
Eight determinizations of search are worth about **30 points a match** over the best rule that
does not search — more than the entire spread between the best and worst simple strategy.

---

## A memory bug this surfaced

The first full-roster run died with a `MemoryError` inside the Python solver. Its
transposition table was capped at 400,000 entries, which is fine for one solver but not for a
round robin: several PIMC agents live inside each of several worker processes at once, and a
tuple-keyed dict entry costs a few hundred bytes. The cap is now 40,000, which keeps a solver
near ten megabytes while still carrying the table across the determinizations of one decision,
which is where it earns its keep.

---

## Re-running

```bash
python run_tournament.py --matches 60 --strategies random duck grab specials count contract heuristic
python run_tournament.py --matches 400 --strategies count contract heuristic
python run_tournament.py --matches 12 --strategies duck grab specials count contract heuristic pimc-8 --workers 4
```
