# College football coin-toss tendencies

Pipeline:
1. `python collect.py 2021 2026` – pulls power-conference games, coin-toss plays, drive logs and spreads from ESPN's public APIs into `data/games.jsonl` (resumable; not committed, ~large).
2. `python analyze.py` – parses toss text (`parse.py`), excludes the unreliable "wins the coin toss, and…" stat-crew format, writes `data/results.json` and CSVs.
3. `python build_report.py` – renders `report.html` from `report_template.html`.

Key outputs: `data/toss_games.csv` (one row per game), `data/toss_decisions.csv` (one row per power-team toss decision), `data/team_tendencies.csv`, `data/team_season_tendencies.csv`.
