"""Attach the head coach to every FBS team-game since 2022.

CollegeFootballData lists, per coach, the school, season and number of games coached, but
not which games. Within a team-season with more than one coach, games are assigned in date
order: the coach who held the job the previous season coaches first (a fired coach, or one
who left before the bowl), then later arrivals by hire date, each for his game count.
CFBD team ids are ESPN team ids.

Inputs: data/cfbd_coaches.csv, data/fbs_toss_games.csv
Output: data/team_games_coaches.csv  (one row per FBS team per game)
"""
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def team_games():
    g = pd.read_csv(os.path.join(HERE, "data", "fbs_toss_games.csv"),
                    dtype={"home_id": str, "away_id": str, "toss_winner_id": str})
    sides = []
    for side, opp in (("home", "away"), ("away", "home")):
        s = g[g[f"{side}_fbs"]].copy()
        s["team_id"], s["team"] = s[f"{side}_id"], s[side]
        s["opp_id"], s["opponent"] = s[f"{opp}_id"], s[opp]
        s["site"] = s.neutral.map({True: "Neutral"}).fillna(side.title())
        sides.append(s)
    t = pd.concat(sides)
    return t.sort_values(["team_id", "date", "game_id"]).reset_index(drop=True)


def assign(tg, coaches):
    coaches = coaches.copy()
    coaches["team_id"] = coaches.team_id.astype(str)
    prev = {(r.team_id, r.season, r.coach) for r in coaches.itertuples()}
    out, issues = [], []
    for (tid, season), games in tg.groupby(["team_id", "season"]):
        c = coaches[(coaches.team_id == tid) & (coaches.season == season)].copy()
        games = games.sort_values("date")
        if c.empty:
            issues.append((tid, season, games.team.iloc[0], "no coach listed", len(games), 0))
            out.append(games.assign(coach=None, coach_method="missing"))
            continue
        if len(c) == 1:
            out.append(games.assign(coach=c.coach.iloc[0], coach_method="sole coach"))
            if c.games.iloc[0] and c.games.iloc[0] != len(games):
                issues.append((tid, season, games.team.iloc[0], "game count differs",
                               len(games), int(c.games.iloc[0])))
            continue
        c["incumbent"] = [(tid, season - 1, n) in prev for n in c.coach]
        c = c.sort_values(["incumbent", "hire_date", "games"], ascending=[False, True, False])
        if c.games.sum() != len(games):
            issues.append((tid, season, games.team.iloc[0], "split counts differ",
                           len(games), int(c.games.sum())))
        names = []
        for r in c.itertuples():
            names += [r.coach] * int(r.games)
        names = (names + [c.coach.iloc[-1]] * len(games))[: len(games)]  # pad with latest coach
        out.append(games.assign(coach=names, coach_method="split by game count"))
    issues = pd.DataFrame(issues, columns=["team_id", "season", "team", "issue", "espn_games", "cfbd_games"])
    return pd.concat(out), issues


if __name__ == "__main__":
    coaches = pd.read_csv(os.path.join(HERE, "data", "cfbd_coaches.csv"), dtype={"team_id": str})
    tg, issues = assign(team_games(), coaches)
    tg.to_csv(os.path.join(HERE, "data", "team_games_coaches.csv"), index=False)
    issues.to_csv(os.path.join(HERE, "data", "coach_assignment_issues.csv"), index=False)
    print(len(tg), "team-games;", tg.coach.notna().mean().round(4) * 100, "% with coach")
    print(tg.coach_method.value_counts().to_dict())
    print(issues.issue.value_counts().to_dict())
    print(issues.head(25).to_string(index=False))
