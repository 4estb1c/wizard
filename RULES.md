# Up the River — Heads-Up Rules

A two-player trick-taking bid game, based on Wizard, with a stripped 24-card deck and an
up-and-down ladder.

## Deck

24 cards:

- **10, J, Q, K, A** in each of ♠ ♥ ♦ ♣ (20 cards, Ace high)
- **2 Wizards** — beat everything
- **2 Jesters** — lose to everything

## Rounds

Sixteen rounds — up the river and back down, playing the peak twice:

**1, 2, 3, 4, 5, 6, 7, 8, 8, 7, 6, 5, 4, 3, 2, 1** — 72 tricks in all.

Round *r* deals *r* cards to each player. The deal alternates every round.

| Cards each | Stock left after deal |
|-----------:|----------------------:|
| 1 | 22 |
| 2 | 20 |
| 3 | 18 |
| 4 | 16 |
| 5 | 14 |
| 6 | 12 |
| 7 | 10 |
| 8 | 8 |

Undealt cards stay face down and out of play. Even at the peak, seven cards are never seen.

## Trump

After dealing, flip the top card of the stock. It stays face up for the whole round.

| Flipped | Result |
|---|---|
| Normal card | Its suit is trump |
| Wizard | Dealer names any suit as trump |
| Jester | No trump this round |

A flipped Wizard or Jester also proves that copy is out of play — which still leaves the
other one live.

## Bidding

The non-dealer bids first, the dealer second. A bid is any number from 0 to *r*.

**The dealer may not bid the number that would make the two bids total *r*.**

Since tricks taken always sum to *r* and bids never do, **at most one player can make their
bid each round.** Every round produces a winner and a loser, or two losers.

## Play

The non-dealer leads the first trick. After that, the winner of each trick leads the next.

You must follow the led suit if you can — **except that a Wizard or Jester may always be
played**, regardless of what you hold.

The **led suit** is the suit of the first non-Jester card played. So if a Wizard or Jester is
led, the opponent may play anything.

A trick is won by, in order:

1. The **first** Wizard played
2. The highest trump
3. The highest card of the led suit
4. The leader, if **both** cards are Jesters

## What the specials actually guarantee

With two of each, the specials are powerful but no longer unconditional — and the exceptions
land on opposite sides:

| | Led | Followed |
|---|---|---|
| **Wizard** | always wins | loses to a Wizard **lead** |
| **Jester** | loses, *unless* the opponent answers with the other Jester | always loses |

So on offence the Wizard is the certain card and the Jester is not; on defence the Jester is
certain and the Wizard is not. Two practical consequences:

- **Never answer a Wizard lead with your Wizard.** It loses, and you have burned the best
  card in the deck for nothing.
- **A Jester lead is no longer a safe way to shed a trick.** If the opponent holds the other
  Jester and also wants to duck, they play it and the trick comes back to you.

Holding **both** copies is what restores certainty: two Wizards guarantee two tricks, because
nothing can outrank a Wizard when you hold them both, and two Jesters guarantee two lost
tricks for the same reason.

## Scoring

| Result | Points |
|---|---|
| Bid made exactly | `2 + tricks taken` |
| Bid missed | `−\|tricks taken − bid\|` |

Highest total after the final round wins. A made bid is worth 2 to 10 points; missing by
everything at the peak costs 8.

## Deal balance

Playing the peak twice makes the ladder even, which makes strict alternation exactly fair:
**each player deals each hand size exactly once.**

| | Deals rounds | Hand sizes dealt |
|---|---|---|
| First dealer | 1, 3, 5, 7, 9, 11, 13, 15 | 1, 3, 5, 7, 8, 6, 4, 2 |
| Second dealer | 2, 4, 6, 8, 10, 12, 14, 16 | 2, 4, 6, 8, 7, 5, 3, 1 |

Both cover 1 through 8 with no overlap. Neither seat gets more of the small hands, where the
hook squeezes the dealer hardest, or more of the large ones, where bidding last is worth the
most.
