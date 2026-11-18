"""Coach vs. school: who drives the 'win the toss, take the ball' decision?

Inputs: data/team_games_coaches.csv (coaches.py)
Outputs (data/): coach_decisions.csv, coach_summary.csv, coach_movers.csv,
                 school_coach_changes.csv, coach_vs_school.json
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda *a: os.path.join(HERE, "data", *a)  # noqa: E731

tg = pd.read_csv(P("team_games_coaches.csv"), dtype={"team_id": str, "toss_winner_id": str, "game_id": str})
tg["verified"] = tg.status.str.startswith("verified")

# coverage: share of each coach's games with a verified toss record
cov = tg.groupby("coach").agg(games=("game_id", "size"), verified_games=("verified", "sum"))

# decisions made by this team's coach = verified games where this team won the toss
d = tg[tg.verified & (tg.toss_winner_id == tg.team_id) & tg.decision.isin(["receive", "defer", "kick"])].copy()
d["receive"] = (d.decision == "receive").astype(int)
d[["game_id", "season", "date", "team_id", "team", "coach", "opponent", "site", "decision", "status", "toss_text"]] \
    .to_csv(P("coach_decisions.csv"), index=False)
BASE = d.receive.mean()


def summarize(g):
    return pd.Series({"tosses_won": len(g), "receives": int(g.receive.sum()),
                      "receive_pct": round(100 * g.receive.mean(), 1),
                      "schools": ", ".join(dict.fromkeys(g.sort_values("date").team)),
                      "seasons": f"{g.season.min()}–{g.season.max()}"})


cs = d.groupby("coach").apply(summarize, include_groups=False).join(cov)
cs["coverage_pct"] = (100 * cs.verified_games / cs.games).round(1)
cs = cs.sort_values(["receive_pct", "tosses_won"], ascending=[False, False])
cs.to_csv(P("coach_summary.csv"))

# coaches who were head coach at 2+ schools in the window
ct = d.groupby(["coach", "team"]).agg(tosses_won=("receive", "size"), receives=("receive", "sum"),
                                       first=("date", "min"), last=("date", "max")).reset_index()
movers = ct[ct.coach.isin(ct.groupby("coach").team.nunique().loc[lambda s: s > 1].index)]
movers = movers.assign(receive_pct=(100 * movers.receives / movers.tosses_won).round(1)).sort_values(["coach", "first"])
movers.to_csv(P("coach_movers.csv"), index=False)

# schools with 2+ coaches in the window (interims included)
st = d.groupby(["team", "coach"]).agg(tosses_won=("receive", "size"), receives=("receive", "sum"),
                                       first=("date", "min"), last=("date", "max")).reset_index()
changes = st[st.team.isin(st.groupby("team").coach.nunique().loc[lambda s: s > 1].index)]
changes = changes.assign(receive_pct=(100 * changes.receives / changes.tosses_won).round(1)).sort_values(["team", "first"])
changes.to_csv(P("school_coach_changes.csv"), index=False)


# --- Which predicts a held-out decision better: the coach's other decisions or the school's? ---
def cv_logloss(key, k=10, prior=8, seed=0):
    """Predict each decision from the rest of the same group's decisions (shrunk toward the
    overall rate with a prior worth `prior` decisions); score with log-loss."""
    rng = np.random.default_rng(seed)
    fold = rng.integers(0, k, len(d))
    losses = []
    for f in range(k):
        tr, te = d[fold != f], d[fold == f]
        base = tr.receive.mean()
        agg = tr.groupby(key).receive.agg(["sum", "size"])
        p = ((agg["sum"] + prior * base) / (agg["size"] + prior)).reindex(te[key]).fillna(base).clip(1e-3, 1 - 1e-3).values
        y = te.receive.values
        losses.append(-(y * np.log(p) + (1 - y) * np.log(1 - p)))
    return float(np.concatenate(losses).mean())


d["coach_school"] = d.coach + " @ " + d.team
ll = {name: round(cv_logloss(key), 4) for name, key in
      [("school", "team"), ("coach", "coach"), ("coach_at_school", "coach_school")]}
ll["no_info_baseline"] = round(float(-(BASE * np.log(BASE) + (1 - BASE) * np.log(1 - BASE))), 4)

# Same test restricted to the decisions where coach and school disagree as predictors:
# schools that changed coaches, and coaches who changed schools.
mv = d[d.coach.isin(movers.coach.unique()) | d.team.isin(changes.team.unique())]


def split_test(sub):
    """Within schools that changed coaches: does the coach's rate elsewhere in the window
    predict better than the school's rate under other coaches?"""
    rows = []
    for r in sub.itertuples():
        same_coach_other = d[(d.coach == r.coach) & (d.game_id != r.game_id)]
        same_school_other_coach = d[(d.team == r.team) & (d.coach != r.coach)]
        if len(same_coach_other) >= 5 and len(same_school_other_coach) >= 5:
            rows.append((r.receive, same_coach_other.receive.mean(), same_school_other_coach.receive.mean()))
    a = np.array(rows)
    if not len(a):
        return {}
    y, pc, ps = a[:, 0], a[:, 1], a[:, 2]
    clip = lambda p: np.clip(p, 0.02, 0.98)  # noqa: E731
    lo = lambda p: float(-(y * np.log(clip(p)) + (1 - y) * np.log(1 - clip(p))).mean())  # noqa: E731
    return {"n": int(len(a)), "logloss_coach_history": round(lo(pc), 4),
            "logloss_school_under_other_coaches": round(lo(ps), 4),
            "corr_coach": round(float(np.corrcoef(y, pc)[0, 1]), 3),
            "corr_school": round(float(np.corrcoef(y, ps)[0, 1]), 3)}


res = {
    "decisions": int(len(d)), "receive_pct": round(100 * BASE, 1), "coaches": int(d.coach.nunique()),
    "schools": int(d.team.nunique()), "movers": int(movers.coach.nunique()),
    "schools_with_change": int(changes.team.nunique()),
    "cv_logloss_lower_is_better": ll,
    "head_to_head_within_changed_schools": split_test(d[d.team.isin(changes.team.unique())]),
}
json.dump(res, open(P("coach_vs_school.json"), "w"), indent=1)

if __name__ == "__main__":
    print(json.dumps(res, indent=1))
    pd.set_option("display.width", 200)
    print(cs[cs.tosses_won >= 12].head(15).to_string())
    print(movers.to_string(index=False))
