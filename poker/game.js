/* Heads-up No-Limit Hold'em: the rules, the opponent, and the range model.
 *
 * Split out of the page so it can be driven headlessly by test_game.js. The betting rules
 * here are the real ones (min-raise increments, all-in for less, returned excess), because a
 * trainer that scores your decisions against a subtly wrong game is worse than no trainer.
 *
 * The honesty boundary in this project runs straight through this file:
 *
 *   core.js      exact      evaluation, equity by enumeration, pot arithmetic
 *   game.js      exact      the rules of the game
 *   game.js      MODELLED   what the opponent is holding (rangeAfter, botAction)
 *
 * Every equity this project reports is exact *given* a range, and every range is a model.
 * Those are different claims and the retro keeps them apart rather than blending them into a
 * single confident-looking number.
 */
(function (root) {
"use strict";

const P = (typeof require !== "undefined") ? require("./core.js") : root.Poker;

const SB = 50, BB = 100, START = 10000;          // 100bb effective
const STREETS = ["preflop", "flop", "turn", "river"];
const HERO = 0, BOT = 1;

/* Reproducible shuffling: a hand is a pure function of its seed, so a spot can be replayed
 * and a bug in the bot can be reproduced from the hand number alone. */
function mulberry(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffled(rand) {
  const d = [];
  for (let c = 0; c < 52; c++) d.push(c);
  for (let i = 51; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    const t = d[i]; d[i] = d[j]; d[j] = t;
  }
  return d;
}

/* --------------------------------------------------------------- preflop ranges
 *
 * Heads-up ranges are much wider than full-ring ones because there are only two players and
 * the button is posting the small blind: folding the button surrenders a blind every orbit.
 * These are conventional published-style ranges, not solver output, and the retro labels any
 * judgement that leans on them as a convention rather than a proof.
 */
const RANGES = {
  // Button (small blind) open-raises this, folds the rest. About 84% of hands.
  btnOpen: "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s," +
           "A2o+,K2o+,Q2o+,J4o+,T5o+,96o+,86o+,76o,65o",
  // Big blind facing that raise.
  bbThreeBet: "88+,A9s+,KTs+,QTs+,JTs,T9s,ATo+,KQo,A5s,A4s,76s,65s",
  bbCall:     "22+,A2s+,K2s+,Q4s+,J6s+,T6s+,96s+,86s+,75s+,64s+,54s," +
              "A2o+,K5o+,Q8o+,J8o+,T8o+,98o,87o",
  // Button facing a 3-bet.
  btnFourBet: "QQ+,AKs,AKo,A5s",
  btnCallThreeBet: "22+,A2s+,KTs+,QTs+,JTs,T9s,98s,ATo+,KQo",
};

const expanded = {};
for (const k in RANGES) expanded[k] = P.expandRange(RANGES[k]);

const comboKey = c => (c[0] < c[1] ? c[0] * 52 + c[1] : c[1] * 52 + c[0]);
function rangeSet(combos) {
  const s = new Set();
  for (const c of combos) s.add(comboKey(c));
  return s;
}
const ALL_COMBOS = (() => {
  const out = [];
  for (let a = 0; a < 52; a++) for (let b = a + 1; b < 52; b++) out.push([a, b]);
  return out;
})();

/* --------------------------------------------------------------- hand state */

function newHand(handNo, button, stacks, seed) {
  const rand = mulberry(seed === undefined ? handNo * 2654435761 : seed);
  const deck = shuffled(rand);
  const st = {
    handNo, button, rand,
    stacks: stacks ? stacks.slice() : [START, START],
    holes: [[deck[0], deck[2]], [deck[1], deck[3]]],
    deck: deck.slice(4),
    board: [],
    street: 0,
    pot: 0,                    // chips settled from previous streets
    bet: [0, 0],               // chips in front of each player this street
    committed: [0, 0],         // chips in from this player all hand
    lastRaise: BB,             // the current min-raise increment
    actedThisStreet: [false, false],
    aggressor: null,
    toAct: button,             // heads-up the button is SB and acts first preflop
    over: false,
    result: null,
    log: [],                   // every action, for the retro
    ranges: [null, null],      // what each player believes about the other
  };
  // Post the blinds. The button posts the small blind heads-up.
  post(st, button, SB);
  post(st, 1 - button, BB);
  st.ranges[HERO] = ALL_COMBOS.slice();   // what the bot believes hero holds
  st.ranges[BOT] = ALL_COMBOS.slice();    // what hero is told the bot holds
  return st;
}

function post(st, who, amount) {
  const put = Math.min(amount, st.stacks[who]);
  st.stacks[who] -= put;
  st.bet[who] += put;
  st.committed[who] += put;
}

const totalPot = st => st.pot + st.bet[0] + st.bet[1];
const toCall = (st, who) => Math.max(0, Math.max(st.bet[0], st.bet[1]) - st.bet[who]);
const allIn = (st, who) => st.stacks[who] === 0;
/* Nobody can win more than the shorter stack, so that is what a bet is really sized against. */
const effective = st => Math.min(st.stacks[0] + st.bet[0], st.stacks[1] + st.bet[1]);

function legalActions(st) {
  const me = st.toAct, opp = 1 - me;
  const need = toCall(st, me), stack = st.stacks[me];
  const out = [];
  if (need > 0) out.push({ type: "fold" });
  if (need === 0) out.push({ type: "check" });
  else out.push({ type: "call", amount: Math.min(need, stack) });

  // You can only raise if you have chips past the call and the opponent can still respond.
  if (stack > need && !allIn(st, opp)) {
    const highest = Math.max(st.bet[0], st.bet[1]);
    const minTo = Math.min(highest + st.lastRaise, st.bet[me] + stack);
    const maxTo = st.bet[me] + stack;
    out.push({ type: need === 0 ? "bet" : "raise", minTo, maxTo });
  }
  return out;
}

/* Apply `act` for the player to move. `act.to` is the total this street, not the increment,
 * which is how raises are quoted at a table and avoids an entire class of off-by-one. */
function applyAction(st, act) {
  const me = st.toAct;
  const before = { pot: totalPot(st), need: toCall(st, me), street: st.street };
  let record = { street: st.street, actor: me, type: act.type,
                 potBefore: before.pot, toCall: before.need,
                 stackBefore: st.stacks[me], board: st.board.slice() };

  if (act.type === "fold") {
    st.over = true;
    st.result = { winner: 1 - me, reason: "fold", pot: totalPot(st) };
    record.amount = 0;
  } else if (act.type === "check") {
    record.amount = 0;
  } else if (act.type === "call") {
    const put = Math.min(toCall(st, me), st.stacks[me]);
    post(st, me, put);
    record.amount = put;
  } else {
    const maxTo = st.bet[me] + st.stacks[me];
    const highest = Math.max(st.bet[0], st.bet[1]);
    const minTo = Math.min(highest + st.lastRaise, maxTo);
    const to = Math.max(minTo, Math.min(act.to, maxTo));
    const increment = to - highest;
    // A raise only resets the min-raise increment when it is a full one; an all-in for less
    // does not reopen the betting.
    if (increment >= st.lastRaise) st.lastRaise = increment;
    post(st, me, to - st.bet[me]);
    st.aggressor = me;
    record.amount = record.stackBefore - st.stacks[me];
    record.to = to;
  }
  record.potAfter = totalPot(st);
  if (act.note) record.note = act.note;
  if (act.why) record.why = act.why;
  // Narrow what the opponent may now believe about the actor. Done here rather than at each
  // call site so the bot's beliefs and the player's panel can never drift apart.
  st.ranges[me] = rangeAfter(st.ranges[me], record, record.board, me === st.button);
  record.oppRangeSize = st.ranges[1 - me].length;
  st.log.push(record);
  st.actedThisStreet[me] = true;

  if (!st.over) advance(st, me);
  return record;
}

function streetClosed(st) {
  const [a, b] = st.bet;
  const bothActed = st.actedThisStreet[0] && st.actedThisStreet[1];
  if (!bothActed) return false;
  if (a !== b) return false;                       // someone still owes chips
  return true;
}

function advance(st, justActed) {
  const opp = 1 - justActed;
  // If either player is all-in and the bets are level, there is nothing left to decide.
  if (streetClosed(st) || allIn(st, justActed) && toCall(st, opp) === 0 && st.actedThisStreet[opp]) {
    nextStreet(st);
    return;
  }
  st.toAct = opp;
  // A player with no chips cannot act; skip straight on when the other side is square.
  if (allIn(st, opp) && toCall(st, opp) === 0) nextStreet(st);
}

function nextStreet(st) {
  st.pot += st.bet[0] + st.bet[1];
  st.bet = [0, 0];
  st.actedThisStreet = [false, false];
  st.lastRaise = BB;
  st.aggressor = null;

  if (st.street === 3) { showdown(st); return; }
  st.street++;
  const draw = st.street === 1 ? 3 : 1;
  for (let i = 0; i < draw; i++) st.board.push(st.deck.pop());

  // Once someone is all-in the rest of the board just runs out.
  if (allIn(st, 0) || allIn(st, 1)) { nextStreet(st); return; }
  st.toAct = 1 - st.button;                        // postflop the button acts last
}

function showdown(st) {
  while (st.board.length < 5) st.board.push(st.deck.pop());
  const a = P.evaluate(st.holes[0].concat(st.board));
  const b = P.evaluate(st.holes[1].concat(st.board));
  st.over = true;
  st.result = { winner: a > b ? 0 : b > a ? 1 : -1, reason: "showdown",
                pot: totalPot(st), ranks: [a, b] };
}

/* Settle stacks. Heads-up there are no side pots, but an all-in for less means the deeper
 * player never risked their excess and must get it back. */
function settle(st) {
  const contested = Math.min(st.committed[0], st.committed[1]);
  for (const i of [0, 1]) st.stacks[i] += st.committed[i] - contested;
  const w = st.result.winner;
  if (w === -1) { st.stacks[0] += contested; st.stacks[1] += contested; }
  else st.stacks[w] += 2 * contested;
  st.result.net = [st.stacks[0] - START, st.stacks[1] - START];
  return st.stacks;
}

/* --------------------------------------------------------------- range model (MODELLED)
 *
 * Nothing below here is exact. It is a stated model of what a player holds given what they
 * did, and its only job is to be a defensible input to the exact equity machinery. The bot
 * consults it instead of looking at the cards, which test_game.js checks by construction.
 */

/* Made-hand strength plus a draw allowance, used only to sort a range. Draws are scored
 * because a flop range that ignores them prices semi-bluffs as pure air. */
function strengthOf(combo, board) {
  const made = P.evaluate(combo.concat(board));
  if (board.length >= 5) return made;
  const cards = combo.concat(board);
  const suits = [0, 0, 0, 0];
  let rmask = 0;
  for (const c of cards) { suits[c & 3]++; rmask |= 1 << (c >> 2); }
  let bonus = 0;
  if (Math.max(...suits) === 4) bonus += 1.6 * 371293;                  // flush draw
  const wheel = rmask | ((rmask >> 12) & 1);
  for (let top = 12; top >= 3; top--) {                                  // 4 to a straight
    let hits = 0;
    for (let i = 0; i < 5; i++) if (wheel & (1 << Math.max(0, top - i))) hits++;
    if (hits >= 4) { bonus += 1.1 * 371293; break; }
  }
  return made + bonus;
}

/* Narrow `range` to the fraction that would take this action, keeping the strongest when
 * continuing and the weakest when giving up. `keepTop` in [0,1]. */
function narrow(range, board, keepTop, fromTop) {
  if (keepTop >= 1) return range.slice();
  const scored = range.map(c => [strengthOf(c, board), c]);
  scored.sort((x, y) => y[0] - x[0]);
  const n = Math.max(1, Math.round(scored.length * keepTop));
  const picked = fromTop === false ? scored.slice(scored.length - n) : scored.slice(0, n);
  return picked.map(x => x[1]);
}

/* How the model updates after a player acts. Preflop it uses the published-style ranges
 * above; postflop it keeps a fraction of the range sorted by strength, with the fraction set
 * by the size they chose. Bigger bets mean narrower ranges, which is the one postflop
 * regularity strong enough to model in one line. */
function rangeAfter(range, rec, board, isRaiser) {
  if (rec.street === 0) {
    let key = null;
    if (rec.type === "raise" || rec.type === "bet") key = isRaiser ? "btnOpen" : "bbThreeBet";
    else if (rec.type === "call") key = isRaiser ? "btnCallThreeBet" : "bbCall";
    if (!key) return range.slice();
    const allow = rangeSet(expanded[key]);
    const hit = range.filter(c => allow.has(comboKey(c)));
    return hit.length ? hit : range.slice();
  }
  if (rec.type === "fold") return [];
  if (rec.type === "check") return narrow(range, board, 0.72, false);   // checks skew weak
  if (rec.type === "call") return narrow(range, board, 0.55, true);
  if (rec.type === "bet" || rec.type === "raise") {
    const size = rec.potBefore > 0 ? (rec.potAfter - rec.potBefore) / rec.potBefore : 1;
    const keep = size > 0.9 ? 0.28 : size > 0.55 ? 0.38 : 0.5;
    // A betting range is not purely the top of a range: it is polarised, so a slice of the
    // bottom comes along as bluffs at roughly the ratio the price makes indifferent.
    const value = narrow(range, board, keep, true);
    const bluffShare = P.bluffRatio(rec.potBefore, rec.potAfter - rec.potBefore);
    const bluffs = narrow(range, board, keep * bluffShare / (1 - bluffShare), false);
    const seen = new Set(value.map(comboKey));
    return value.concat(bluffs.filter(c => !seen.has(comboKey(c))));
  }
  return range.slice();
}

/* --------------------------------------------------------------- the opponent (MODELLED)
 *
 * Range-based rather than card-based: it computes its own exact equity against what it
 * believes you hold, then applies pot odds and defence frequencies. It never reads your
 * cards, so its mistakes are honest ones.
 */
function botAction(st) {
  const me = BOT, opp = HERO;
  const acts = legalActions(st);
  const need = toCall(st, me), pot = totalPot(st);
  const heroRange = st.ranges[HERO].length ? st.ranges[HERO] : ALL_COMBOS;
  const raise = acts.find(a => a.type === "bet" || a.type === "raise");
  const roll = st.rand();

  if (st.street === 0 && st.board.length === 0) {
    return preflopBot(st, acts, need, roll);
  }

  const eq = P.equityVsRange(st.holes[me], heroRange, st.board).share;
  const why = { eq, combos: heroRange.length };

  if (need > 0) {
    const price = P.requiredEquity(pot - need, need);
    why.price = price;
    // Raise for value only when well ahead of a calling range, which is tighter than the
    // range that bet in the first place.
    if (raise && eq > 0.80 && roll < 0.65) {
      return sized(st, raise, pot, 0.72, why, "value raise");
    }
    if (raise && eq < 0.22 && roll < 0.07 && st.street >= 2) {
      return sized(st, raise, pot, 0.85, why, "bluff raise");
    }
    if (eq >= price) return { type: "call", why, note: "the price is good enough" };
    // Defend down to the minimum defence frequency so a bluff does not print for free.
    const defend = P.mdf(pot - need, need);
    if (roll < defend * 0.45) return { type: "call", why, note: "defending to MDF" };
    return { type: "fold", why, note: "short of the price" };
  }

  if (raise) {
    if (eq > 0.68) return sized(st, raise, pot, eq > 0.85 ? 0.75 : 0.55, why, "value bet");
    // Bluff at roughly the frequency that makes a call indifferent at this size.
    const target = P.bluffRatio(pot, pot * 0.6);
    if (eq < 0.35 && roll < target) return sized(st, raise, pot, 0.6, why, "bluff");
  }
  return { type: "check", why, note: "not strong enough to bet, not weak enough to bluff" };
}

/* Every requested raise goes through here. Clamping only downward to maxTo lets a size fall
 * under the min re-raise, which applyAction then quietly corrects: no error, no symptom, and
 * a bot whose sizing is not the sizing it asked for. */
function clampTo(raise, want) {
  return Math.max(raise.minTo, Math.min(Math.round(want), raise.maxTo));
}

function sized(st, raise, pot, fraction, why, note) {
  return { type: raise.type, to: clampTo(raise, (st.bet[1 - st.toAct] || 0) + pot * fraction),
           why, note };
}

function preflopBot(st, acts, need, roll) {
  const cls = P.classOf(st.holes[BOT]);
  const inRange = key => expanded[key].some(c => P.classOf(c) === cls);
  const raise = acts.find(a => a.type === "bet" || a.type === "raise");
  const isButton = st.button === BOT;
  const why = { preflop: true, cls };

  if (isButton && need === SB) {                        // button first in
    if (inRange("btnOpen") && raise) return { type: "raise", to: clampTo(raise, BB * 2.5), why, note: `${cls} opens` };
    return { type: "fold", why, note: `${cls} is outside the button opening range` };
  }
  if (!isButton && need > 0) {                          // big blind facing a raise
    if (inRange("bbThreeBet") && raise && roll < 0.8) {
      return { type: "raise", to: clampTo(raise, need + BB * 3.5), why, note: `${cls} three-bets` };
    }
    if (inRange("bbCall")) return { type: "call", why, note: `${cls} defends` };
    return { type: "fold", why, note: `${cls} folds to the raise` };
  }
  if (need > 0) {                                       // facing a three-bet or more
    if (inRange("btnFourBet") && raise && roll < 0.7) {
      return { type: "raise", to: clampTo(raise, need + BB * 6), why, note: `${cls} four-bets` };
    }
    if (inRange("btnCallThreeBet")) return { type: "call", why, note: `${cls} calls the three-bet` };
    return { type: "fold", why, note: `${cls} folds` };
  }
  return { type: "check", why, note: `${cls} checks` };
}


/* --------------------------------------------------------------- decision analysis
 *
 * The EV table behind the live panel and the retro. Exact where it can be and explicit about
 * where it cannot:
 *
 *   exact      your equity against the modelled range (enumerated over every runout)
 *   exact      the pot arithmetic
 *   MODELLED   which combos the opponent holds at all
 *   ASSUMED    that a call ends the betting
 *
 * That last one is the big one. Calling with a draw is worth more than this says because you
 * win extra when you hit, and calling with a marginal made hand is worth less because you pay
 * off later. The number is a floor for draws and a ceiling for bluff-catchers, and the retro
 * says so rather than pretending otherwise.
 *
 * Fold is the zero point: every EV is chips gained relative to giving up now.
 */
/* A stable seed for one decision point, so the sampled preflop equity is identical every
 * time the same spot is analysed. */
function posSeed(st, hero) {
  let h = 2166136261;
  const push = v => { h ^= v; h = Math.imul(h, 16777619); };
  push(st.handNo); push(st.street); push(totalPot(st)); push(toCall(st, st.toAct));
  for (const c of hero) push(c + 1);
  for (const c of st.board) push(c + 53);
  return h >>> 0;
}

function analyse(st, hero, extraSizes) {
  const me = st.toAct, pot = totalPot(st), need = toCall(st, me);
  const source = (st.ranges[1 - me] && st.ranges[1 - me].length) ? st.ranges[1 - me] : ALL_COMBOS;
  /* One pass over the range, reused by everything below. Hero's equity against each combo
   * gives the aggregate as its mean, and villain's equity is its complement, which is what
   * fold equity needs. Computing it once rather than once per bet size is the difference
   * between a panel that keeps up with clicking and one that does not.
   *
   * combosEquity enumerates postflop and samples preflop, and says which. */
  // Its own stream, seeded from the position. Drawing from st.rand would mean that merely
  // looking at the panel advanced the bot's randomiser and changed how it played, and it
  // would also make the retro disagree with the live number for the same decision.
  const R = P.combosEquity(hero, source, st.board, 200000, mulberry(posSeed(st, hero)));
  const live = R.live, eqs = R.eqs;
  let sum = 0;
  for (let i = 0; i < eqs.length; i++) sum += eqs[i];
  const equity = eqs.length ? sum / eqs.length : 0.5;

  /* How often hero's hand, exactly as it stands, already beats theirs. Distinct from equity:
     equity asks how often you end up winning, this asks whether you are in front right now.
     The two come apart badly with a made hand, where outs describe a bonus rather than the
     route to the pot, and reporting only the outs invites reading a strong hand as a draw. */
  let ahead = null;
  if (st.board.length >= 3) {
    const mine = P.evaluate(hero.concat(st.board));
    let won = 0;
    for (const c of live) if (P.evaluate(c.concat(st.board)) < mine) won++;
    ahead = live.length ? won / live.length : 0.5;
  }

  const acts = legalActions(st);
  const rows = [];
  if (need > 0) {
    rows.push({ action: "fold", ev: 0, exact: true,
                note: "the zero point: what is already in the pot is gone either way" });
    const price = P.requiredEquity(pot - need, need);
    rows.push({ action: "call", amount: need, price, edge: equity - price,
                ev: equity * pot - (1 - equity) * need,
                note: `${pct(equity)} equity against a ${pct(price)} price` });
  } else {
    rows.push({ action: "check", ev: equity * pot,
                note: "value of seeing it through with no more betting" });
  }

  const raise = acts.find(a => a.type === "bet" || a.type === "raise");
  if (raise) {
    const seen = new Set();
    const sizes = [0.33, 0.5, 0.75, 1.0]
      .map(f => ({ f, to: clampTo(raise, (st.bet[1 - me] || 0) + pot * f) }))
      .concat([{ f: null, to: raise.maxTo }])
      .concat((extraSizes || []).map(to => ({ f: null, to: clampTo(raise, to), extra: true })));
    for (const { f, to } of sizes) {
      // Distinct sizes can clamp onto the same number (a third of a small pot is below the
      // minimum bet), and the same row twice is noise, not a choice.
      if (seen.has(to)) continue;
      seen.add(to);
      const put = to - st.bet[me];
      if (put <= need) continue;
      const r = betEV(eqs, st.board, pot, put, need);
      rows.push({ action: to === raise.maxTo ? "all-in" : (need > 0 ? "raise" : "bet"),
                  to, amount: put, frac: f, ev: r.ev, folds: r.folds, eqCalled: r.eqCalled,
                  custom: !!(extraSizes || []).length && seenExtra(sizes, to),
                  note: `${pct(r.folds)} of their range cannot call this price` });
    }
  }
  rows.sort((a, b) => b.ev - a.ev);
  return { rows, equity, ahead, combos: live.length, pot, need,
           exact: R.exact, samplesEach: R.samplesEach, stderr: R.stderr,
           price: need > 0 ? P.requiredEquity(pot - need, need) : null,
           mdf: need > 0 ? P.mdf(pot - need, need) : null, best: rows[0] };
}

/* EV of putting in `put` chips, given hero's equity against each combo of the live range.
 * Fold equity is combo by combo: can that holding profitably call the price it is offered?
 * This reads hero's own cards, which is legitimate because it is hero's analysis of hero's
 * spot, not the bot deciding. */
/* True when `to` came in as a caller-supplied size rather than one of the presets, so the
 * panel can mark the slider's own row. */
function seenExtra(sizes, to) {
  const hit = sizes.find(x => x.to === to);
  return !!(hit && hit.extra);
}

function betEV(eqs, board, pot, put, need) {
  const raiseBy = put - need;
  const price = P.requiredEquity(pot + need, raiseBy);
  let folds = 0, callEq = 0, callN = 0;
  for (let i = 0; i < eqs.length; i++) {
    const theirs = 1 - eqs[i];
    if (theirs < price) folds++;
    else { callEq += eqs[i]; callN++; }
  }
  const n = eqs.length || 1;
  const f = folds / n;
  const eqCalled = callN ? callEq / callN : 0;      // hero's equity against what continues
  return { ev: f * pot + (1 - f) * (eqCalled * (pot + put) - (1 - eqCalled) * put),
           folds: f, eqCalled };
}

const pct = x => (x * 100).toFixed(1) + "%";

const api = { SB, BB, START, STREETS, HERO, BOT, RANGES, expanded, ALL_COMBOS,
              mulberry, shuffled, newHand, legalActions, applyAction, settle,
              totalPot, toCall, effective, allIn, strengthOf, narrow, rangeAfter,
              botAction, comboKey, rangeSet, clampTo, analyse, betEV, posSeed };
if (typeof module !== "undefined" && module.exports) module.exports = api;
else root.Game = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
