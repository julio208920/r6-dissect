"""Tests for launcher.py. Run from the repo root:  python -m unittest discover -s desktop"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import launcher

HERE = Path(__file__).resolve().parent


@unittest.skipUnless(sys.platform == "win32", "console windows are a Windows thing")
class TestHideConsoleWindows(unittest.TestCase):
    def test_every_program_started_gets_no_console_window(self):
        seen = []

        def record(self, *args, **kwargs):  # stands in for the real Popen.__init__
            self._child_created = False
            seen.append(kwargs.get("creationflags", 0))

        with mock.patch.object(subprocess.Popen, "__init__", record):
            launcher.hide_console_windows()
            launcher.hide_console_windows()  # a second call changes nothing
            subprocess.Popen(["anything"])
            subprocess.Popen(["anything"], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            subprocess.Popen(["anything"], creationflags=subprocess.CREATE_NEW_CONSOLE)  # asked for: kept
        no_window = subprocess.CREATE_NO_WINDOW
        self.assertEqual(seen, [no_window, subprocess.CREATE_NEW_PROCESS_GROUP | no_window,
                                subprocess.CREATE_NEW_CONSOLE])

    def test_a_plain_subprocess_call_from_the_app_opens_no_window(self):
        # Like Streamlit's Git lookup: subprocess.run with no flags, from a process with no
        # console (pythonw.exe, as the app is), which would otherwise give the child a window.
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            self.skipTest("no pythonw.exe next to this Python")
        with tempfile.TemporaryDirectory() as td:
            result, runner, probe = Path(td, "result.json"), Path(td, "runner.py"), Path(td, "probe.py")
            probe.write_text("import ctypes, json, sys\n"
                             "json.dump({'window': bool(ctypes.windll.kernel32.GetConsoleWindow())}, open(sys.argv[1], 'w'))\n")
            runner.write_text("\n".join([
                "import subprocess, sys",
                f"sys.path.insert(0, {str(HERE)!r})",
                "import launcher",
                "launcher.hide_console_windows()",
                f"subprocess.run([{sys.executable!r}, {str(probe)!r}, {str(result)!r}], timeout=60)",
            ]))
            subprocess.run([str(pythonw), str(runner)], timeout=90, check=True)
            self.assertEqual(json.loads(result.read_text()), {"window": False})


if __name__ == "__main__":
    unittest.main()
