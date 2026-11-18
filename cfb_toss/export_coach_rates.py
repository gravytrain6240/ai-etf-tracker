"""Export current FBS head coaches' toss tendencies for the weekly email -> JSON.

Usage: python export_coach_rates.py OUT.json
Each entry is keyed by ESPN team id and carries the 2026 head coach, his raw record when
winning the toss (any school, 2022+), a receive-rate estimate shrunk toward the FBS average
(prior worth 8 decisions), and his opening-drive / first-half history after receiving.
"""
import json
import sys

import pandas as pd

D = "data/"
tg = pd.read_csv(D + "team_games_coaches.csv", dtype={"team_id": str})
cur = tg[tg.season == 2026].sort_values("date").groupby("team_id").agg(team=("team", "last"), coach=("coach", "last"))
card = pd.read_csv(D + "coach_card.csv").set_index("coach")
h = json.load(open(D + "halves_results.json"))
out = {"generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
       "fbs_receive_rate": h["fbs_receive_rate"],
       "receiver_1h_cover": h["opening_receiver_all_games"]["first_half"]["cover_pct"] / 100,
       "teams": {}}
for tid, r in cur.iterrows():
    c = card.loc[r.coach] if r.coach in card.index else None
    get = lambda k, default=None: (None if c is None or pd.isna(c[k]) else c[k]) if c is not None else default  # noqa: E731
    out["teams"][tid] = {
        "team": r.team, "coach": r.coach,
        "tosses_won": int(get("tosses_won") or 0),
        "receives": int(round((get("receive_pct") or 0) * (get("tosses_won") or 0) / 100)),
        "receive_est": float(get("receive_est") or h["fbs_receive_rate"]),
        "recv_open_score_pct": get("recv_open_score_pct"), "recv_h1_cover_pct": get("recv_h1_cover_pct"),
    }
json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
print(len(out["teams"]), "teams exported")
