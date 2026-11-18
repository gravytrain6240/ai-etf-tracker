"""Analysis of 'win the toss, choose to receive' for power-conference teams.

Reads data/toss_games.csv (from parse.py) and writes data/results.json plus
team-level CSVs used by the report.
"""
import json
import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import norm

import parse

HERE = os.path.dirname(os.path.abspath(__file__))
SIGMA = 15.5  # std. dev. of CFB final margin around the closing spread


def team_view(df):
    """One row per (game, toss-winning power team) decision."""
    d = df[df.decision.isin(["receive", "defer", "kick"]) & df.toss_winner_id.notna()
           & (df.toss_family != "A")].copy()
    is_home = d.toss_winner_id == d.home_id
    d["team_id"] = np.where(is_home, d.home_id, d.away_id)
    d["team"] = np.where(is_home, d.home, d.away)
    d["opp"] = np.where(is_home, d.away, d.home)
    d["conf"] = np.where(is_home, d.home_conf, d.away_conf)
    d["opp_conf"] = np.where(is_home, d.away_conf, d.home_conf)
    d["power"] = np.where(is_home, d.home_power, d.away_power)
    d["site"] = np.where(d.neutral, "Neutral", np.where(is_home, "Home", "Away"))
    pts = np.where(is_home, d.home_score, d.away_score)
    opp_pts = np.where(is_home, d.away_score, d.home_score)
    d["margin"] = pts - opp_pts
    d["win"] = (d.margin > 0).astype(int)
    d["spread"] = np.where(is_home, d.home_spread, -d.home_spread)  # negative = favored
    d["exp_margin"] = -d.spread
    d["exp_win"] = norm.cdf(d.exp_margin / SIGMA)
    d["ats_margin"] = d.margin + d.spread
    d["cover"] = np.where(d.ats_margin == 0, np.nan, (d.ats_margin > 0).astype(float))
    d["receive"] = (d.decision == "receive").astype(int)
    ht_team = np.where(is_home, d.get("ht_home"), d.get("ht_away"))
    ht_opp = np.where(is_home, d.get("ht_away"), d.get("ht_home"))
    d["ht_margin"] = ht_team - ht_opp
    d["h2_margin"] = d.margin - d.ht_margin
    d["fav_bucket"] = pd.cut(d.spread, [-100, -21, -10, -3, 3, 10, 100],
                             labels=["Fav 21+", "Fav 10-21", "Fav 3-10", "Pick'em (±3)",
                                     "Dog 3-10", "Dog 10+"])
    d["vs_power"] = d.opp_conf != "Non-power"
    dt = pd.to_datetime(d.date)
    d["phase"] = np.where((dt.dt.month == 1) | ((dt.dt.month == 12) & (dt.dt.day >= 12)),
                          "Bowls / CFP",
                          np.where((dt.dt.month == 12) | (d.neutral & (dt.dt.month == 11) & (dt.dt.day >= 29)),
                                   "Conf. championships", "Regular season"))
    return d


def rate(s):
    return round(100 * s.mean(), 1)


def grp(d, col, min_n=1):
    g = d.groupby(col, observed=True).agg(n=("receive", "size"), receive_pct=("receive", rate))
    return g[g.n >= min_n].reset_index()


