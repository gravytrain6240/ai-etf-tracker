"""Embed coach/team results into coach_report_template.html -> report.html."""
import json, os
import pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); P = lambda f: os.path.join(H, "data", f)
g = pd.read_csv(P("fbs_toss_games.csv"))
g["ok"] = g.status.str.startswith("verified")
cs = pd.read_csv(P("coach_summary.csv"))
mv = pd.read_csv(P("coach_movers.csv")); ch = pd.read_csv(P("school_coach_changes.csv"))
cov = pd.read_csv(P("fbs_team_coverage.csv"))
res = json.load(open(P("coach_vs_school.json")))
ts = pd.read_csv(P("fbs_team_season.csv"))
season_rate = ts.groupby("season")[["receives", "tosses_won"]].sum()
data = {
  "res": res,
  "games": int(len(g)), "verified": int(g.ok.sum()),
  "by_season": [{"season": int(s), "games": int(len(x)), "verified": int(x.ok.sum()),
                 "receive_pct": round(100 * season_rate.loc[s, "receives"] / season_rate.loc[s, "tosses_won"], 1)}
                for s, x in g.groupby("season")],
  "gaps": g[~g.ok].status.value_counts().to_dict(),
  "takers": cs[(cs.tosses_won >= 12) & (cs.receive_pct >= 40)].to_dict("records"),
  "never": cs[(cs.tosses_won >= 15) & (cs.receives == 0)].sort_values("tosses_won", ascending=False).to_dict("records"),
  "coaches_n15": int((cs.tosses_won >= 15).sum()),
  "movers": mv.to_dict("records"),
  "changes": ch.to_dict("records"),
  "low_cov": cov[cov.games >= 20].head(12).to_dict("records"),
  "cov_median": float(cov.coverage_pct.median()),
}
html = open(os.path.join(H, "coach_report_template.html")).read().replace("__DATA__", json.dumps(data, default=str))
open(os.path.join(H, "report.html"), "w").write(html)
print("ok", len(html))
