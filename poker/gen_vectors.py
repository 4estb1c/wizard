"""Emit test vectors from the verified Python evaluator for the JS port to reproduce."""
import json, random
from eval7 import *

rng = random.Random(20260818)
vec = {"eval7": [], "eval5": [], "equity": []}
for _ in range(6000):
    c = rng.sample(range(52), 7)
    vec["eval7"].append([c, evaluate(c)])
for _ in range(2000):
    c = rng.sample(range(52), 5)
    vec["eval5"].append([c, evaluate(c)])
# A few equities on flop and turn, where enumeration is cheap enough to check quickly.
for h, v, b in [("Ah Ad","Kh Ks","5c 9d Jh"), ("Ts 9s","Ah Kd","8s 7h 2c"),
                ("Kh Qh","Ah 2c","Jh Th 3s"), ("2c 2d","As Ks","Ah 7d 2s"),
                ("Ah Ad","Kh Ks","5c 9d Jh 2s"), ("7c 2d","Ah As","Kh Qd Jc 9s")]:
    e, n = equity(hand(h), hand(v), hand(b))
    vec["equity"].append([hand(h), hand(v), hand(b), e, n])
json.dump(vec, open("vectors.json", "w"))
print(f"wrote {len(vec['eval7'])} seven-card, {len(vec['eval5'])} five-card, "
      f"{len(vec['equity'])} equity vectors")
