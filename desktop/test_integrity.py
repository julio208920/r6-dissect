"""Tests for integrity.py. Run from the repo root:  python -m unittest discover -s desktop"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from integrity import AppIntegrity


class TestAppIntegrity(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / "_internal" / "scripts").mkdir(parents=True)
        (self.dir / "R6MatchStats.exe").write_bytes(b"MZ app")
        (self.dir / "_internal" / "python312.dll").write_bytes(b"MZ python")
        (self.dir / "_internal" / "scripts" / "parser.py").write_text("print('hi')\n")
        self.check = AppIntegrity(self.dir)
        self.assertEqual(self.check.create(), 3)

    def test_untouched_install_passes(self):
        (self.dir / "unins000.exe").write_bytes(b"MZ uninstaller")  # added by the installer: fine
        (self.dir / "unins000.dat").write_bytes(b"data")
        self.assertEqual(self.check.verify(), [])

    def test_changed_added_and_removed_files_are_caught(self):
        (self.dir / "_internal" / "scripts" / "parser.py").write_text("import os; os.system('evil')\n")
        (self.dir / "_internal" / "version.dll").write_bytes(b"MZ planted")
        (self.dir / "_internal" / "scripts" / "__pycache__").mkdir()
        (self.dir / "_internal" / "scripts" / "__pycache__" / "parser.cpython-312.pyc").write_bytes(b"x")
        (self.dir / "_internal" / "python312.dll").unlink()
        self.assertEqual(sorted(self.check.verify()), [
            "changed file: _internal/scripts/parser.py",
            "missing file: _internal/python312.dll",
            "unexpected file: _internal/scripts/__pycache__/parser.cpython-312.pyc",
            "unexpected file: _internal/version.dll",
        ])

    def test_same_size_edit_is_caught(self):
        (self.dir / "R6MatchStats.exe").write_bytes(b"MZ bad")  # same length as before
        self.assertEqual(self.check.verify(), ["changed file: R6MatchStats.exe"])

    @unittest.skipUnless(sys.platform == "win32", "junctions are a Windows feature")
    def test_a_planted_junction_is_reported_not_followed(self):
        elsewhere = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        (elsewhere / "payload.dll").write_bytes(b"MZ")
        junction = self.dir / "_internal" / "plugins"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(elsewhere)], check=True, capture_output=True)
        self.addCleanup(os.rmdir, junction)  # removes the junction only, not what it points to
        self.assertEqual(self.check.verify(), ["unexpected file: _internal/plugins"])

    def test_missing_manifest(self):
        self.check.manifest.unlink()
        self.assertEqual(len(self.check.verify()), 1)


if __name__ == "__main__":
    unittest.main()