def drive_outcomes(df):
    """Opening-drive and 2nd-half-opening-drive scoring, by how the receiver got the ball."""
    d = df[(df.consistent == True) & (df.toss_family != "A")].copy()  # noqa: E712
    d["open_via"] = np.where(d.decision == "receive", "Toss winner chose to receive",
                             "Received after opponent deferred")
    out = {}
    for via, g in d.groupby("open_via"):
        pts = g.open_drive_points.dropna()
        out[via] = {"n": int(len(pts)), "score_pct": rate(pts > 0), "td_pct": rate(pts >= 6),
                    "avg_pts": round(pts.mean(), 2)}
    # 2nd half opening drive: the deferring team (if winner deferred) gets it
    h2 = d[d.decision == "defer"].h2_drive_points.dropna()
    h1 = d.open_drive_points.dropna()
    out["second_half_opener_all"] = {"n": int(len(d.h2_drive_points.dropna())),
                                     "score_pct": rate(d.h2_drive_points.dropna() > 0),
                                     "avg_pts": round(d.h2_drive_points.dropna().mean(), 2)}
    out["first_half_opener_all"] = {"n": int(len(h1)), "score_pct": rate(h1 > 0),
                                    "avg_pts": round(h1.mean(), 2)}
    out["second_half_opener_deferrer"] = {"n": int(len(h2)), "score_pct": rate(h2 > 0),
                                          "avg_pts": round(h2.mean(), 2)}
    # double dip: same team scores on last possession of H1 and first possession of H2
    dd = d.dropna(subset=["h1_last_drive_team", "h2_receiver_id"])
    dd = dd[dd.h1_last_drive_team == dd.h2_receiver_id]
    hit = (dd.h1_last_drive_points > 0) & (dd.h2_drive_points > 0)
    out["double_dip"] = {"opportunities": int(len(dd)), "hits": int(hit.sum()),
                         "pct_of_opportunities": rate(hit),
                         "pct_of_all_games": round(100 * hit.sum() / len(d), 1)}
    return out


def outcomes(t):
    t = t[(t.consistent == True) & t.decision.isin(["receive", "defer"])]  # noqa: E712
    rows = []
    for dec, g in t.groupby("decision"):
        s = g.dropna(subset=["spread"])
        rows.append({
            "decision": dec, "n": len(g), "win_pct": rate(g.win),
            "n_with_spread": len(s), "avg_spread": round(s.spread.mean(), 1),
            "expected_win_pct": rate(s.exp_win), "actual_win_pct_with_spread": rate(s.win),
            "win_over_expected": round(100 * (s.win.mean() - s.exp_win.mean()), 1),
            "avg_ats_margin": round(s.ats_margin.mean(), 2), "cover_pct": rate(s.cover.dropna()),
            "avg_ht_margin": round(g.ht_margin.mean(), 2),
            "avg_2h_margin": round(g.h2_margin.mean(), 2),
            # half-by-half margin vs. expectation (half of the spread-implied margin)
            "h1_vs_exp": round((s.ht_margin - s.exp_margin / 2).mean(), 2),
            "h1_vs_exp_se": round((s.ht_margin - s.exp_margin / 2).std() / np.sqrt(len(s)), 2),
            "h2_vs_exp": round((s.h2_margin - s.exp_margin / 2).mean(), 2),
            "h2_vs_exp_se": round((s.h2_margin - s.exp_margin / 2).std() / np.sqrt(len(s)), 2),
            "ats_margin_se": round(s.ats_margin.std() / np.sqrt(len(s)), 2),
        })
    # regression: does choosing receive change margin after controlling for spread & site?
    s = t.dropna(subset=["spread"]).copy()
    s["home"] = (s.site == "Home").astype(int)
    s["neutral"] = (s.site == "Neutral").astype(int)
    ols = smf.ols("margin ~ receive + exp_margin + home + neutral", data=s).fit(cov_type="HC1")
    logit = smf.logit("win ~ receive + exp_margin + home + neutral", data=s).fit(disp=0)
    reg = {
        "ols_receive_coef": round(ols.params["receive"], 2),
        "ols_receive_ci": [round(x, 2) for x in ols.conf_int().loc["receive"]],
        "ols_receive_p": round(ols.pvalues["receive"], 3),
        "logit_receive_odds_ratio": round(float(np.exp(logit.params["receive"])), 3),
        "logit_receive_p": round(logit.pvalues["receive"], 3),
        "n": int(len(s)),
    }
    return rows, reg


