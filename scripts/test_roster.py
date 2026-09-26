"""Tests for roster.py, metrics_engine.combine_player_stats and the operator names.
Run from the repo root:  python -m unittest discover -s scripts"""

from __future__ import annotations

import unittest

from metrics_engine import PlayerStats, combine_player_stats, compute_match_metrics
from parser import _operator_name
from roster import Roster, find_roster_matches, roster_report, roster_side
from sample_data import SAMPLE_MATCH

TEAM0 = [p["name"] for p in SAMPLE_MATCH["players"] if p["team"] == 0]
TEAM1 = [p["name"] for p in SAMPLE_MATCH["players"] if p["team"] == 1]


def swapped(match: dict) -> dict:
    """The demo match with the teams' sides swapped."""
    return {**match, "players": [{**p, "team": 1 - p["team"]} for p in match["players"]],
            "final_score": list(reversed(match["final_score"]))}


class TestCombine(unittest.TestCase):
    def test_counts_add_up_and_eps_is_rounds_weighted(self):
        a = PlayerStats(name="x", team=0, rounds_played=10, kills=12, deaths=5, headshots=6, rating=1.2)
        a.clutches[2] = 1
        b = PlayerStats(name="x", team=1, rounds_played=5, kills=3, deaths=5, headshots=0, rating=0.9)
        b.clutches[2], b.clutches[1] = 1, 1
        total = combine_player_stats("x", [a, b])
        self.assertEqual((total.rounds_played, total.kills, total.deaths), (15, 15, 10))
        self.assertEqual(total.clutches[2], 2)
        self.assertEqual(total.total_clutches, 3)
        self.assertAlmostEqual(total.hs_pct, 40.0)
        self.assertEqual(total.eps, round(100 * (1.2 * 10 + 0.9 * 5) / 15))

    def test_one_match_is_unchanged(self):
        s = compute_match_metrics(SAMPLE_MATCH)[TEAM0[0]]
        total = combine_player_stats(s.name, [s])
        self.assertEqual((total.kills, total.deaths, total.kost_rounds, total.eps), (s.kills, s.deaths, s.kost_rounds, s.eps))


class TestRoster(unittest.TestCase):
    def test_from_input_cleans_names(self):
        r = Roster.from_input(" Varsity ", ["  Ace ", "", "ace", "Bob"])
        self.assertEqual((r.team, r.players), ("Varsity", ["Ace", "Bob"]))

    def test_side_is_where_most_of_the_roster_played(self):
        roster = Roster("T", ["A", "b", "C"])
        self.assertEqual(roster_side({"a": 1, "B": 1, "c": 0, "z": 0}, roster), (1, ["A", "b"]))
        self.assertIsNone(roster_side({"z": 0}, roster))

    def test_finds_matches_and_parses_only_those(self):
        roster = Roster("Liquid", TEAM0[:3])
        matches = {"m1": SAMPLE_MATCH, "m2": swapped(SAMPLE_MATCH), "m3": {**SAMPLE_MATCH, "players": []}}
        groups = {name: [f"{name}-R01.rec"] for name in matches}
        parsed = []

        def players_of(name, recs):
            return {p["name"]: p["team"] for p in matches[name]["players"]}

        def parse(name, recs):
            parsed.append(name)
            return matches[name]

        found = find_roster_matches(groups, roster, 3, players_of, parse)
        self.assertEqual([(m.name, m.side) for m in found], [("m1", 0), ("m2", 1)])
        self.assertEqual(sorted(parsed), ["m1", "m2"])  # m3 never had the roster, so it isn't parsed
        self.assertEqual(find_roster_matches(groups, Roster("x", ["nobody"]), 1, players_of, parse), [])

    def test_report_adds_up_each_players_matches(self):
        roster = Roster("Liquid", [TEAM0[0].upper(), TEAM0[1], "NotInAnyMatch"])
        groups = {"m1": ["a"], "m2": ["b"]}
        matches = {"m1": SAMPLE_MATCH, "m2": swapped(SAMPLE_MATCH)}
        found = find_roster_matches(groups, roster, 2, lambda n, r: {p["name"]: p["team"] for p in matches[n]["players"]},
                                    lambda n, r: matches[n])
        report = roster_report(roster, found)
        one = compute_match_metrics(SAMPLE_MATCH)[TEAM0[0]]
        combined = report.players[TEAM0[0].upper()]
        self.assertEqual((combined.kills, combined.rounds_played), (2 * one.kills, 2 * one.rounds_played))
        self.assertEqual(combined.eps, one.eps)
        self.assertEqual(report.matches_played[TEAM0[1]], 2)
        self.assertEqual(report.missing, ["NotInAnyMatch"])
        self.assertEqual(report.record, (2, 0))  # Liquid won the demo match, on either side

    def test_stats_against_the_roster_do_not_count(self):
        # TEAM1[0] is typed into the roster but played on the other side
        roster = Roster("Liquid", TEAM0[:2] + [TEAM1[0]])
        found = find_roster_matches({"m": ["r"]}, roster, 2, lambda n, r: {p["name"]: p["team"] for p in SAMPLE_MATCH["players"]},
                                    lambda n, r: SAMPLE_MATCH)
        report = roster_report(roster, found)
        self.assertEqual(report.missing, [TEAM1[0]])


class TestOperatorNames(unittest.TestCase):
    def test_display_names(self):
        self.assertEqual(_operator_name({"operator": {"name": "SolidSnake"}}), "Solid Snake")
        self.assertEqual(_operator_name({"operator": {"name": "Jager"}}), "Jäger")
        self.assertEqual(_operator_name({"operator": {"name": "Ash"}}), "Ash")

    def test_unknown_operator_uses_the_replays_role_name(self):
        self.assertEqual(_operator_name({"operator": {"name": "Operator(456757346397)"}, "roleName": "NOOR"}), "Noor")
        self.assertEqual(_operator_name({"operator": {"name": "Operator(1)"}}), "Operator(1)")


if __name__ == "__main__":
    unittest.main()
