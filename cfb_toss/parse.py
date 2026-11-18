"""Turn raw games.jsonl into a tidy one-row-per-game table (data/toss_games.csv)."""
import json
import os
import re
from difflib import SequenceMatcher

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

RECEIVE = re.compile(r"\b(receiv|elect(?:s|ed)? to receive|take the ball|ball first)", re.I)
DEFER = re.compile(r"\bdefer", re.I)
KICK = re.compile(r"\b(will kick|elect(?:s|ed)? to kick|chose to kick|choose to kick|kick ?off)", re.I)
GOAL = re.compile(r"\b(defend|goal|wind|end zone|direction)", re.I)


# --- Conference membership by season (ESPN only exposes *current* conference) ---------
CUR_CONF = {"1": "ACC", "4": "Big 12", "5": "Big Ten", "8": "SEC"}
OLD_PAC12 = {"30", "26", "264", "2483", "12", "9", "38", "254", "25", "24", "204", "265"}
TO_SEC_2024 = {"251", "201"}                        # Texas, Oklahoma (Big 12 through 2023)
JOINED_BIG12_2023 = {"252", "2132", "248", "2116"}  # BYU, Cincinnati, Houston, UCF
SMU, NOTRE_DAME = "2567", "87"
OREGON_ST, WASH_ST = "204", "265"


def season_conf(team_id, cur_conf, season):
    """Conference the team actually played in that season; 'Non-power' otherwise."""
    if team_id == NOTRE_DAME:
        return "Notre Dame"
    if team_id in OLD_PAC12 and season <= 2023:
        return "Pac-12"
    if team_id in (OREGON_ST, WASH_ST):
        return "Non-power"  # Pac-12 remnant from 2024 on
    if team_id in TO_SEC_2024 and season <= 2023:
        return "Big 12"
    if team_id in JOINED_BIG12_2023 and season <= 2022:
        return "Non-power"
    if team_id == SMU and season <= 2023:
        return "Non-power"
    return CUR_CONF.get(cur_conf, "Non-power")


def decision(text):
    """Decision stated by the toss winner, read from the clause about the winner.

    Returns defer / receive / kick / endzone, or 'ambiguous' when the text only says who
    receives (e.g. "X won the toss. Y will receive ...") — those are resolved later from
    who actually received the opening kickoff."""
    t = text or ""
    head = re.split(r"\.\s|;", t, maxsplit=1)[0]
    if DEFER.search(head):
        return "defer"
    if RECEIVE.search(head):
        return "receive"
    if KICK.search(head):
        return "kick"
    if re.search(r"end ?zone|goal", head, re.I):
        return "endzone"
    if DEFER.search(t):
        return "defer"
    return "ambiguous"


# Stat-crew wording families. Family A ("X wins the coin toss, and will receive / and
# defers ...") names the *receiving* team as the toss winner most of the time: the same
# team (e.g. Alabama, Michigan) shows 0% receive under every other wording but ~70% under
# this one. Its toss-winner field is therefore unreliable and those games are excluded.
FAMILIES = [
    ("A", r"wins the coin toss, and"),
    ("B", r"has deferred to the second"),
    ("C", r"wins toss and"),
    ("D", r"won the toss\. "),
    ("E", r"wins the toss, and"),
    ("F", r"chooses|elects"),
]


def family(text):
    for code, pat in FAMILIES:
        if re.search(pat, text or "", re.I):
            return code
    return "other"


def mmss(s):
    try:
        m, sec = s.split(":")
        return int(m) * 60 + int(sec)
    except Exception:  # noqa: BLE001
        return None


ALIASES = {"southern california": "usc", "pho": "elon", "ole miss": "mississippi"}


def _norm(s):
    s = (s or "").lower().strip()
    s = ALIASES.get(s, s).replace("st.", "state").replace("&", "and")
    s = re.sub(r"\bfla\b\.?", "florida", s)
    return re.sub(r"[^a-z0-9]", "", s)


def toss_winner(toss, teams):
    """Team id that won the toss.

    The winner is the subject of the sentence ("Kansas St. wins toss and defers; ..."),
    so fuzzy-match that phrase to the two teams. ESPN's team tag on the play is often the
    home team rather than the winner, so it is only a fallback."""
    m = re.match(r"^\s*(.*?)\s+(?:wins|won|has won|elects|chooses)\b", toss.get("text") or "", re.I)
    if m:
        subj = _norm(m.group(1))
        best, best_score = None, 0.0
        for t in teams:
            for cand in (t["name"], t["abbr"]):
                c = _norm(cand)
                if not c or not subj:
                    continue
                score = 1.0 if subj == c else SequenceMatcher(None, subj, c).ratio()
                if subj.startswith(c) or c.startswith(subj):
                    score = max(score, 0.9)
                if score > best_score:
                    best, best_score = t["id"], score
        if best_score >= 0.6:
            return best
    return _tagged_or_text(toss, teams)


