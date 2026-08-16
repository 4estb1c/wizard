"""Play Up the River against a bot, from the terminal.

    python play.py                       # quick game: ladder to 4, 8 rounds
    python play.py --peak 8              # the full 16-round game
    python play.py --opponent pimc-24    # a harder bot
    python play.py --no-review           # skip the post-game analysis

Every decision is written to a JSONL log under ``games/`` as it happens, straight from the
engine's own event hook, so the log cannot drift from what was actually played. The log holds
both hands, which is what lets the post-game review solve each position exactly — during play
you only ever see your own.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from agents import ROSTER
from agents.base import Agent
from engine import (DECK_SIZE, NO_TRUMP, NUM_RANKS, NUM_SUITS, card_name, is_jester,
                    is_wizard, ladder_for, play_match, suit_of)

GAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games")


def enable_utf8() -> None:
    """Ask for UTF-8 on stdout so suit symbols render instead of turning into noise.

    Windows consoles default to a legacy codepage that cannot encode the suit glyphs or an
    em-dash. Reconfiguring is best-effort; :func:`_suits` re-checks afterwards and falls back
    to letters if it did not take.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


enable_utf8()

_RANK_TEXT = ("10", "J", "Q", "K", "A")
_SUIT_UNICODE = ("♠", "♥", "♦", "♣")
_SUIT_ASCII = ("S", "H", "D", "C")

#: Difficulty labels, easiest first. The default is a searching bot small enough to stay
#: quick at the table but strong enough that sloppy bidding gets punished.
OPPONENTS = {
    "random": "barely plays",
    "heuristic": "no search, plays sensibly",
    "pimc-8": "searches; moderate",
    "pimc-24": "searches harder; strong",
    "pimc-64": "the strongest here, and slow",
}


def _suits():
    try:
        "".join(_SUIT_UNICODE).encode(sys.stdout.encoding or "ascii")
        return _SUIT_UNICODE
    except (UnicodeEncodeError, LookupError):
        return _SUIT_ASCII


SUIT_TEXT = _suits()


