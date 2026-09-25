"""
match_stats.py
==============
Print the R6 Pro League-style scoreboard for a match straight from its
replay files -- no browser needed.

    python match_stats.py Match-2026-09-23_19-19-11-23660.zip
    python match_stats.py "C:/.../MatchReplay/Match-2026-09-23_19-19-11-23660"
    python match_stats.py match.zip --csv stats.csv --json stats.json --txt stats.txt

Accepts a .zip of a match folder, a match folder, or a single .rec round.
A zip or folder holding several matches prints one scoreboard per match
(pointing it at the whole MatchReplay folder works too).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from metrics_engine import compute_match_metrics, leaderboard_rows, pro_league_rows, rows_csv, scoreboard_text
from file_guard import ReplayScanner
from parser import ReplayParseError, collect_rec_files, group_by_match, parse_match

# matches parsed at once; each r6-dissect process needs up to ~400 MB for a long match
PARALLEL_MATCHES = 4


def _parse(recs: list[str]):
    """parse_match's result, or the ReplayParseError it raised."""
    try:
        return parse_match(recs)
    except ReplayParseError as e:
        return e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help=".zip of a match folder, a match folder, or a .rec file")
    ap.add_argument("--csv", type=Path, help="also write the numeric per-player stats to this CSV")
    ap.add_argument("--json", type=Path, help="also write the scoreboards to this JSON file")
    ap.add_argument("--txt", type=Path, help="also write the scoreboards, as printed, to this text file")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # player names aren't always ASCII
    results, csv_rows, scoreboards = [], [], []
    with tempfile.TemporaryDirectory() as td:
        scanner = ReplayScanner()
        try:
            matches = group_by_match(collect_rec_files(args.source, Path(td), scanner))
        except ReplayParseError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if scanner.summary():
            print(f"warning: {scanner.summary()}", file=sys.stderr)
        if not matches:
            print("error: no Siege replay files found", file=sys.stderr)
            return 1
        # r6-dissect runs as its own process, so a few matches can be parsed at once;
        # results still come back (and print) in match order
        with ThreadPoolExecutor(max_workers=min(PARALLEL_MATCHES, os.cpu_count() or 1)) as pool:
            for name, result in zip(matches, pool.map(_parse, matches.values())):
                if isinstance(result, ReplayParseError):
                    print(f"error: {name}: {result}", file=sys.stderr)
                    continue
                match, _raw, warnings = result
                for w in warnings:
                    print(f"warning: {name}: {w}", file=sys.stderr)
                stats = compute_match_metrics(match)
                rows = pro_league_rows(stats)
                scoreboards.append(f"=== {name} ===\n{scoreboard_text(match, rows)}")
                print(f"\n{scoreboards[-1]}")
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
        args.csv.write_text(rows_csv(csv_rows), encoding="utf-8", newline="")
    if args.txt and scoreboards:
        args.txt.write_text("\n\n".join(scoreboards) + "\n", encoding="utf-8")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
