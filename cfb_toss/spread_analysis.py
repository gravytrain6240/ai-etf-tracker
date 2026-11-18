"""Does the point spread change the toss decision? Overall, and within each head coach.

Inputs: data/coach_decisions.csv, data/fbs_toss_games.csv, data/odds_fbs.csv
Outputs: data/spread_results.json, data/coach_spread_splits.csv
"""
import json
import os

import numpy as np
import pandas as pd
from statsmodels.discrete.conditional_models import ConditionalLogit

H = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(H, "data", f)  # noqa: E731

d = pd.read_csv(P("coach_decisions.csv"), dtype={"game_id": str, "team_id": str})
g = pd.read_csv(P("fbs_toss_games.csv"), dtype={"game_id": str, "home_id": str})[["game_id", "home_id"]]
o = pd.read_csv(P("odds_fbs.csv"), dtype={"game_id": str})
d = d.merge(g, on="game_id").merge(o[["game_id", "home_spread"]], on="game_id", how="left")
d["receive"] = (d.decision == "receive").astype(int)
# spread from the toss winner's side: negative = favored
d["spread"] = np.where(d.team_id == d.home_id, d.home_spread, -d.home_spread)
s = d.dropna(subset=["spread"]).copy()

BUCKETS = [(-100, -14, "Favored by 14+"), (-14, -3, "Favored by 3.5–13.5"), (-3, 3, "Within a field goal"),
           (3, 14, "Underdog by 3.5–13.5"), (14, 100, "Underdog by 14+")]


def bucket(x):
    if x <= -14:
        return BUCKETS[0][2]
    if x < -3:
        return BUCKETS[1][2]
    if x <= 3:
        return BUCKETS[2][2]
    if x < 14:
        return BUCKETS[3][2]
    return BUCKETS[4][2]


s["bucket"] = s.spread.map(bucket)
s["role"] = np.where(s.spread < -3, "Favorite", np.where(s.spread > 3, "Underdog", "Close (±3)"))
order = [b[2] for b in BUCKETS]


def tab(df, col, order=None):
    t = df.groupby(col).receive.agg(n="size", receives="sum")
    t["receive_pct"] = (100 * t.receives / t.n).round(1)
    t = t.reindex(order) if order else t
    return t.reset_index().to_dict("records")


res = {
    "decisions": int(len(d)), "with_spread": int(len(s)),
    "overall_by_bucket": tab(s, "bucket", order),
    "overall_by_role": tab(s, "role", ["Favorite", "Close (±3)", "Underdog"]),
}

# within-coach: conditional logit (coach fixed effects); coaches with no variation drop out
for name, x in [("underdog_vs_favorite", (s.spread > 3).astype(float) - (s.spread < -3).astype(float)),
                ("per_point_of_spread", s.spread / 7.0)]:
    m = ConditionalLogit(s.receive.values, x.values.reshape(-1, 1), groups=s.coach.values).fit(disp=0)
    res[f"within_coach_{name}"] = {
        "odds_ratio": round(float(np.exp(m.params[0])), 3),
        "ci95": [round(float(np.exp(v)), 3) for v in m.conf_int()[0]],
        "p": round(float(m.pvalues[0]), 4),
        "coaches_used": int(s.groupby("coach").receive.agg(lambda v: 0 < v.mean() < 1).sum()),
        "decisions_used": int(s[s.groupby("coach").receive.transform(lambda v: 0 < v.mean() < 1)].shape[0]),
    }

# within-coach in plain numbers: each coach's favorite vs underdog rate, decision-weighted
mixed = s[s.groupby("coach").receive.transform(lambda v: 0 < v.mean() < 1)]
w = mixed[mixed.role != "Close (±3)"].groupby(["coach", "role"]).receive.agg(["mean", "size"]).unstack()
w = w.dropna()
res["mixed_coaches_fav_vs_dog"] = {
    "coaches": int(len(w)),
    "avg_rate_as_favorite": round(100 * float(np.average(w[("mean", "Favorite")], weights=w[("size", "Favorite")])), 1),
    "avg_rate_as_underdog": round(100 * float(np.average(w[("mean", "Underdog")], weights=w[("size", "Underdog")])), 1),
}

# per-coach split table (coaches with >=5 decisions as favorite and as underdog)
cs = s[s.role != "Close (±3)"].groupby(["coach", "role"]).receive.agg(["sum", "size"]).unstack()
cs.columns = [f"{a}_{b}" for a, b in cs.columns]
cs = cs.dropna()
cs = cs[(cs.size_Favorite >= 5) & (cs.size_Underdog >= 5)].copy()
cs["fav_pct"] = (100 * cs.sum_Favorite / cs.size_Favorite).round(1)
cs["dog_pct"] = (100 * cs.sum_Underdog / cs.size_Underdog).round(1)
cs["dog_minus_fav"] = (cs.dog_pct - cs.fav_pct).round(1)
schools = d.groupby("coach").team.agg(lambda v: ", ".join(dict.fromkeys(v)))
cs = cs.join(schools.rename("schools")).astype({c: int for c in cs.columns if c.startswith(("sum_", "size_"))})
cs = cs.sort_values("dog_minus_fav", ascending=False)
cs.to_csv(P("coach_spread_splits.csv"))
res["coach_splits"] = cs.reset_index().to_dict("records")

json.dump(res, open(P("spread_results.json"), "w"), indent=1, default=float)

if __name__ == "__main__":
    print(json.dumps({k: v for k, v in res.items() if k != "coach_splits"}, indent=1, default=float))
    print(cs[(cs.sum_Favorite + cs.sum_Underdog) > 0].to_string())
