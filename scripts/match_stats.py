"""
match_stats.py
==============
Print the R6 Pro League-style scoreboard for a match straight from its
replay files -- no browser needed.

    python match_stats.py Match-2026-09-23_19-19-11-23660.zip
    python match_stats.py "C:/.../MatchReplay/Match-2026-09-23_19-19-11-23660"
    python match_stats.py match.zip --csv stats.csv --json stats.json

Accepts a .zip of a match folder, a match folder, or a single .rec round.
A zip or folder holding several matches prints one scoreboard per match
(pointing it at the whole MatchReplay folder works too).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

from metrics_engine import PRO_LEAGUE_COLUMNS, compute_match_metrics, leaderboard_rows, pro_league_rows
from parser import ReplayParseError, collect_rec_files, group_by_match, parse_match


def scoreboard_text(match: dict, rows: list[dict]) -> str:
    """Plain-text scoreboard, one table per team, like the R6 Esports match page."""
    cols = ("Player",) + PRO_LEAGUE_COLUMNS
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols} if rows else {c: len(c) for c in cols}
    names, score = match["team_names"], match["final_score"]
    out = [f"{match['map']}  |  {names[0]} {score[0]} - {score[1]} {names[1]}  |  {len(match['rounds'])} round(s)"]
    for team in (0, 1):
        out += ["", names[team], "  ".join(c.ljust(widths[c]) for c in cols)]
        out += ["  ".join(str(r[c]).ljust(widths[c]) for c in cols) for r in rows if r["Team"] == team]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help=".zip of a match folder, a match folder, or a .rec file")
    ap.add_argument("--csv", type=Path, help="also write the numeric per-player stats to this CSV")
    ap.add_argument("--json", type=Path, help="also write the scoreboards to this JSON file")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # player names aren't always ASCII
    results, csv_rows = [], []
    with tempfile.TemporaryDirectory() as td:
        try:
            matches = group_by_match(collect_rec_files(args.source, Path(td)))
        except ReplayParseError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not matches:
            print("error: no .rec replay files found", file=sys.stderr)
            return 1
        for name, recs in matches.items():
            try:
                match, _raw, warnings = parse_match(recs)
            except ReplayParseError as e:
                print(f"error: {name}: {e}", file=sys.stderr)
                continue
            for w in warnings:
                print(f"warning: {name}: {w}", file=sys.stderr)
            stats = compute_match_metrics(match)
            rows = pro_league_rows(stats)
            print(f"\n=== {name} ===\n{scoreboard_text(match, rows)}")
            results.append({
                "match": name, "map": match["map"], "match_id": match["match_id"],
                "teams": match["team_names"], "score": match["final_score"],
                "rounds": len(match["rounds"]), "players": rows,
            })
            for r in leaderboard_rows(stats):
                csv_rows.append({"Match": name, "Team Name": match["team_names"][r["Team"]], **r})

    if args.json:
        args.json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.csv and csv_rows:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
            w.writeheader()
            w.writerows(csv_rows)
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
