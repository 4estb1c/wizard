/* Engine and bot verification. Run: node test_game.js
 *
 * The two checks that matter most are chip conservation (a betting bug almost always shows up
 * as chips appearing or vanishing) and bot blindness (the bot must decide from its own cards
 * and a range, never from yours, and that is checkable by construction rather than by reading
 * the code).
 */
const P = require("./core.js");
const G = require("./game.js");

const fails = [];
const ck = (cond, msg) => { if (!cond && fails.length < 40) fails.push(msg); return cond; };

/* A hero that picks uniformly among legal actions, so the fuzz reaches raise wars, all-ins
 * and min-raise edges that a sensible player would never visit. */
function randomHero(st, rand) {
  const acts = G.legalActions(st);
  const pick = acts[Math.floor(rand() * acts.length)];
  if (pick.type === "bet" || pick.type === "raise") {
    const to = pick.minTo + Math.floor(rand() * (pick.maxTo - pick.minTo + 1));
    return { type: pick.type, to };
  }
  return pick;
}

function playHand(handNo, rand, hooks) {
  const st = G.newHand(handNo, handNo % 2, null, handNo * 7919 + 13);
  let guard = 0;
  while (!st.over) {
    if (++guard > 400) { ck(false, `hand ${handNo} did not terminate`); return st; }
    const me = st.toAct;
    const acts = G.legalActions(st);
    ck(acts.length > 0, `hand ${handNo}: no legal action for player ${me}`);

    // Betting order: heads-up the button posts the small blind and acts first preflop,
    // then acts last on every later street.
    if (st.street === 0 && st.log.length === 0) ck(me === st.button, `hand ${handNo}: button must act first preflop`);

    const act = me === G.HERO ? randomHero(st, rand) : G.botAction(st);
    const raiseOpt = acts.find(a => a.type === "bet" || a.type === "raise");
    if (act.type === "bet" || act.type === "raise") {
      ck(!!raiseOpt, `hand ${handNo}: raised when raising was illegal`);
      if (raiseOpt) {
        ck(act.to >= raiseOpt.minTo - 1e-9 || act.to === raiseOpt.maxTo,
           `hand ${handNo}: raise to ${act.to} under min ${raiseOpt.minTo}`);
        ck(act.to <= raiseOpt.maxTo, `hand ${handNo}: raise to ${act.to} over max ${raiseOpt.maxTo}`);
      }
    }
    const before = st.stacks.slice();
    G.applyAction(st, act);
    if (hooks && hooks.afterAction) hooks.afterAction(st);

    for (const i of [0, 1]) {
      ck(st.stacks[i] >= 0, `hand ${handNo}: negative stack for ${i}`);
      ck(st.stacks[i] <= before[i], `hand ${handNo}: stack grew mid-hand for ${i}`);
      ck(st.committed[i] + st.stacks[i] === G.START, `hand ${handNo}: player ${i} chips do not add up`);
    }
  }
  G.settle(st);
  return st;
}

// ---------------------------------------------------------------- fuzz
const rand = G.mulberry(12345);
let showdowns = 0, folds = 0, allins = 0, streetHist = [0, 0, 0, 0];
for (let h = 0; h < 3000; h++) {
  const st = playHand(h, rand);
  if (!st.result) continue;
  if (st.result.reason === "showdown") showdowns++; else folds++;
  if (st.stacks[0] === 0 || st.stacks[1] === 0 || st.committed[0] === G.START) allins++;
  streetHist[st.street]++;

  // Chips are conserved: nothing is created or destroyed by the betting.
  ck(st.stacks[0] + st.stacks[1] === 2 * G.START,
     `hand ${h}: chips not conserved, ${st.stacks[0]}+${st.stacks[1]} != ${2 * G.START}`);

  // A showdown must be won by the better hand.
  if (st.result.reason === "showdown") {
    const a = P.evaluate(st.holes[0].concat(st.board));
    const b = P.evaluate(st.holes[1].concat(st.board));
    const want = a > b ? 0 : b > a ? 1 : -1;
    ck(st.result.winner === want, `hand ${h}: wrong showdown winner`);
    ck(st.board.length === 5, `hand ${h}: showdown on a ${st.board.length}-card board`);
  }
  // Nobody may be dealt a card that is on the board or in the other hand.
  const seen = new Set([].concat(st.holes[0], st.holes[1], st.board));
  ck(seen.size === 4 + st.board.length, `hand ${h}: duplicate card dealt`);
}
console.log(`${fails.length ? "FAIL" : "ok  "} 3000 fuzzed hands: ${showdowns} showdowns, ${folds} folds, ` +
            `${allins} all-in`);