def show(card: int) -> str:
    if is_wizard(card):
        return "Wz"
    if is_jester(card):
        return "Je"
    return _RANK_TEXT[card % NUM_RANKS] + SUIT_TEXT[card // NUM_RANKS]


def show_hand(cards) -> str:
    return "  ".join(show(c) for c in sorted(cards, key=lambda c: (suit_of(c), c)))


def trump_text(trump: int) -> str:
    return "none" if trump == NO_TRUMP else SUIT_TEXT[trump]


# --------------------------------------------------------------------------- input

def ask(prompt: str, options: list[str]) -> int:
    """Prompt until the answer matches one of `options` by index or by label."""
    lowered = [o.lower() for o in options]
    while True:
        try:
            raw = input(prompt).strip().lower()
        except EOFError:
            print("\n(input closed)")
            raise SystemExit(1)
        if raw in ("q", "quit", "exit"):
            print("Resigning — the log is still on disk.")
            raise SystemExit(0)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        if raw in lowered:
            return lowered.index(raw)
        print(f"  please answer 1-{len(options)}, or one of: {', '.join(options)}")


# --------------------------------------------------------------------------- the player

class HumanAgent(Agent):
    """Prompts a person. Sees exactly what any other agent sees — the View, and nothing else."""

    def __init__(self, name: str = "you"):
        super().__init__(name)
        self._round_shown = -1
        self._total_rounds = 0

    def reset(self) -> None:
        self._round_shown = -1

    def _round_header(self, view) -> None:
        if view.round_index == self._round_shown:
            return
        self._round_shown = view.round_index
        total = self._total_rounds or "?"
        role = "You deal — you bid second and they lead." if view.i_am_dealer \
            else "They deal — you bid first and you lead."
        print(f"\n{'=' * 62}")
        print(f"Round {view.round_index + 1} of {total}   |   {view.hand_size} card"
              f"{'s' if view.hand_size != 1 else ''} each   |   "
              f"score  you {view.my_match_score}  them {view.opp_match_score}")
        print(f"Trump: {trump_text(view.trump)}"
              f"{'' if view.trump_card is None else f'  (flipped {show(view.trump_card)})'}"
              f"   |   {role}")
        print("=" * 62)

    def choose_trump(self, view) -> int:
        self._round_header(view)
        print(f"\nA Wizard was flipped, so you name trump.\nYour hand:  {show_hand(view.hand)}")
        labels = [SUIT_TEXT[s] for s in range(NUM_SUITS)]
        print("  " + "   ".join(f"{i + 1}) {label}" for i, label in enumerate(labels)))
        return ask("Name trump > ", labels)

    def bid(self, view, legal):
        self._round_header(view)
        print(f"\nYour hand:  {show_hand(view.hand)}")
        if view.opp_bid is not None:
            forbidden = view.hand_size - view.opp_bid
            print(f"They bid {view.opp_bid}.  The hook forbids you {forbidden}.")
        options = [str(b) for b in legal]
        print(f"Legal bids: {', '.join(options)}")
        return legal[ask("Your bid > ", options)]

    def play(self, view, legal):
        need = view.my_bid - view.my_tricks
        print(f"\n--- Trick {view.tricks_played + 1} of {view.hand_size} ---  "
              f"bid {view.my_bid}, taken {view.my_tricks} "
              f"({'need ' + str(need) if need > 0 else 'need no more'})   "
              f"| they bid {view.opp_bid}, taken {view.opp_tricks}")
        if view.lead_card is not None:
            print(f"They lead {show(view.lead_card)}.")
        else:
            print("You lead.")
        if len(legal) == 1:
            print(f"Only legal card: {show(legal[0])}")
            return legal[0]
        ordered = sorted(legal, key=lambda c: (suit_of(c), c))
        print("  " + "   ".join(f"{i + 1}) {show(c)}" for i, c in enumerate(ordered)))
        held = sorted(set(view.hand) - set(legal), key=lambda c: (suit_of(c), c))
        if held:
            print(f"  (must follow suit — cannot play {show_hand(held)})")
        return ordered[ask("Your card > ", [show(c) for c in ordered])]


# --------------------------------------------------------------------------- logging

class GameLogger:
    """Appends one JSON record per engine event, and narrates the table as it goes."""

    def __init__(self, path: str, meta: dict, human_seat: int, narrate: bool = True):
        self.path = path
        self.human = human_seat
        self.narrate = narrate
        self._file = open(path, "w", encoding="utf-8")
        self._write({"type": "game_start", "ts": time.time(), **meta})

    def _write(self, record: dict) -> None:
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()

    def __call__(self, event: dict) -> None:
        self._write(event)
        if not self.narrate:
            return
        if event["type"] == "trick_end":
            lead, follow = event["lead_card"], event["follow_card"]
            mine, theirs = (lead, follow) if event["leader"] == self.human else (follow, lead)
            took = "You take it" if event["winner"] == self.human else "They take it"
            print(f"  you {show(mine)}  |  them {show(theirs)}  ->  {took}"
                  f"   ({event['tricks'][self.human]}-{event['tricks'][1 - self.human]})")
        elif event["type"] == "round_end":
            me, them = self.human, 1 - self.human
            verdict = ("you made it" if event["tricks"][me] == event["bids"][me]
                       else "you missed")
            print(f"\n  Round over: you bid {event['bids'][me]} took {event['tricks'][me]}"
                  f" ({verdict}, {event['scores'][me]:+d}) | "
                  f"them bid {event['bids'][them]} took {event['tricks'][them]}"
                  f" ({event['scores'][them]:+d})")

    def finish(self, result, human_seat: int) -> None:
        self._write({
            "type": "game_end", "ts": time.time(),
            "scores": list(result.scores),
            "human_score": result.scores[human_seat],
            "opponent_score": result.scores[1 - human_seat],
        })
        self._file.close()


# --------------------------------------------------------------------------- driver

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--peak", type=int, default=4,
                        help="highest hand size; 4 is a quick game, 8 the full one")
    parser.add_argument("--opponent", default="pimc-8", choices=sorted(OPPONENTS),
                        help="; ".join(f"{k}: {v}" for k, v in OPPONENTS.items()))
    parser.add_argument("--seed", type=int, default=None, help="replay a specific deal")
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="log without narrating tricks")
    args = parser.parse_args()

    if 2 * args.peak >= DECK_SIZE:
        parser.error(f"--peak must be under {DECK_SIZE // 2}")

    ladder = ladder_for(args.peak)
    seed = args.seed if args.seed is not None else int(time.time() * 1000) & 0x7FFFFFFF

    os.makedirs(GAMES_DIR, exist_ok=True)
    path = os.path.join(GAMES_DIR, f"game-{time.strftime('%Y%m%d-%H%M%S')}-{seed}.jsonl")

    human = HumanAgent()
    human._total_rounds = len(ladder)
    bot = ROSTER[args.opponent]()
    bot.seed(seed ^ 0x5EED)

    print(f"\nUp the River — heads-up, {DECK_SIZE}-card deck")
    print(f"Ladder: {', '.join(str(s) for s in ladder)}   ({len(ladder)} rounds, "
          f"{sum(ladder)} tricks)")
    print(f"Opponent: {args.opponent} ({OPPONENTS[args.opponent]})")
    print(f"Log: {os.path.relpath(path)}")
    print("Answer with the number next to a choice. 'q' resigns.")

    logger = GameLogger(path, {
        "seed": seed, "opponent": args.opponent, "human_seat": 0,
        "ladder": list(ladder), "deck_size": DECK_SIZE,
    }, human_seat=0, narrate=not args.quiet)

    result = play_match(human, bot, seed, ladder=ladder, on_event=logger)
    logger.finish(result, human_seat=0)

    mine, theirs = result.scores
    verdict = "You win." if mine > theirs else "You lose." if mine < theirs else "A draw."
    print(f"\n{'=' * 62}\nFINAL   you {mine}   them {theirs}   —  {verdict}")
    print(f"Log written to {os.path.relpath(path)}")

    if not args.no_review:
        from review import review_log
        review_log(path)
    else:
        print(f"Review it later with:  python review.py {os.path.relpath(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
