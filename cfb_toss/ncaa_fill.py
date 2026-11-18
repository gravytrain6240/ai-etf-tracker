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


CONTESTS = ("https://sdataprod.ncaa.com?meta=GetContests_web&extensions="
            + urllib.parse.quote(json.dumps({"persistedQuery": {"version": 1, "sha256Hash":
              "4bcb5e6432fa9da365c0c19af01b1f9015cc7eb5c21e7af2dba308784a166df7"}})))


def contests(args):
    """NCAA game list for one season/week/division (11 = FBS, 12 = FCS; weeks 0-20, bowls run through ~week 19)."""
    year, week, div = args
    v = {"sportCode": "MFB", "division": div, "seasonYear": year, "contestDate": None, "week": week}
    d = get_json(CONTESTS + "&" + urllib.parse.urlencode({"queryName": "GetContests_web", "variables": json.dumps(v)}))
    return ((d or {}).get("data") or {}).get("contests") or []


def scoreboards():
    jobs = [(y, w, div) for y in range(2022, 2027) for w in range(0, 21) for div in (11, 12)]
    rows = []
    with ThreadPoolExecutor(6) as ex:
        for cs in ex.map(contests, jobs):
            for x in cs:
                t = {("home" if tm["isHome"] else "away"): tm for tm in x.get("teams") or []}
                if set(t) != {"home", "away"} or t["home"].get("score") is None:
                    continue
                rows.append({"contest_id": str(x["contestId"]),
                             "date": dt.datetime.strptime(x["startDate"], "%m/%d/%Y").date(),
                             "n_home": t["home"]["nameShort"], "n_away": t["away"]["nameShort"],
                             "n_home_score": int(t["home"]["score"]), "n_away_score": int(t["away"]["score"])})
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
    st = g.espn_status if "espn_status" in g else g.status  # ESPN's own verdict, before any NCAA fill
    todo = g[~st.str.startswith("verified")]
    sample = g[st.str.startswith("verified")].sample(300, random_state=7)
    targets = pd.concat([todo.assign(purpose="fill"), sample.assign(purpose="check")])

    sb = scoreboards()
    print(len(sb), "NCAA contests on scoreboards", flush=True)
    idx = {}
    for r in sb.itertuples():
        idx.setdefault((r.n_home_score, r.n_away_score), []).append(r)
        idx.setdefault((r.n_away_score, r.n_home_score), []).append(r)

    def sim(a, b):
        a, b = parse._norm(a), parse._norm(b)
        if not a or not b:
            return 0.0
        return 0.9 if (a.startswith(b) or b.startswith(a)) else SequenceMatcher(None, a, b).ratio()

    def name_score(c, r):
        same = (sim(c.n_home, r.home) + sim(c.n_away, r.away)) / 2
        swap = (sim(c.n_home, r.away) + sim(c.n_away, r.home)) / 2
        return max(same, swap)

    def match(r):
        # same date (+/- 1 day for UTC vs. Eastern), same final score, and the team names must agree
        cands = [c for c in idx.get((r.home_score, r.away_score), []) if abs((c.date - r.d).days) <= 1]
        cands = [(name_score(c, r), c) for c in cands]
        cands = [x for x in cands if x[0] >= 0.6]
        cands.sort(key=lambda x: -x[0])
        return cands[0][1].contest_id if cands else None

    targets["contest_id"] = [match(r) for r in targets.itertuples()]
    print("matched", targets.contest_id.notna().sum(), "of", len(targets), flush=True)

    def work(r):
        out = {"game_id": r.game_id, "purpose": r.purpose, "contest_id": r.contest_id}
        if not isinstance(r.contest_id, str) or not r.contest_id:
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