def main():
    df = parse.build()
    games_total = len(df)
    has_toss = df.toss_text.notna()
    t_all = team_view(df)
    t = t_all[t_all.power]  # decisions made by power-conference teams

    res = {
        "coverage": {
            "games": games_total, "games_with_toss_text": int(has_toss.sum()),
            "decided": int(df.decision.notna().sum()),
            "consistency_check_pct": rate(df.consistent.dropna().astype(float)),
            "inconsistent_games": int((df.consistent == False).sum()),  # noqa: E712
            "seasons": sorted(df.season.unique().tolist()),
            "by_season_games": df.groupby("season").size().to_dict(),
            "decision_text_breakdown": df.decision_text.fillna("no toss record").value_counts().to_dict(),
        },
        "overall_power_teams": {
            "n": len(t), "receive_pct": rate(t.receive),
            "defer_pct": rate(t.decision == "defer"), "kick_pct": rate(t.decision == "kick"),
        },
        "overall_all_toss_winners": {"n": len(t_all), "receive_pct": rate(t_all.receive)},
        "non_power_vs_power": {"n": int((~t_all.power).sum()),
                               "receive_pct": rate(t_all[~t_all.power].receive)},
        "by_season": grp(t, "season").to_dict("records"),
        "by_conf": grp(t[t.conf != "Non-power"], "conf").to_dict("records"),
        "by_conf_season": grp(t, ["conf", "season"]).to_dict("records"),
        "by_site": grp(t, "site").to_dict("records"),
        "by_spread": grp(t.dropna(subset=["spread"]), "fav_bucket").to_dict("records"),
        "by_opponent": grp(t.assign(opp_type=np.where(t.vs_power, "vs Power", "vs Non-power")),
                           "opp_type").to_dict("records"),
        "by_phase": grp(t, "phase").to_dict("records"),
        "by_family": grp(t_all, "toss_family").to_dict("records"),
        "by_month": grp(t.assign(month=pd.to_datetime(t.date).dt.month_name().str[:3]),
                        "month").to_dict("records"),
    }
    res["outcomes"], res["regression"] = outcomes(t)
    res["drives"] = drive_outcomes(df)

    # team tendencies
    teams = t.groupby(["team", "conf"] if False else "team").agg(
        n=("receive", "size"), receives=("receive", "sum"), receive_pct=("receive", rate),
        conf=("conf", lambda s: s.iloc[-1]),
        win_pct_when_receive=("win", lambda s: np.nan),
    ).reset_index()
    rec = t[t.receive == 1].groupby("team").ats_margin.mean().round(1)
    dfr = t[t.receive == 0].groupby("team").ats_margin.mean().round(1)
    teams["ats_when_receive"] = teams.team.map(rec)
    teams["ats_when_defer"] = teams.team.map(dfr)
    teams = teams.drop(columns="win_pct_when_receive").sort_values("receive_pct", ascending=False)
    teams.to_csv(os.path.join(HERE, "data", "team_tendencies.csv"), index=False)
    res["teams"] = teams.to_dict("records")

    ts = t.groupby(["team", "season"]).agg(n=("receive", "size"), receive_pct=("receive", rate)).reset_index()
    ts.to_csv(os.path.join(HERE, "data", "team_season_tendencies.csv"), index=False)
    res["team_seasons"] = ts.to_dict("records")

    # teams that flipped strategy (>= 60 pt swing between seasons, with >=4 tosses each)
    flips = []
    for team, g in ts[ts.n >= 4].groupby("team"):
        if g.receive_pct.max() - g.receive_pct.min() >= 60:
            flips.append({"team": team, "by_season": dict(zip(g.season.astype(str), g.receive_pct))})
    res["strategy_flips"] = flips

    # overtime toss winners (first OT toss of the game)
    ot = df[df.ot_toss_text.notna()]
    res["overtime"] = {"games_with_ot_toss": int(len(ot)),
                       "samples": ot.ot_toss_text.head(8).tolist()}

    t.to_csv(os.path.join(HERE, "data", "toss_decisions.csv"), index=False)
    with open(os.path.join(HERE, "data", "results.json"), "w") as f:
        json.dump(res, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: r[k] for k in ("coverage", "overall_power_teams", "by_season", "by_conf",
                                         "by_site", "by_spread", "by_opponent", "outcomes",
                                         "regression", "drives")}, indent=1, default=str))
