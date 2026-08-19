/* Texas Hold'em core: hand evaluation, exact equity, ranges, and the pot arithmetic.
 *
 * This file is the trustworthy layer. Everything in it is either exact enumeration or closed
 * form, and it is cross-checked against the Python evaluator in eval7.py, which is itself
 * verified against the exhaustive five-card census. Nothing here estimates. The parts of the
 * project that must approximate (opponent ranges, preflop strategy) live elsewhere and say so.
 *
 * Cards are ints 0..51 with rank = c >> 2 (0 = deuce, 12 = ace) and suit = c & 3.
 */
(function (root) {
"use strict";

const RANKS = "23456789TJQKA", SUITS = "cdhs";
const CAT = ["high card", "a pair", "two pair", "three of a kind", "a straight",
             "a flush", "a full house", "four of a kind", "a straight flush"];

const cardOf = t => RANKS.indexOf(t[0].toUpperCase()) * 4 + SUITS.indexOf(t[1].toLowerCase());
const nameOf = c => RANKS[c >> 2] + SUITS[c & 3];
const parse = s => s.trim().split(/\s+/).filter(Boolean).map(cardOf);
const show = cs => cs.map(nameOf).join(" ");

/* For each 13-bit rank mask, the top rank of the best straight, or -1. Scanned high to low:
 * a seven-card hand can hold two straights and the higher one is the hand. A five-card
 * census cannot catch a low-to-high scan here, because five cards only ever hold one. */
const STRAIGHT = new Int8Array(1 << 13).fill(-1);
for (let mask = 0; mask < (1 << 13); mask++) {
  let hi = -1;
  for (let top = 12; top >= 4 && hi < 0; top--) {
    let all = true;
    for (let i = 0; i < 5; i++) if (!(mask & (1 << (top - i)))) { all = false; break; }
    if (all) hi = top;
  }
  // The wheel is the one straight an ace plays low in, and the lowest of all, so it only
  // counts when nothing above it matched.
  if (hi < 0 && (mask & (1 << 12)) && (mask & 0b1111) === 0b1111) hi = 3;
  STRAIGHT[mask] = hi;
}

const P5 = 371293, P4 = 28561, P3 = 2197, P2 = 169, P1 = 13;

// Reused across calls: evaluate sits in the innermost loop of every equity enumeration, so
// it must allocate nothing.
const rc = new Int8Array(13), sc = new Int8Array(4), sm = new Int32Array(4);
const kbuf = new Int8Array(5);

/* Strength of the best five-card hand inside `cards` (five to seven of them). Larger is
 * better; the value is category * 13^5 plus five kickers, so one < compares two hands. */
function evaluate(cards) {
  rc.fill(0); sc.fill(0); sm.fill(0);
  let mask = 0;
  for (let i = 0; i < cards.length; i++) {
    const c = cards[i], r = c >> 2, s = c & 3;
    rc[r]++; sc[s]++; sm[s] |= 1 << r; mask |= 1 << r;
  }

  /* Flushes first. With seven cards, five of one suit leaves only two others, and two cards
   * cannot lift the rank shape past trips, so a flush found here can never be losing to a
   * full house. That is what makes the early return safe. */
  for (let s = 0; s < 4; s++) {
    if (sc[s] >= 5) {
      const f = sm[s], sf = STRAIGHT[f];
      if (sf >= 0) return 8 * P5 + sf * P4;
      let v = 5 * P5, n = 0;
      const w = [P4, P3, P2, P1, 1];
      for (let r = 12; r >= 0 && n < 5; r--) if (f & (1 << r)) v += r * w[n++];
      return v;
    }
  }

  let quad = -1, trip = -1, trip2 = -1, pair = -1, pair2 = -1;
  for (let r = 12; r >= 0; r--) {
    const k = rc[r];
    if (k === 4) { if (quad < 0) quad = r; }
    else if (k === 3) { if (trip < 0) trip = r; else if (trip2 < 0) trip2 = r; }
    else if (k === 2) { if (pair < 0) pair = r; else if (pair2 < 0) pair2 = r; }
  }

  // Top `want` ranks present, skipping up to two named ones. Zero-filled so every category
  // writes all five slots and ties resolve on the last card rather than on a short compare.
  const kick = (skipA, skipB, want) => {
    let n = 0;
    for (let r = 12; r >= 0 && n < want; r--) if (rc[r] && r !== skipA && r !== skipB) kbuf[n++] = r;
    while (n < want) kbuf[n++] = 0;
    return kbuf;
  };

  if (quad >= 0) { const k = kick(quad, -1, 1); return 7 * P5 + quad * P4 + k[0] * P3; }
  if (trip >= 0 && (trip2 >= 0 || pair >= 0)) {
    const partner = trip2 > pair ? trip2 : pair;   // better of a second set of trips or a pair
    return 6 * P5 + trip * P4 + partner * P3;
  }
  const st = STRAIGHT[mask];
  if (st >= 0) return 4 * P5 + st * P4;
  if (trip >= 0) { const k = kick(trip, -1, 2); return 3 * P5 + trip * P4 + k[0] * P3 + k[1] * P2; }
  if (pair2 >= 0) { const k = kick(pair, pair2, 1); return 2 * P5 + pair * P4 + pair2 * P3 + k[0] * P2; }
  if (pair >= 0) { const k = kick(pair, -1, 3); return 1 * P5 + pair * P4 + k[0] * P3 + k[1] * P2 + k[2] * P1; }
  const k = kick(-1, -1, 5);
  return k[0] * P4 + k[1] * P3 + k[2] * P2 + k[3] * P1 + k[4];
}

const categoryOf = v => Math.floor(v / P5);
const describe = v => CAT[categoryOf(v)];

/* --------------------------------------------------------------- exact equity */

/* Every remaining runout, enumerated; a tie counts as half. Exact, so there is no sample
 * size to quote and no seed to record: on the flop this is 990 boards, the turn 44, the
 * river 1. */
function equity(hero, villain, board) {
  board = board || [];
  const dead = new Uint8Array(52);
  for (const c of hero) dead[c] = 1;
  for (const c of villain) dead[c] = 1;
  for (const c of board) dead[c] = 1;
  const deck = [];
  for (let c = 0; c < 52; c++) if (!dead[c]) deck.push(c);

  const need = 5 - board.length;
  const pad = new Array(need).fill(0);
  const h = hero.concat(board, pad), v = villain.concat(board, pad);
  const hAt = hero.length + board.length, vAt = villain.length + board.length;
  let won = 0, tie = 0, total = 0;

  const rec = (start, depth) => {
    if (depth === need) {
      const a = evaluate(h), b = evaluate(v);
      total++;
      if (a > b) won++; else if (a === b) tie++;
      return;
    }
    for (let i = start; i <= deck.length - (need - depth); i++) {
      h[hAt + depth] = v[vAt + depth] = deck[i];
      rec(i + 1, depth + 1);
    }
  };
  rec(0, 0);
  return { share: (won + tie / 2) / total, runouts: total, won, tie };
}


/* Hero's equity against every combo of a range, exact when that is affordable and sampled
 * when it is not, and it always reports which.
 *
 * The line is not a matter of taste. Postflop a runout is 990 boards on the flop, 44 on the
 * turn and 1 on the river, so a whole range enumerates in milliseconds. Preflop a single
 * matchup is 1,712,304 boards and a full 1326-combo range is 2.27 BILLION, which is not a
 * slow answer but no answer at all. So preflop samples, and every caller is told so rather
 * than being handed a number that merely looks like the exact ones.
 */
function choose(n, k) {
  if (k < 0 || k > n) return 0;
  let r = 1;
  for (let i = 0; i < k; i++) r = r * (n - i) / (i + 1);
  return Math.round(r);
}

/* Sampled equity for one matchup: `k` random runouts drawn without replacement. */
function mcEquity(hero, villain, board, k, rand) {
  const dead = new Uint8Array(52);
  for (const c of hero) dead[c] = 1;
  for (const c of villain) dead[c] = 1;
  for (const c of board) dead[c] = 1;
  const deck = [];
  for (let c = 0; c < 52; c++) if (!dead[c]) deck.push(c);
  const need = 5 - board.length;
  const pad = new Array(need).fill(0);
  const h = hero.concat(board, pad), v = villain.concat(board, pad);
  const hAt = hero.length + board.length, vAt = villain.length + board.length;
  let won = 0, tie = 0;
  for (let t = 0; t < k; t++) {
    // Partial Fisher-Yates: `need` distinct cards without shuffling the whole deck.
    for (let i = 0; i < need; i++) {
      const j = i + Math.floor(rand() * (deck.length - i));
      const tmp = deck[i]; deck[i] = deck[j]; deck[j] = tmp;
      h[hAt + i] = v[vAt + i] = deck[i];
    }
    const a = evaluate(h), b = evaluate(v);
    if (a > b) won++; else if (a === b) tie++;
  }
  return (won + tie / 2) / k;
}

function combosEquity(hero, range, board, budget, rand) {
  board = board || [];
  const dead = new Uint8Array(52);
  for (const c of hero) dead[c] = 1;
  for (const c of board) dead[c] = 1;
  const live = range.filter(c => !dead[c[0]] && !dead[c[1]]);
  const need = 5 - board.length;
  const per = choose(48 - board.length, need);
  budget = budget || 200000;
  const eqs = new Float64Array(live.length);

  if (live.length * per <= budget) {
    for (let i = 0; i < live.length; i++) eqs[i] = equity(hero, live[i], board).share;
    return { live, eqs, exact: true, runouts: live.length * per };
  }
  rand = rand || Math.random;
  const k = Math.max(60, Math.floor(budget / Math.max(1, live.length)));
  for (let i = 0; i < live.length; i++) eqs[i] = mcEquity(hero, live[i], board, k, rand);
  // The aggregate is far tighter than any single entry: per-combo noise averages down by
  // sqrt(number of combos), so the headline equity is good even when each row is rough.
  return { live, eqs, exact: false, samplesEach: k, runouts: live.length * k,
           stderr: 0.5 / Math.sqrt(k * live.length) };
}

/* Hero against a whole range, weighting each villain combo equally. Combos clashing with
 * hero or the board are dropped, which is card removal and is not optional: holding an ace
 * genuinely reduces how many ace-x combos the opponent can hold. */
function equityVsRange(hero, range, board) {
  board = board || [];
  const blocked = new Uint8Array(52);
  for (const c of hero) blocked[c] = 1;
  for (const c of board) blocked[c] = 1;
  let sum = 0, live = 0, runouts = 0, beaten = 0;
  for (const combo of range) {
    if (blocked[combo[0]] || blocked[combo[1]]) continue;
    const r = equity(hero, combo, board);
    sum += r.share; live++; runouts += r.runouts;
    if (r.share < 0.5) beaten++;
  }
  return { share: live ? sum / live : 0.5, combos: live, runouts, beaten };
}


/* --------------------------------------------------------------- outs
 *
 * Counted structurally, the way a player counts at the table: which unseen cards improve
 * YOUR hand, grouped by what they make. A card that only improves the board is not an out,
 * so a jack landing on a jack-high board does not count even though it technically raises
 * your five-card category.
 *
 * The union matters. A card can be both a flush card and a straight card and it is still one
 * card, which is where hand counting most often goes wrong.
 */
function outs(hero, board) {
  if (board.length < 3 || board.length > 4) return null;
  const dead = new Uint8Array(52);
  for (const c of hero) dead[c] = 1;
  for (const c of board) dead[c] = 1;
  const unseen = [];
  for (let c = 0; c < 52; c++) if (!dead[c]) unseen.push(c);

  const all = hero.concat(board);
  const suitN = [0, 0, 0, 0], heroSuit = [0, 0, 0, 0];
  let rmaskAll = 0, rmaskBoard = 0;
  const rankN = new Int8Array(13), heroRank = new Int8Array(13);
  for (const c of all) { suitN[c & 3]++; rankN[c >> 2]++; rmaskAll |= 1 << (c >> 2); }
  for (const c of hero) { heroSuit[c & 3]++; heroRank[c >> 2]++; }
  for (const c of board) rmaskBoard |= 1 << (c >> 2);

  const groups = [], hit = new Set();
  const add = (label, cards) => {
    const fresh = cards.filter(c => !hit.has(c));
    for (const c of fresh) hit.add(c);
    if (fresh.length) groups.push({ label, n: fresh.length, cards: fresh });
  };

  // Flush: four to a suit with at least one of them yours.
  for (let s = 0; s < 4; s++) {
    if (suitN[s] === 4 && heroSuit[s] >= 1) add("flush", unseen.filter(c => (c & 3) === s));
  }
  // Straight: a rank that completes a straight for you but not for the board on its own, so
  // a board that already plays a straight is not credited to you.
  const straightRanks = [];
  for (let r = 0; r < 13; r++) {
    if (STRAIGHT[rmaskAll | (1 << r)] >= 0 && STRAIGHT[rmaskBoard | (1 << r)] < 0) straightRanks.push(r);
  }
  if (straightRanks.length) {
    add(straightRanks.length >= 2 ? "straight (open)" : "straight (gutshot)",
        unseen.filter(c => straightRanks.includes(c >> 2)));
  }
  // Pairing or improving your own cards. Sorted high first so the better out is named first.
  const heroRanks = [...new Set(hero.map(c => c >> 2))].sort((a, b) => b - a);
  for (const r of heroRanks) {
    const cards = unseen.filter(c => (c >> 2) === r);
    if (!cards.length) continue;
    add(RANKS[r] + (rankN[r] >= 2 ? " trips" : " pair"), cards);
  }

  const n = hit.size, U = unseen.length;
  const miss = U - n;
  const turn = n / U;
  // Two cards to come only on the flop. Computed as one minus missing twice, which is why
  // the rule of four drifts high: it double counts the runouts that hit both times.
  const river = board.length === 3 ? 1 - (miss / U) * ((miss - 1) / (U - 1)) : turn;
  return { n, groups, unseen: U, turn, river, cards: [...hit],
           ruleOf2: n * 2 / 100, ruleOf4: board.length === 3 ? n * 4 / 100 : n * 2 / 100 };
}

/* --------------------------------------------------------------- ranges */

/* Every specific two-card combo of a class written "AA", "AKs" or "AKo". */
function combosOf(cls) {
  const a = RANKS.indexOf(cls[0]), b = RANKS.indexOf(cls[1]);
  const out = [];
  if (a === b) {
    for (let s1 = 0; s1 < 4; s1++) for (let s2 = s1 + 1; s2 < 4; s2++) out.push([a * 4 + s1, a * 4 + s2]);
  } else if (cls[2] === "s") {
    for (let s = 0; s < 4; s++) out.push([a * 4 + s, b * 4 + s]);
  } else {
    for (let s1 = 0; s1 < 4; s1++) for (let s2 = 0; s2 < 4; s2++) if (s1 !== s2) out.push([a * 4 + s1, b * 4 + s2]);
  }
  return out;
}

/* "QQ+,AKs,A2s+,JTo" into a flat combo list. A trailing + walks the obvious axis: up the
 * pairs for a pocket pair, up the kicker for anything else. */
function expandRange(text) {
  const out = [];
  for (let tok of String(text).split(",").map(t => t.trim()).filter(Boolean)) {
    const plus = tok.endsWith("+");
    if (plus) tok = tok.slice(0, -1);
    const a = RANKS.indexOf(tok[0]), b = RANKS.indexOf(tok[1]), suit = tok[2] || "";
    if (!plus) { out.push(...combosOf(tok)); continue; }
    if (a === b) {
      for (let r = a; r <= 12; r++) out.push(...combosOf(RANKS[r] + RANKS[r]));
    } else {
      const hi = Math.max(a, b), lo = Math.min(a, b);
      for (let r = lo; r < hi; r++) out.push(...combosOf(RANKS[hi] + RANKS[r] + suit));
    }
  }
  return out;
}

/* The 169-class label for one specific holding. */
function classOf(combo) {
  const [c1, c2] = combo, r1 = c1 >> 2, r2 = c2 >> 2;
  const hi = Math.max(r1, r2), lo = Math.min(r1, r2);
  if (r1 === r2) return RANKS[hi] + RANKS[lo];
  return RANKS[hi] + RANKS[lo] + ((c1 & 3) === (c2 & 3) ? "s" : "o");
}

/* --------------------------------------------------------------- pot arithmetic
 *
 * Closed form, exact, and independent of any read on the opponent. These are the numbers
 * that turn a decision from a matter of taste into something checkable.
 */

/* Equity a call needs to break even. `pot` is the pot BEFORE the bet goes in, so calling
 * `bet` plays for pot + 2*bet in total, of which you contributed bet. Half pot is 3:1 and
 * needs 25%; a pot-sized bet is 2:1 and needs 33.3%. */
const requiredEquity = (pot, bet) => bet / (pot + 2 * bet);

/* Minimum defence frequency: continue this often or a bluff of `bet` prints for free. */
const mdf = (pot, bet) => pot / (pot + bet);

/* The share of a betting range that may be bluffs while a call still breaks even. */
const bluffRatio = (pot, bet) => bet / (pot + 2 * bet);

/* Fold equity a pure bluff needs: risk `bet` to pick up `pot` immediately. */
const breakevenFold = (pot, bet) => bet / (pot + bet);

const api = { RANKS, SUITS, CAT, cardOf, nameOf, parse, show, evaluate, categoryOf, describe,
              equity, equityVsRange, combosEquity, mcEquity, choose, outs, combosOf, expandRange, classOf,
              requiredEquity, mdf, bluffRatio, breakevenFold, STRAIGHT };
if (typeof module !== "undefined" && module.exports) module.exports = api;
else root.Poker = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
