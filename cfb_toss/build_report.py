"""Embed results into report_template.html -> report.html."""
import json, os
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
r = json.load(open(os.path.join(HERE, "data", "results.json")))
t = pd.read_csv(os.path.join(HERE, "data", "toss_decisions.csv"))
teams = (t.groupby("team").agg(n=("receive", "size"), rec=("receive", "sum"), conf=("conf", "last"))
         .reset_index())
teams = teams[teams.n >= 12].assign(pct=lambda d: (100 * d.rec / d.n).round(1)).sort_values("pct", ascending=False)
ts = t.groupby(["team", "season"]).agg(n=("receive", "size"), rec=("receive", "sum")).reset_index()
focus = ["Mississippi State", "West Virginia", "USC", "Oklahoma", "Ole Miss", "SMU", "Iowa", "Syracuse"]
seasons = {tm: {int(s): [int(rc), int(n)] for s, rc, n in g[["season", "rec", "n"]].values}
           for tm, g in ts[ts.team.isin(focus)].groupby("team")}
fam = (pd.read_csv(os.path.join(HERE, "data", "toss_games.csv")).toss_family.value_counts().to_dict())
data = {k: r[k] for k in ("coverage", "overall_power_teams", "by_season", "by_conf", "by_site", "by_spread",
                          "by_opponent", "by_phase", "by_family", "outcomes", "regression", "drives")}
data["teams"] = teams.to_dict("records")
data["team_seasons"] = seasons
data["family_counts"] = fam
html = open(os.path.join(HERE, "report_template.html")).read().replace("__DATA__", json.dumps(data))
open(os.path.join(HERE, "report.html"), "w").write(html)
print("teams", len(teams), "bytes", len(html))
