"""Strategies for heads-up Up the River."""
from agents.base import Agent
from agents.heuristic_bot import HeuristicBot
from agents.pimc_bot import PIMCBot
from agents.random_bot import RandomBot
from agents.simple_bots import (ContractBot, CountBot, DuckBot, GrabBot, SpecialsBot)

__all__ = ["Agent", "HeuristicBot", "PIMCBot", "RandomBot",
           "DuckBot", "GrabBot", "SpecialsBot", "CountBot", "ContractBot",
           "ROSTER", "build_roster"]


#: The ranked population. Each entry is ``(name, factory)``.
#:
#: The cheating oracle in ``oracle.py`` is deliberately absent: it reads the opponent's hand,
#: so including it would let it farm the population and distort both the dominance filter and
#: the Nash mixture. It is a measuring instrument, not a competitor.
ROSTER: dict[str, callable] = {
    "random":        lambda: RandomBot(name="random"),
    # One-sentence rules, in rough order of how much they know. Neighbouring pairs differ by
    # exactly one idea, so the gap between two rows is the price of that idea.
    "duck":          lambda: DuckBot(name="duck"),
    "grab":          lambda: GrabBot(name="grab"),
    "specials":      lambda: SpecialsBot(name="specials"),
    "count":         lambda: CountBot(name="count"),
    "contract":      lambda: ContractBot(name="contract"),
    "heuristic":     lambda: HeuristicBot(name="heuristic"),
    "pimc-8":        lambda: PIMCBot(samples=8, name="pimc-8"),
    "pimc-24":       lambda: PIMCBot(samples=24, name="pimc-24"),
    "pimc-64":       lambda: PIMCBot(samples=64, name="pimc-64"),
    "pimc-24-veto":  lambda: PIMCBot(samples=24, veto=1.0, name="pimc-24-veto"),
    "pimc-24-infer": lambda: PIMCBot(samples=24, infer=True, name="pimc-24-infer"),
}


def build_roster(names=None) -> list[tuple[str, callable]]:
    """Return ``[(name, factory)]`` for `names`, or the whole roster in declaration order."""
    if names is None:
        return list(ROSTER.items())
    missing = [n for n in names if n not in ROSTER]
    if missing:
        raise KeyError(f"unknown strategies: {missing}; available: {sorted(ROSTER)}")
    return [(n, ROSTER[n]) for n in names]
