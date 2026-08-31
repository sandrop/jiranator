"""Atomic snapshot persistence for the jiranator downloader.

Ports downloader B's staging discipline: write ``issues.jsonl`` and
``meta.json`` to sibling ``.tmp`` files, ``os.replace`` each into place (atomic
on the same filesystem), then touch a ``download.complete`` sentinel so a
partial write is never mistaken for a finished snapshot. On any failure the
``.tmp`` files are unlinked and the exception re-raised, leaving no half-written
output.

The completion sentinel is removed BEFORE either final file is replaced and
re-touched only after both replacements succeed. Without that, a repeat download
over an existing complete snapshot that failed between the two ``os.replace``
calls would leave a new ``issues.jsonl`` beside the old ``meta.json`` while the
prior sentinel still certified the pair as complete. Snapshot files are written
owner-only (0600) and a freshly created output dir is 0700, since a snapshot
holds raw Jira fields and changelog. Staging files carry a pid suffix so two
downloaders targeting one dir do not truncate each other's ``.tmp``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ISSUES_NAME = "issues.jsonl"
META_NAME = "meta.json"
SENTINEL_NAME = "download.complete"

_FILE_MODE = 0o600
_DIR_MODE = 0o700


def _open_private(path: Path):
    """Open ``path`` for writing, created 0600, truncating any prior file.

    ``os.open`` applies the mode at creation (subject to umask, which never adds
    owner-only bits back), so the file is never briefly group/other-readable the
    way a create-then-``chmod`` would be.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
    return os.fdopen(fd, "w", encoding="utf-8")


def write_snapshot(records: list[dict], meta: dict, out_dir) -> tuple[Path, Path]:
    """Atomically write ``issues.jsonl`` + ``meta.json`` and the sentinel.

    Returns the ``(issues_path, meta_path)`` pair. Raises (after cleaning up any
    ``.tmp`` files) if serialization or the filesystem write fails. A prior
    completion sentinel is invalidated up front, so a failure part-way through
    never leaves an inconsistent snapshot marked complete.
    """
    out_dir = Path(out_dir)
    dir_existed = out_dir.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not dir_existed:
        os.chmod(out_dir, _DIR_MODE)

    issues_path = out_dir / ISSUES_NAME
    meta_path = out_dir / META_NAME
    sentinel = out_dir / SENTINEL_NAME
    suffix = f".{os.getpid()}.tmp"
    issues_tmp = out_dir / (ISSUES_NAME + suffix)
    meta_tmp = out_dir / (META_NAME + suffix)

    # Invalidate any prior completion marker before mutating the final files, so
    # the mid-replace window is never certified as a complete snapshot.
    try:
        sentinel.unlink()
    except FileNotFoundError:
        pass

    try:
        # Create staging files owner-only from the first byte: the raw snapshot
        # is written into them before any rename, so a post-write chmod would
        # leave a readable window for another local user under a 022 umask.
        with _open_private(issues_tmp) as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False))
                fh.write("\n")
        with _open_private(meta_tmp) as fh:
            fh.write(json.dumps(meta, ensure_ascii=False, indent=2))
        os.replace(issues_tmp, issues_path)
        os.replace(meta_tmp, meta_path)
        sentinel.touch()
        os.chmod(sentinel, _FILE_MODE)
    except BaseException:
        for tmp in (issues_tmp, meta_tmp):
            try:
                tmp.unlink()
            except OSError:
                pass
        raise

    return issues_path, meta_path
