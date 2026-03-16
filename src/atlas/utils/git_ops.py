"""Git operations for the autoresearch loop.

Merges josjo80's clean _git() helper with artcompany's autoresearch branch
functions.  All branch operations target **main** (not master).
"""

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level helper
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


# ---------------------------------------------------------------------------
# Basic operations (josjo80)
# ---------------------------------------------------------------------------

def get_repo_root() -> Path:
    return Path(_git(["rev-parse", "--show-toplevel"]).stdout.strip())


def get_current_branch(repo: Path | None = None) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip()


def create_branch(name: str, repo: Path | None = None) -> None:
    _git(["checkout", "-b", name], cwd=repo)


def checkout_branch(name: str, repo: Path | None = None) -> None:
    _git(["checkout", name], cwd=repo)


def delete_branch(name: str, repo: Path | None = None) -> None:
    _git(["branch", "-D", name], cwd=repo)


def commit_file(file_path: Path, message: str, repo: Path | None = None) -> None:
    _git(["add", str(file_path)], cwd=repo)
    _git(["commit", "-m", message], cwd=repo)


# ---------------------------------------------------------------------------
# Autoresearch helpers (artcompany, fixed to use "main")
# ---------------------------------------------------------------------------

def create_autoresearch_branch(agent_name: str, slug: str, repo: Path | None = None) -> str:
    """Create ``autoresearch/<agent>-<slug>`` and check it out."""
    clean = re.sub(r"[^a-z0-9]+", "-", slug.lower())[:40].strip("-")
    branch = f"autoresearch/{agent_name}-{clean}"
    _git(["checkout", "-b", branch], cwd=repo)
    logger.info("Created autoresearch branch: %s", branch)
    return branch


def commit_prompt_modification(agent_name: str, description: str, repo: Path | None = None) -> str:
    """Stage all prompt changes and commit."""
    _git(["add", "-A", "--", "src/atlas/prompts/"], cwd=repo)
    _git(["commit", "-m", f"autoresearch: {agent_name} - {description}"], cwd=repo)
    sha = _git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
    logger.info("Committed prompt modification: %s", sha[:8])
    return sha


def merge_autoresearch_branch(
    feature_branch: str, base_branch: str = "main", repo: Path | None = None
) -> bool:
    try:
        _git(["checkout", base_branch], cwd=repo)
        _git(
            ["merge", "--no-ff", feature_branch, "-m",
             f"merge: {feature_branch} (autoresearch success)"],
            cwd=repo,
        )
        _git(["branch", "-d", feature_branch], cwd=repo)
        logger.info("Merged %s into %s", feature_branch, base_branch)
        return True
    except RuntimeError as exc:
        logger.error("Merge failed: %s", exc)
        return False


def revert_autoresearch_branch(
    feature_branch: str, base_branch: str = "main", repo: Path | None = None
) -> bool:
    try:
        _git(["checkout", base_branch], cwd=repo)
        _git(["branch", "-D", feature_branch], cwd=repo)
        logger.info("Reverted (deleted) %s", feature_branch)
        return True
    except RuntimeError as exc:
        logger.error("Revert failed: %s", exc)
        return False


def get_prompt_history(agent_name: str, n: int = 10, repo: Path | None = None) -> list[dict]:
    """Return last *n* commits that touched an agent's prompt."""
    result = _git(
        ["log", f"-{n}", "--oneline", "--follow", "--",
         f"src/atlas/prompts/layer1/{agent_name}.md",
         f"src/atlas/prompts/layer2/{agent_name}.md",
         f"src/atlas/prompts/layer3/{agent_name}.md",
         f"src/atlas/prompts/layer4/{agent_name}.md"],
        cwd=repo,
    )
    commits = []
    for line in result.stdout.strip().splitlines():
        if line:
            parts = line.split(" ", 1)
            commits.append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})
    return commits
