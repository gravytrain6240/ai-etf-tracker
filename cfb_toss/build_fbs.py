"""One row per game for every FBS game since 2022: who won the opening toss, what they
chose, and whether that agrees with who actually took the opening kickoff.

Input: data/games_fbs.jsonl (collect.py with ALL_FBS=1)
Output: data/fbs_toss_games.csv
"""
import json
import os

import re
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

import parse

HERE = os.path.dirname(os.path.abspath(__file__))
# ESPN conference ids for FBS conferences (current membership)
FBS_CONFS = {"1", "4", "5", "8", "9", "12", "15", "17", "18", "37", "151"}


def named_receiver(text, teams):
    """Team named as receiving ("MIZ will receive", "LSU to receive"), if it can be matched."""
    m = re.search(r"([A-Za-z.&' ]+?)\s+(?:will receive|to receive|wT receive)", text or "")
    if not m:
        return None
    subj = parse._norm(m.group(1).split(";")[-1].split(".")[-1] if m.group(1).strip() else "")
    subj = parse._norm(m.group(1).strip().split()[-1]) if not subj else subj
    best, score = None, 0.0
    for t in teams:
        for cand in (t["name"], t["abbr"]):
            c = parse._norm(cand)
            if not c or not subj:
                continue
            sc = 1.0 if c == subj else SequenceMatcher(None, subj, c).ratio()
            if sc > score:
                best, score = t["id"], sc
    return best if score >= 0.75 else None


def status_of(fam, consistent, decision):
    if fam is None:
        return "no toss record"
    if fam == "A":
        return "unreliable format"
    if decision is None:
        return "undetermined"
    if consistent is False:
        return "conflicts with kickoff"
    if consistent == "text":
        return "verified (text only)"
    if consistent == "kickoff":
        return "verified (abbrev. resolved by kickoff)"
    return "verified"


def build():
    rows = []
    with open(os.path.join(HERE, "data", "games_fbs.jsonl")) as f:
        for line in f:
            g = json.loads(line)
            teams = g["teams"]
            if len(teams) != 2:
                continue
            home = next(t for t in teams if t["home_away"] == "home")
            away = next(t for t in teams if t["home_away"] == "away")
            drives = [d for d in g.get("drives", []) if d.get("team_id")]
            q1 = [d for d in drives if d["start_period"] == 1]
            rcv = q1[0]["team_id"] if q1 else None
            opening = [t for t in g.get("toss", []) if t.get("period") == 1]
            r = {
                "game_id": g["game_id"], "season": g["season"], "date": g["date"][:10],
                "home_id": home["id"], "home": home["name"], "home_fbs": home["conf"] in FBS_CONFS,
                "away_id": away["id"], "away": away["name"], "away_fbs": away["conf"] in FBS_CONFS,
                "neutral": g["neutral"], "home_score": home["score"], "away_score": away["score"],
                "opening_receiver_id": rcv, "toss_text": opening[0]["text"] if opening else None,
            }
            fam = parse.family(opening[0]["text"]) if opening else None
            winner = decision = consistent = None
            if opening and fam != "A":
                winner = parse.toss_winner(opening[0], teams)
                stated = parse.decision(opening[0]["text"])
                if stated in ("defer", "receive"):
                    decision = stated
                    if winner and rcv:
                        consistent = (winner == rcv) == (stated == "receive")
                elif stated == "kick":
                    decision = "kick"
                    consistent = (winner != rcv) if (winner and rcv) else None
                elif winner and rcv:  # ambiguous / end-zone wording: settled by actual kickoff
                    decision = "receive" if winner == rcv else "defer"
                    consistent = True
                # Second check: the text often names the receiving team. If that agrees with
                # the stated decision, the text is self-consistent; trust it over the drive log.
                nr = named_receiver(opening[0]["text"], teams)
                if consistent is False and nr and decision in ("defer", "receive"):
                    ids = [home["id"], away["id"]]
                    text_winner = nr if decision == "receive" else next(i for i in ids if i != nr)
                    if decision == "defer" and nr != winner:
                        consistent = "text"
                    elif text_winner != winner:
                        winner, consistent = text_winner, "text"
                # Ambiguous short subject ("KSU", "MSU", "Tech"): name matching can't tell the
                # teams apart, so take the stated decision and identify the team by the kickoff.
                subj = re.match(r"^\s*(\S+)\s+(?:wins|won)\b", opening[0]["text"] or "")
                if (consistent is False and rcv and subj and len(subj.group(1)) <= 4
                        and decision in ("defer", "receive", "kick")):
                    other = away["id"] if rcv == home["id"] else home["id"]
                    winner, consistent = (rcv if decision == "receive" else other), "kickoff"
            r.update({
                "toss_format": fam, "toss_winner_id": winner,
                "toss_winner": {home["id"]: home["name"], away["id"]: away["name"]}.get(winner),
                "decision": decision, "kickoff_check": consistent,
                "status": status_of(fam, consistent, decision),
            })
            rows.append(r)
    df = pd.DataFrame(rows).sort_values(["date", "game_id"])
    df["espn_status"] = df.status
    df["source"] = np.where(df.status.str.startswith("verified"), "ESPN", None)
    df = apply_ncaa(df)
    df.to_csv(os.path.join(HERE, "data", "fbs_toss_games.csv"), index=False)
    return df


def apply_ncaa(df):
    """Fill games ESPN couldn't verify from NCAA.com's official play-by-play (ncaa_fill.py)."""
    path = os.path.join(HERE, "data", "ncaa_toss.csv")
    if not os.path.exists(path):
        return df
    n = pd.read_csv(path, dtype={"game_id": str, "ncaa_winner_id": str})
    n = n[(n.purpose == "fill") & (n.ncaa_status == "ok")].set_index("game_id")
    df = df.copy()
    for i, r in df.iterrows():
        if r.status.startswith("verified") or r.game_id not in n.index:
            continue
        x = n.loc[r.game_id]
        w, dec, rcv = x.ncaa_winner_id, x.ncaa_decision, r.opening_receiver_id
        teams = [{"id": r.home_id, "name": r.home, "abbr": None}, {"id": r.away_id, "name": r.away, "abbr": None}]
        status = None
        if dec in ("defer", "receive", "kick"):
            if isinstance(rcv, str) and rcv:
                ok = (w == rcv) == (dec == "receive")
                if ok:
                    status = "verified (NCAA)"
                else:
                    # official text names the receiver consistently -> trust text over drive log
                    nr = named_receiver(x.ncaa_text, teams)
                    if nr and ((dec == "receive" and nr == w) or (dec != "receive" and nr != w)):
                        status = "verified (NCAA text only)"
                    else:
                        status = "NCAA conflicts with kickoff"
            else:
                status = "verified (NCAA text only)"
        elif isinstance(rcv, str) and rcv:  # ambiguous wording -> settle with the actual kickoff
            dec = "receive" if w == rcv else "defer"
            status = "verified (NCAA + kickoff)"
        if status:
            df.at[i, "toss_winner_id"], df.at[i, "decision"], df.at[i, "status"] = w, dec, status
            df.at[i, "toss_winner"] = r.home if w == r.home_id else r.away
            df.at[i, "toss_text"] = x.ncaa_text
            if status.startswith("verified"):
                df.at[i, "source"] = "NCAA"
    return df


if __name__ == "__main__":
    df = build()
    print(len(df), "games")
    print(df.status.value_counts())
    v = df[df.status == "verified"]
    print("receive rate (verified):", round(100 * (v.decision == "receive").mean(), 1), "%  n =", len(v))
