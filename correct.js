/* Correctness check for the optimised solver. Compares it against a plain minimax with no
   transposition table and no alpha-beta pruning — slow but obviously right — on many random
   deals. Any disagreement means the packed table entries or the numeric keys are wrong.
   Run: node _correct.js [deals]                                                            */
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
const A = new Function(s.slice(a+8,b) + `
  return {DoubleDummy, tricksPayoff, scorePayoff, maskOf, DECK, legalMask, trickWinner,
          roundScore};`)();
const { DoubleDummy, tricksPayoff, scorePayoff, maskOf, DECK, legalMask, trickWinner } = A;

/* Reference: full minimax, every node, no table, no pruning. */
function refValue(trump, payoff, a, b, aMove, lead, at, bt){
  if (a === 0 && b === 0) return payoff(at, bt);
  const hand = aMove ? a : b;
  const ok = legalMask(hand, lead);
  let best = aMove ? -Infinity : Infinity;
  for (let card = 0; card < 24; card++) {
    if (!((ok >>> card) & 1)) continue;
    const bit = 1 << card;
    let v;
    if (lead === null) {
      v = aMove ? refValue(trump, payoff, a^bit, b, false, card, at, bt)
                : refValue(trump, payoff, a, b^bit, true,  card, at, bt);
    } else {
      const fw = trickWinner(lead, card, trump) === 1;
      v = aMove ? refValue(trump, payoff, a^bit, b,  fw, null, at+(fw?1:0), bt+(fw?0:1))
                : refValue(trump, payoff, a, b^bit, !fw, null, at+(fw?0:1), bt+(fw?1:0));
    }
    if (aMove) { if (v > best) best = v; } else { if (v < best) best = v; }
  }
  return best;
}

let seed = 555111;
const rnd = () => { seed = (seed*1103515245+12345)>>>0; return seed/4294967296; };
const shuffled = () => { const c = DECK.slice();
  for (let i=c.length-1;i>0;i--){const j=(rnd()*(i+1))|0;[c[i],c[j]]=[c[j],c[i]];} return c; };

const DEALS = +(process.argv[2] || 120);
let checked = 0, bad = 0;

for (let d = 0; d < DEALS; d++) {
  const size = 3 + ((rnd()*2)|0);            // 3 or 4 cards: reference must stay tractable
  const c = shuffled();
  const A0 = c.slice(0, size), B0 = c.slice(size, 2*size);
  const trump = ((rnd()*5)|0) - 1;           // -1 (no trump) through 3
  const am = maskOf(A0), bm = maskOf(B0);
  const aLeads = rnd() < 0.5;

  for (const [name, payoff] of [
      ["tricks", tricksPayoff],
      ["-tricks", at => -at],
      ["score", scorePayoff(1 + ((rnd()*size)|0), 1 + ((rnd()*size)|0))]]) {
    const fast = new DoubleDummy(trump, payoff).value(am, bm, aLeads);
    const slow = refValue(trump, payoff, am, bm, aLeads, null, 0, 0);
    checked++;
    if (fast !== slow) {
      bad++;
      if (bad <= 5) console.log(`  MISMATCH ${name}: fast ${fast} vs reference ${slow}`
        + ` (size ${size}, trump ${trump})`);
    }
  }
}
console.log(`${checked} solves compared against plain minimax across ${DEALS} deals`);
console.log(bad === 0 ? "  all values identical" : `  ${bad} MISMATCHES`);

/* Also confirm the table is actually being reused rather than silently disabled. */
const c = shuffled(), size = 6;
const dd = new DoubleDummy(0, tricksPayoff);
dd.value(maskOf(c.slice(0,size)), maskOf(c.slice(size,2*size)), true);
console.log(`  table populated: ${dd.tt.size} buckets after one 6-card solve`
  + ` (${dd.nodes} nodes)`);
