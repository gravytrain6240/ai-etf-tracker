"""After the toss: does the choice pay off on the opening drive and in the first half?

From the toss winner's side, for every verified decision by an FBS team:
  - opening possession: if they chose to receive, did that first drive score (TD / FG)?
  - what deferring gives up: opponent's opening-drive scoring; own 2nd-half opening drive.
  - first half: led at halftime? covered the first-half spread?
First-half spreads are not in ESPN's feed; they are estimated as half the full-game spread.

Inputs: data/coach_decisions.csv, data/fbs_toss_games.csv, data/odds_fbs.csv,
        data/linescores.csv, data/games_fbs.jsonl, data/team_games_coaches.csv
Outputs: data/decision_outcomes.csv, data/halves_results.json, data/coach_card.csv
"""
import json
import os

import numpy as np
import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(H, "data", f)  # noqa: E731
S = {"dtype": {"game_id": str, "team_id": str, "home_id": str}}

d = pd.read_csv(P("coach_decisions.csv"), **S)
d = d[d.decision.isin(["receive", "defer"])].copy()
g = pd.read_csv(P("fbs_toss_games.csv"), **S)[["game_id", "home_id", "away_id", "home_score", "away_score"]]
g["away_id"] = g.away_id.astype(str)
o = pd.read_csv(P("odds_fbs.csv"), dtype={"game_id": str})[["game_id", "home_spread"]]
ls = pd.read_csv(P("linescores.csv"), dtype={"game_id": str})

# drive facts per game
dr = {}
for line in open(P("games_fbs.jsonl")):
    gm = json.loads(line)
    drives = [x for x in gm.get("drives", []) if x.get("team_id")]

    def first(period):
        x = [v for v in drives if v["start_period"] == period]
        if not x:
            return None, None
        v = x[0]
        b, a = v["score_before"], v["score_after"]
        home = next(t["id"] for t in gm["teams"] if t["home_away"] == "home")
        if None in b or None in a:
            return v["team_id"], None
        i = 1 if v["team_id"] == home else 0
        # points for the drive team (a kickoff/punt return TD by the other side shows up as 0 here)
        return v["team_id"], (a[i] or 0) - (b[i] or 0)

    t1, p1 = first(1)
    t3, p3 = first(3)
    dr[gm["game_id"]] = (t1, p1, t3, p3)
dd = pd.DataFrame([(k, *v) for k, v in dr.items()],
                  columns=["game_id", "open_team", "open_pts", "h2_team", "h2_pts"])

x = d.merge(g, on="game_id").merge(o, on="game_id", how="left").merge(ls, on="game_id").merge(dd, on="game_id", how="left")
home = x.team_id == x.home_id
x["spread"] = np.where(home, x.home_spread, -x.home_spread)          # negative = favored
q = lambda s, a, b: x[[f"{s}_q{i}" for i in range(a, b + 1)]].sum(axis=1)  # noqa: E731
x["h1_for"] = np.where(home, q("home", 1, 2), q("away", 1, 2))
x["h1_against"] = np.where(home, q("away", 1, 2), q("home", 1, 2))
x["h1_margin"] = x.h1_for - x.h1_against
x["h1_result"] = np.select([x.h1_margin > 0, x.h1_margin < 0], ["Led", "Trailed"], "Tied")
x["h1_spread"] = x.spread / 2.0
x["h1_ats"] = x.h1_margin + x.h1_spread
x["h1_cover"] = np.where(x.h1_ats == 0, np.nan, (x.h1_ats > 0).astype(float))
x["receive"] = (x.decision == "receive").astype(int)
# opening drive: who had it and did it score
x["open_is_winner"] = x.open_team == x.team_id
x["open_score"] = np.where(x.open_pts.isna(), np.nan, (x.open_pts > 0).astype(float))
x["open_td"] = np.where(x.open_pts.isna(), np.nan, (x.open_pts >= 6).astype(float))
x["h2_is_winner"] = x.h2_team == x.team_id
x["h2_score"] = np.where(x.h2_pts.isna(), np.nan, (x.h2_pts > 0).astype(float))
# keep games where the drive log agrees with the decision (opening drive belongs to the receiver)
x["drive_ok"] = (x.receive == 1) == x.open_is_winner
x.to_csv(P("decision_outcomes.csv"), index=False)

ok = x[x.drive_ok]


def pct(s):
    s = s.dropna()
    return round(100 * s.mean(), 1) if len(s) else None


def ci(s):
    s = s.dropna()
    if len(s) < 2:
        return None
    p = s.mean()
    h = 1.96 * np.sqrt(p * (1 - p) / len(s))
    return [round(100 * (p - h), 1), round(100 * (p + h), 1)]


