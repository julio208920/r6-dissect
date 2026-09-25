"""File signatures include nested rounds, not just a parent folder's mtime."""
from pathlib import Path


def source_signature(path: Path) -> tuple:
    files = sorted((p for p in path.rglob('*') if p.is_file() and p.suffix.lower() == '.rec')) if path.is_dir() else [path]
    return ('path', str(path.resolve()), tuple(
        (str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files
    ))
