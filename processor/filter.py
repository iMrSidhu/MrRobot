"""Repository file filtering (DESIGN.md section 5, Step 3.2).

Walks a cloned repo and keeps only core source files and READMEs, so the
chunker (Step 3.3) feeds the LLM signal instead of noise. Edit the constants
below to change policy — no logic edits needed.
"""
import os
from dataclasses import dataclass
from pathlib import Path

# --- allow list: extension -> language label -------------------------------
LANGUAGE_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".kt": "Kotlin", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
    ".hpp": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".scala": "Scala", ".sh": "Shell", ".bash": "Shell",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".vue": "Vue",
    ".svelte": "Svelte", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML",
}

# --- deny lists -------------------------------------------------------------
DENY_DIRS = {"node_modules", "vendor", "tests", "test", "__pycache__",
             ".git", ".venv", "venv", "build", "dist"}
LOCKFILE_NAMES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
                  "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "uv.lock",
                  "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
              ".tiff", ".svg", ".heic"}
BINARY_EXTS = {".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".pyc",
               ".bin", ".zip", ".gz", ".tar", ".bz2", ".7z", ".pdf",
               ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov",
               ".avi", ".wasm"}
MINIFIED_SUFFIXES = (".min.js", ".min.css", ".min.mjs")

MAX_FILE_SIZE = 200 * 1024  # 200 KB — larger files are not "core source"
BINARY_SNIFF_BYTES = 4096   # a NUL byte in the head means binary, whatever the name


@dataclass(frozen=True)
class KeptFile:
    path: Path     # absolute path inside the clone
    size: int      # bytes on disk
    language: str  # label from LANGUAGE_BY_EXT, "Markdown" for READMEs


def _is_readme(name: str) -> bool:
    lower = name.lower()
    return lower == "readme" or lower.startswith("readme.")


def _looks_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True  # unreadable = not worth keeping


def keep_file(path: Path, root: Path) -> bool:
    """Single-file policy check (deny rules still apply to READMEs).

    Directory denials are matched against the path RELATIVE to the clone
    root, so a cache root that itself lives under e.g. 'build' is unaffected.
    """
    name = path.name
    lower = name.lower()
    if path.is_symlink():
        return False
    if any(part in DENY_DIRS for part in path.relative_to(root).parts[:-1]):
        return False
    if lower in LOCKFILE_NAMES or lower.endswith(".lock"):
        return False
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS or ext in BINARY_EXTS:
        return False
    if lower.endswith(MINIFIED_SUFFIXES):
        return False
    if not _is_readme(name) and ext not in LANGUAGE_BY_EXT:
        return False
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return not _looks_binary(path)


def filter_repo(root: str | Path) -> list[KeptFile]:
    """Return kept files (path, size, language) under ``root``, sorted by path.

    Symlinked files and directories are skipped (os.walk does not follow
    links; symlink files fail keep_file), denied directories are pruned,
    and only allow-listed source files plus READMEs survive the deny rules.
    """
    root = Path(root)
    kept: list[KeptFile] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in DENY_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fname in filenames:
            path = Path(dirpath) / fname
            if keep_file(path, root):
                kept.append(KeptFile(path=path, size=path.stat().st_size,
                                     language=("Markdown" if _is_readme(fname)
                                               else LANGUAGE_BY_EXT[path.suffix.lower()])))
    kept.sort(key=lambda k: str(k.path))
    return kept
