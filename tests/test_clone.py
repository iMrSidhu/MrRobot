"""Tests for processor.clone (DESIGN.md Step 3.1) — local repos only, no network."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor import clone as clone_mod
from processor.clone import CloneError, cleanup, clone_repo, sanitize_dir_name


def run_git(*args, cwd):
    proc = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test", *args],
        cwd=str(cwd), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


def make_source_repo(tmp_path, *, hook_marker: Path | None = None,
                     extra: dict[str, str] | None = None) -> Path:
    src = tmp_path / "source"
    src.mkdir()
    run_git("init", cwd=src)
    (src / "README.md").write_text("# rover\n")
    (src / "main.py").write_text("print('hi')\n")
    for rel, text in (extra or {}).items():
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    run_git("add", ".", cwd=src)
    run_git("commit", "-m", "init", cwd=src)
    if hook_marker is not None:
        hook = src / ".git" / "hooks" / "post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch '{hook_marker.as_posix()}'\n")
        os.chmod(hook, 0o755)
    return src


def test_sanitize_dir_name():
    assert sanitize_dir_name("owner/repo") == "owner_repo"
    assert sanitize_dir_name("../../evil") == "evil"
    assert sanitize_dir_name("..\\..\\evil") == "evil"
    assert sanitize_dir_name("a b\tc") == "a_b_c"
    assert sanitize_dir_name("...") == "repo"


def test_clone_files_present_and_git_wiped(tmp_path):
    src = make_source_repo(tmp_path)
    dest = clone_repo(str(src), "acme/rover", dest_root=tmp_path / "cache")
    assert dest == (tmp_path / "cache").resolve() / "acme_rover"
    assert (dest / "README.md").read_text() == "# rover\n"
    assert not (dest / ".git").exists()          # acceptance: .git is gone
    assert not (dest / ".git").is_symlink()


def test_existing_cache_dir_is_replaced(tmp_path):
    src = make_source_repo(tmp_path)
    cache = tmp_path / "cache"
    stale = cache / "acme_rover"
    stale.mkdir(parents=True)
    (stale / "stale.txt").write_text("old")
    dest = clone_repo(str(src), "acme/rover", dest_root=cache)
    assert not (dest / "stale.txt").exists()
    assert (dest / "main.py").exists()


def test_traversal_name_stays_inside_root(tmp_path):
    src = make_source_repo(tmp_path)
    root = tmp_path / "cache"
    dest = clone_repo(str(src), "../../../../etc/passwd", dest_root=root)
    assert dest.parent == root.resolve()
    assert (dest / "README.md").exists()


def test_malicious_hook_does_not_run(tmp_path):
    marker = tmp_path / "pwned"
    src = make_source_repo(tmp_path, hook_marker=marker)
    dest = clone_repo(str(src), "evil/repo", dest_root=tmp_path / "cache")
    assert not marker.exists()                  # acceptance: hook never executed
    assert not (dest / ".git").exists()         # and no hooks survive in the clone


def test_failure_and_timeout_leave_no_partial_dir(tmp_path, monkeypatch):
    def patched_run(cmd, **kwargs):
        dest = Path(cmd[-1])                      # simulate a partial checkout
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".git").mkdir(exist_ok=True)
        if patched_run.mode == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        return subprocess.CompletedProcess(cmd, 1, "", "fatal: repository not found")

    patched_run.mode = "fail"
    monkeypatch.setattr(clone_mod.subprocess, "run", patched_run)
    cache = tmp_path / "cache"
    with pytest.raises(CloneError, match="repository not found"):
        clone_repo("https://example.invalid/x.git", "bad/repo", dest_root=cache)
    assert not (cache / "bad_repo").exists()

    patched_run.mode = "timeout"
    with pytest.raises(CloneError, match="timed out"):
        clone_repo("https://example.invalid/x.git", "slow/repo", dest_root=cache, timeout=7)
    assert not (cache / "slow_repo").exists()


def test_hostile_defaults_on_the_command_line(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        dest = Path(cmd[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("ok")
        (dest / ".git").mkdir()                  # git would leave this behind
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(clone_mod.subprocess, "run", fake_run)
    dest = clone_repo("https://example.invalid/x.git", "some/repo",
                      dest_root=tmp_path / "cache", timeout=42)
    cmd, kwargs = calls[0]
    joined = " ".join(cmd)
    assert "--depth 1" in joined
    assert "--no-local" in joined
    assert "core.hooksPath=/dev/null" in joined
    assert "core.symlinks=false" in joined
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kwargs["env"]["GIT_LFS_SKIP_SMUDGE"] == "1"
    assert kwargs["timeout"] == 42
    assert not (dest / ".git").exists()          # wiped right after clone


def test_cleanup_removes_tree_and_ignores_missing(tmp_path):
    target = tmp_path / "gone"
    (target / "sub").mkdir(parents=True)
    (target / "sub" / "f.txt").write_text("x")
    cleanup(target)
    assert not target.exists()
    cleanup(target)                              # no error on missing path

def test_local_directory_url_is_copied_not_cloned(tmp_path):
    src = tmp_path / 'tree'
    (src / 'pkg').mkdir(parents=True)
    (src / 'pkg' / 'main.py').write_text('print(1)', encoding='utf-8')
    (src / '.git').mkdir()
    (src / '.git' / 'config').write_text('gitdata', encoding='utf-8')

    dest = clone_repo(str(src), 'local/colibri', dest_root=tmp_path / 'cache')

    assert (dest / 'pkg' / 'main.py').read_text(encoding='utf-8') == 'print(1)'
    assert not (dest / '.git').exists()                       # git metadata never enters cache
    assert (src / '.git' / 'config').exists()                 # source untouched
    cleanup(dest)
    assert src.exists() and dest.exists() is False
