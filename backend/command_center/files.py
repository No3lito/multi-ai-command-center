"""Read-only access to one owner-chosen folder, for attaching files to runs.

The folder is mounted read-only (Docker: FILES_FOLDER on the host is /shared in the
container) and only the owner can browse it. Paths are always relative to the root and are
resolved and checked to stay inside it (no "..", no absolute paths, no symlinks pointing
out). Only text files are read; content is a snapshot stored with the run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".txt",
        ".csv",
        ".tsv",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".log",
        ".py",
        ".sql",
        ".ini",
    }
)
MAX_LISTED = 500
MAX_FILE_BYTES = 5 * 1024 * 1024  # never read anything bigger than this from disk


class FileAccessError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    path: str  # relative to the root, with forward slashes
    type: str  # "dir" | "file"
    size: int | None
    readable: bool  # a text file that can be attached


@dataclass(frozen=True)
class Snapshot:
    path: str
    content: str
    chars: int
    sha256: str


def available(root: Path | None) -> bool:
    return root is not None and root.is_dir()


def resolve(root: Path, relative: str) -> Path:
    """The real path for `relative` inside root, or FileAccessError."""
    rel = relative.replace("\\", "/").strip().strip("/")
    if rel.startswith("/") or any(part == ".." for part in rel.split("/")) or ":" in rel:
        raise FileAccessError("Path must be inside the shared folder.")
    base = root.resolve()
    target = (base / rel).resolve() if rel else base
    if target != base and base not in target.parents:
        raise FileAccessError("Path must be inside the shared folder.")
    return target


def relative_path(root: Path, target: Path) -> str:
    return target.relative_to(root.resolve()).as_posix()


def list_dir(root: Path, relative: str = "") -> list[Entry]:
    folder = resolve(root, relative)
    if not folder.is_dir():
        raise FileAccessError("Not a folder.")
    entries: list[Entry] = []
    for child in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith("."):
            continue  # hidden files and folders (.git, .env and the like) are never offered
        try:
            real = child.resolve()
            if real != root.resolve() and root.resolve() not in real.parents:
                continue  # a link pointing outside the shared folder
            if child.is_dir():
                entries.append(Entry(child.name, relative_path(root, real), "dir", None, False))
            elif child.is_file():
                size = child.stat().st_size
                ok = child.suffix.lower() in TEXT_EXTENSIONS and size <= MAX_FILE_BYTES
                entries.append(Entry(child.name, relative_path(root, real), "file", size, ok))
        except OSError:
            continue
        if len(entries) >= MAX_LISTED:
            break
    return entries


def read_snapshot(root: Path, relative: str) -> Snapshot:
    target = resolve(root, relative)
    if not target.is_file():
        raise FileAccessError(f"{relative}: not a file.")
    if target.name.startswith("."):
        raise FileAccessError(f"{relative}: hidden files cannot be attached.")
    if target.suffix.lower() not in TEXT_EXTENSIONS:
        raise FileAccessError(f"{relative}: only text files can be attached.")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise FileAccessError(f"{relative}: larger than 5 MB.")
    raw = target.read_bytes()
    if b"\x00" in raw[:4096]:
        raise FileAccessError(f"{relative}: looks like a binary file.")
    content = raw.decode("utf-8", errors="replace")
    return Snapshot(
        path=relative_path(root, target),
        content=content,
        chars=len(content),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
