"""Tests for metrics_engine.py and parser.py's normalizer / replay file handling.
Run from scripts/:  python -m unittest"""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import file_guard
from metrics_engine import PRO_LEAGUE_COLUMNS, compute_match_metrics, leaderboard_rows, pro_league_rows, rows_csv
from parser import (
    ReplayParseError, _stage_match_folder, collect_rec_files, group_by_match, normalize_from_r6_dissect, save_uploads,
)
from file_guard import ReplayScanner
from sample_data import SAMPLE_MATCH

A = ["a1", "a2", "a3", "a4", "a5"]  # team 0
B = ["b1", "b2", "b3", "b4", "b5"]  # team 1


def kill(clock, killer, target, headshot=False):
    return {"type": {"name": "Kill", "id": 0}, "username": killer, "target": target,
            "headshot": headshot, "timeInSeconds": clock}


def plant(clock, username=None):
    fb = {"type": {"name": "DefuserPlantComplete", "id": 3}, "timeInSeconds": clock}
    if username:
        fb["username"] = username
    return fb


def rnd(n, feed, winner=0, attack=0, stats=None):
    teams = [{"name": "Alpha", "score": 0, "won": winner == 0, "role": "Attack" if attack == 0 else "Defense"},
             {"name": "Bravo", "score": 0, "won": winner == 1, "role": "Attack" if attack == 1 else "Defense"}]
    players = [{"username": u, "teamIndex": 0} for u in A] + [{"username": u, "teamIndex": 1} for u in B]
    return {"roundNumber": n, "teams": teams, "players": players, "matchFeedback": feed,
            "map": {"name": "BorderY10", "id": 1}, "matchID": "m1", "stats": stats}


def metrics(*rounds):
    return compute_match_metrics(normalize_from_r6_dissect({"rounds": list(rounds)}))


class TestRoundStats(unittest.TestCase):
    def test_entry_trade_and_clock(self):
        # clock counts down: b1 opens on a1 at 2:50, a2 trades 4 s later
        s = metrics(rnd(0, [kill(170, "b1", "a1"), kill(166, "a2", "b1", headshot=True)]))
        self.assertEqual((s["b1"].entry_kills, s["a1"].entry_deaths), (1, 1))
        self.assertEqual(s["a2"].entry_kills, 0)
        self.assertEqual((s["a1"].trades, s["a2"].trade_kills), (1, 1))
        self.assertEqual((s["a2"].headshots, s["a2"].hs_pct), (1, 100.0))

    def test_no_trade_outside_window(self):
        s = metrics(rnd(0, [kill(170, "b1", "a1"), kill(150, "a2", "b1")]))
        self.assertEqual((s["a1"].trades, s["a2"].trade_kills), (0, 0))

    def test_team_kill_is_death_not_kill(self):
        s = metrics(rnd(0, [kill(170, "a1", "a2")]))
        self.assertEqual((s["a1"].kills, s["a2"].deaths), (0, 1))
        self.assertEqual((s["a2"].entry_deaths, s["a1"].entry_kills), (1, 0))

    def test_clutch_won_and_lost(self):
        feed = [kill(170 - i, "b1", a) for i, a in enumerate(A[1:])]  # a1 alone vs 5
        feed += [kill(100 - i, "a1", b) for i, b in enumerate(B)]     # ...and wins
        s = metrics(rnd(0, feed, winner=0))
        self.assertEqual(s["a1"].clutches[5], 1)
        self.assertEqual(s["a1"].multikill_rounds, 1)
        lost = metrics(rnd(0, feed[:4] + [kill(90, "b2", "a1")], winner=1))
        self.assertEqual(lost["a1"].total_clutches, 0)
        self.assertEqual(lost["a1"].round_breakdown[0].clutch_attempt, "1v5")

    def test_unattributed_plant_goes_to_last_attacker(self):
        feed = [kill(170 - i, "b1", a) for i, a in enumerate(A[1:])] + [plant(60)]
        s = metrics(rnd(0, feed, winner=0, attack=0))
        self.assertEqual((s["a1"].plants, s["a1"].objectives), (1, 1))
        # several attackers alive: nobody is credited
        s = metrics(rnd(0, [plant(60)], winner=0, attack=0))
        self.assertEqual(sum(p.plants for p in s.values()), 0)

    def test_named_plant_and_kost_srv(self):
        s = metrics(rnd(0, [plant(60, "a3"), kill(50, "b1", "a3")]),
                    rnd(1, [kill(170, "a1", "b1")], winner=0))
        a3 = s["a3"]
        self.assertEqual((a3.plants, a3.rounds_played, a3.kost_pct, a3.srv_pct), (1, 2, 100.0, 50.0))

    def test_assists_from_r6_dissect_stats(self):
        s = metrics(rnd(0, [kill(170, "a1", "b1")], stats=[{"username": "a2", "assists": 1}]))
        self.assertEqual(s["a2"].assists, 1)

    def test_pro_league_row_format(self):
        s = metrics(rnd(0, [kill(170, "b1", "a1"), kill(166, "a2", "b1")]),
                    rnd(1, [kill(170, "a2", "b2")]))
        row = next(r for r in pro_league_rows(s) if r["Player"] == "a2")
        self.assertEqual(list(row)[2:], list(PRO_LEAGUE_COLUMNS))
        self.assertEqual((row["KD (+/-)"], row["Entry"], row["KPR"], row["SRV"]), ("2-0 (+2)", "1-0 (+1)", "1", "100%"))
        b1 = next(r for r in pro_league_rows(s) if r["Player"] == "b1")
        self.assertEqual((b1["KD (+/-)"], b1["KOST"]), ("1-1 (0)", "100%"))

    def test_demo_match_eps_centered(self):
        stats = compute_match_metrics(SAMPLE_MATCH)
        mean = sum(p.eps for p in stats.values()) / len(stats)
        self.assertAlmostEqual(mean, 100, delta=1)
        self.assertEqual(sum(p.kills for p in stats.values()), sum(p.deaths for p in stats.values()))

    def test_rows_csv(self):
        rows = leaderboard_rows(compute_match_metrics(SAMPLE_MATCH))
        parsed = list(csv.DictReader(io.StringIO(rows_csv(rows))))
        self.assertEqual(list(parsed[0]), list(rows[0]))  # same columns, same order
        self.assertEqual(parsed, [{k: str(v) for k, v in r.items()} for r in rows])
        self.assertEqual(rows_csv([]), "\r\n")


