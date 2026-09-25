"""
example_season_stats.py
=======================
Example usage of season_stats.StatsManager, runnable as a small CLI.

    # log the bundled demo match into a throwaway DB and print the results
    python scripts/example_season_stats.py --demo

    # log real matches (a match folder, a .zip of one, or individual round .rec files)
    python scripts/example_season_stats.py --season Y10S3 \
        --track "Fabian,Kanto,Sens" replays/Match-2026-09-23_xxx/

    # just print / export what's already stored
    python scripts/example_season_stats.py --season Y10S3 --export season.json
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from parser import ReplayParseError, collect_rec_files, group_by_match, load_demo_match, parse_match
from season_stats import DEFAULT_DB_PATH, StatsManager


def print_season(sm: StatsManager) -> None:
    print(f"\n=== Season {sm.season} ===")
    print(f"{'Player':<16}{'Team':<22}{'Rnds':>5}{'K':>5}{'D':>5}{'A':>5}{'KD':>6}"
          f"{'EntryΔ':>8}{'Trd':>5}{'KOST%':>7}{'Clutch':>8}")
    for p in sm.all_player_stats():
        t = p.totals
        print(f"{p.username:<16}{(p.team or '-'):<22}{t['rounds_played']:>5}{t['kills']:>5}"
              f"{t['deaths']:>5}{t['assists']:>5}{p.kd:>6.2f}{p.entry_diff:>+8}{t['trades']:>5}"
              f"{p.kost_pct:>7.1f}{f'{p.clutches_won}/{p.clutch_attempts}':>8}")

    print(f"\n{'Team':<22}{'KD':>6}{'EntryΔ':>8}{'Clutch%':>9}{'KOST avg':>10}  Players")
    for name in sm.teams():
        t = sm.get_team_stats(name)
        rate = "-" if t.clutch_success_rate is None else f"{100 * t.clutch_success_rate:.0f}%"
        print(f"{t.team:<22}{t.kd:>6.2f}{t.entry_diff:>+8}{rate:>9}{t.kost_avg:>10.1f}  {', '.join(t.players)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("matches", nargs="*", type=Path, help="match folders, .zip files or .rec files to log")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite file (default {DEFAULT_DB_PATH})")
    ap.add_argument("--season", default="current")
    ap.add_argument("--track", default="", help="comma-separated usernames to start tracking")
    ap.add_argument("--team", default=None, help="pin --track players to this team name")
    ap.add_argument("--untrack", default="", help="comma-separated usernames to stop tracking")
    ap.add_argument("--demo", action="store_true", help="log the bundled demo match into an in-memory DB")
    ap.add_argument("--export", type=Path, help="write the season to this JSON file")
    ap.add_argument("--reset", action="store_true", help="delete this season's stats first")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the Windows console defaults to cp1252

    with StatsManager(":memory:" if args.demo else args.db, season=args.season) as sm:
        if args.reset:
            sm.reset_season()
        for u in filter(None, (s.strip() for s in args.track.split(","))):
            sm.add_player(u, team=args.team)
        for u in filter(None, (s.strip() for s in args.untrack.split(","))):
            sm.remove_player(u)

        if args.demo:
            demo = load_demo_match()
            sm.add_players(["Fabian", "Kanto", "Sens", "Bosco", "Nyx"])  # only these get saved
            print(sm.log_match(demo))
            print("re-logging the same match:", sm.log_match(demo))  # skipped, never double counted

        for target in args.matches:
            with tempfile.TemporaryDirectory() as td:
                try:
                    matches = group_by_match(collect_rec_files(target, Path(td)))
                except ReplayParseError as e:
                    print(f"[skip] {target}: {e}")
                    continue
                for name, recs in matches.items():
                    try:
                        match, _raw, warnings = parse_match(recs)
                    except ReplayParseError as e:
                        print(f"[skip] {name}: {e}")
                        continue
                    for w in warnings:
                        print(f"[warn] {name}: {w}")
                    res = sm.log_match(match)
                    print(f"[log]  {name}: {res.rounds_logged} player-rounds logged, "
                          f"{res.rounds_skipped_duplicate} already counted; "
                          f"untracked in this match: {', '.join(sorted(res.untracked_players)) or 'none'}")

        if not sm.tracked_players():
            print("No tracked players yet -- add some with --track \"name1,name2\".")
        print_season(sm)
        if args.export:
            sm.export_json(args.export)
            print(f"\nExported to {args.export}")


if __name__ == "__main__":
    main()
