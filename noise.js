/* How much of the EV column is signal and how much is sampling noise?
   For each position: the standard error of each card's mean across determinizations, and how
   often the sample count actually in use picks the same best card as a 400-sample run.
   Run: node _noise.js [positions]                                                          */
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
  return {DoubleDummy, scorePayoff, maskOf, DECK, samplesFor, mulberry, sampleWith,
          legalPlays, cardName};`)();
const { DoubleDummy, scorePayoff, maskOf, DECK, samplesFor, mulberry, sampleWith,
        legalPlays } = A;

let seed = 31337;
const rnd = () => { seed = (seed*1103515245+12345)>>>0; return seed/4294967296; };
const shuffled = () => { const c = DECK.slice();
  for (let i=c.length-1;i>0;i--){const j=(rnd()*(i+1))|0;[c[i],c[j]]=[c[j],c[i]];} return c; };

/* Per-card values over `n` determinizations drawn from `rand`. */
function sample(trump, myBid, oppBid, mine, unseen, size, legal, n, rand){
  const dd = new DoubleDummy(trump, scorePayoff(myBid, oppBid));
  const hm = maskOf(mine);
  const per = new Map(legal.map(c => [c, []]));
  for (let i = 0; i < n; i++) {
    const vals = dd.rootValues(hm, maskOf(sampleWith(rand, unseen, size)), null, 0, 0);
    for (const c of legal) if (vals.has(c)) per.get(c).push(vals.get(c));
  }
  return per;
}
const mean = xs => xs.reduce((s,x)=>s+x,0)/xs.length;
const sd = xs => { const m = mean(xs);
  return Math.sqrt(xs.reduce((s,x)=>s+(x-m)*(x-m),0)/Math.max(1,xs.length-1)); };

const POS = +(process.argv[2] || 40);
for (const size of [6, 7, 8]) {
  const N = samplesFor(size);
  let seMax = 0, seMean = 0, agree = 0, gapMean = 0, counted = 0;
  let regret = 0, regretN = 0, badMiss = 0;
  for (let p = 0; p < POS; p++) {
    const c = shuffled();
    const mine = c.slice(0, size), unseen = c.slice(size + 1);
    const legal = legalPlays(mine, null);
    if (legal.length < 2) continue;
    const myBid = 1 + ((rnd()*size)|0), oppBid = 1 + ((rnd()*size)|0);

    /* truth: a much larger run from an independent stream */
    const truth = sample(0, myBid, oppBid, mine, unseen, size, legal, 300, mulberry(p*7919+1));
    const tBest = [...truth.entries()].map(([c,v])=>[c,mean(v)])
                    .sort((x,y)=>y[1]-x[1]);

    /* what the game actually runs */
    const got = sample(0, myBid, oppBid, mine, unseen, size, legal, N, mulberry(p*104729+3));
    const gStats = [...got.entries()].map(([c,v])=>[c, mean(v), sd(v)/Math.sqrt(v.length)]);
    const gBest = gStats.slice().sort((x,y)=>y[1]-x[1])[0];

    for (const [,,se] of gStats) { seMean += se; seMax = Math.max(seMax, se); }
    counted += gStats.length;
    if (gBest[0] === tBest[0][0]) agree++;
    gapMean += tBest[0][1] - (tBest[1] ? tBest[1][1] : tBest[0][1]);

    /* The metric that matters: what does the recommendation actually cost, judged by the
       large run? Picking a differently-labelled card is free if the two are really equal. */
    const tMap = new Map(tBest);
    regret += tBest[0][1] - tMap.get(gBest[0]);
    if (tBest[0][1] - tMap.get(gBest[0]) > 0.5) badMiss++;
    regretN++;
  }
  console.log(`size ${size} — ${N} determinizations in play`);
  console.log(`  standard error per card : mean ${(seMean/counted).toFixed(2)},`
    + ` worst ${seMax.toFixed(2)} points`);
  console.log(`  picks the same best card as a 300-sample run: `
    + `${Math.round(100*agree/POS)}%`);
  console.log(`  true gap between best and second: ${(gapMean/POS).toFixed(2)} points`);
  console.log(`  cost of following the short run  : ${(regret/regretN).toFixed(3)} pts/decision`);
  console.log(`  wrong by more than 0.5 points    : ${Math.round(100*badMiss/regretN)}%`);
  console.log("");
}
