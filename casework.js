/* Offline casework. Plays many rounds with the real engine and bot, and at every decision
   the human would face, solves the true deal to find the best action. Then it buckets those
   decisions by features a player can actually see at the table and reports how often each
   rule of thumb is right.

   The point is not to build a model — the solver already does that. The point is to find
   which few facts explain the solver's answer, so the game can say something true and
   specific instead of just printing a number.

   Run: node _casework.js [rounds]                                                        */
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

const A = new Function(s.slice(a + 8, b) + `
  return {DoubleDummy, tricksPayoff, scorePayoff, maskOf, DECK, roundScore, legalPlays,
          trickWinner, isWizard, isJester, suitOf, rankOf, NO_TRUMP, legalBids, botBid,
          botPlay, DIFFICULTY, cardName, NUM_NORMAL, RANKS, SUITS};`)();
const { DoubleDummy, tricksPayoff, scorePayoff, maskOf, DECK, legalPlays, trickWinner,
        isWizard, isJester, suitOf, rankOf, NO_TRUMP, legalBids, botBid, botPlay,
        DIFFICULTY, cardName, NUM_NORMAL } = A;

let seed = 987654321;
const rnd = () => { seed = (seed * 1103515245 + 12345) >>> 0; return seed / 4294967296; };
function shuffled(){
  const c = DECK.slice();
  for (let i = c.length - 1; i > 0; i--) { const j = (rnd()*(i+1))|0; [c[i],c[j]]=[c[j],c[i]]; }
  return c;
}
const power = (c, trump) => isJester(c) ? -1 : isWizard(c) ? 100
  : (trump >= 0 && suitOf(c) === trump ? rankOf(c) + 50 : rankOf(c));

/* ---------------------------------------------------------------- counters */
const bucket = {};
const bump = (k, sub) => {
  bucket[k] = bucket[k] || { n:0, hit:{} };
  bucket[k].n++;
  bucket[k].hit[sub] = (bucket[k].hit[sub] || 0) + 1;
};
const bandStats = { n:0, width:0, widths:{}, topBest:0, anyMakeable:0 };
const hookStats = { n:0, forced:0, cost:0 };
const decisions = { n:0, real:0, tied:0, gap:0 };

const ROUNDS = +(process.argv[2] || 200);
const SIZES = [3,4,5,6,7,8];

for (let r = 0; r < ROUNDS; r++) {
  const size = SIZES[(rnd()*SIZES.length)|0];
  const c = shuffled();
  const hands = [c.slice(0,size).sort((x,y)=>x-y), c.slice(size,2*size).sort((x,y)=>x-y)];
  const up = c[2*size];
  const trump = isWizard(up) ? 0 : isJester(up) ? NO_TRUMP : suitOf(up);
  const leadSeat = 1;

  /* ---- bid stage: the band, and whether its top is the right bid ---- */
  const hm = maskOf(hands[0]), om = maskOf(hands[1]);
  const hi = new DoubleDummy(trump, tricksPayoff).value(hm, om, leadSeat === 0);
  const lo = -new DoubleDummy(trump, at => -at).value(hm, om, leadSeat === 0);
  const bLo = Math.min(lo,hi), bHi = Math.max(lo,hi);
  bandStats.n++; bandStats.width += bHi - bLo;
  bandStats.widths[bHi-bLo] = (bandStats.widths[bHi-bLo]||0) + 1;

  const unseen1 = DECK.filter(x => !hands[1].includes(x) && x !== up);
  const oppBid = botBid(hands[1], unseen1, size, trump, true, null,
                        legalBids(size, false, null), size, DIFFICULTY.normal);
  const myLegal = legalBids(size, true, oppBid);           // I am dealer, hook applies to me
  /* best bid if the band is honoured: highest makeable, since a made bid pays 2 + tricks */
  let want = bHi;
  hookStats.n++;
  if (!myLegal.includes(want)) {
    hookStats.forced++;
    let alt = null;
    for (let d = 1; d <= size; d++) {
      for (const cand of [want-d, want+d])
        if (cand >= 0 && cand <= size && myLegal.includes(cand) && alt === null) alt = cand;
      if (alt !== null) break;
    }
    const madeVal = 2 + want;
    const altVal = (alt >= bLo && alt <= bHi) ? 2 + alt
                 : -Math.min(Math.abs(alt-bLo), Math.abs(alt-bHi));
    hookStats.cost += madeVal - altVal;
    want = alt;
  }
  if (want >= bLo && want <= bHi) bandStats.anyMakeable++;

  /* ---- card stage: solve every decision on the true deal ---- */
  const myBid = want, theirBid = oppBid;
  const h = [hands[0].slice(), hands[1].slice()];
  const tricks = [0,0], played = [];
  const voids = [new Set(), new Set()];
  let leader = leadSeat;

  while (h[0].length) {
    const table = [null,null], follower = 1 - leader;
    for (const seat of [leader, follower]) {
      const lead = seat === follower ? table[leader] : null;
      const legal = legalPlays(h[seat], lead);

      if (seat === 0 && legal.length > 1) {
        /* the solver's answer on the true deal, contract-aware */
        const dd = new DoubleDummy(trump, scorePayoff(myBid, theirBid));
        const vals = dd.rootValues(maskOf(h[0]), maskOf(h[1]), lead, tricks[0], tricks[1]);
        let best = null, bv = -Infinity, second = -Infinity;
        for (const card of legal) {
          const v = vals.get(card);
          if (v === undefined) continue;
          if (v > bv) { second = bv; bv = v; best = card; }
          else if (v > second) second = v;
        }
        /* When every legal card scores the same the decision is not a decision — the
           contract is already made or already dead. Counting those alongside real choices
           was the thing skewing the table toward whatever card happened to sort first. */
        const gap = bv - second;
        const real = best !== null && second > -Infinity && gap > 1e-9;
        if (best !== null) {
          decisions.n++;
          if (!real) decisions.tied++; else { decisions.real++; decisions.gap += gap; }
        }
        if (best !== null && real) {
          const need = myBid - tricks[0], left = h[0].length;
          const sorted = legal.slice().sort((x,y)=>power(x,trump)-power(y,trump));
          const lowest = sorted[0], highest = sorted[sorted.length-1];

          const phase = need <= 0 ? "at or over bid"
                      : need >= left ? "need every trick"
                      : "need some";
          const role = lead === null ? "leading" : "following";
          const key = `${role} / ${phase}`;

          let act = "middle";
          if (isWizard(best)) act = "Wizard";
          else if (isJester(best)) act = "Jester";
          else if (best === highest) act = "highest";
          else if (best === lowest) act = "lowest";
          bump(key, act);

          /* does the simple rule "win it if you need it, duck if you do not" agree? */
          if (lead !== null) {
            const wins = trickWinner(lead, best, trump) === 1;
            bump(`${role} / ${phase} :: outcome`, wins ? "takes the trick" : "gives it up");
          }
        }
      }

      const seen = new Set(h[seat]); played.forEach(x=>seen.add(x));
      if (table[1-seat] !== null) seen.add(table[1-seat]);
      const unseen = DECK.filter(x => !seen.has(x));
      const card = botPlay(h[seat], h[1-seat].length, unseen, voids[seat], trump,
                           seat===0?myBid:theirBid, seat===0?theirBid:myBid,
                           tricks[seat], tricks[1-seat], lead, legal, DIFFICULTY.normal);
      if (lead !== null && suitOf(lead) >= 0 && card < NUM_NORMAL && suitOf(card) !== suitOf(lead))
        voids[1-seat].add(suitOf(lead));
      h[seat] = h[seat].filter(x => x !== card);
      table[seat] = card;
    }
    const fw = trickWinner(table[leader], table[follower], trump) === 1;
    const winner = fw ? follower : leader;
    tricks[winner]++;
    played.push(table[0], table[1]);
    leader = winner;
  }
}

