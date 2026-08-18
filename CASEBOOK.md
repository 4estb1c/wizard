# Positions you can solve with a pencil

Seven scenarios where the optimal decision falls out of arithmetic rather than search, plus
three exercises. Every number below is produced by `casebook.py`, which enumerates the
opponent's hand exhaustively rather than sampling, so the "check" line under each case is an
exact count and not an estimate.

```bash
python casebook.py
```

## What you need before starting

The deck is 24 cards: four suits of `10 J Q K A`, two Wizards, two Jesters. Making your bid
exactly scores `2 + bid`; missing costs `1` per trick off. The dealer may not make the two
bids total the hand size, which is what guarantees at most one player can make their bid. The
non-dealer bids first and leads first.

At hand size `n` you can see your `n` cards and the flipped trump card, so

```
U = 23 - n     cards unseen,  of which the opponent holds exactly n
```

and everything else is one formula. For `B` specific cards you care about,

```
                       B-1
P(they hold none) =     ∏    (U - B - j) / (U - j)
                       j=0
```

Use it as `n` factors, not two binomials: at size 3 with 6 beaters and `U = 20` that is
`(14/20)(13/19)(12/18)`, which is three multiplications you can do in your head.

---

## Case 1. Size 1 is a solved game

**Setup.** Round 1, you are the non-dealer, so you bid first and lead. One card each.

**The trick nobody notices.** The dealer's bid is *forced*. Bids may not total 1, so if you
bid 0 the dealer cannot bid 1, and if you bid 1 the dealer cannot bid 0. The dealer must copy
you. There is no play decision either, since you each hold one card. So you are choosing
between exactly two games.

Write `p` for the probability your card takes the trick.

| both bid | you win | you lose | margin |
|---|---|---|---|
| 0 | −1 vs +2 | +2 vs −1 | `3 − 6p` |
| 1 | +3 vs −1 | −1 vs +3 | `8p − 4` |

Those cross at `8p − 4 = 3 − 6p`, so **bid 1 exactly when `p > 1/2`**.

**Now count `p`.** You lead, so your card wins unless the single unseen card the opponent
holds beats it. With 22 unseen, `p = (22 − B)/22`, and `B` is the beater count: two Wizards,
plus every trump you cannot see, plus every higher card of your own suit.

The worst case a normal card can face is the ten of a non-trump suit with a trump on the
table: `B = 2 + 4 + 4 = 10`, giving `p = 12/22 = 6/11 = 0.545`.

**Answer.** `12/22 > 1/2`, so **bid 1 with every normal card in the deck**. Bid 0 only with a
Jester, where `p = 1/22` (they must be holding its twin). A Wizard is `p = 1`. Even the worst
card in the game bids 1, worth `8(6/11) − 4 = +4/11` against `−3/11` for bidding 0.

The reason is entirely about the lead. A follower needs a *specific* beater, and most cards
are not one.

**Footnote worth knowing.** Maximizing your own score instead of the margin puts the
threshold at `3/7 = 0.4286`, which would flip the bid at 11 or 12 beaters. No single card
reaches 11, so at size 1 the two objectives never actually disagree. At larger sizes they do,
and the margin threshold is the right one, since the ladder is a race.

**Check.** `bid 1 iff p > 1/2` agrees with the payoff lines on all 506 (card, trump) pairs;
worst normal card `p = 0.545455`; most beaters any one card faces = 10.

---

## Case 2. How long does a bare Ace last?

**Setup.** You hold the ace of hearts. The king of spades is face up, so spades are trump.

**The count.** The ace of hearts is beaten by the two Wizards and by any spade. The king of
spades is on the table, so four spades are unseen. `B = 6`, at every hand size. Nothing about
the ace changes as the hand grows. Only `n` changes.

| n | U | P(the ace holds) | worked |
|---|---|---|---|
| 1 | 22 | **0.727** | `16/22` |
| 2 | 21 | **0.500** | `(15/21)(14/20)` |
| 3 | 20 | **0.319** | `(14/20)(13/19)(12/18)` |
| 4 | 19 | **0.185** | `(13/19)(12/18)(11/17)(10/16)` |
| 5 | 18 | **0.092** | |
| 6 | 17 | **0.037** | |
| 7 | 16 | **0.011** | |
| 8 | 15 | **0.001** | `1/715` |

**Answer.** A bare off-suit ace is a coin flip at size 2 and worth essentially nothing from
size 5 up. Six beaters is a small number and it still destroys the card, because the opponent
draws `n` chances at it while the pool shrinks underneath.

The rule of thumb: each extra card in the opponent's hand multiplies your survival odds by
roughly `1 − B/U`. At `B = 6` that is about a third off per card.

**Check.** The closed form matches the exhaustive count at all eight sizes.

---

## Case 3. When the specials stop being special

The two duplicate rules are exact mirrors of each other:

```
Wizard led       always wins        Wizard followed  loses to a Wizard lead
Jester followed  always loses       Jester led       wins if answered by a Jester
```

