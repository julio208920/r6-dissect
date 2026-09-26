"""
launcher.py
===========
Entry point of the Windows app (R6MatchStats.exe, built by build.ps1 with
PyInstaller). It opens the app in its own window (Microsoft Edge WebView2,
built into Windows 10 and 11) and runs the dashboard's server as a hidden
child process on this PC only, stopping it when the window closes.

    R6MatchStats.exe                      the app window
    R6MatchStats.exe --serve PORT PID     the server (started by the window)

Settings, for testing:
    R6_NO_WINDOW=1         open the app in the default browser instead of a window
    R6_SMOKE_TEST=FILE     load the app, write what the window shows to FILE
                           (JSON), then quit: exit code 0 if the app rendered.
                           Also saves a screenshot of the screen as FILE.png
From source:  python desktop/launcher.py   (needs pip install pywebview)
"""

from __future__ import annotations

import functools
import html
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from integrity import AppIntegrity

# Never write compiled .pyc caches into the app's folder: the integrity check
# would (rightly) flag them as files that weren't there when it was built.
sys.dont_write_bytecode = True

# the unpacked app, or the repo root when run from source
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from app_info import APP_NAME, quiet_windows_connection_resets  # noqa: E402  ships as a plain file next to app.py

IS_WINDOWS = sys.platform == "win32"
STARTUP_TIMEOUT = 90  # seconds; the first start after install is slow while antivirus scans the files
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "R6MatchStats"
LOG_FILE = DATA_DIR / "app.log"


# ----------------------------------------------------------- no terminals --
def hide_console_windows() -> None:
    """This app has no console, so Windows gives each console program it starts its own
    console window: an empty terminal flashing up for every replay parse (r6-dissect),
    or when Streamlit asks Git about the app's folder. Make every program started from
    this process run without one, whichever code starts it (a program that explicitly
    asks for a new console still gets it). Windows only; safe to call more than once."""
    if not IS_WINDOWS or getattr(subprocess.Popen.__init__, "hides_console_windows", False):
        return
    original = subprocess.Popen.__init__
    explicit = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS

    @functools.wraps(original)
    def init(self, *args, **kwargs):
        # creationflags is Popen's 14th parameter; nobody passes it by position, but leave that alone
        if len(args) < 14 and not kwargs.get("creationflags", 0) & explicit:
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    init.hides_console_windows = True
    subprocess.Popen.__init__ = init


# ------------------------------------------------------------------ server --
def serve(port: int, parent_pid: int) -> int:
    """Run the dashboard's server on 127.0.0.1:port until the window's process exits."""
    parser_exe = ROOT / "r6-dissect.exe"
    if parser_exe.is_file():
        os.environ["R6_DISSECT_BIN"] = str(parser_exe)
    os.environ["R6_DESKTOP"] = "1"
    if sys.stdout is None:  # a windowed build can drop the log file handle start_server passed in
        sys.stdout = sys.stderr = open(LOG_FILE, "a", encoding="utf-8", errors="replace", buffering=1)
    quiet_windows_connection_resets()
    threading.Thread(target=_exit_with_parent, args=(parent_pid,), daemon=True).start()

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit", "run", str(SCRIPTS / "app.py"),
        "--global.developmentMode=false",  # a PyInstaller build otherwise looks like a Streamlit dev checkout
        "--server.address=127.0.0.1",  # only this PC can reach the app
        f"--server.port={port}",
        "--server.headless=true",  # the window shows the app, not a browser tab
        "--server.fileWatcherType=none",
        "--server.maxUploadSize=2048",
        "--browser.gatherUsageStats=false",
        "--client.toolbarMode=minimal",  # no Streamlit developer menu (Deploy, Rerun, ...)
        "--theme.base=dark",
    ]
    return stcli.main()


def _exit_with_parent(pid: int) -> None:
    """Stop the server when the window's process is gone, even if it crashed."""
    if IS_WINDOWS:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return  # can't watch it; the window still stops this server when it quits
        ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    else:
        while True:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(1)
    os._exit(0)


def start_server() -> tuple[subprocess.Popen, str]:
    """Start the server as a hidden child process; returns it and the app's URL."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    me = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        me + ["--serve", str(port), str(os.getpid())],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
    )
    return proc, f"http://127.0.0.1:{port}/"


def integrity_problems() -> list[str]:
    """What's wrong with the installed app's files (see integrity.py); nothing when run from source."""
    if not getattr(sys, "frozen", False):
        return []
    return AppIntegrity(Path(sys.executable).parent).verify()


class Server:
    """The dashboard's server: started only once the app's files check out, and
    stopped when the app quits."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.url = ""
        self.problems: list[str] = []

    def start(self) -> bool:
        """Check the app's files, then start the server. False if the check failed."""
        if self.proc is None and not self.problems:
            self.problems = integrity_problems()
            if self.problems:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                LOG_FILE.write_text("The app's files failed their check:\n" + "\n".join(self.problems) + "\n",
                                    encoding="utf-8")
                return False
            self.proc, self.url = start_server()
        return self.proc is not None

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()


def wait_until_up(proc: subprocess.Popen, url: str) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen(url + "_stcore/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.3)
    return False


# ------------------------------------------------------------------ window --
def _page(body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin:0; height:100vh; display:flex; flex-direction:column; align-items:center;
       justify-content:center; gap:18px; background:#0d1117; color:#f0f3f6;
       font:15px 'Segoe UI', system-ui, sans-serif; text-align:center; }}
.spin {{ width:42px; height:42px; border:4px solid #232b36; border-top-color:#ff5c1a;
         border-radius:50%; animation:s .9s linear infinite; }}
