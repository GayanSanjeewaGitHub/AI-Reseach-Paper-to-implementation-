from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def ref_exists(repo: Path, ref: str) -> bool:
    """Check if a git ref (branch, tag, or commit) exists."""
    result = _git(repo, "rev-parse", "--verify", ref, check=False)
    return result.returncode == 0


def create_branch(repo: Path, branch_name: str, start_point: str | None = None) -> None:
    """Create branch_name in repo if it does not already exist."""
    result = _git(repo, "branch", "--list", branch_name)
    if branch_name not in result.stdout:
        args = ["branch", branch_name]
        if start_point:
            args.append(start_point)
        _git(repo, *args)


def create_worktree(repo: Path, worktree_path: Path, branch: str) -> None:
    """Add a git worktree at worktree_path checked out to branch."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(worktree_path), branch)


def remove_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove a git worktree and prune stale worktree entries."""
    _git(repo, "worktree", "remove", str(worktree_path), "--force", check=False)
    _git(repo, "worktree", "prune")


def list_worktrees(repo: Path) -> list[str]:
    """Return a list of worktree paths registered in repo."""
    result = _git(repo, "worktree", "list", "--porcelain")
    worktrees = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            worktrees.append(line[len("worktree "):])
    return worktrees
