"""Fill games without a trustworthy ESPN toss record from NCAA.com's official play-by-play.

1. NCAA weekly scoreboards (2022-2026) -> contest ids, dates, teams, final scores.
2. Match each target ESPN game by date (+/- 1 day) and exact final score.
3. Pull NCAA play-by-play, take the first coin-toss call of the game.
4. Map the toss winner to the ESPN team through the final scores.

Targets: every ESPN game not yet verified, plus a random sample of 300 verified games used
to measure how often NCAA and ESPN agree.
Output: data/ncaa_toss.csv
"""
import datetime as dt
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

import pandas as pd

import parse

H = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(H, "data", f)  # noqa: E731
HASH = "47928f2cabc7a164f0de0ed535a623bdf5a852cce7c30d6a6972a38609ba46a2"
WEEKS = [f"{w:02d}" for w in range(1, 17)] + ["P"]


def get_json(url, tries=4):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(url, timeout=30).read())
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))


def scoreboards():
    urls = [f"https://data.ncaa.com/casablanca/scoreboard/football/fbs/{y}/{w}/scoreboard.json"
            for y in range(2022, 2027) for w in WEEKS]
    rows = []
    with ThreadPoolExecutor(6) as ex:
        for sb in ex.map(get_json, urls):
            for g in (sb or {}).get("games", []):
                x = g["game"]
                try:
                    hs, as_ = int(x["home"]["score"]), int(x["away"]["score"])
                except (ValueError, KeyError):
                    continue
                rows.append({"contest_id": x["url"].rstrip("/").split("/")[-1],
                             "date": dt.datetime.strptime(x["startDate"], "%m-%d-%Y").date(),
                             "n_home": x["home"]["names"]["short"], "n_away": x["away"]["names"]["short"],
                             "n_home_score": hs, "n_away_score": as_})
    return pd.DataFrame(rows).drop_duplicates("contest_id")


def pbp(cid):
    ext = json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASH}})
    var = json.dumps({"contestId": str(cid), "staticTestEnv": None})
    url = ("https://sdataprod.ncaa.com/?meta=NCAA_GetGamecenterPbpFootballById_web&extensions="
           + urllib.parse.quote(ext) + "&variables=" + urllib.parse.quote(var))
    d = get_json(url)
    return ((d or {}).get("data") or {}).get("playbyplay")


def opening_toss(pb):
    for per in pb.get("periods") or []:
        if per.get("periodNumber") not in (1, "1"):
            continue
        for st in per.get("playbyplayStats") or []:
            for p in st.get("plays") or []:
                t = p.get("playText") or ""
                if re.search(r"\btoss\b", t, re.I):
                    return t
    return None


def winner_side(text, teams):
    """Which NCAA team won the toss, from the sentence subject."""
    m = re.match(r"^\s*(.*?)\s+(?:wins|won|has won|elects|chooses)\b", text or "", re.I)
    if not m:
        return None
    subj = parse._norm(m.group(1))
    best, score = None, 0.0
    for t in teams:
        for cand in (t.get("nameShort"), t.get("name6Char"), t.get("nameFull"), t.get("teamName"), t.get("seoname")):
            c = parse._norm(cand)
            if not c or not subj:
                continue
            sc = 1.0 if c == subj else SequenceMatcher(None, subj, c).ratio()
            if subj.startswith(c) or c.startswith(subj):
                sc = max(sc, 0.9)
            if sc > score:
                best, score = t, sc
    return best if score >= 0.6 else None


def main():
    g = pd.read_csv(P("fbs_toss_games.csv"), dtype={"game_id": str, "home_id": str, "away_id": str})
    g["d"] = pd.to_datetime(g.date).dt.date
    todo = g[~g.status.str.startswith("verified")]
    sample = g[g.status.str.startswith("verified")].sample(300, random_state=7)
    targets = pd.concat([todo.assign(purpose="fill"), sample.assign(purpose="check")])

    sb = scoreboards()
    print(len(sb), "NCAA contests on scoreboards", flush=True)
    idx = {}
    for r in sb.itertuples():
        idx.setdefault((r.n_home_score, r.n_away_score), []).append(r)
        idx.setdefault((r.n_away_score, r.n_home_score), []).append(r)

    def match(r):
        cands = [c for c in idx.get((r.home_score, r.away_score), []) if abs((c.date - r.d).days) <= 1]
        if len(cands) > 1:  # break ties on names
            cands.sort(key=lambda c: -max(SequenceMatcher(None, parse._norm(c.n_home), parse._norm(r.home)).ratio(),
                                          SequenceMatcher(None, parse._norm(c.n_away), parse._norm(r.home)).ratio()))
        return cands[0].contest_id if cands else None

    targets["contest_id"] = [match(r) for r in targets.itertuples()]
    print("matched", targets.contest_id.notna().sum(), "of", len(targets), flush=True)

    def work(r):
        out = {"game_id": r.game_id, "purpose": r.purpose, "contest_id": r.contest_id}
        if not r.contest_id:
            return {**out, "ncaa_status": "no NCAA match"}
        pb = pbp(r.contest_id)
        if not pb:
            return {**out, "ncaa_status": "no play-by-play"}
        text = opening_toss(pb)
        if not text:
            return {**out, "ncaa_status": "no toss line"}
        teams = pb.get("teams") or []
        w = winner_side(text, teams)
        out.update({"ncaa_text": text, "ncaa_decision": parse.decision(text)})
        if not w:
            return {**out, "ncaa_status": "winner unclear"}
        # map NCAA team -> ESPN team via final scores (NCAA isHome can differ at neutral sites)
        ncaa_home_is_home = (r.home_score, r.away_score) == (
            next((c.n_home_score for c in sb.itertuples() if c.contest_id == r.contest_id), None),
            next((c.n_away_score for c in sb.itertuples() if c.contest_id == r.contest_id), None))
        w_is_ncaa_home = bool(w.get("isHome"))
        espn_home = w_is_ncaa_home == ncaa_home_is_home
        out["ncaa_winner_id"] = r.home_id if espn_home else r.away_id
        out["ncaa_status"] = "ok"
        return out

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(work, targets.itertuples()))
    pd.DataFrame(res).to_csv(P("ncaa_toss.csv"), index=False)
    df = pd.DataFrame(res)
    print(df.groupby(["purpose", "ncaa_status"]).size())


if __name__ == "__main__":
    main()
