"""Fetch the closing spread (home-team perspective) for every FBS game -> data/odds_fbs.csv."""
import csv, json, os
from concurrent.futures import ThreadPoolExecutor
import collect

H = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(H, "data", "odds_fbs.csv")
ids = [json.loads(l)["game_id"] for l in open(os.path.join(H, "data", "games_fbs.jsonl"))]
done = set()
if os.path.exists(OUT):
    done = {r["game_id"] for r in csv.DictReader(open(OUT))}
todo = [i for i in ids if i not in done]
print(len(ids), "games;", len(todo), "to fetch", flush=True)


def one(gid):
    o = collect.odds(gid) or {}
    return {"game_id": gid, "home_spread": o.get("home_spread"), "over_under": o.get("over_under"),
            "provider": o.get("provider")}


new = not os.path.exists(OUT)
with open(OUT, "a", newline="") as f, ThreadPoolExecutor(12) as ex:
    w = csv.DictWriter(f, ["game_id", "home_spread", "over_under", "provider"])
    if new:
        w.writeheader()
    for i, r in enumerate(ex.map(one, todo), 1):
        w.writerow(r)
        if i % 500 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
