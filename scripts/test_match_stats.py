"""Tests for match_stats.py, the command-line tool. Run from the repo root:
python -m unittest discover -s scripts"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import match_stats
from sample_data import SAMPLE_MATCH


def run_cli(*args: str) -> tuple[int, str]:
    """Run match_stats on two matches that are both the demo match (no r6-dissect needed);
    returns the exit code and what it printed."""
    recs = ["m1/Match-1-R01.rec", "m2/Match-2-R01.rec"]
    out = io.StringIO()
    with mock.patch.object(match_stats, "collect_rec_files", return_value=recs), \
            mock.patch.object(match_stats, "parse_match", return_value=(SAMPLE_MATCH, {}, [])), \
            contextlib.redirect_stdout(out):
        code = match_stats.main(["replays", *args])
    return code, out.getvalue()


class TestCommandLine(unittest.TestCase):
    def test_writes_csv_json_and_txt(self):
        with tempfile.TemporaryDirectory() as td:
            files = {ext: Path(td) / f"stats.{ext}" for ext in ("csv", "json", "txt")}
            code, printed = run_cli(*(arg for ext, path in files.items() for arg in (f"--{ext}", str(path))))
            self.assertEqual(code, 0)

            text = files["txt"].read_text(encoding="utf-8")
            self.assertEqual(text, printed.lstrip("\n"))  # the scoreboards, as printed
            self.assertEqual(text.count("=== Match-"), 2)
            for player in SAMPLE_MATCH["players"]:
                self.assertIn(player["name"], text)

            self.assertEqual([m["match"] for m in json.loads(files["json"].read_text(encoding="utf-8"))],
                             ["Match-1", "Match-2"])
            rows = list(csv.DictReader(io.StringIO(files["csv"].read_text(encoding="utf-8"))))
            self.assertEqual(len(rows), 2 * len(SAMPLE_MATCH["players"]))
            self.assertEqual(list(rows[0])[:3], ["Match", "Team Name", "Player"])

    def test_writes_only_the_files_asked_for(self):
        with tempfile.TemporaryDirectory() as td:
            txt = Path(td) / "scores.txt"
            code, _ = run_cli("--txt", str(txt))
            self.assertEqual(code, 0)
            self.assertEqual([p.name for p in Path(td).iterdir()], ["scores.txt"])


if __name__ == "__main__":
    unittest.main()
