/* Pulls the real engine, solver and bot out of play.html and asks one question:
   is the trick model behind bidEV actually predictive of how a round plays out?
   Run: node _solvertest.js */
const fs = require("fs");
const s = fs.readFileSync("play.html", "utf8");
const a = s.indexOf("<script>"), b = s.lastIndexOf("</script>");

const el = { style:{setProperty(){}}, classList:{add(){},remove(){}}, addEventListener(){},
  appendChild(){}, querySelectorAll:()=>[], querySelector:()=>null, innerHTML:"",
  textContent:"", dataset:{}, onclick:null, remove(){} };
global.window = { matchMedia:()=>({matches:false}), addEventListener(){} };
global.document = { getElementById:()=>el, addEventListener(){}, querySelectorAll:()=>[],
  querySelector:()=>null, createElement:()=>({...el}),
  documentElement:{style:{setProperty(){}}}, body:el };
global.location = {};

const API = new Function(s.slice(a + 8, b) + `
  return {DoubleDummy, tricksPayoff, scorePayoff, maskOf, DECK, DECK_SIZE, roundScore,
          legalPlays, trickWinner, isWizard, isJester, suitOf, NO_TRUMP, legalBids,
          botBid, botPlay, DIFFICULTY, cardName};`)();

const { DoubleDummy, tricksPayoff, scorePayoff, maskOf, DECK, roundScore, legalPlays,
        trickWinner, isWizard, isJester, suitOf, NO_TRUMP, legalBids,
        botBid, botPlay, DIFFICULTY } = API;

/* deterministic deals so runs are comparable */
let seed = 12345;
const rnd = () => { seed = (seed * 1103515245 + 12345) >>> 0; return seed / 4294967296; };
function shuffled(){
  const c = DECK.slice();
  for (let i = c.length - 1; i > 0; i--) { const j = (rnd()*(i+1))|0; [c[i],c[j]]=[c[j],c[i]]; }
  return c;
}

/* Play a round out with the real bot on both seats, each trying to make its own bid. */
function playOut(hands, trump, bids, leadSeat){
  const h = [hands[0].slice(), hands[1].slice()];
  const tricks = [0, 0], played = [];
  const voids = [new Set(), new Set()];
  let leader = leadSeat;
  while (h[0].length) {
    const table = [null, null], follower = 1 - leader;
    for (const seat of [leader, follower]) {
      const lead = seat === follower ? table[leader] : null;
      const legal = legalPlays(h[seat], lead);
      const seen = new Set(h[seat]); played.forEach(c=>seen.add(c));
      if (table[1-seat] !== null) seen.add(table[1-seat]);
      const unseen = DECK.filter(c => !seen.has(c));
      const card = botPlay(h[seat], h[1-seat].length, unseen, voids[seat], trump,
                           bids[seat], bids[1-seat], tricks[seat], tricks[1-seat],
                           lead, legal, DIFFICULTY.normal);
      if (lead !== null && suitOf(lead) >= 0 && card < 20 && suitOf(card) !== suitOf(lead))
        voids[1-seat].add(suitOf(lead));
      h[seat] = h[seat].filter(x => x !== card);
      table[seat] = card;
    }
    const followerWon = trickWinner(table[leader], table[follower], trump) === 1;
    const winner = followerWon ? follower : leader;
    tricks[winner]++;
    played.push(table[0], table[1]);
    leader = winner;
  }
  return tricks;
}

const SIZE = +(process.argv[2] || 7);
const DEALS = +(process.argv[3] || 60);

let inBand = 0, exactMatch = 0, bandWidth = 0, absErrDD = 0, absErrMid = 0;
const rows = [];
for (let d = 0; d < DEALS; d++) {
  const c = shuffled();
  const hands = [c.slice(0, SIZE).sort((x,y)=>x-y), c.slice(SIZE, 2*SIZE).sort((x,y)=>x-y)];
  const up = c[2*SIZE];
  const trump = isWizard(up) ? 0 : isJester(up) ? NO_TRUMP : suitOf(up);
  const leadSeat = 1;                        // non-dealer leads; seat 0 is "me"

  const hm = maskOf(hands[0]), om = maskOf(hands[1]);

  /* What bidEV currently believes: one number, both sides fighting over the trick count.
     max_A min_B — the most I can force through best defence. */
  const ddMax = new DoubleDummy(trump, tricksPayoff);
  const T = ddMax.value(hm, om, leadSeat === 0);

  /* The other end: min_A max_B, the fewest I can hold myself to while they push tricks at
     me. Playing to duck is a different game from playing to win, so this is a second solve,
     not a sign flip of the first. Together the two bound what I can actually contract for:
     I can guarantee at least T, and guarantee no more than U. Every bid in [T,U] is makeable
     — which is the thing the single-number model cannot express. */
  const ddMin = new DoubleDummy(trump, (at) => -at);
  const U = -ddMin.value(hm, om, leadSeat === 0);
  const lo = Math.min(T, U), hi = Math.max(T, U);

  /* what really happens when both sides play for their own contracts */
  const unseen0 = DECK.filter(x => !hands[0].includes(x) && x !== up);
  const unseen1 = DECK.filter(x => !hands[1].includes(x) && x !== up);
  const bid1 = botBid(hands[1], unseen1, SIZE, trump, true, null,
                      legalBids(SIZE, false, null), SIZE, DIFFICULTY.normal);
  const bid0 = botBid(hands[0], unseen0, SIZE, trump, false, bid1,
                      legalBids(SIZE, true, bid1), SIZE, DIFFICULTY.normal);
  const actual = playOut(hands, trump, [bid0, bid1], leadSeat)[0];

  if (actual >= lo && actual <= hi) inBand++;
  if (actual === T) exactMatch++;
  bandWidth += hi - lo;
  absErrDD  += Math.abs(actual - T);
  absErrMid += Math.abs(actual - Math.round((lo + hi) / 2));
  rows.push({lo, hi, T, actual, bid0});
}

console.log(`size ${SIZE}, ${DEALS} deals, both seats playing their own contract\n`);
console.log(`  double-dummy trick count (what bidEV uses)`);
console.log(`    equals the real outcome        : ${(100*exactMatch/DEALS).toFixed(0)}%`);
console.log(`    mean absolute error            : ${(absErrDD/DEALS).toFixed(2)} tricks`);
console.log(`\n  reachable band [min forced, max forced]`);
console.log(`    contains the real outcome      : ${(100*inBand/DEALS).toFixed(0)}%`);
console.log(`    mean width                     : ${(bandWidth/DEALS).toFixed(1)} tricks`);
console.log(`    mean abs error from band centre: ${(absErrMid/DEALS).toFixed(2)} tricks`);
console.log("\n  sample rows (lo..hi | dd | actual | bid):");
rows.slice(0, 12).forEach(r =>
  console.log(`    ${r.lo}..${r.hi}  dd=${r.T}  actual=${r.actual}  bid=${r.bid0}`));