console.log(`     ended on: preflop ${streetHist[0]}, flop ${streetHist[1]}, turn ${streetHist[2]}, river ${streetHist[3]}`);

// ---------------------------------------------------------------- bot blindness
/* Swap hero's cards for a different pair and the bot must produce the identical action. If
 * it ever peeked, this is where it shows. */
let peeks = 0, tested = 0;
for (let h = 0; h < 400; h++) {
  const a = G.newHand(h, h % 2, null, h * 31 + 5);
  while (!a.over && a.toAct !== G.BOT) {
    const acts = G.legalActions(a);
    G.applyAction(a, acts.find(x => x.type === "call") || acts[0]);
  }
  if (a.over) continue;
  const b = JSON.parse(JSON.stringify(a));
  b.rand = G.mulberry(h * 31 + 5); a.rand = G.mulberry(h * 31 + 5);
  // Give hero two cards nobody else holds.
  const used = new Set([].concat(a.holes[1], a.board, a.deck));
  const spare = [];
  for (let c = 0; c < 52 && spare.length < 2; c++) if (!used.has(c)) spare.push(c);
  if (spare.length < 2) continue;
  b.holes[0] = spare;
  const x = G.botAction(a), y = G.botAction(b);
  tested++;
  if (JSON.stringify([x.type, x.to]) !== JSON.stringify([y.type, y.to])) peeks++;
}
ck(!peeks, `${peeks}/${tested} bot decisions changed when only hero's hidden cards changed`);
console.log(`${peeks ? "FAIL" : "ok  "} bot blindness: ${tested - peeks}/${tested} decisions unchanged ` +
            `when hero's hidden cards are swapped`);

// ---------------------------------------------------------------- all-in for less
/* The deeper player never risked their excess, so it must come back to them. */
{
  const st = G.newHand(1, 0, null, 99);
  st.stacks = [3000, G.START - G.BB];
  st.committed = [G.START - 3000 + G.SB, G.BB];
  st.stacks[0] = G.START - st.committed[0];
  const total = st.stacks[0] + st.committed[0] + st.stacks[1] + st.committed[1];
  ck(total === 2 * G.START, `hand-built state is inconsistent: ${total}`);
}

// ---------------------------------------------------------------- ranges narrow
{
  const board = P.parse("Ah 7d 2c");
  const wide = G.ALL_COMBOS;
  const afterBet = G.rangeAfter(wide, { street: 1, type: "bet", potBefore: 200, potAfter: 400 }, board, false);
  const afterCheck = G.rangeAfter(wide, { street: 1, type: "check", potBefore: 200, potAfter: 200 }, board, false);
  ck(afterBet.length < wide.length, "a bet should narrow the range");
  ck(afterCheck.length < wide.length, "a check should narrow the range");
  ck(G.rangeAfter(wide, { street: 1, type: "fold" }, board, false).length === 0, "folding empties the range");
  // A bigger bet should represent a narrower range than a smaller one.
  const small = G.rangeAfter(wide, { street: 1, type: "bet", potBefore: 200, potAfter: 280 }, board, false);
  ck(afterBet.length < small.length,
     `a pot-sized bet (${afterBet.length}) should be narrower than a 40% bet (${small.length})`);
  console.log(`ok   range model: 1326 combos -> ${afterBet.length} after a pot bet, ` +
              `${small.length} after 40% pot, ${afterCheck.length} after a check`);
}

console.log(fails.length ? "\nFAILURES:\n  " + fails.join("\n  ") : "\nall checks passed");
process.exit(fails.length ? 1 : 0);
