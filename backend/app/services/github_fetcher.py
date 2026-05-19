"""
github_fetcher.py
-----------------
Clones a public GitHub repo locally, traverses its file tree,
and returns structured file metadata for downstream analysis.

Uses GitPython for cloning. Respects IGNORED_DIRS and
SUPPORTED_EXTENSIONS from config. Auto-cleans stale clones.
"""

from __future__ import annotations

import os
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import git
from git.exc import GitCommandError, InvalidGitRepositoryError

from app.config import settings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Data classes                                                         #
# ------------------------------------------------------------------ #

@dataclass
class FileEntry:
    """Metadata + content for a single repository file."""
    path: str               # relative path from repo root
    abs_path: str           # absolute path on disk
    extension: str          # e.g. ".py"
    size_bytes: int
    content: str = ""       # raw text content (empty if too large)
    language: str = ""      # detected from extension


@dataclass
class RepoTree:
    """Complete picture of a cloned repository."""
    repo_url: str
    repo_name: str
    local_path: str
    files: list[FileEntry] = field(default_factory=list)
    folder_structure: list[str] = field(default_factory=list)   # relative dir paths
    total_files: int = 0
    analysed_files: int = 0


# ------------------------------------------------------------------ #
# Extension → language map                                            #
# ------------------------------------------------------------------ #

EXT_LANGUAGE_MAP: dict[str, str] = {
    ".py":    "Python",
    ".js":    "JavaScript",
    ".ts":    "TypeScript",
    ".tsx":   "TypeScript",
    ".jsx":   "JavaScript",
    ".json":  "JSON",
    ".toml":  "TOML",
    ".yaml":  "YAML",
    ".yml":   "YAML",
    ".md":    "Markdown",
    ".txt":   "Text",
    ".cfg":   "Config",
    ".ini":   "Config",
}


# ------------------------------------------------------------------ #
# Main fetcher class                                                   #
# ------------------------------------------------------------------ #

class GitHubFetcher:
    """
    Handles cloning and traversal of a public GitHub repository.

    Usage:
        fetcher = GitHubFetcher()
        tree = fetcher.fetch("https://github.com/user/repo")
        fetcher.cleanup(tree.local_path)   # call after analysis
    """

    def __init__(self) -> None:
        self.clone_base = Path(settings.REPO_CLONE_DIR)
        self.ignored_dirs = set(settings.IGNORED_DIRS)
        self.supported_exts = set(settings.SUPPORTED_EXTENSIONS)
        self.max_file_size = settings.MAX_FILE_SIZE_BYTES

    # ---------------------------------------------------------------- #
    # Public API                                                         #
    # ---------------------------------------------------------------- #

    def fetch(self, github_url: str) -> RepoTree:
        """
        Clone the repo and return a populated RepoTree.
        Raises ValueError on bad URL, RuntimeError on clone failure.
        """
        repo_name = self._parse_repo_name(github_url)
        local_path = self.clone_base / repo_name

        logger.info("Fetching repo: %s → %s", github_url, local_path)

        # Remove stale clone if it exists
        if local_path.exists():
            logger.debug("Removing stale clone at %s", local_path)
            shutil.rmtree(local_path, ignore_errors=True)

        self._clone(github_url, local_path)

        tree = RepoTree(
            repo_url=github_url,
            repo_name=repo_name,
            local_path=str(local_path),
        )

        self._traverse(local_path, tree)

        logger.info(
            "Fetched %s: %d total files, %d analysed",
            repo_name,
            tree.total_files,
            tree.analysed_files,
        )
        return tree

    def cleanup(self, local_path: str) -> None:
        path = Path(local_path)
        if path.exists():
            self._force_remove(path)
            logger.debug("Cleaned up clone: %s", local_path)

    # ---------------------------------------------------------------- #
    # Internal helpers                                                   #
    # ---------------------------------------------------------------- #

    def _parse_repo_name(self, url: str) -> str:
        """
        Extract 'owner__repo' from a GitHub URL.
        e.g. https://github.com/tiangolo/fastapi → tiangolo__fastapi
        """
        url = url.strip().rstrip("/")
        parts = url.replace("https://github.com/", "").split("/")
        if len(parts) < 2:
            raise ValueError(f"Cannot parse repo name from URL: {url}")
        # Use double underscore so the folder name is unambiguous
        return f"{parts[0]}__{parts[1]}"

    def _clone(self, url: str, dest: Path) -> None:
        """Shallow clone (depth=1) for speed."""
        # Force remove if exists — handles Windows permission errors
        if dest.exists():
            self._force_remove(dest)

        try:
            git.Repo.clone_from(url, str(dest), depth=1)
        except GitCommandError as exc:
            raise RuntimeError(f"Git clone failed for {url}: {exc}") from exc

    @staticmethod
    def _force_remove(path: Path) -> None:
        """Windows-safe recursive delete — handles read-only .git files."""
        import stat
        def _on_error(func, path, exc):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(path, onerror=_on_error)

    def _traverse(self, root: Path, tree: RepoTree) -> None:
        """
        Walk the repo directory tree, populate tree.files and
        tree.folder_structure. Skips ignored dirs and oversized files.
        """
        root_str = str(root)

        for dirpath, dirnames, filenames in os.walk(root_str):
            # Prune ignored directories in-place so os.walk skips them
            dirnames[:] = [
                d for d in dirnames
                if d not in self.ignored_dirs and not d.startswith(".")
            ]

            # Record folder structure (relative paths only)
            rel_dir = os.path.relpath(dirpath, root_str)
            if rel_dir != ".":
                tree.folder_structure.append(rel_dir)

            for filename in filenames:
                abs_path = os.path.join(dirpath, filename)
                ext = Path(filename).suffix.lower()
                tree.total_files += 1

                # Skip unsupported extensions
                if ext not in self.supported_exts:
                    continue

                file_size = self._safe_file_size(abs_path)

                entry = FileEntry(
                    path=os.path.relpath(abs_path, root_str),
                    abs_path=abs_path,
                    extension=ext,
                    size_bytes=file_size,
                    language=EXT_LANGUAGE_MAP.get(ext, "Unknown"),
                )

                # Read content only for files within size limit
                if file_size <= self.max_file_size:
                    entry.content = self._safe_read(abs_path)
                else:
                    logger.debug("Skipping large file: %s (%d bytes)", abs_path, file_size)

                tree.files.append(entry)
                tree.analysed_files += 1

    @staticmethod
    def _safe_file_size(path: str) -> int:
        """Return file size in bytes; 0 on any OS error."""
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    @staticmethod
    def _safe_read(path: str) -> str:
        """
        Read file as UTF-8 text.
        Falls back to latin-1 if UTF-8 decoding fails.
        Returns empty string on any other error.
        """
        for encoding in ("utf-8", "latin-1"):
            try:
                with open(path, "r", encoding=encoding) as fh:
                    return fh.read()
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                logger.warning("Cannot read %s: %s", path, exc)
                return ""
        return ""


# ------------------------------------------------------------------ #
# Module-level convenience function                                    #
# ------------------------------------------------------------------ #

def fetch_repo(github_url: str) -> RepoTree:
    """
    Thin wrapper — instantiates GitHubFetcher and calls fetch().
    Import this in services/routes for a one-liner call.
    """
    return GitHubFetcher().fetch(github_url)