/* ---------------------------------------------------------------- report */
console.log(`${ROUNDS} rounds, sizes ${SIZES.join("/")}\n`);
console.log("BID STAGE");
console.log(`  mean band width            : ${(bandStats.width/bandStats.n).toFixed(2)} tricks`);
const wk = Object.keys(bandStats.widths).map(Number).sort((x,y)=>x-y);
console.log(`  band width distribution    : `
  + wk.map(w=>`${w}:${Math.round(100*bandStats.widths[w]/bandStats.n)}%`).join("  "));
console.log(`  hook forced off best bid   : ${Math.round(100*hookStats.forced/hookStats.n)}%`
  + ` of rounds, costing ${(hookStats.cost/Math.max(1,hookStats.forced)).toFixed(1)} pts when it does`);

console.log(`\nCARD STAGE — ${decisions.n} points where you had more than one legal card`);
console.log(`  every card scored the same : ${Math.round(100*decisions.tied/decisions.n)}%`
  + `  (contract already safe or already dead — nothing to get wrong)`);
console.log(`  a genuine choice           : ${Math.round(100*decisions.real/decisions.n)}%`
  + `, and the wrong card costs ${(decisions.gap/Math.max(1,decisions.real)).toFixed(2)} pts on average`);
console.log("\n  what the solver picks when the choice actually matters:");
const keys = Object.keys(bucket).filter(k=>!k.includes("::")).sort();
for (const k of keys) {
  const B = bucket[k];
  if (B.n < 15) continue;
  const parts = Object.entries(B.hit).sort((x,y)=>y[1]-x[1])
    .map(([act,n])=>`${act} ${Math.round(100*n/B.n)}%`);
  console.log(`  ${k.padEnd(32)} n=${String(B.n).padStart(4)}   ${parts.join(" · ")}`);
}
console.log("\nCARD STAGE — does the best card take the trick?");
for (const k of Object.keys(bucket).filter(k=>k.includes("::")).sort()) {
  const B = bucket[k];
  if (B.n < 15) continue;
  const parts = Object.entries(B.hit).sort((x,y)=>y[1]-x[1])
    .map(([act,n])=>`${act} ${Math.round(100*n/B.n)}%`);
  console.log(`  ${k.replace(" :: outcome","").padEnd(32)} n=${String(B.n).padStart(4)}   ${parts.join(" · ")}`);
}
