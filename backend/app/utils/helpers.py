"""
helpers.py
----------
Shared utility functions used across the backend.
No business logic here — pure, stateless, easily testable helpers.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ------------------------------------------------------------------ #
# URL helpers                                                          #
# ------------------------------------------------------------------ #

def normalise_github_url(url: str) -> str:
    """
    Strip trailing slashes, .git suffix, and query strings.
    https://github.com/user/repo.git?foo=bar → https://github.com/user/repo
    """
    url = url.strip().rstrip("/")
    url = re.sub(r"\.git$", "", url)
    url = re.sub(r"\?.*$", "", url)
    return url


def extract_owner_repo(url: str) -> tuple[str, str]:
    """
    Return (owner, repo_name) from a GitHub URL.
    Raises ValueError if the URL doesn't look like a valid repo URL.
    """
    url = normalise_github_url(url)
    match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
    if not match:
        raise ValueError(f"Cannot extract owner/repo from: {url}")
    return match.group(1), match.group(2)


def repo_cache_key(url: str) -> str:
    """
    Short deterministic key for a repo URL — used for cache lookups
    and temp directory naming.
    e.g. "tiangolo/fastapi" → "tiangolo__fastapi"
    """
    owner, repo = extract_owner_repo(url)
    return f"{owner}__{repo}"


# ------------------------------------------------------------------ #
# Text / string helpers                                                #
# ------------------------------------------------------------------ #

def truncate(text: str, max_chars: int = 500, ellipsis: str = "…") -> str:
    """Truncate text to max_chars, appending ellipsis if cut."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + ellipsis


def slugify(text: str) -> str:
    """
    Convert arbitrary text to a URL/filename-safe slug.
    "My Repo Name!" → "my-repo-name"
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def md_escape(text: str) -> str:
    """Escape special Markdown characters in a plain-text string."""
    special = r"\`*_{}[]<>()#+-.!|"
    return "".join(f"\\{c}" if c in special else c for c in text)


# ------------------------------------------------------------------ #
# Data helpers                                                         #
# ------------------------------------------------------------------ #

def deep_get(obj: dict, *keys: str, default: Any = None) -> Any:
    """
    Safely traverse nested dicts.
    deep_get(data, "a", "b", "c") == data.get("a", {}).get("b", {}).get("c")
    """
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
    return obj


def flatten_list(nested: list[list[Any]]) -> list[Any]:
    """Flatten one level of nesting: [[1,2],[3]] → [1,2,3]."""
    return [item for sublist in nested for item in sublist]


def dedupe_preserve_order(items: list[Any]) -> list[Any]:
    """Remove duplicates while preserving insertion order."""
    seen: set = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def safe_json_serialise(obj: Any) -> Any:
    """
    Recursively convert an object to a JSON-serialisable form.
    Converts sets → sorted lists, Paths → strings, unknowns → str().
    Used before passing data to Supabase JSONB columns.
    """
    if isinstance(obj, dict):
        return {k: safe_json_serialise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json_serialise(i) for i in obj]
    if isinstance(obj, set):
        return sorted(safe_json_serialise(i) for i in obj)
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return safe_json_serialise(obj.__dict__)
    # Primitives: str, int, float, bool, None
    try:
        import json
        json.dumps(obj)     # probe — raises TypeError if not serialisable
        return obj
    except (TypeError, ValueError):
        return str(obj)


# ------------------------------------------------------------------ #
# Hashing                                                              #
# ------------------------------------------------------------------ #

def sha256_short(text: str, length: int = 8) -> str:
    """Return the first `length` hex chars of the SHA-256 of text."""
    return hashlib.sha256(text.encode()).hexdigest()[:length]


# ------------------------------------------------------------------ #
# Timing decorator                                                     #
# ------------------------------------------------------------------ #

def timed(label: str = "") -> Callable[[F], F]:
    """
    Decorator that logs wall-clock execution time.

    @timed("GitHub fetch")
    def fetch_repo(...): ...
    """
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tag = label or fn.__name__
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                elapsed = time.perf_counter() - start
                logger.info("[%s] completed in %.2fs", tag, elapsed)
                return result
            except Exception as exc:
                elapsed = time.perf_counter() - start
                logger.error("[%s] FAILED after %.2fs — %s", tag, elapsed, exc)
                raise
        return wrapper  # type: ignore[return-value]
    return decorator


# ------------------------------------------------------------------ #
# Retry decorator                                                      #
# ------------------------------------------------------------------ #

def retry(
    max_attempts: int = 3,
    delay_seconds: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Simple retry decorator with fixed delay.

    @retry(max_attempts=3, delay_seconds=2, exceptions=(RuntimeError,))
    def clone_repo(...): ...
    """
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception = RuntimeError("No attempts made")
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "Retry %d/%d for %s — %s",
                            attempt, max_attempts, fn.__name__, exc,
                        )
                        time.sleep(delay_seconds)
            raise last_exc
        return wrapper  # type: ignore[return-value]
    return decorator


# ------------------------------------------------------------------ #
# File helpers                                                         #
# ------------------------------------------------------------------ #

def format_bytes(num_bytes: int) -> str:
    """Human-readable file size: 1_500_000 → '1.4 MB'."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes //= 1024
    return f"{num_bytes:.1f} TB"


def is_binary_file(path: str) -> bool:
    """
    Quick heuristic: read first 1024 bytes and check for null bytes.
    Avoids trying to decode images/compiled files as text.
    """
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(1024)
        return b"\x00" in chunk
    except OSError:
        return False
