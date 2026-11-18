"""Quarter-by-quarter scores for every FBS game since 2022 -> data/linescores.csv
(from ESPN's daily scoreboards, which carry linescores)."""
import csv, datetime, json, os
from concurrent.futures import ThreadPoolExecutor
import collect

H = os.path.dirname(os.path.abspath(__file__))
want = {json.loads(l)["game_id"] for l in open(os.path.join(H, "data", "games_fbs.jsonl"))}
days = []
for season in range(2022, 2027):
    start = datetime.date(season, 8, 20)
    days += [start + datetime.timedelta(i) for i in range(165) if start + datetime.timedelta(i) <= datetime.date.today()]


def day(d):
    return collect.get(f"{collect.SITE}/scoreboard?dates={d:%Y%m%d}&groups=80&limit=300").get("events", [])


rows = {}
with ThreadPoolExecutor(8) as ex:
    for evs in ex.map(day, days):
        for e in evs:
            if e["id"] not in want:
                continue
            r = {"game_id": e["id"]}
            for c in e["competitions"][0]["competitors"]:
                ls = [x.get("value") for x in c.get("linescores", [])]
                side = c["homeAway"]
                for q in range(4):
                    r[f"{side}_q{q + 1}"] = ls[q] if q < len(ls) else None
                r[f"{side}_ot"] = sum(ls[4:]) if len(ls) > 4 else 0
            rows[e["id"]] = r
cols = ["game_id"] + [f"{s}_{p}" for s in ("home", "away") for p in ("q1", "q2", "q3", "q4", "ot")]
with open(os.path.join(H, "data", "linescores.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows.values())
print(len(want), "games;", len(rows), "with linescores")
