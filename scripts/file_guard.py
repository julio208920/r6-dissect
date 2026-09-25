"""
file_guard.py
=============
ReplayScanner decides which files are allowed through to the replay parser.
Every file the app reads, whether uploaded, inside a zip or in a folder,
must pass it, so an unwanted file (a renamed program, a document, a zip
bomb) is skipped and reported instead of being handed to r6-dissect.

A file passes only if it
- has a .rec name (and isn't a macOS "._" resource fork),
- is a sensible size for one round of a Siege match, and
- starts with the bytes every Siege replay starts with: "dissect\\0" for
  current game versions, or zstd's frame signature for older ones.
Batches (a zip, an upload, a folder) are also capped in file count and total
size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import BinaryIO

REPLAY_SIGNATURES = (b"dissect\x00", b"\x28\xb5\x2f\xfd")  # current format, older zstd-compressed format
MIN_REPLAY_BYTES = 1024  # a header alone is bigger than this
MAX_REPLAY_BYTES = 256 * 1024**2  # one round is ~6-15 MB
MAX_BATCH_FILES = 2000  # a whole MatchReplay folder of a busy season
MAX_BATCH_BYTES = 4 * 1024**3


class ReplayRejected(Exception):
    """A whole batch was refused (too many files, or too large)."""


@dataclass
class ReplayScanner:
    """Checks candidate replay files; remembers what it skipped and why."""

    skipped: list[tuple[str, str]] = field(default_factory=list)  # (file name, reason)

    @staticmethod
    def name_problem(name: str) -> str | None:
        base = PurePath(name.replace("\\", "/")).name
        if base.startswith("._"):
            return "macOS metadata file"
        if not base.lower().endswith(".rec"):
            return "not a .rec replay file"
        return None

    @staticmethod
    def size_problem(size: int) -> str | None:
        if size < MIN_REPLAY_BYTES:
            return "too small to be a replay"
        if size > MAX_REPLAY_BYTES:
            return "too large to be a replay"
        return None

    @staticmethod
    def content_problem(stream: BinaryIO) -> str | None:
        head = stream.read(8)
        if not any(head.startswith(sig) for sig in REPLAY_SIGNATURES):
            return "not a Siege replay (unrecognized contents)"
        return None

    def check(self, name: str, size: int, open_stream) -> bool:
        """Whether a file may be parsed. open_stream() opens it for reading;
        it's only called once the name and size look right."""
        problem = self.name_problem(name) or self.size_problem(size)
        if problem is None:
            with open_stream() as stream:
                problem = self.content_problem(stream)
        if problem:
            self.skipped.append((PurePath(name.replace("\\", "/")).name, problem))
            return False
        return True

    @staticmethod
    def check_batch(count: int, total_bytes: int) -> None:
        """Refuse a batch that's far bigger than any real set of matches."""
        if count > MAX_BATCH_FILES:
            raise ReplayRejected(f"That's {count} files; the limit is {MAX_BATCH_FILES} replay files at once.")
        if total_bytes > MAX_BATCH_BYTES:
            raise ReplayRejected("That's too much data to be match replays (the limit is 4 GB at once).")

    def summary(self) -> str | None:
        """One line about skipped files, or None if nothing was skipped."""
        if not self.skipped:
            return None
        shown = ", ".join(f"{name} ({reason})" for name, reason in self.skipped[:5])
        more = f" and {len(self.skipped) - 5} more" if len(self.skipped) > 5 else ""
        return f"Skipped {len(self.skipped)} file(s) that aren't Siege replays: {shown}{more}."
