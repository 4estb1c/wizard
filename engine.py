"""Up the River — heads-up game engine. See RULES.md for the rules this implements.

Cards are plain ints so the double-dummy solver can pack hands into bitmasks. The layout is
derived from the constants below, so changing the deck is a one-line edit:

    0..19   normal cards, ``suit = c // NUM_RANKS``, ``rank = c % NUM_RANKS`` (0=10 … 4=A)
    20,21   Wizards
    22,23   Jesters

With *two* of each special, the two clauses that a single-Wizard deck leaves unreachable
both come alive: "the first Wizard played wins" and "if both cards are Jesters, the leader
wins". The consequence is that the specials stop being absolute and become
position-dependent, in mirrored ways:

    Wizard led    -> always wins        Wizard followed -> loses to a Wizard lead
    Jester led    -> loses *unless* the opponent also plays a Jester
    Jester followed -> always loses

So on lead the Wizard is the certain card and the Jester is not; on defence the Jester is
certain and the Wizard is not.

Randomness is deliberately not taken from the global ``random`` module. The deal comes from
a dedicated stream keyed on the deal seed, and each agent gets its own ``random.Random``
via :meth:`agents.base.Agent.seed`. That keeps a match reproducible from ``(seed,
agent_seeds)`` alone and lets the two seat orders of a pairing replay the identical deal.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

# --------------------------------------------------------------------------- deck

NUM_SUITS = 4
NUM_RANKS = 5          # 10 J Q K A
NUM_WIZARDS = 2
NUM_JESTERS = 2

NUM_NORMAL = NUM_SUITS * NUM_RANKS            # 20
FIRST_WIZARD = NUM_NORMAL                     # 20
FIRST_JESTER = FIRST_WIZARD + NUM_WIZARDS     # 22
DECK_SIZE = FIRST_JESTER + NUM_JESTERS        # 24
DECK = tuple(range(DECK_SIZE))

WIZARDS = tuple(range(FIRST_WIZARD, FIRST_JESTER))
JESTERS = tuple(range(FIRST_JESTER, DECK_SIZE))

NO_TRUMP = -1

#: Highest hand size. The peak deals ``2 * PEAK`` cards and needs one more for the trump
#: flip, so ``2 * PEAK < DECK_SIZE`` must hold — at 8 that leaves 7 cards dead.
PEAK = 8

#: Hand size per round — up the river and back down, peak played twice so that strict
#: alternation gives each player every hand size exactly once.
LADDER = tuple(range(1, PEAK + 1)) + tuple(range(PEAK, 0, -1))

_SUIT_NAMES = "SHDC"
_RANK_NAMES = "TJQKA"   # T is the ten, kept to one character so every name is two wide

assert 2 * PEAK < DECK_SIZE, "the peak round must leave a card to flip for trump"


def is_wizard(card: int) -> bool:
    return FIRST_WIZARD <= card < FIRST_JESTER


def is_jester(card: int) -> bool:
    return card >= FIRST_JESTER


def suit_of(card: int) -> int:
    """Suit index of `card`, or -1 for a Wizard or Jester."""
    return card // NUM_RANKS if card < NUM_NORMAL else -1


def rank_of(card: int) -> int:
    """Rank index of `card` (0=10 … 4=A), or -1 for a Wizard or Jester."""
    return card % NUM_RANKS if card < NUM_NORMAL else -1


def card_name(card: int) -> str:
    """Both Wizards print as ``Wz`` and both Jesters as ``Je`` — they are interchangeable."""
    if is_wizard(card):
        return "Wz"
    if is_jester(card):
        return "Je"
    return _RANK_NAMES[card % NUM_RANKS] + _SUIT_NAMES[card // NUM_RANKS]


def hand_str(cards) -> str:
    return " ".join(card_name(c) for c in sorted(cards))


# --------------------------------------------------------------------------- trick rules

def legal_plays(hand, lead_card: int | None) -> tuple[int, ...]:
    """Cards in `hand` that may legally be played.

    You must follow the led suit when you hold it — except that the Wizard and Jester are
    always legal, whatever else you hold. When the leader played a Wizard or a Jester there
    is no led suit at all, so the follower is unconstrained.
    """
    if lead_card is None:
        return tuple(hand)
    led = suit_of(lead_card)
    if led < 0:  # Wizard or Jester led: no suit is established
        return tuple(hand)
    follow = [c for c in hand if c < NUM_NORMAL and (c // NUM_RANKS) == led]
    if not follow:
        return tuple(hand)
    return tuple(follow + [c for c in hand if c >= NUM_NORMAL])


def trick_winner(lead_card: int, follow_card: int, trump: int) -> int:
    """Return 0 if the leader wins the trick, 1 if the follower does.

    Precedence: Wizard, then trump, then the led suit. The order of the tests is what
    encodes the two duplicate-card rules — a Wizard lead is checked before a Wizard follow,
    so the first Wizard played wins; a Jester follow is checked before a Jester lead, so two
    Jesters go to the leader.
    """
    if is_wizard(lead_card):
        return 0
    if is_wizard(follow_card):
        return 1
    if is_jester(follow_card):
        return 0
    if is_jester(lead_card):
        return 1

    led_suit, follow_suit = lead_card // NUM_RANKS, follow_card // NUM_RANKS
    if trump >= 0:
        if follow_suit == trump and led_suit != trump:
            return 1
        if led_suit == trump and follow_suit != trump:
            return 0
    if follow_suit == led_suit and (follow_card % NUM_RANKS) > (lead_card % NUM_RANKS):
        return 1
    return 0


# --------------------------------------------------------------------------- scoring

def round_score(bid: int, tricks: int) -> int:
    """Points for one round: 2 + tricks when the bid is made exactly, else minus the miss."""
    return 2 + tricks if tricks == bid else -abs(tricks - bid)


def legal_bids(hand_size: int, is_dealer: bool, opp_bid: int | None) -> tuple[int, ...]:
    """Bids available to a player. The dealer may not make the two bids total `hand_size`.

    That single forbidden number is what guarantees at most one player can make their bid in
    any round, since tricks taken always sum to `hand_size`.
    """
    everything = range(hand_size + 1)
    if not is_dealer or opp_bid is None:
        return tuple(everything)
    forbidden = hand_size - opp_bid
    return tuple(b for b in everything if b != forbidden)


# --------------------------------------------------------------------------- views

@dataclass(frozen=True)
class View:
    """Everything one player may legally know at a decision point.

    Constructed fresh for every call, and holds only public information plus the acting
    player's own hand. Notably absent: the opponent's hand and the undealt cards, which stay
    hidden all round — the three dead cards at the peak are never revealed even after play.
    """
    round_index: int              # 0..13, position on the ladder
    hand_size: int                # tricks this round
    hand: tuple[int, ...]         # my remaining cards
    trump: int                    # suit index, or NO_TRUMP
    trump_card: int               # the flipped card that set trump (public all round)
    i_am_dealer: bool
    my_bid: int | None            # None while bidding
    opp_bid: int | None           # None until they have bid
    my_tricks: int
    opp_tricks: int
    tricks_played: int
    i_lead: bool                  # am I leading the current trick
    lead_card: int | None         # their card, if I am following
    # Completed tricks this round, from *my* point of view: (i_led, my_card, their_card).
    # Deliberately not seat-indexed — an agent is never told which seat it occupies.
    history: tuple[tuple[bool, int, int], ...]
    my_match_score: int
    opp_match_score: int
    rounds_left: int              # rounds after this one

    @property
    def tricks_left(self) -> int:
        return self.hand_size - self.tricks_played

    @property
    def unseen(self) -> tuple[int, ...]:
        """Cards whose location I do not know: opponent's hand plus the dead stock.

        Excludes my hand, the trump card, and every card already played.
        """
        seen = set(self.hand)
        seen.add(self.trump_card)
        for _, mine, theirs in self.history:
            seen.add(mine)
            seen.add(theirs)
        if self.lead_card is not None:
            seen.add(self.lead_card)
        return tuple(c for c in DECK if c not in seen)

    @property
    def opp_hand_size(self) -> int:
        """How many cards the opponent still holds."""
        played_by_them = self.tricks_played + (1 if self.lead_card is not None else 0)
        return self.hand_size - played_by_them


# --------------------------------------------------------------------------- results

@dataclass
class RoundResult:
    round_index: int
    hand_size: int
    dealer: int
    trump: int
    trump_card: int
    bids: tuple[int, int]
    tricks: tuple[int, int]
    scores: tuple[int, int]
    hands_dealt: tuple[tuple[int, ...], tuple[int, ...]]  # as dealt, before any card is played


@dataclass
class MatchResult:
    scores: tuple[int, int]
    rounds: list[RoundResult]

    @property
    def winner(self) -> int:
        """0, 1, or -1 for a draw."""
        if self.scores[0] > self.scores[1]:
            return 0
        if self.scores[1] > self.scores[0]:
            return 1
        return -1

    @property
    def margin(self) -> int:
        return self.scores[0] - self.scores[1]


# --------------------------------------------------------------------------- play

def deal(hand_size: int, rng: random.Random):
    """Shuffle and deal one round. Returns ``(hand0, hand1, trump_card)``.

    The stock beyond the flipped card is never used and never revealed — it is the hidden
    information that keeps even the peak round from collapsing into a solved position.
    """
    cards = list(DECK)
    rng.shuffle(cards)
    hand0 = tuple(sorted(cards[:hand_size]))
    hand1 = tuple(sorted(cards[hand_size:2 * hand_size]))
    return hand0, hand1, cards[2 * hand_size]


def _make_view(*, round_index, hand_size, hand, trump, trump_card, is_dealer, my_bid,
               opp_bid, my_tricks, opp_tricks, tricks_played, i_lead, lead_card, history,
               my_score, opp_score, rounds_left) -> View:
    return View(
        round_index=round_index, hand_size=hand_size, hand=tuple(sorted(hand)),
        trump=trump, trump_card=trump_card, i_am_dealer=is_dealer, my_bid=my_bid,
        opp_bid=opp_bid, my_tricks=my_tricks, opp_tricks=opp_tricks,
        tricks_played=tricks_played, i_lead=i_lead, lead_card=lead_card,
        history=tuple(history), my_match_score=my_score, opp_match_score=opp_score,
        rounds_left=rounds_left,
    )


def ladder_for(peak: int) -> tuple[int, ...]:
    """Up-and-down ladder to `peak`, playing the peak twice so the deal stays balanced."""
    if 2 * peak >= DECK_SIZE:
        raise ValueError(f"peak {peak} leaves no card to flip for trump in a "
                         f"{DECK_SIZE}-card deck")
    return tuple(range(1, peak + 1)) + tuple(range(peak, 0, -1))


def play_round(agents, hand_size: int, dealer: int, rng: random.Random, *,
               round_index: int = 0, match_scores=(0, 0), rounds_left: int = 0,
               on_event=None) -> RoundResult:
    """Deal, set trump, take both bids, play out the tricks, and score.

    Args:
        agents: ``[agent0, agent1]``.
        dealer: Which seat deals. The non-dealer bids first and leads the first trick.
        on_event: Optional ``callable(dict)`` receiving one record per decision and per
            resolved trick. It sees both hands, so it is a spectator channel for logging and
            review, never something an agent may be wired to. Emitting from inside the loop
            is what keeps a game log from drifting away from what the engine actually did.

    Returns:
        A :class:`RoundResult` with both players' bids, tricks and points.
    """
    def emit(kind: str, **fields) -> None:
        if on_event is not None:
            on_event({"type": kind, "round": round_index, **fields})
    lead_seat = 1 - dealer
    hands = list(deal(hand_size, rng))
    trump_card = hands.pop()
    dealt = (hands[0], hands[1])  # snapshot before play empties the working sets
    hands = [set(hands[0]), set(hands[1])]
    history: list[tuple[int, int, int]] = []  # (leader_seat, lead_card, follow_card)

    def view(seat, **kw):
        # History is rewritten from `seat`'s point of view so no agent ever learns which
        # seat it occupies — only whether it led each trick and what the two cards were.
        mine = tuple(
            (leader == seat, lead if leader == seat else follow,
             follow if leader == seat else lead)
            for leader, lead, follow in history
        )
        return _make_view(
            round_index=round_index, hand_size=hand_size, hand=hands[seat],
            trump=kw.pop("trump"), trump_card=trump_card, is_dealer=(seat == dealer),
            my_score=match_scores[seat], opp_score=match_scores[1 - seat],
            rounds_left=rounds_left, history=mine, **kw,
        )

    # -- trump -------------------------------------------------------------
    if is_jester(trump_card):
        trump = NO_TRUMP
    elif is_wizard(trump_card):
        # Dealer names trump before either bid — which in a two-player game leaks the shape
        # of their hand to the only opponent there is.
        pick = agents[dealer].choose_trump(view(
            dealer, trump=NO_TRUMP, my_bid=None, opp_bid=None, my_tricks=0, opp_tricks=0,
            tricks_played=0, i_lead=(dealer == lead_seat), lead_card=None,
        ))
        trump = pick if 0 <= pick < NUM_SUITS else 0
    else:
        trump = trump_card // NUM_RANKS

    # -- measurement hook --------------------------------------------------
    # Any agent defining `reveal` is handed both hands from its own perspective, after the
    # deal and before any decision. This exists solely for the double-dummy oracle in
    # oracle.py, which is a measuring instrument and never a member of the ranked roster.
    # Ordinary strategies do not define it and see nothing.
    for seat in (0, 1):
        peek = getattr(agents[seat], "reveal", None)
        if peek is not None:
            peek(tuple(sorted(hands[seat])), tuple(sorted(hands[1 - seat])), trump)

    emit("round_start", hand_size=hand_size, dealer=dealer, trump=trump,
         trump_card=trump_card, hands=[list(dealt[0]), list(dealt[1])])

    # -- bidding -----------------------------------------------------------
    bids: list[int | None] = [None, None]
    for seat in (lead_seat, dealer):
        options = legal_bids(hand_size, seat == dealer, bids[1 - seat])
        choice = agents[seat].bid(view(
            seat, trump=trump, my_bid=None, opp_bid=bids[1 - seat], my_tricks=0,
            opp_tricks=0, tricks_played=0, i_lead=(seat == lead_seat), lead_card=None,
        ), options)
        bids[seat] = choice if choice in options else options[0]
        emit("bid", seat=seat, legal=list(options), chosen=bids[seat],
             opp_bid=bids[1 - seat], hand=sorted(hands[seat]),
             opp_hand=sorted(hands[1 - seat]), leads=(seat == lead_seat),
             trump=trump, trump_card=trump_card)

    # -- play --------------------------------------------------------------
    tricks = [0, 0]
    leader = lead_seat

    for played in range(hand_size):
        follower = 1 - leader
        cards: dict[int, int] = {}

        def act(seat: int, lead_card: int | None) -> int:
            options = legal_plays(hands[seat], lead_card)
            before = sorted(hands[seat])
            choice = agents[seat].play(view(
                seat, trump=trump, my_bid=bids[seat], opp_bid=bids[1 - seat],
                my_tricks=tricks[seat], opp_tricks=tricks[1 - seat], tricks_played=played,
                i_lead=(lead_card is None), lead_card=lead_card,
            ), options)
            if choice not in options:
                choice = options[0]
            emit("play", trick=played, seat=seat, legal=list(options), chosen=choice,
                 lead_card=lead_card, hand=before, opp_hand=sorted(hands[1 - seat]),
                 my_tricks=tricks[seat], opp_tricks=tricks[1 - seat],
                 bids=[bids[0], bids[1]], trump=trump)
            hands[seat].discard(choice)
            return choice

        cards[leader] = act(leader, None)
        cards[follower] = act(follower, cards[leader])

        won_by_follower = trick_winner(cards[leader], cards[follower], trump)
        winner = follower if won_by_follower else leader
        tricks[winner] += 1
        history.append((leader, cards[leader], cards[follower]))
        emit("trick_end", trick=played, leader=leader, lead_card=cards[leader],
             follow_card=cards[follower], winner=winner, tricks=[tricks[0], tricks[1]])
        leader = winner

    scores = (round_score(bids[0], tricks[0]), round_score(bids[1], tricks[1]))
    emit("round_end", bids=[bids[0], bids[1]], tricks=[tricks[0], tricks[1]],
         scores=list(scores))
    return RoundResult(
        round_index=round_index, hand_size=hand_size, dealer=dealer, trump=trump,
        trump_card=trump_card, bids=(bids[0], bids[1]), tricks=(tricks[0], tricks[1]),
        scores=scores, hands_dealt=dealt,
    )


def play_match(agent0, agent1, seed: int, *, ladder=LADDER, on_event=None) -> MatchResult:
    """Play a full ladder. Seat 0 deals round 0, and the deal alternates from there.

    The deal for round *i* is drawn from a stream keyed on ``(seed, i)`` and nothing else,
    so calling this with the agents swapped replays the identical cards with the roles
    reversed — an exact mirror, which is what makes a pairing a paired comparison.
    """
    agents = [agent0, agent1]
    for agent in agents:
        agent.reset()

    totals = [0, 0]
    rounds: list[RoundResult] = []
    for index, hand_size in enumerate(ladder):
        rng = random.Random((seed * 1000003) ^ (index * 2654435761))
        result = play_round(
            agents, hand_size, dealer=index % 2, rng=rng, round_index=index,
            match_scores=(totals[0], totals[1]), rounds_left=len(ladder) - index - 1,
            on_event=on_event,
        )
        totals[0] += result.scores[0]
        totals[1] += result.scores[1]
        rounds.append(result)

    return MatchResult(scores=(totals[0], totals[1]), rounds=rounds)
