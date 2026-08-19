/* The JS core must reproduce the Python evaluator exactly, because every number the browser
 * shows is computed here while the verification lives there. Run: node test_core.js */
const P = require("./core.js");
const V = require("./vectors.json");

const fails = [];
const ck = (cond, msg) => { if (!cond) fails.push(msg); return cond; };
const near = (a, b) => Math.abs(a - b) < 1e-12;

let bad7 = 0;
for (const [cards, want] of V.eval7) if (P.evaluate(cards) !== want) bad7++;
ck(!bad7, `${bad7} seven-card evaluations differ from Python`);
console.log(`${bad7 ? "FAIL" : "ok  "} seven-card: ${V.eval7.length - bad7}/${V.eval7.length} match Python`);

let bad5 = 0;
for (const [cards, want] of V.eval5) if (P.evaluate(cards) !== want) bad5++;
ck(!bad5, `${bad5} five-card evaluations differ from Python`);
console.log(`${bad5 ? "FAIL" : "ok  "} five-card:  ${V.eval5.length - bad5}/${V.eval5.length} match Python`);

for (const [h, v, b, want, n] of V.equity) {
  const got = P.equity(h, v, b);
  const hit = near(got.share, want) && got.runouts === n;
  ck(hit, `equity ${P.show(h)} vs ${P.show(v)}: ${got.share} vs ${want}`);
  console.log(`${hit ? "ok  " : "FAIL"} ${P.show(h)} vs ${P.show(v)} on ${P.show(b).padEnd(14)}` +
              ` ${(got.share * 100).toFixed(2)}%  (${got.runouts} runouts)`);
}

// Equity is a share of a two-player pot, so the two sides must sum to exactly one.
for (const [h, v, b] of V.equity) {
  ck(near(P.equity(h, v, b).share + P.equity(v, h, b).share, 1),
     `equity does not sum to 1 for ${P.show(h)} vs ${P.show(v)}`);
}
console.log(`${fails.length ? "FAIL" : "ok  "} equity sums to 1 from both seats`);

// Range plumbing, including the combo counts every poker player knows by heart.
ck(P.combosOf("AA").length === 6, "AA is 6 combos");
ck(P.combosOf("AKs").length === 4, "AKs is 4 combos");
ck(P.combosOf("AKo").length === 12, "AKo is 12 combos");
ck(P.expandRange("QQ+").length === 18, "QQ+ is three pairs = 18 combos");
ck(P.expandRange("A2s+").length === 48, "A2s+ is twelve classes x 4 = 48 combos");
ck(P.expandRange("22+").length === 78, "all pocket pairs is 78 combos");
ck(P.classOf([P.cardOf("As"), P.cardOf("Ks")]) === "AKs", "classOf AKs");
ck(P.classOf([P.cardOf("As"), P.cardOf("Kd")]) === "AKo", "classOf AKo");
ck(P.classOf([P.cardOf("As"), P.cardOf("Ad")]) === "AA", "classOf AA");
// A full 169-class range must be exactly the deck's 1326 holdings.
let all = 0;
for (const r of P.RANKS) for (const s of P.RANKS) {
  const hi = P.RANKS.indexOf(r), lo = P.RANKS.indexOf(s);
  if (hi < lo) continue;
  all += hi === lo ? P.combosOf(r + r).length
                   : P.combosOf(r + s + "s").length + P.combosOf(r + s + "o").length;
}
ck(all === 1326, `the 169 classes should cover all 1326 holdings, got ${all}`);
console.log(`${fails.length ? "FAIL" : "ok  "} range plumbing (169 classes cover ${all} holdings)`);

// Card removal: holding an ace must reduce the live ace-x combos the opponent can have.
const withAce = P.equityVsRange(P.parse("Ah Kd"), P.expandRange("A2s+"), P.parse("2c 7d 9s"));
const without = P.equityVsRange(P.parse("Qh Jd"), P.expandRange("A2s+"), P.parse("2c 7d 9s"));
ck(withAce.combos < without.combos,
   `card removal not applied: ${withAce.combos} vs ${without.combos}`);
console.log(`ok   card removal: holding an ace leaves ${withAce.combos} A2s+ combos, ` +
            `holding none leaves ${without.combos}`);

// Pot arithmetic, checked against cases you can do in your head.
ck(near(P.requiredEquity(100, 50), 0.25), "a half-pot call needs 25%, laid 3:1");
ck(near(P.requiredEquity(100, 100), 1 / 3), "a pot-sized call needs 33.3%");
ck(near(P.mdf(100, 100), 0.5), "MDF against a pot bet is 50%");
ck(near(P.mdf(100, 50), 2 / 3), "MDF against a half-pot bet is 2/3");
ck(near(P.breakevenFold(100, 100), 0.5), "a pot-sized bluff needs 50% folds");
ck(near(P.breakevenFold(100, 50), 1 / 3), "a half-pot bluff needs 33.3% folds");
ck(near(P.bluffRatio(100, 100), 1 / 3), "a pot bet may be 1/3 bluffs");
// The bettor's bluff ratio and the caller's required equity are the same number by
// construction: both are the point where calling is indifferent.
for (const b of [25, 50, 75, 100, 200]) {
  ck(near(P.bluffRatio(100, b), P.requiredEquity(100, b)),
     `bluff ratio and required equity diverge at bet ${b}`);
}
console.log(`${fails.length ? "FAIL" : "ok  "} pot arithmetic`);

console.log(fails.length ? "\nFAILURES:\n  " + fails.join("\n  ") : "\nall checks passed");
process.exit(fails.length ? 1 : 0);