def _tagged_or_text(toss, teams):
    ids = {t["id"] for t in teams}
    if toss.get("team_id") in ids:
        # ESPN's team tag is usually the toss winner; confirm against the text when possible
        tagged = toss["team_id"]
        txt = (toss.get("text") or "").lower()
        for t in teams:
            names = [n.lower() for n in (t["name"], t["abbr"]) if n]
            pos = [txt.find(n) for n in names if txt.find(n) >= 0]
            t["_pos"] = min(pos) if pos else 10**6
        first = min(teams, key=lambda t: t["_pos"])
        if first["_pos"] < 10**6 and first["id"] != tagged and first["_pos"] < 5:
            return first["id"]
        return tagged
    txt = (toss.get("text") or "").lower()
    best, best_pos = None, 10**6
    for t in teams:
        for n in (t["name"], t["abbr"]):
            if n and (p := txt.find(n.lower())) >= 0 and p < best_pos:
                best, best_pos = t["id"], p
    return best


def points_on_drive(dr, team_id, home_id):
    b, a = dr["score_before"], dr["score_after"]
    if None in b or None in a:
        return None
    idx = 1 if team_id == home_id else 0
    return (a[idx] or 0) - (b[idx] or 0)


def build():
    rows = []
    with open(os.path.join(HERE, "data", "games.jsonl")) as f:
        for line in f:
            g = json.loads(line)
            if g.get("error") or len(g["teams"]) != 2:
                continue
            teams = g["teams"]
            for t in teams:
                t["conf_name"] = season_conf(t["id"], t["conf"], g["season"])
                t["power"] = t["conf_name"] != "Non-power"
            if not any(t["power"] for t in teams):
                continue
            home = next(t for t in teams if t["home_away"] == "home")
            away = next(t for t in teams if t["home_away"] == "away")
            opening = [t for t in g.get("toss", []) if t.get("period") == 1]
            ot = [t for t in g.get("toss", []) if (t.get("period") or 0) >= 5]
            drives = [d for d in g.get("drives", []) if d.get("team_id")]
            r = {
                "game_id": g["game_id"], "season": g["season"], "season_type": g["season_type"],
                "week": g["week"], "date": g["date"][:10], "neutral": g["neutral"],
                "conf_game": g["conf_game"],
                "home_id": home["id"], "home": home["name"], "home_conf": home["conf_name"],
                "home_power": home["power"], "home_score": home["score"],
                "away_id": away["id"], "away": away["name"], "away_conf": away["conf_name"],
                "away_power": away["power"], "away_score": away["score"],
                "home_spread": (g.get("odds") or {}).get("home_spread"),
                "over_under": (g.get("odds") or {}).get("over_under"),
                "toss_text": opening[0]["text"] if opening else None,
                "toss_family": family(opening[0]["text"]) if opening else None,
                "has_ot": any((d.get("start_period") or 0) >= 5 for d in drives),
                "ot_toss_text": ot[0]["text"] if ot else None,
            }
            # who actually received the opening kickoff / 2nd-half kickoff
            q1 = [d for d in drives if d["start_period"] == 1]
            h2 = [d for d in drives if d["start_period"] == 3]
            r["opening_receiver_id"] = q1[0]["team_id"] if q1 else None
            r["h2_receiver_id"] = h2[0]["team_id"] if h2 else None

            r["toss_winner_id"] = r["decision_text"] = r["decision"] = None
            r["consistent"] = None
            if opening:
                w = toss_winner(opening[0], teams)
                stated = decision(opening[0]["text"])
                rcv = r["opening_receiver_id"]
                r["toss_winner_id"], r["decision_text"] = w, stated
                if stated in ("defer", "receive"):
                    r["decision"] = stated
                    if w and rcv:
                        r["consistent"] = (w == rcv) == (stated == "receive")
                elif stated == "kick":
                    r["decision"] = "kick"
                    r["consistent"] = (w != rcv) if (w and rcv) else None
                elif w and rcv:
                    # ambiguous / end-zone wording: settle from who actually received
                    r["decision"] = "receive" if w == rcv else "defer"
                    r["consistent"] = True
            if ot:
                r["ot_toss_winner_id"] = toss_winner(ot[0], teams)
                r["ot_decision_text"] = ot[0]["text"]

            # drive-level outcomes, from the opening receiver's perspective
            if q1:
                d0 = q1[0]
                r["open_drive_result"] = d0["result"]
                r["open_drive_points"] = points_on_drive(d0, d0["team_id"], home["id"])
                r["open_drive_yards"] = d0.get("yards")
            if h2:
                d2 = h2[0]
                r["h2_drive_result"] = d2["result"]
                r["h2_drive_points"] = points_on_drive(d2, d2["team_id"], home["id"])
            # last possession of the first half, for the "double dip" (score late Q2 + open Q3)
            h1 = [d for d in drives if d["start_period"] in (1, 2)]
            if h1:
                last = h1[-1]
                r["h1_last_drive_team"] = last["team_id"]
                r["h1_last_drive_points"] = points_on_drive(last, last["team_id"], home["id"])
            # halftime score
            ht = [d for d in drives if d["start_period"] <= 2]
            if ht and None not in ht[-1]["score_after"]:
                r["ht_away"], r["ht_home"] = ht[-1]["score_after"]
            rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(HERE, "data", "toss_games.csv"), index=False)
    return df


if __name__ == "__main__":
    df = build()
    print(len(df), "games")
    print(df["decision"].value_counts(dropna=False))