# what real replays start with: the current format, and the older zstd-compressed one
REC = b"dissect\x00" + bytes(2000)
OLD_REC = b"\x28\xb5\x2f\xfd" + bytes(2000)


class TestReplayFiles(unittest.TestCase):
    def test_zip_with_two_matches_and_grouping(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            zp = td / "m.zip"
            with zipfile.ZipFile(zp, "w") as zf:
                for m in ("Match-A", "Match-B"):
                    for r in ("R01", "R02"):
                        zf.writestr(f"{m}/{m}-{r}.rec", REC)
                zf.writestr("Match-A/._Match-A-R03.rec", REC)  # macOS resource fork
                zf.writestr("Match-A/notes.txt", b"x")
            scanner = ReplayScanner()
            recs = collect_rec_files(zp, td / "out", scanner)
            self.assertEqual(len(recs), 4)
            self.assertEqual(len(scanner.skipped), 2)
            groups = group_by_match(recs)
            self.assertEqual(list(groups), ["Match-A", "Match-B"])
            self.assertEqual([Path(p).name for p in groups["Match-B"]], ["Match-B-R01.rec", "Match-B-R02.rec"])

    def test_a_round_found_twice_is_kept_once(self):
        # a copy of a match folder left inside another match's folder
        top = ["MatchReplay/Match-B/Match-B-R01.rec", "MatchReplay/Match-B/Match-B-R02.rec"]
        nested = ["MatchReplay/Match-A/Match-B/Match-B-R01.rec", "MatchReplay/Match-A/Match-B/Match-B-R02.rec"]
        self.assertEqual(group_by_match(nested + top + ["MatchReplay/Match-A/Match-A-R01.rec"]),
                         {"Match-A": ["MatchReplay/Match-A/Match-A-R01.rec"], "Match-B": top})

    def test_staging_rounds_never_writes_to_a_replay(self):
        with tempfile.TemporaryDirectory() as td:
            a, b, stage = Path(td, "a"), Path(td, "b"), Path(td, "stage")
            for folder, data in ((a, REC), (b, OLD_REC)):
                folder.mkdir()
                (folder / "M-R01.rec").write_bytes(data)
            stage.mkdir()
            self.assertEqual(_stage_match_folder([a / "M-R01.rec", b / "M-R01.rec"], stage), stage)
            # stage/M-R01.rec is a hard link to a's file: copying b's over it would overwrite a's
            self.assertEqual((a / "M-R01.rec").read_bytes(), REC)
            self.assertEqual((b / "M-R01.rec").read_bytes(), OLD_REC)

    @staticmethod
    def upload(name: str, data: bytes) -> io.BytesIO:
        f = io.BytesIO(data)  # what Streamlit's UploadedFile is
        f.name = name
        return f

    @staticmethod
    def zip_bytes(files: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_uploads(self):
        zipped = self.zip_bytes({"Match-A/Match-A-R01.rec": REC, "Match-B/Match-B-R01.rec": OLD_REC})
        uploads = [self.upload("matches.zip", zipped), self.upload("Match-C-R01.rec", REC),
                   self.upload("notes.txt", b"ignored")]
        with tempfile.TemporaryDirectory() as td:
            groups = group_by_match(save_uploads(uploads, Path(td)))
            self.assertEqual(list(groups), ["Match-A", "Match-B", "Match-C"])
            self.assertEqual(Path(groups["Match-C"][0]).read_bytes(), REC)

    def test_unwanted_files_are_never_extracted(self):
        zipped = self.zip_bytes({
            "Match-A/Match-A-R01.rec": REC,
            "Match-A/Match-A-R02.rec": b"MZ\x90\x00" + bytes(4000),  # a Windows program renamed to .rec
            "Match-A/run.exe": b"MZ\x90\x00" + bytes(4000),
            "../../evil/Match-A-R03.rec": REC,  # path traversal: lands safely inside the workdir
        })
        with tempfile.TemporaryDirectory() as td:
            scanner = ReplayScanner()
            paths = save_uploads([self.upload("m.zip", zipped)], Path(td), scanner)
            names = sorted(Path(p).name for p in paths)
            self.assertEqual(names, ["Match-A-R01.rec", "Match-A-R03.rec"])
            self.assertTrue(all(Path(p).resolve().is_relative_to(Path(td).resolve()) for p in paths))
            written = sorted(f.name for f in Path(td).rglob("*") if f.is_file())
            self.assertEqual(written, names)  # the program was never written to disk
            self.assertEqual({reason for _, reason in scanner.skipped},
                             {"not a Siege replay (unrecognized contents)", "not a .rec replay file"})

    def test_bad_and_oversized_zip_uploads(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ReplayParseError):
                save_uploads([self.upload("broken.zip", b"not a zip")], Path(td))
            big = self.zip_bytes({"Match-A/Match-A-R01.rec": REC})
            with mock.patch.object(file_guard, "MAX_BATCH_BYTES", 50):
                with self.assertRaisesRegex(ReplayParseError, "too much data"):
                    save_uploads([self.upload("big.zip", big)], Path(td))

    def test_a_single_file_that_is_not_a_replay(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "Match-A-R01.rec"
            fake.write_bytes(b"#!/bin/sh" + bytes(2000))  # a script renamed to .rec
            with self.assertRaisesRegex(ReplayParseError, "isn't a Siege replay"):
                collect_rec_files(fake, Path(td) / "out")


class TestReplayScanner(unittest.TestCase):
    def check(self, name, data):
        return ReplayScanner().check(name, len(data), lambda: io.BytesIO(data))

    def test_accepts_both_replay_formats(self):
        self.assertTrue(self.check("Match-R01.rec", REC))
        self.assertTrue(self.check("MATCH-R01.REC", OLD_REC))

    def test_rejects(self):
        for name, data in [("Match-R01.rec", b"MZ" + bytes(4000)),  # renamed program
                           ("Match-R01.exe", REC),  # wrong extension
                           ("._Match-R01.rec", REC),  # macOS metadata
                           ("Match-R01.rec", b"dissect\x00"),  # too small
                           ]:
            self.assertFalse(self.check(name, data), name)

    def test_too_large_is_rejected_without_reading_it(self):
        opened = mock.MagicMock()
        self.assertFalse(ReplayScanner().check("Match-R01.rec", file_guard.MAX_REPLAY_BYTES + 1, opened))
        opened.assert_not_called()

    def test_batch_limits(self):
        with self.assertRaises(file_guard.ReplayRejected):
            ReplayScanner.check_batch(file_guard.MAX_BATCH_FILES + 1, 0)
        ReplayScanner.check_batch(10, 10 * 1024**2)


if __name__ == "__main__":
    unittest.main()
