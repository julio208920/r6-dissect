"""Packaged-asset integrity checks."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))
import integrity


class IntegrityTest(unittest.TestCase):
    def test_manifest_detects_changes_and_missing_assets(self):
        with tempfile.TemporaryDirectory() as td, patch.object(integrity, "ASSETS", ("scripts/app.py", "r6-dissect.exe")):
            root = Path(td)
            (root / "scripts").mkdir()
            (root / "scripts/app.py").write_bytes(b"app")
            (root / "r6-dissect.exe").write_bytes(b"parser")
            manifest = root / "integrity.json"
            integrity.write_manifest(root, manifest)
            self.assertEqual(integrity.verify_manifest(root, manifest), [])
            (root / "scripts/app.py").write_bytes(b"changed")
            self.assertEqual(integrity.verify_manifest(root, manifest), ["scripts/app.py"])
            (root / "r6-dissect.exe").unlink()
            self.assertEqual(set(integrity.verify_manifest(root, manifest)),
                             {"scripts/app.py", "r6-dissect.exe"})

    def test_missing_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertTrue(integrity.verify_manifest(root, root / "integrity.json"))