@keyframes s {{ to {{ transform:rotate(360deg) }} }}
h1 {{ font-size:22px; margin:0; }} p {{ color:#8b949e; margin:0; max-width:520px; }}
code {{ color:#f0f3f6; user-select:all; }}
</style></head><body>{body}</body></html>"""


LOADING = _page(f'<div class="spin"></div><h1>{APP_NAME}</h1><p>Starting up...</p>')


def failed_page() -> str:
    return _page(f"<h1>{APP_NAME} couldn't start</h1><p>Close this window and open the app again. "
                 f"If it keeps happening, the details are in <code>{LOG_FILE}</code></p>")


TAMPERED = (f"{APP_NAME} won't start: some of its files were changed, added or removed since it was "
            "installed, so it may not be safe to run. Uninstall it, then reinstall it from its official "
            "download page.")


def tampered_page(problems: list[str]) -> str:
    listed = "".join(f"<li><code>{html.escape(p)}</code></li>" for p in problems[:8])
    return _page(f"<h1>{APP_NAME} won't start</h1><p>{html.escape(TAMPERED)}</p>"
                 f"<ul style='text-align:left; color:#8b949e'>{listed}</ul>")


SMOKE_TEST_JS = """(() => {
  const main = document.querySelector('[data-testid="stMain"]') || document.querySelector('.stApp');
  const text = main ? main.innerText : '';
  const error = !!document.querySelector('[data-testid="stException"]');
  return JSON.stringify({title: document.title, url: location.href, error, text: text.slice(0, 4000)});
})()"""


def run_window(server: Server) -> int:
    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True  # the report's CSV, JSON and TXT buttons
    smoke_file = os.environ.get("R6_SMOKE_TEST")
    result = {"ok": False}

    def load(window) -> None:
        # the check runs while the window shows "Starting up...", before any server code
        if not server.start():
            window.load_html(tampered_page(server.problems))
            if smoke_file:
                result["tampered"] = server.problems
                window.destroy()
            return
        if not wait_until_up(server.proc, server.url):
            window.load_html(failed_page())
            return
        window.load_url(server.url)
        if smoke_file:
            result.update(smoke_test(window))
            window.destroy()

    window = webview.create_window(APP_NAME, html=LOADING, width=1440, height=900, min_size=(900, 600),
                                   background_color="#0d1117", text_select=True)
    webview.start(load, window, private_mode=False, storage_path=str(DATA_DIR / "webview"))
    if smoke_file:
        Path(smoke_file).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0 if result["ok"] else 1
    return 0


def smoke_test(window) -> dict:
    """Wait for the report page to render in the window and report what it shows."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    seen: dict = {}
    while time.monotonic() < deadline:
        try:
            seen = json.loads(window.evaluate_js(SMOKE_TEST_JS) or "{}")
        except Exception as e:  # the page is still loading
            seen = {"js_error": repr(e)}
        if seen.get("error"):
            break
        if dashboard_is_rendered(seen.get("text", "")):
            time.sleep(2)  # let the page finish painting for the screenshot
            try:
                from PIL import ImageGrab

                ImageGrab.grab().save(os.environ["R6_SMOKE_TEST"] + ".png")
            except Exception as e:  # no desktop to capture
                seen["screenshot_error"] = repr(e)
            return {"ok": True, **seen}
        time.sleep(1)
    return {"ok": False, **seen}


def dashboard_is_rendered(text: str) -> bool:
    """Recognize the current page name while preserving older report wording."""
    return "Dashboard" in text or "Match Report" in text


def run_in_browser(server: Server) -> int:
    """Fallback without WebView2: open the default browser, and keep the server
    running until the user says to quit."""
    import webbrowser

    if not server.start():
        message_box(TAMPERED + "\n\n" + "\n".join(server.problems[:8]))
        return 1
    if not wait_until_up(server.proc, server.url):
        message_box(f"{APP_NAME} couldn't start. The details are in {LOG_FILE}")
        return 1
    webbrowser.open(server.url)
    message_box(f"{APP_NAME} is open in your web browser at {server.url}\n\nClick OK to quit the app.")
    return 0


def message_box(text: str) -> None:
    if IS_WINDOWS:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x40)  # MB_ICONINFORMATION
    else:
        print(text)
        try:
            input()
        except EOFError:
            threading.Event().wait()


# ---------------------------------------------------------- single instance --
def already_running() -> bool:
    """If the app is already open, bring its window to the front and return True."""
    if not IS_WINDOWS:
        return False
    import ctypes

    kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    already = kernel32.CreateMutexW(None, False, "Local\\R6MatchStats") and kernel32.GetLastError() == 183
    if already:  # ERROR_ALREADY_EXISTS
        hwnd = user32.FindWindowW(None, APP_NAME)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    return bool(already)


def main() -> int:
    hide_console_windows()  # first, before anything can start a program
    if len(sys.argv) >= 4 and sys.argv[1] == "--serve":
        return serve(int(sys.argv[2]), int(sys.argv[3]))
    if not os.environ.get("R6_SMOKE_TEST") and already_running():
        return 0

    server = Server()
    try:
        if os.environ.get("R6_NO_WINDOW"):
            return run_in_browser(server)
        try:
            return run_window(server)
        except Exception as e:  # no WebView2 runtime, or it failed to start
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as log:
                log.write(f"\nThe app window couldn't open ({e!r}); using the web browser instead.\n")
            if os.environ.get("R6_SMOKE_TEST"):
                raise
            return run_in_browser(server)
    finally:
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