rec, dfr = ok[ok.receive == 1], ok[ok.receive == 0]
res = {
    "decisions": int(len(x)), "drive_consistent": int(len(ok)),
    "receive": {
        "n": int(len(rec)),
        "open_drive_score_pct": pct(rec.open_score), "open_drive_score_ci": ci(rec.open_score),
        "open_drive_td_pct": pct(rec.open_td),
        "h1_led_pct": pct((rec.h1_margin > 0).astype(float)), "h1_trailed_pct": pct((rec.h1_margin < 0).astype(float)),
        "h1_cover_pct": pct(rec.h1_cover), "h1_cover_ci": ci(rec.h1_cover),
        "h1_vs_spread_avg": round(rec.h1_ats.mean(), 2),
    },
    "defer": {
        "n": int(len(dfr)),
        "opp_open_drive_score_pct": pct(dfr.open_score), "opp_open_drive_td_pct": pct(dfr.open_td),
        "own_h2_open_score_pct": pct(dfr[dfr.h2_is_winner].h2_score),
        "h1_led_pct": pct((dfr.h1_margin > 0).astype(float)), "h1_trailed_pct": pct((dfr.h1_margin < 0).astype(float)),
        "h1_cover_pct": pct(dfr.h1_cover), "h1_cover_ci": ci(dfr.h1_cover),
        "h1_vs_spread_avg": round(dfr.h1_ats.mean(), 2),
    },
}
# same comparison within coach (coaches who did both), decision-weighted
both = ok.groupby("coach").receive.transform(lambda v: 0 < v.mean() < 1)
w = ok[both].groupby(["coach", "receive"]).h1_cover.agg(["mean", "count"]).unstack().dropna()
res["within_coach_h1_cover"] = {
    "coaches": int(len(w)),
    "receive_pct": round(100 * float(np.average(w[("mean", 1)], weights=w[("count", 1)])), 1),
    "defer_pct": round(100 * float(np.average(w[("mean", 0)], weights=w[("count", 0)])), 1),
}

# --- structural: team that took the opening kickoff, all games with a line -------------
gm = pd.read_csv(P("fbs_toss_games.csv"), dtype={"game_id": str, "home_id": str, "away_id": str,
                                                   "opening_receiver_id": str})
gm = gm.merge(ls, on="game_id").merge(o, on="game_id").dropna(subset=["home_spread", "opening_receiver_id"])
gm = gm[(gm.opening_receiver_id == gm.home_id) | (gm.opening_receiver_id == gm.away_id)]
hm = gm.opening_receiver_id == gm.home_id
sp = np.where(hm, gm.home_spread, -gm.home_spread)
sgn = np.where(hm, 1, -1)
h1 = sgn * (gm.home_q1 + gm.home_q2 - gm.away_q1 - gm.away_q2)
h2 = sgn * (gm.home_q3 + gm.home_q4 - gm.away_q3 - gm.away_q4)
fg = sgn * (gm.home_score - gm.away_score)


def cover(v):
    v = pd.Series(v)
    v = v[v != 0]
    p = (v > 0).mean()
    h = 1.96 * np.sqrt(p * (1 - p) / len(v))
    return {"cover_pct": round(100 * p, 1), "ci": [round(100 * (p - h), 1), round(100 * (p + h), 1)], "n": int(len(v))}


res["opening_receiver_all_games"] = {
    "games": int(len(gm)),
    "first_half": {**cover(h1 + sp / 2), "avg_vs_line": round(float((h1 + sp / 2).mean()), 2)},
    "second_half": {**cover(h2 + sp / 2), "avg_vs_line": round(float((h2 + sp / 2).mean()), 2)},
    "full_game": {**cover(fg + sp), "avg_vs_line": round(float((fg + sp).mean()), 2)},
    "first_half_by_season": {int(k): round(100 * float((v[v != 0] > 0).mean()), 1)
                             for k, v in pd.Series(h1 + sp / 2).groupby(gm.season.values)},
}

# --- coach card: current (2026) head coaches -------------------------------------------
tg = pd.read_csv(P("team_games_coaches.csv"), dtype={"team_id": str})
cur = tg[tg.season == 2026].sort_values("date").groupby("team").coach.last().reset_index()
cur.columns = ["current_team", "coach"]


def card(c):
    a, r, f = ok[ok.coach == c], ok[(ok.coach == c) & (ok.receive == 1)], ok[(ok.coach == c) & (ok.receive == 0)]
    return pd.Series({
        "tosses_won": len(a), "receive_pct": pct(a.receive.astype(float)),
        "recv_n": len(r), "recv_open_score_pct": pct(r.open_score), "recv_open_td_pct": pct(r.open_td),
        "recv_h1_led_pct": pct((r.h1_margin > 0).astype(float)), "recv_h1_cover_pct": pct(r.h1_cover),
        "defer_n": len(f), "defer_opp_open_score_pct": pct(f.open_score),
        "defer_h2_open_score_pct": pct(f[f.h2_is_winner].h2_score),
        "defer_h1_led_pct": pct((f.h1_margin > 0).astype(float)), "defer_h1_cover_pct": pct(f.h1_cover),
        "schools_in_data": ", ".join(dict.fromkeys(a.sort_values("date").team)),
    })


cc = cur.join(cur.coach.apply(card))
# receive rate shrunk toward the FBS average (worth 8 decisions) for matchup estimates
base = ok.receive.mean()
recs = ok.groupby("coach").receive.agg(["sum", "size"])
cc["receive_est"] = cc.coach.map(((recs["sum"] + 8 * base) / (recs["size"] + 8)).round(3)).fillna(round(base, 3))
cc = cc.sort_values(["receive_pct", "tosses_won"], ascending=[False, False])
cc.to_csv(P("coach_card.csv"), index=False)
res["coach_card"] = cc.to_dict("records")
res["fbs_receive_rate"] = round(float(base), 3)
json.dump(res, open(P("halves_results.json"), "w"), indent=1, default=lambda v: None if pd.isna(v) else float(v))

if __name__ == "__main__":
    print(json.dumps({k: v for k, v in res.items() if k != "coach_card"}, indent=1))
    pd.set_option("display.width", 250)
    print(cc[cc.recv_n >= 5].to_string(index=False))
