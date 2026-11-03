"""Tests for processor.filter (DESIGN.md Step 3.2) — synthetic trees only."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.filter import MAX_FILE_SIZE, KeptFile, filter_repo


def touch(root: Path, rel: str, data: bytes = b"print('x')\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def languages_by_name(kept):
    return {p.path.name: p.language for p in kept}


def test_keeps_source_and_readme(repo):
    touch(repo, "README.md", b"# hello\n")
    touch(repo, "main.py", b"import os\n")
    touch(repo, "src/app.ts", b"let x = 1;\n")
    names = languages_by_name(filter_repo(repo))
    assert names == {"README.md": "Markdown", "main.py": "Python", "app.ts": "TypeScript"}
    assert all(isinstance(k, KeptFile) and k.size > 0 for k in filter_repo(repo))


def test_drops_directories_in_deny_list(repo):
    touch(repo, "README.md")
    for bad in ["node_modules/pkg/index.js", "vendor/lib.php", "tests/test_x.py",
                "src/tests/test_y.py", "dist/bundle.js"]:
        touch(repo, bad)
    names = {p.path.name for p in filter_repo(repo)}
    assert names == {"README.md"}  # everything under a denied dir is dropped


def test_drops_lockfiles(repo):
    touch(repo, "requirements.txt")
    touch(repo, "package-lock.json", b"{}")
    touch(repo, "Cargo.lock", b"")
    touch(repo, "src/poetry.lock", b"")
    names = {p.path.name for p in filter_repo(repo)}
    assert names == set()  # .txt is not a source ext; all three locks dropped


def test_lockfile_allowed_if_in_source_ext_but_named_lock(repo):
    # a .py file is fine; only lock *names* are denied
    touch(repo, "not_a_lock.py", b"x=1\n")
    assert {p.path.name for p in filter_repo(repo)} == {"not_a_lock.py"}


def test_drops_images_and_binaries(repo):
    touch(repo, "logo.png", b"\x89PNG")
    touch(repo, "clip.mp4", b"...")
    touch(repo, "lib.so", b"\x7fELF")
    touch(repo, "keep.go", b"package main\n")
    names = {p.path.name for p in filter_repo(repo)}
    assert names == {"keep.go"}


def test_drops_minified_files(repo):
    touch(repo, "app.min.js", b"a=1")
    touch(repo, "styles.min.css", b"a{}")
    touch(repo, "real.js", b"a=1")
    names = {p.path.name for p in filter_repo(repo)}
    assert names == {"real.js"}


def test_drops_files_over_size_limit(repo):
    touch(repo, "big.py", b"x" * (MAX_FILE_SIZE + 1))
    touch(repo, "ok.py", b"y = 1\n")
    names = {p.path.name for p in filter_repo(repo)}
    assert names == {"ok.py"}


def test_drops_binary_content_by_extension(repo):
    # .py with a NUL byte is rejected as binary
    touch(repo, "not_text.py", b"\x00\x01binary")
    touch(repo, "real.py", b"x = 1\n")
    names = {p.path.name for p in filter_repo(repo)}
    assert names == {"real.py"}


def test_skips_symlinks(repo):
    real = touch(repo, "src/real.py", b"x = 1\n")
    link = repo / "src" / "link.py"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform/session")
    names = {p.path.name for p in filter_repo(repo)}
    assert names == {"real.py"}


def test_paths_are_absolute_and_sorted(repo):
    touch(repo, "b.py")
    touch(repo, "a.py")
    kept = filter_repo(repo)
    assert [p.path.name for p in kept] == ["a.py", "b.py"]
    assert all(p.path.is_absolute() for p in kept)
