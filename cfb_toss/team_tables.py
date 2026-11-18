"""Team-level toss tables from data/fbs_toss_games.csv (FBS teams only).

Outputs:
  data/fbs_team_decisions.csv  one row per verified toss won by an FBS team
  data/fbs_team_season.csv     receives / tosses won by team and season
  data/fbs_team_coverage.csv   games played vs. games with a verified toss record, per team
  data/fbs_missing_games.csv   every game without a verified toss record, with the reason
"""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
g = pd.read_csv(os.path.join(HERE, "data", "fbs_toss_games.csv"), dtype={"home_id": str, "away_id": str, "toss_winner_id": str})
ok = g.status.str.startswith("verified")
# ESPN renames some schools over time (e.g. "Appalachian State" -> "App State"); key by id and
# use each team's most recent name everywhere.
names = pd.concat([g[["date", "home_id", "home"]].set_axis(["date", "id", "name"], axis=1),
                   g[["date", "away_id", "away"]].set_axis(["date", "id", "name"], axis=1)])
NAME = names.sort_values("date").groupby("id").name.last().to_dict()
for side in ("home", "away"):
    g[side] = g[side + "_id"].map(NAME)
g["toss_winner"] = g.toss_winner_id.map(NAME)

# decisions by FBS toss winners
d = g[ok].copy()
d["winner_fbs"] = ((d.toss_winner_id == d.home_id) & d.home_fbs) | ((d.toss_winner_id == d.away_id) & d.away_fbs)
d["opponent"] = d.apply(lambda r: r.away if r.toss_winner_id == r.home_id else r.home, axis=1)
d["site"] = d.apply(lambda r: "Neutral" if r.neutral else ("Home" if r.toss_winner_id == r.home_id else "Away"), axis=1)
d = d[d.winner_fbs]
d[["game_id", "season", "date", "toss_winner_id", "toss_winner", "opponent", "site", "decision", "status", "toss_text"]] \
    .rename(columns={"toss_winner_id": "team_id", "toss_winner": "team"}) \
    .to_csv(os.path.join(HERE, "data", "fbs_team_decisions.csv"), index=False)

ts = d.assign(rec=d.decision.eq("receive")).groupby(["toss_winner", "season"]).rec.agg(receives="sum", tosses_won="size").reset_index()
ts.rename(columns={"toss_winner": "team"}).to_csv(os.path.join(HERE, "data", "fbs_team_season.csv"), index=False)

# coverage per FBS team
long = pd.concat([
    g[g.home_fbs].assign(team=g.home, team_id=g.home_id, verified=ok),
    g[g.away_fbs].assign(team=g.away, team_id=g.away_id, verified=ok),
])
cov = long.groupby(["team_id", "team"]).agg(games=("game_id", "size"), verified=("verified", "sum")).reset_index()
cov["coverage_pct"] = (100 * cov.verified / cov.games).round(1)
cov = cov.sort_values("coverage_pct")
cov.to_csv(os.path.join(HERE, "data", "fbs_team_coverage.csv"), index=False)

g[~ok][["game_id", "season", "date", "away", "home", "status", "toss_text"]] \
    .to_csv(os.path.join(HERE, "data", "fbs_missing_games.csv"), index=False)

tot = d.assign(rec=d.decision.eq("receive")).groupby("toss_winner").rec.agg(["sum", "size"])
print("FBS teams:", cov.shape[0], " decisions:", len(d), " receive rate:", round(100 * d.decision.eq("receive").mean(), 1))
print("team coverage: median", cov.coverage_pct.median(), " min", cov.coverage_pct.min())
print(cov.head(12).to_string(index=False))
print("teams with 100% coverage:", (cov.coverage_pct == 100).sum())
