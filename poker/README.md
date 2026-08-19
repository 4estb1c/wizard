# Heads-Up Hold'em trainer

Play heads-up No-Limit Texas Hold'em against a range-based opponent, with the arithmetic
shown while you play and every decision broken down afterwards.

```bash
python -m http.server 8901      # then open play.html
```

It needs to be served rather than opened from disk, because the page loads `core.js` and
`game.js` as separate files so they can also be driven headlessly by the tests.

---

## What is exact, and what is not

Hold'em is not a game you can solve the way you can solve a small trick-taking game. The
useful thing is not to pretend otherwise, so this project keeps three claims apart and labels
every number with which one it is:

| | | |
|---|---|---|
| **Exact** | hand evaluation, equity, all pot arithmetic | enumeration and closed form |
| **Modelled** | which hands the opponent holds | a stated range, narrowed by their actions |
| **Assumed** | that a call ends the betting | a floor for draws, a ceiling for bluff-catchers |

Every equity the trainer reports is exact *given a range*, and every range is a model. Those
are different claims, and blending them into one confident-looking number is the main way a
tool like this misleads you.

### The one place equity is estimated

Postflop a runout is 990 boards on the flop, 44 on the turn and 1 on the river, so a whole
range enumerates in milliseconds. Preflop a single matchup is **1,712,304** boards and a full
1,326-combo range is **2.27 billion**, which is not a slow answer but no answer at all.

So preflop samples, and says so: the panel prints the sample count and standard error
(typically ±0.11%) instead of quietly showing an estimate in the same style as the exact ones.

### The closed forms it leans on

With `P` the pot before a bet of `B`:

```
required equity to call     B / (P + 2B)      half pot is 3:1, so 25%
minimum defence frequency   P / (P + B)       against a pot bet, 50%
bluffs a bet may contain    B / (P + 2B)      the same number, by construction
fold equity a bluff needs   B / (P + B)
```

The bettor's bluff ratio and the caller's required equity being the same number is not a
coincidence: both are the point where calling is indifferent, which is what makes the pair
checkable against each other in `test_core.js`.

---

## The retro

After each hand, every one of your decisions gets:

- your exact equity against the combos the model still gives the opponent
- the price you were laid and the minimum defence frequency
- the EV of **every** action available, with folding as the zero point
- what the best action was, and what your choice cost against it
- what the opponent's reasoning was, since it is a range-based bot and its logic is legible

**Copy for Claude** puts the whole hand on the clipboard with a rules brief, the numbers, and
a request to explain the mathematics and say where the model rather than the maths is doing
the work.

---

## Verification

```bash
python test_eval.py     # the evaluator, against combinatorics
node test_core.js       # the JS port, against Python
node test_game.js       # the rules and the opponent
```

**`test_eval.py`** evaluates all **2,598,960** five-card hands and checks the count of each
category against the known census. If any hand shape were misclassified the counts could not
come out right, because they are fixed by combinatorics and not by anything this code
believes. Then 25,000 random seven-card hands are checked against the best of their own
twenty-one five-card subsets.

That pair of tests is what caught the one real evaluator bug: the straight table scanned
low to high and returned the *lowest* straight in a hand. The census passed anyway, because
five cards can only ever contain one straight. Only the seven-card check could see it.

**`test_core.js`** replays 8,000 evaluations and every equity from Python and requires exact
agreement, since the verification lives in Python while every number the browser shows is
computed in JS.

**`test_game.js`** fuzzes 3,000 hands with a hero picking uniformly among legal actions, so it
reaches raise wars, min-raise edges and all-ins that a sensible player never visits. It checks
chip conservation, that showdowns are won by the better hand, that no card is dealt twice, and
that the betting order is right.

It also checks **bot blindness** directly: swap hero's hole cards for a different pair and the
opponent must produce the identical action. 400/400 do. That is a property you can test rather
than a claim you have to trust.

---

## Two bugs worth knowing about

**The bot's sizing was being silently overridden.** `preflopBot` clamped its raise down to the
maximum but never up to the minimum re-raise, so against a large raise it would request an
illegal size. `applyAction` then corrected it — no error, no symptom, and an opponent whose
sizing was not the sizing it asked for. The fuzz test caught it because it checks requested
sizes against the legal range rather than only checking that the game did not crash.

**Opening the panel changed how the opponent played.** The preflop sampler drew from
`st.rand`, the same stream that randomises the bot's frequencies. Analysing a spot therefore
advanced that stream and altered the bot's next decision, and the retro disagreed with the
live panel for the same decision. The sampler now has its own stream seeded from the position,
which makes analysis both side-effect free and repeatable.

---

## Files

| | |
|---|---|
| `play.html` | the table, the live panel, the retro |
| `core.js` | evaluation, equity, ranges, pot arithmetic — the exact layer |
| `game.js` | the rules, the range model, the opponent, the EV analysis |
| `eval7.py` | the reference evaluator the JS port is checked against |

---

## What is not here

Postflop bet sizing is priced against a **modelled** range, not solved. The river is the one
street where a real solve is tractable, since there are no cards to come and range versus
range is a finite matrix game with measurable exploitability. That would be the honest next
step, and it would replace the modelled river numbers with genuinely optimal ones rather than
adding a layer on top of them.
