"""Judge decisions on the information available when they were made.

There is a tempting alternative this module deliberately does **not** use: after the game both
hands are known, so every position is a solved perfect-information game and the optimal line
can be computed exactly. That is the classic double-dummy post-mortem, and it is the wrong
teacher. It marks you down for not seeing through the back of the cards, and the lesson it
gives — "you should have played the other ten" — is one you could not have acted on.

So every number here is computed from what the player could actually see: their own hand, the
trump card, the bids, the cards already played, and the suits the opponent has shown a void
in. Opponent hands are sampled from everything consistent with that, and each candidate action
is scored as its average over those samples. This is the same determinization procedure the
PIMC bots use to choose, which is the point: the reference is a strong player working from the
same information, not an oracle working from more.

Two consequences worth stating:

* **Costs are averages, so they carry sampling noise.** Every candidate is evaluated on the
  *same* sampled hands, making the comparison paired, and :func:`review_play` reports the
  standard error of the paired difference. A cost inside the noise is not a finding.
* **It is not GTO either.** Averaging over determinizations still suffers strategy fusion —
  it can prefer an action justified by playing differently in worlds it cannot tell apart. A
  true equilibrium reference needs CFR over information sets, which this project does not
  build.
"""
from __future__ import annotations

import math
import random

from engine import (NUM_RANKS, card_name, is_jester, is_wizard, round_score, suit_of,
                    trick_winner)
from solver import DoubleDummy, score_payoff, tricks_payoff

_SUIT_WORDS = ("spades", "hearts", "diamonds", "clubs")


