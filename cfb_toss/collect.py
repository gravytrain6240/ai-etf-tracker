"""Collect coin-toss decisions, drive logs and spreads for power-conference
college football games from ESPN's public APIs.

Output: one JSON line per game in data/games.jsonl (resumable).

Usage: python collect.py [first_season] [last_season]
"""
import datetime
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
HERE = os.path.dirname(os.path.abspath(__file__))
# ALL_FBS=1: every game with an FBS team (no power filter, no odds) -> data/games_fbs.jsonl
ALL_FBS = os.environ.get("ALL_FBS") == "1"
OUT = os.path.join(HERE, "data", "games_fbs.jsonl" if ALL_FBS else "games.jsonl")

# ESPN conference group ids
ACC, BIG12, BIG10, SEC, PAC12, IND = "1", "4", "5", "8", "9", "18"
NOTRE_DAME = "87"
CONF_NAME = {ACC: "ACC", BIG12: "Big 12", BIG10: "Big Ten", SEC: "SEC", PAC12: "Pac-12"}


def is_power(conf_id, team_id, season):
    if team_id == NOTRE_DAME:
        return True
    if conf_id in (ACC, BIG12, BIG10, SEC):
        return True
    # Pac-12 dissolved as a power conference after the 2023 season
    return conf_id == PAC12 and season <= 2023


def get(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def scoreboard_urls(first, last):
    """ESPN's scoreboard silently truncates large result sets (and `limit=1000` returns
    *fewer* rows than `limit=300`), so query both season-wide per conference and
    day-by-day for all FBS, and take the union."""
    for year in range(first, last + 2):  # +1 for January bowl/playoff games
        for stype in (2, 3):
            for grp in (ACC, BIG12, BIG10, SEC, PAC12, IND):
                yield f"{SITE}/scoreboard?dates={year}&groups={grp}&seasontype={stype}&limit=1000"
    for season in range(first, last + 1):
        start = datetime.date(season, 8, 20)
        for i in range(165):  # through late January
            day = start + datetime.timedelta(days=i)
            if day > datetime.date.today():
                break
            yield f"{SITE}/scoreboard?dates={day:%Y%m%d}&groups=80&limit=300"


def list_games(first, last):
    games = {}
    with ThreadPoolExecutor(8) as ex:
        pages = list(ex.map(lambda u: get(u).get("events", []), scoreboard_urls(first, last)))
    for events in pages:
                for ev in events:
                    season = ev["season"]["year"]
                    if not (first <= season <= last):
                        continue
                    comp = ev["competitions"][0]
                    if not comp["status"]["type"].get("completed"):
                        continue
                    teams = []
                    for c in comp["competitors"]:
                        t = c["team"]
                        teams.append({
                            "id": t["id"], "name": t.get("location") or t.get("displayName"),
                            "abbr": t.get("abbreviation"), "conf": t.get("conferenceId"),
                            "home_away": c["homeAway"], "score": int(c.get("score") or 0),
                            "winner": bool(c.get("winner")),
                        })
                    if not ALL_FBS and not any(is_power(t["conf"], t["id"], season) for t in teams):
                        continue
                    for t in teams:
                        t["power"] = is_power(t["conf"], t["id"], season)
                        t["conf_name"] = ("Notre Dame (Ind)" if t["id"] == NOTRE_DAME
                                          else CONF_NAME.get(t["conf"], "Non-power"))
                        if t["conf"] == PAC12 and season > 2023:
                            t["conf_name"] = "Pac-12 (post-2023)"
                    games[ev["id"]] = {
                        "game_id": ev["id"], "season": season, "season_type": ev["season"].get("type"),
                        "week": ev.get("week", {}).get("number"), "date": ev["date"],
                        "neutral": comp.get("neutralSite", False),
                        "conf_game": comp.get("conferenceCompetition", False),
                        "teams": teams,
                    }
    return games


def toss_plays(gid):
    url = f"{CORE}/events/{gid}/competitions/{gid}/plays?limit=1000"
    data = get(url)
    out = []
    for p in data.get("items", []):
        if p.get("type", {}).get("id") == "70" or "toss" in (p.get("text") or "").lower():
            team_ref = (p.get("team") or {}).get("$ref", "")
            team_id = team_ref.split("/teams/")[1].split("?")[0] if "/teams/" in team_ref else None
            out.append({"text": p.get("text"), "period": p.get("period", {}).get("number"),
                        "team_id": team_id, "seq": p.get("sequenceNumber")})
    return out


def drives(gid):
    d = get(f"{SITE}/summary?event={gid}")
    out = []
    for dr in (d.get("drives") or {}).get("previous", []):
        plays = dr.get("plays") or []
        first, last = (plays[0], plays[-1]) if plays else ({}, {})
        out.append({
            "team_id": (dr.get("team") or {}).get("id"),
            "result": dr.get("result"), "is_score": dr.get("isScore"),
            "start_period": dr.get("start", {}).get("period", {}).get("number"),
            "start_clock": dr.get("start", {}).get("clock", {}).get("displayValue"),
            "start_yardline": dr.get("start", {}).get("yardLine"),
            "end_period": dr.get("end", {}).get("period", {}).get("number"),
            "end_clock": dr.get("end", {}).get("clock", {}).get("displayValue"),
            "yards": dr.get("yards"), "plays": dr.get("offensivePlays"),
            "score_before": [first.get("awayScore"), first.get("homeScore")],
            "score_after": [last.get("awayScore"), last.get("homeScore")],
            "first_play_type": (first.get("type") or {}).get("text"),
        })
    return out


def odds(gid):
    try:
        data = get(f"{CORE}/events/{gid}/competitions/{gid}/odds")
    except Exception:  # noqa: BLE001
        return None
    for it in data.get("items", []):
        if it.get("spread") is not None:
            return {"home_spread": it["spread"], "over_under": it.get("overUnder"),
                    "provider": it["provider"]["name"]}
    return None


def enrich(g):
    gid = g["game_id"]
    try:
        g["toss"] = toss_plays(gid)
        g["drives"] = drives(gid)
        g["odds"] = None if ALL_FBS else odds(gid)
    except Exception as e:  # noqa: BLE001
        g["error"] = repr(e)
    return g


def main():
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 2021
    last = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            done = {json.loads(l)["game_id"] for l in f if '"error"' not in l}
    games = list_games(first, last)
    todo = [g for gid, g in games.items() if gid not in done]
    print(f"{len(games)} power-conference games, {len(todo)} to fetch", flush=True)
    with open(OUT, "a") as f, ThreadPoolExecutor(12) as ex:
        for i, g in enumerate(ex.map(enrich, todo), 1):
            f.write(json.dumps(g) + "\n")
            if i % 200 == 0:
                print(f"  {i}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