So each card is a certainty in one seat and a gamble in the other, and both exceptions need
the same thing: the opponent holding the *other copy*. One probability covers both.

| n | U | P(twin opposite) = `n/(23−n)` |
|---|---|---|
| 1 | 22 | 0.045 |
| 2 | 21 | 0.095 |
| 4 | 19 | 0.211 |
| 6 | 17 | 0.353 |
| 8 | 15 | **0.533** |

**Answer.** At the peak your Wizard is not a safe defensive card: the other Wizard is opposite
you more often than not. Lead it. Symmetrically, a Jester you are forced to *lead* at the peak
wins about a third of the time, which is a real risk when you are trying to lose a trick.

This is an upper bound on the risk in both directions, since they also have to still hold the
twin when it matters and choose to play it.

**Check.** `n/(23−n)` matches the exhaustive count at every hand size.

---

## Case 4. The exit card, and why it reverses the lead

**Setup.** Size 2, spades trump (king of spades up). You hold a Wizard and one other card. You
bid 1; the dealer is barred from 1 and bids 0.

Your Wizard is a trick you cannot avoid taking, and every trick beyond the first breaks your
bid. So the entire round is one question: **can you lose the other trick?** The margin is `+4`
if you take exactly one, `−3` if you take both, and `+1` in the single line where they strip
your Wizard and you take none.

### Hand A: Wizard + Jester

*Lead the Wizard.* You win. Now you lead the Jester, and a led Jester loses to everything
except its twin. You make your bid unless they hold the other Jester, one card out of 21:

```
1 − 2/21 = 19/21 = 0.905
```

*Lead the Jester.* Now they get a choice. Answering with a Jester hands you the trick you did
not want; keeping a Wizard to lead back on trick 2 kills your Wizard and you take zero. You
need them holding neither, and only one of each is unseen:

```
(19/21)(18/20) = 0.814
```

**Lead the Wizard.**

### Hand B: Wizard + ten of diamonds

*Lead the Wizard.* You win, then lead the ten. They discarded one card on trick 1 and kept
whichever they liked, so they keep something that ducks. You only make your bid if **both**
their cards were forced to beat the ten. The ten of diamonds is beaten by the one unseen
Wizard, four unseen spades, and four higher diamonds, so `B = 9`:

```
(9/21)(8/20) = 0.171
```

*Lead the ten.* Now *they* have to solve the problem. They can duck with a Jester always, or
with any losing card when they are void in diamonds; but holding a diamond forces them to
follow, and every unseen diamond beats the ten. You need them holding no special and unable to
duck, which is `68/210 = 0.324`.

**Lead the ten.**

**Answer.** Same bid, same Wizard, opposite play. With a Jester you own a guaranteed exit, so
cash the Wizard and bail out. With a rag you own no exit, so you must probe with the rag first
while the Wizard is still in hand as insurance. Playing each hand at its best, the Jester
version makes the bid 0.905 of the time against 0.324, so the second card is worth **58
percentage points** on an identical contract.

**Check.** Enumerated over all 210 opponent hands with the solver: 0.904762, 0.814286,
0.171429, 0.323810, all matching the closed forms exactly.

---

## Case 5. The bid-up ratio

**The question.** You are between two bids. When is one more trick worth bidding?

Making bid `b` scores `2 + b`. A typical miss is by one and costs `1`. So

```
EV(b) = p_b (2 + b) − (1 − p_b) = p_b (3 + b) − 1
```

Setting `EV(b+1) > EV(b)` gives

```
p_(b+1) / p_b  >  (b + 3) / (b + 4)
```

| bid `b` | the higher bid must be this likely, relative |
|---|---|
| 0 → 1 | 0.750 |
| 1 → 2 | 0.800 |
| 2 → 3 | 0.833 |
| 3 → 4 | 0.857 |
| 4 → 5 | 0.875 |

**Answer.** The bar rises with the bid. A speculative bid of 1 needs only three quarters the
chance of a bid of 0; a speculative bid of 5 needs seven eighths. Low bids are cheap to reach
for, high bids are not, because you are risking a bigger sure thing to gain the same `+1`.

If misses were free the threshold would be `(b+2)/(b+3)` instead. The gap between the two
columns is what the miss penalty is worth.

**Check.** The two expectations are equal exactly at `(b+3)/(b+4)` for every `b`.

---

## Case 6. The Wizard floor and the Jester ceiling

No probability at all here. These are proofs.

**Floor.** A Wizard on lead cannot be beaten, and the winner of a trick leads the next one. So
holding `w` Wizards with the opening lead, you cash them back to back and **force `w` tricks**.

**Ceiling.** A Jester played as a follower always loses, and losing leaves the lead where it
was. So holding `j` Jesters while the opponent leads, you **shed `j` tricks**.

Together, any bid outside `[w, n − j]` is a guaranteed miss, which makes it dominated no
matter what else is in your hand. That is a hard constraint, and it is the base case of the
reachable band the solver computes for the real hand.