def samples_for(hand_size: int, budget: int = 320) -> int:
    """Determinizations to average over, scaled so big rounds stay affordable.

    Solve cost climbs steeply with hand size — roughly 1 ms at four cards and 50 ms at
    eight — so a flat sample count either wastes time on small rounds or stalls on large
    ones.
    """
    return max(24, min(150, budget // max(1, hand_size)))


def suit_word(suit: int) -> str:
    return "no trump" if suit < 0 else _SUIT_WORDS[suit]


def plural(value: float, word: str = "point") -> str:
    return f"{value:.1f} {word}s" if abs(value - 1) > 1e-9 else f"{value:.1f} {word}"


# --------------------------------------------------------------------------- sampling

def consistent_hands(unseen, size: int, voids, count: int, rng: random.Random):
    """Opponent hands consistent with everything observed.

    Consistency means the right number of cards, drawn from what we have not seen, avoiding
    any suit they have shown a void in. Whatever is left over is the dead stock, which is
    never revealed — so unlike most trick-taking games this never collapses to certainty.
    """
    pool = [c for c in unseen if suit_of(c) not in voids] if voids else list(unseen)
    if len(pool) < size:
        pool = list(unseen)
    if len(pool) < size:
        return
    for _ in range(count):
        yield rng.sample(pool, size)


# --------------------------------------------------------------------------- rules

def why_trick(lead_card: int, follow_card: int, trump: int) -> str:
    """Name the rule that decides a trick. Only used where both cards are already known."""
    lead, follow = card_name(lead_card), card_name(follow_card)
    if is_wizard(lead_card):
        return f"{lead} was led, and the first Wizard played always wins - nothing answers it"
    if is_wizard(follow_card):
        return f"{follow} is a Wizard and beats everything except a Wizard lead"
    if is_jester(follow_card) and is_jester(lead_card):
        return "both cards were Jesters, and two Jesters go to the leader"
    if is_jester(follow_card):
        return f"{follow} is a Jester and loses to every real card"
    if is_jester(lead_card):
        return f"a led Jester loses to any real card, so {follow} took it"

    led_suit, follow_suit = suit_of(lead_card), suit_of(follow_card)
    if trump >= 0 and follow_suit == trump and led_suit != trump:
        return f"{follow} trumped the {suit_word(led_suit)} lead"
    if trump >= 0 and led_suit == trump and follow_suit != trump:
        return f"{lead} was a trump lead and {follow} could not answer it"
    if follow_suit != led_suit:
        return (f"{follow} was off-suit and not trump, so it could not compete and "
                f"{lead} won by default")
    higher, lower = ((follow, lead) if (follow_card % NUM_RANKS) > (lead_card % NUM_RANKS)
                     else (lead, follow))
    return f"both followed {suit_word(led_suit)}, and {higher} outranks {lower}"


def exposure(card: int, unseen, trump: int) -> int:
    """How many of the cards you cannot see would beat `card` if played against it.

    Stated as a count rather than a win probability on purpose: the opponent chooses which
    card to play, so this is what you are exposed to, not what you will lose to.
    """
    return sum(1 for other in unseen if trick_winner(card, other, trump) == 1)


def why_lead(card: int, unseen, trump: int) -> str:
    if is_wizard(card):
        return "a Wizard lead always takes the trick"
    if is_jester(card):
        return ("a led Jester loses to every real card - it only comes back to you if they "
                "answer with the other Jester")
    beaten = exposure(card, unseen, trump)
    if beaten == 0:
        return f"nothing you cannot see beats {card_name(card)} - the trick was certain"
    return (f"{beaten} of the {len(unseen)} cards you cannot see beat {card_name(card)}, "
            f"and they choose which to play")


def contract_state(bid: int, taken: int, tricks_left: int) -> str:
    need = bid - taken
    if need < 0:
        return f"you were already {-need} over your bid of {bid}, with {tricks_left} to play"
    if need == 0:
        return f"you had your {bid} and needed to duck all {tricks_left} remaining"
    if need == tricks_left:
        return f"you needed every one of the last {tricks_left} tricks to reach {bid}"
    return f"you needed {need} more from {tricks_left} remaining to reach {bid}"


# --------------------------------------------------------------------------- scoring a choice

def _paired_stats(per_action: dict[int, list[float]], chosen: int):
    """Best actions, the cost of `chosen`, and the noise floor on that cost.

    Every action is scored on the identical sampled hands, so each comparison against the
    leader is paired and its standard error comes from per-sample differences rather than
    from two independent means. That is what makes a small cost distinguishable from
    sampling noise at all.

    ``best`` holds every action within one standard error of the top rather than only the
    argmax. Reporting a single winner out of a set that the sampling cannot separate would
    dress noise up as advice — and near-ties are common here, because bidding one higher
    trades a slightly worse chance of hitting for the extra point a made bid pays.
    """
    means = {a: sum(v) / len(v) for a, v in per_action.items()}
    top = max(means.values())
    leader = max(per_action, key=lambda a: (means[a], -a))

    def paired_stderr(action: int) -> float:
        diffs = [x - y for x, y in zip(per_action[leader], per_action[action])]
        n = len(diffs)
        if n < 2:
            return 0.0
        mean = sum(diffs) / n
        variance = sum((d - mean) ** 2 for d in diffs) / (n - 1)
        return math.sqrt(variance / n)

    best = sorted(a for a in per_action if top - means[a] <= paired_stderr(a) + 1e-9)
    return means, best, top - means[chosen], paired_stderr(chosen)


# --------------------------------------------------------------------------- play review

def review_play(event: dict, unseen, voids=frozenset(), samples: int | None = None,
                seed: int = 0) -> dict:
    """Score one play against the best action available on the information at the time."""
    trump, seat = event["trump"], event["seat"]
    my_bid, opp_bid = event["bids"][seat], event["bids"][1 - seat]
    hand, lead, legal = event["hand"], event["lead_card"], event["legal"]
    chosen = event["chosen"]
    # The opponent's card count is public — it follows from the hand size and the tricks
    # played. Their identities are not, and are never read.
    opp_size = len(event["opp_hand"])

    count = samples if samples is not None else samples_for(len(hand))
    dd = DoubleDummy(trump, score_payoff(my_bid, opp_bid))
    per_action: dict[int, list[float]] = {c: [] for c in legal}
    rng = random.Random(seed)

    for opponent in consistent_hands(unseen, opp_size, voids, count, rng):
        values = dd.root_values(hand, opponent, lead=lead,
                                a_tricks=event["my_tricks"], b_tricks=event["opp_tricks"])
        for card in legal:
            per_action[card].append(values.get(card, 0.0))

    if not per_action[chosen]:
        return {"kind": "play", "round": event["round"], "trick": event["trick"],
                "chosen": chosen, "best": [chosen], "cost": 0.0, "stderr": 0.0,
                "significant": False, "samples": 0,
                "explanation": "no consistent opponent hand could be sampled here."}

    means, best, cost, stderr = _paired_stats(per_action, chosen)

    parts = [contract_state(my_bid, event["my_tricks"], len(hand))]
    if lead is not None:
        outcome = "wins" if trick_winner(lead, chosen, trump) == 1 else "loses"
        parts.append(f"{card_name(chosen)} {outcome} it - {why_trick(lead, chosen, trump)}")
    else:
        parts.append(f"you led {card_name(chosen)} and {why_lead(chosen, unseen, trump)}")

    significant = cost > 2 * stderr and cost > 1e-9
    if cost <= 1e-9:
        parts.append("nothing else scored better on what you could see")
    else:
        names = " or ".join(card_name(c) for c in best)
        parts.append(f"{names} averaged {plural(cost)} more across "
                     f"{len(per_action[chosen])} consistent deals")
        alt = best[0]
        if lead is not None:
            alt_outcome = "wins" if trick_winner(lead, alt, trump) == 1 else "loses"
            parts.append(f"because {card_name(alt)} {alt_outcome} the trick instead"
                         if alt_outcome != outcome
                         else "with the same result on this trick, so the gain is in what "
                              "it keeps back")
        else:
            mine, theirs = exposure(chosen, unseen, trump), exposure(alt, unseen, trump)
            parts.append(
                f"because {theirs} unseen cards beat {card_name(alt)} where only {mine} "
                f"beat {card_name(chosen)}" if mine != theirs else
                f"which is equally exposed - {mine} unseen cards beat either - so the gain "
                f"is in what it keeps back")

    return {
        "kind": "play", "round": event["round"], "trick": event["trick"],
        "chosen": chosen, "best": best, "cost": cost, "stderr": stderr,
        "significant": significant, "samples": len(per_action[chosen]),
        "values": {c: round(m, 2) for c, m in sorted(means.items())},
        "explanation": "; ".join(parts) + ".",
    }


# --------------------------------------------------------------------------- bid review

def review_bid(event: dict, unseen, samples: int | None = None, seed: int = 0) -> dict:
    """Score one bid against the best bid available on the information at the time.

    When we bid first the opponent's bid is unknown, so the objective is our own expected
    score. When we bid second it is already on the table, so the objective is the real score
    differential — and the hook has already removed a bid from our options.
    """
    trump, hand, legal = event["trump"], event["hand"], event["legal"]
    opp_bid, leads, chosen = event["opp_bid"], event["leads"], event["chosen"]
    size = len(hand)

    count = samples if samples is not None else samples_for(size)
    dd = DoubleDummy(trump, tricks_payoff)
    rng = random.Random(seed)
    counts = [
        int(round(dd.value(hand, opponent, a_to_move=leads)))
        for opponent in consistent_hands(unseen, size, frozenset(), count, rng)
    ]
    if not counts:
        return {"kind": "bid", "round": event["round"], "trick": None, "chosen": chosen,
                "best": [chosen], "cost": 0.0, "stderr": 0.0, "significant": False,
                "samples": 0, "explanation": "no consistent opponent hand could be sampled."}

    per_action = {
        b: [float(round_score(b, t)) if opp_bid is None
            else float(round_score(b, t) - round_score(opp_bid, size - t))
            for t in counts]
        for b in legal
    }
    means, best, cost, stderr = _paired_stats(per_action, chosen)

    average = sum(counts) / len(counts)
    mode = max(set(counts), key=counts.count)
    share = counts.count(mode) / len(counts)
    basis = ("your own expected score - they had not bid yet" if opp_bid is None
             else "the score differential, against the bid they had already made")

    parts = [f"across {len(counts)} deals consistent with what you could see, this hand "
             f"averaged {average:.1f} tricks, most often {mode} ({share:.0%})"]
    parts.append(f"you bid {chosen}")
    if mode not in legal:
        parts.append(f"the hook denied you {mode}, the most likely count")
    significant = cost > 2 * stderr and cost > 1e-9
    if cost <= 1e-9:
        parts.append(f"that was the best bid available, judged on {basis}")
    else:
        parts.append(f"bidding {' or '.join(str(b) for b in best)} was worth "
                     f"{plural(cost)} more, judged on {basis}")

    return {
        "kind": "bid", "round": event["round"], "trick": None,
        "chosen": chosen, "best": best, "cost": cost, "stderr": stderr,
        "significant": significant, "samples": len(counts),
        "expected_tricks": average, "likely_tricks": mode,
        "values": {b: round(m, 2) for b, m in sorted(means.items())},
        "explanation": "; ".join(parts) + ".",
    }
