"""Post-game analysis of a logged game, judged on what you could see at the time.

    python review.py games/game-20260816-120000-12345.jsonl
    python review.py games/....jsonl --all        # every decision, not just costly ones
    python review.py games/....jsonl --samples 200

Every decision is scored against the best action available **on the information you had** —
your hand, the trump card, the bids, the cards played, and the suits the opponent has shown a
void in. Opponent hands are sampled from everything consistent with that, and each candidate
is scored as its average across those samples.

This deliberately does not use the double-dummy optimum. Both hands are in the log, so the
exact best line is computable after the fact, but marking you down for not seeing through the
back of the cards produces advice you could never have followed. The opponent's actual cards
are read for one thing only: how many of them there were.

Costs are averages, so they carry sampling noise. Candidates are evaluated on identical
sampled hands, making the comparison paired, and a decision is only reported as costly when
its cost clears twice the standard error of that paired difference.
"""
from __future__ import annotations

import argparse
import json
import sys

from engine import DECK, NUM_NORMAL, card_name, suit_of
from explain import review_bid, review_play
from play import enable_utf8

enable_utf8()


def load(path: str) -> tuple[dict, list[dict]]:
    events, meta = [], {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record["type"] == "game_start":
                meta = record
            events.append(record)
    if not meta:
        raise SystemExit(f"{path}: no game_start record - not a game log")
    return meta, events


def _unseen(hand, trump_card: int, played: set[int], lead_card=None) -> list[int]:
    """Cards whose location you could not know: their hand plus the dead stock.

    The dead stock is never revealed — seven cards at the peak — which is why this stays
    large all the way to the last trick, and why the reference is a genuine average over
    possibilities rather than a near-certainty dressed up as one.
    """
    seen = set(hand) | {trump_card} | played
    if lead_card is not None:
        seen.add(lead_card)
    return [c for c in DECK if c not in seen]


def _void_from(trick: dict, seat: int) -> int | None:
    """The suit the opponent revealed a void in on this trick, if any.

    Only tricks *we* led carry the information, and only when they answered with a normal
    card: Wizards and Jesters are legal at any time, so discarding one reveals nothing.
    """
    if trick["leader"] != seat:
        return None
    led = suit_of(trick["lead_card"])
    follow = trick["follow_card"]
    if led < 0 or follow >= NUM_NORMAL or suit_of(follow) == led:
        return None
    return led


def review_log(path: str, show_all: bool = False, samples: int | None = None,
               out=sys.stdout) -> list[dict]:
    """Analyse every decision the human made in `path`, printing a report."""
    meta, events = load(path)
    seat = meta.get("human_seat", 0)

    entries: list[dict] = []
    trump_card: int | None = None
    played: set[int] = set()
    voids: set[int] = set()

    for event in events:
        kind = event["type"]
        if kind == "round_start":
            trump_card, played, voids = event["trump_card"], set(), set()
            continue
        if kind == "trick_end":
            played.add(event["lead_card"])
            played.add(event["follow_card"])
            void = _void_from(event, seat)
            if void is not None:
                voids.add(void)
            continue
        if event.get("seat") != seat or kind not in ("bid", "play"):
            continue

        seed = event["round"] * 101 + (event.get("trick") or 0)
        if kind == "play":
            unseen = _unseen(event["hand"], trump_card, played, event["lead_card"])
            entries.append(review_play(event, unseen, voids, samples, seed))
        else:
            unseen = _unseen(event["hand"], trump_card, set())
            entries.append(review_bid(event, unseen, samples, seed))

    bids = [e for e in entries if e["kind"] == "bid"]
    costly = [e for e in entries if e["significant"]]
    marginal = [e for e in entries if e["cost"] > 1e-9 and not e["significant"]]

    print(f"\n{'=' * 70}", file=out)
    print("POST-GAME REVIEW", file=out)
    print("judged only on what you could see at the time", file=out)
    print("=" * 70, file=out)
    print(f"  decisions analysed   {len(entries)}  "
          f"({len(bids)} bids, {len(entries) - len(bids)} plays)", file=out)
    print(f"  cost you something   {len(costly)}   "
          f"totalling {sum(e['cost'] for e in costly):.1f} points", file=out)
    print(f"  too close to call    {len(marginal)}   "
          f"(cost inside the sampling noise)", file=out)
    if bids:
        matched = sum(1 for e in bids if e["chosen"] == e["likely_tricks"])
        print(f"  bids matching the most likely trick count: {matched}/{len(bids)}",
              file=out)

    shown = entries if show_all else costly
    if not shown:
        print("\n  Nothing you could have known cost you a point. Anything that went wrong "
              "went wrong behind the cards.", file=out)
        return entries

    print(f"\n{'-' * 70}", file=out)
    print("Every decision, worst first" if show_all
          else "Decisions that cost more than the noise, worst first", file=out)
    print("-" * 70, file=out)

    for entry in sorted(shown, key=lambda e: (-e["cost"], e["round"])):
        where = (f"round {entry['round'] + 1}, bid" if entry["kind"] == "bid"
                 else f"round {entry['round'] + 1}, trick {entry['trick'] + 1}")
        label = card_name if entry["kind"] == "play" else str
        best = ", ".join(label(b) for b in entry["best"])
        if entry["cost"] <= 1e-9:
            verdict = "best available"
        else:
            verdict = (f"cost {entry['cost']:.1f} +/- {entry['stderr']:.1f}"
                       + ("" if entry["significant"] else "  (within noise)"))
        print(f"\n  {where}: played {label(entry['chosen'])}, best {best}   {verdict}",
              file=out)
        print(f"        {entry['explanation']}", file=out)

    if not show_all and len(entries) > len(shown):
        print(f"\n  ({len(entries) - len(shown)} other decisions cost nothing you could "
              f"have known about; --all shows them)", file=out)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", help="path to a games/*.jsonl log")
    parser.add_argument("--all", action="store_true",
                        help="show every decision, not only the costly ones")
    parser.add_argument("--samples", type=int, default=None,
                        help="determinizations per decision (default scales with hand size)")
    args = parser.parse_args()
    review_log(args.log, show_all=args.all, samples=args.samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