**Check** at size 3, over every opponent hand: one Wizard on lead forces exactly 1 and both
force exactly 2; one Jester while following caps you at 2 and both cap you at 1.

---

## Case 7. Counting your winners, and the correction that fixes it

**The estimate.** Add up `P(this card wins)` over your hand and call the sum your bid. One
hypergeometric per card, from Case 2. This is the closed form you would actually use at the
table, and it is what the `count` strategy in `TOURNAMENT.md` does.

**It is badly wrong, and always in the same direction.** Measured against the exact
double-dummy mean over every opponent hand:

| n | true mean tricks | flat estimate | mean abs error |
|---|---|---|---|
| 2 | 1.227 | 1.008 | 0.219 |
| 3 | 1.466 | 0.980 | 0.485 |
| 4 | 2.087 | 1.122 | 0.965 |
| 5 | 2.478 | 0.900 | 1.578 |

It is pessimistic, by nearly a full trick at size 4. The reason is that it prices every card as
though it had to win **the first** trick, against a full opponent hand. But your worst card is
played on the *last* trick, when the opponent holds exactly one card and almost nothing can
beat it.

**The correction costs nothing.** Sort your hand strongest first, and price the `k`-th card
against an opponent hand of `n − k + 1` cards instead of `n`:

```
             n
estimate =   ∑   P(none of B_k beaters among n − k + 1 cards)
            k=1
```

| n | true | flat | staged | abs error flat → staged |
|---|---|---|---|---|
| 2 | 1.227 | 1.008 | **1.215** | 0.219 → **0.109** |
| 3 | 1.466 | 0.980 | **1.401** | 0.485 → **0.158** |
| 4 | 2.087 | 1.122 | **1.869** | 0.965 → **0.297** |
| 5 | 2.478 | 0.900 | **1.710** | 1.578 → **0.794** |

**Answer.** Staging the hand cuts the error by more than half at every size. What is left is
still biased downward, and stays that way because the estimate never models the two things
that manufacture extra tricks: winning a trick hands you the lead, and being void in a suit
lets you trump it.

Shrinking the unseen pool as well, rather than just the opponent's hand, does not help further
(tested: 0.109 / 0.164 / 0.305). The opponent's hand size is the term that matters.

---

## Exercises

Worked answers below, derivations left to you. `casebook.py` has the machinery if you want to
confirm.

**E1.** Size 3, spades trump with the king of spades up. You hold `Wz A♠ 10♣`. You bid 2, they
bid 0. Which card do you lead?

**E2.** Size 2, you are the non-dealer and hold both Jesters. What is your bid, and what is the
guaranteed margin?

**E3.** Redo the Case 2 table for a bare king of hearts instead of the ace. At which hand size
does it drop below a coin flip?

<details>
<summary>Answers</summary>

**E1.** Lead the ten of clubs, and it is not close: `395/1140 = 0.347` against `215/1140 =
0.189` for the trump ace and `95/1140 = 0.083` for the Wizard. Leading the Wizard is more than
four times *worse* than leading your most worthless card.

This and Case 4 are the same rule: **spend the card you want to lose with first, while your
winners are still in hand as insurance.** Hand A of Case 4 looks like an exception and is not.
There the Jester is a guaranteed loser you can deploy whenever you like, so the exit is never
at risk and you are free to cash first.

**E2.** Bid 0, and it is a guaranteed `+3`. Both Jesters are yours, so nothing can answer
either one; you lead them both and lose both tricks with certainty, taking 0 for `+2`. The
dealer is then barred from bidding 2, so they must bid 0 or 1 while taking both tricks, and
the best they can do is `−1`. Verified: over all 210 opponent hands, the most tricks you can
be made to take is 0.

**E3.** `B = 7` (two Wizards, four spades, the ace of hearts). It is already under water at
size 2, where the ace sits exactly even.

| n | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| P | 0.682 | 0.433 | 0.251 | 0.128 | 0.054 | 0.017 | 0.003 | 0.000 |

The cost of that one extra beater has its own closed form, and it is not a constant:

```
P(B+1) / P(B) = (U − B − n) / (U − B)
```

At size 2 the king keeps 13/15 of the ace's odds, at size 3 it keeps 11/14, at size 4 only
9/13. Each additional beater hurts more as the hand grows, which is the same shrinking-pool
effect as Case 2 seen from the other side.

</details>

---

## Where these stop working

Cases 1, 2, 3 and 6 are exact statements about the deck and hold everywhere. Cases 4, 5 and 7
are decision rules, and they lean on assumptions worth naming:

- The solver numbers in Case 4 come from a **double-dummy** enumeration, meaning an opponent
  who can see your cards. Where the opponent is the one benefiting from that sight (all four
  lines in Case 4), the real figure is a little better for you than what is printed.
- Case 5 prices a miss at exactly 1 point. Missing by two costs 2, so the threshold is
  slightly conservative for wild hands.
- Case 7's staging assumes you play your hand in strength order, which is right when you are
  chasing tricks and wrong when you are dodging them.

`SOLVER.md` covers what the full solver does with the cases these do not reach.
