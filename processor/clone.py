"""Safe repository cloning (DESIGN.md section 5, Step 3.1).

Clones into settings.repo_cache_dir (/tmp/repo_cache on Linux; on Windows it
lands on the current drive, see PROGRESS.md Open questions). Every repository
is treated as HOSTILE: shallow clone only, no credential prompts, no LFS
smudge filters, no hooks, symlinks checked out as plain files, directory name
sanitized against path traversal, `.git` wiped immediately after cloning, and
nothing here ever reads, imports, or executes cloned content.
"""
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from shared.config import settings

CLONE_TIMEOUT_SEC = 300


class CloneError(RuntimeError):
    """Raised when a repository could not be cloned safely."""


def _rmtree_force(path: Path) -> None:
    """rmtree that copes with Windows: git writes objects read-only (0444)."""
    if not path.exists():
        return

    def onexc(func, p, exc):
        if isinstance(exc, PermissionError):
            os.chmod(p, stat.S_IWRITE)
            func(p)
        elif not isinstance(exc, FileNotFoundError):
            raise exc

    shutil.rmtree(path, onexc=onexc)


def sanitize_dir_name(name: str) -> str:
    """Turn a repo name (e.g. 'owner/repo') into a single safe directory name.

    Any character outside [A-Za-z0-9._-] becomes '_', which removes '/',
    '..', backslashes and control characters that could escape the cache root.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe or "repo"


def clone_repo(url: str, name: str, *, dest_root: Path | None = None,
               timeout: int = CLONE_TIMEOUT_SEC) -> Path:
    """Shallow-clone ``url`` into ``repo_cache_dir/<sanitized name>``.

    Returns the clone directory. A pre-existing directory for the same repo
    is replaced. Raises CloneError on timeout or git failure.
    """
    root = Path(dest_root or settings.repo_cache_dir).resolve()
    dest = root / sanitize_dir_name(name)
    if root not in dest.parents:  # paranoia: sanitized name must stay a direct child
        raise CloneError(f"refusing to clone outside cache root: {name!r}")
    cleanup(dest)
    root.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"    # never open a username/password prompt
    env["GIT_LFS_SKIP_SMUDGE"] = "1"    # never run the LFS filter binary on fetch
    cmd = [
        "git",
        "-c", "core.hooksPath=/dev/null",   # no hooks, wherever they come from
        "-c", "core.symlinks=false",        # symlinks land as plain files, never followed
        "clone", "--depth", "1", "--no-local",
        url, str(dest),
    ]
    try:
        proc = subprocess.run(cmd, env=env, timeout=timeout,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        cleanup(dest)
        raise CloneError(f"clone of {name!r} timed out after {timeout}s")
    if proc.returncode != 0:
        cleanup(dest)
        raise CloneError(
            f"clone of {name!r} failed: {(proc.stderr.strip().splitlines() or ['unknown git error'])[-1]}"
        )

    wipe_git(dest)
    return dest


def wipe_git(path: Path) -> None:
    """Delete a clone's .git directory (design: history is wiped immediately)."""
    git_dir = path / ".git"
    if git_dir.is_dir():
        _rmtree_force(git_dir)
    if git_dir.exists():
        raise CloneError(f"could not wipe {git_dir}; refusing to keep the clone")
    # .git gone => no refs, config, hooks or templates can be executed later.


def cleanup(path: Path | str) -> None:
    """Remove a cached clone directory tree; missing paths are a no-op.

    shutil.rmtree unlinks symlinks instead of following them, so a hostile
    repo's symlinks can never make this delete anything outside ``path``.
    """
    try:
        _rmtree_force(Path(path))
    except OSError:  # best-effort: callers that care re-check existence
        pass
