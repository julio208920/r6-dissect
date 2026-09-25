"""
integrity.py
============
AppIntegrity checks the Windows app's folder against the list of files it was
built with (_internal/manifest.json, which build.ps1 writes right after
PyInstaller). Every listed file must be there and unchanged (same SHA-256),
and nothing else may have been added, so a planted DLL, a swapped library or
an edited script is caught. The launcher runs the check every time the app
starts and refuses to run a copy that fails it.

    python desktop/integrity.py create dist/R6MatchStats    (build.ps1 does this)
    python desktop/integrity.py verify "%LOCALAPPDATA%/Programs/R6 Match Stats"

What it can't catch: someone replacing R6MatchStats.exe itself, since that's
the file doing the checking. For that, users can compare the installer's
SHA-256 with the one published on the release before running it.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MANIFEST = "_internal/manifest.json"
# added to the folder by the installer, after the build
ALLOWED_EXTRAS = ("unins*.exe", "unins*.dat")


class AppIntegrity:
    def __init__(self, app_dir: str | Path):
        self.app_dir = Path(app_dir)
        self.manifest = self.app_dir / MANIFEST

    def _files(self) -> list[tuple[str, Path, int]]:
        """(path relative to the app folder, path, size) of everything but folders and the
        manifest, sorted. A link or junction counts as a file and is never followed, so a
        planted one is reported too. os.scandir lists sizes along with the names (on
        Windows, without a call per file)."""
        found = []
        dirs = [self.app_dir]
        while dirs:
            with os.scandir(dirs.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False) and not entry.is_junction():
                        dirs.append(Path(entry.path))
                        continue
                    path = Path(entry.path)
                    if path != self.manifest:
                        rel = path.relative_to(self.app_dir).as_posix()
                        found.append((rel, path, entry.stat(follow_symlinks=False).st_size))
        return sorted(found)

    @staticmethod
    def _sha256(path: Path) -> str:
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    @classmethod
    def _sha256_all(cls, paths: list[Path]) -> list[str]:
        """Hashes in the same order, several files at a time: hashlib releases the GIL
        while hashing, so this makes the check at every app start several times faster."""
        with ThreadPoolExecutor() as pool:
            return list(pool.map(cls._sha256, paths))

    def create(self) -> int:
        """Write the manifest for the folder as it is now; returns how many files it lists."""
        found = self._files()
        digests = self._sha256_all([path for _, path, _ in found])
        files = {rel: {"size": path.stat().st_size, "sha256": digest} for (rel, path, _), digest in zip(found, digests)}
        self.manifest.write_text(json.dumps({"files": files}, indent=1, sort_keys=True), encoding="utf-8")
        return len(files)

    def verify(self) -> list[str]:
        """Problems with the folder, one line each; an empty list means it's intact."""
        try:
            expected = json.loads(self.manifest.read_text(encoding="utf-8"))["files"]
        except (OSError, ValueError, KeyError):
            return [f"the list of the app's files ({MANIFEST}) is missing or unreadable"]
        found = self._files()

        def listed_size(rel: str, path: Path, size: int) -> bool:
            want = expected[rel]["size"]
            return size == want or path.stat().st_size == want  # a listing's size can lag behind

        # hash only the listed files that still have their listed size; a size change is enough
        to_hash = [(rel, path) for rel, path, size in found if rel in expected and listed_size(rel, path, size)]
        digests = dict(zip((rel for rel, _ in to_hash), self._sha256_all([path for _, path in to_hash])))
        problems = []
        seen = set()
        for rel, path, _ in found:
            seen.add(rel)
            want = expected.get(rel)
            if want is None:
                if not any(fnmatch.fnmatch(rel, pattern) for pattern in ALLOWED_EXTRAS):
                    problems.append(f"unexpected file: {rel}")
            elif digests.get(rel) != want["sha256"]:
                problems.append(f"changed file: {rel}")
        problems += [f"missing file: {rel}" for rel in sorted(set(expected) - seen)]
        return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("create", "verify"):
        print(__doc__)
        return 2
    check = AppIntegrity(argv[2])
    if argv[1] == "create":
        print(f"Listed {check.create()} files in {check.manifest}")
        return 0
    problems = check.verify()
    print("\n".join(problems) or "All files are intact.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
