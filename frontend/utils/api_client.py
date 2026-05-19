"""
api_client.py
-------------
All HTTP calls from the Streamlit frontend to the FastAPI backend.

Keeps every requests.* call in one place — components never import
requests directly. Handles errors, timeouts, and response parsing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from requests.exceptions import (
    ConnectionError,
    Timeout,
    RequestException,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Config                                                               #
# ------------------------------------------------------------------ #

# Read from environment; default to local dev backend
API_BASE_URL: str = os.getenv(
    "API_BASE_URL", "http://localhost:8000/api/v1"
).rstrip("/")

# Timeouts (seconds)
HEALTH_TIMEOUT   = 5
ANALYSE_TIMEOUT  = 300   # analysis can take ~60-120s for large repos
HISTORY_TIMEOUT  = 10


# ------------------------------------------------------------------ #
# Response wrappers                                                    #
# ------------------------------------------------------------------ #

@dataclass
class APIResponse:
    """Uniform response wrapper — components always receive this shape."""
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    status_code: int = 200


# ------------------------------------------------------------------ #
# Client                                                               #
# ------------------------------------------------------------------ #

class Repo2ArchClient:
    """
    Thin HTTP client for the Repo2Arch FastAPI backend.

    Usage:
        client = get_client()
        result = client.analyse("https://github.com/user/repo")
    """

    def __init__(self, base_url: str = API_BASE_URL) -> None:
        self.base_url = base_url
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept":       "application/json",
        })

    # ---------------------------------------------------------------- #
    # Endpoints                                                          #
    # ---------------------------------------------------------------- #

    def health(self) -> APIResponse:
        """
        GET /health
        Returns backend status + Supabase / HF connectivity flags.
        """
        return self._get("/health", timeout=HEALTH_TIMEOUT)

    def analyse(self, github_url: str) -> APIResponse:
        """
        POST /analyse-repo
        Triggers the full analysis pipeline for a GitHub URL.
        Long-running — uses a 5-minute timeout.
        """
        return self._post(
            "/analyse-repo",
            payload={"github_url": github_url},
            timeout=ANALYSE_TIMEOUT,
        )

    def get_history(self, limit: int = 20) -> APIResponse:
        """
        GET /history?limit=N
        Returns the N most recent analyses from Supabase.
        """
        return self._get(
            "/history",
            params={"limit": limit},
            timeout=HISTORY_TIMEOUT,
        )

    def get_cached(self, owner: str, repo: str) -> APIResponse:
        """
        GET /analysis/{owner}/{repo}
        Fetch a single cached analysis without re-running the pipeline.
        """
        return self._get(
            f"/analysis/{owner}/{repo}",
            timeout=HISTORY_TIMEOUT,
        )

    # ---------------------------------------------------------------- #
    # Internal HTTP helpers                                              #
    # ---------------------------------------------------------------- #

    def _get(
        self,
        path: str,
        params: Optional[dict] = None,
        timeout: int = 30,
    ) -> APIResponse:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=timeout)
            return self._parse(resp)
        except Timeout:
            return APIResponse(
                success=False,
                error=f"Request timed out after {timeout}s — backend may be busy.",
                status_code=408,
            )
        except ConnectionError:
            return APIResponse(
                success=False,
                error=(
                    f"Cannot reach backend at {self.base_url}. "
                    "Is the FastAPI server running?"
                ),
                status_code=503,
            )
        except RequestException as exc:
            logger.error("GET %s failed: %s", url, exc)
            return APIResponse(success=False, error=str(exc), status_code=500)

    def _post(
        self,
        path: str,
        payload: dict,
        timeout: int = 60,
    ) -> APIResponse:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.post(url, json=payload, timeout=timeout)
            return self._parse(resp)
        except Timeout:
            return APIResponse(
                success=False,
                error=(
                    f"Analysis timed out after {timeout}s. "
                    "The repository may be too large. Try a smaller repo."
                ),
                status_code=408,
            )
        except ConnectionError:
            return APIResponse(
                success=False,
                error=(
                    f"Cannot reach backend at {self.base_url}. "
                    "Is the FastAPI server running?"
                ),
                status_code=503,
            )
        except RequestException as exc:
            logger.error("POST %s failed: %s", url, exc)
            return APIResponse(success=False, error=str(exc), status_code=500)

    @staticmethod
    def _parse(resp: requests.Response) -> APIResponse:
        """
        Convert a requests.Response into a uniform APIResponse.
        Handles non-JSON responses gracefully.
        """
        try:
            data = resp.json()
        except ValueError:
            # Server returned non-JSON (nginx error page, etc.)
            return APIResponse(
                success=False,
                error=f"Backend returned non-JSON response (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )

        if resp.status_code >= 400:
            error_msg = (
                data.get("detail")
                or data.get("error")
                or f"HTTP {resp.status_code}"
            )
            return APIResponse(
                success=False,
                error=error_msg,
                data=data,
                status_code=resp.status_code,
            )

        return APIResponse(
            success=data.get("success", True),
            data=data,
            error=data.get("error"),
            status_code=resp.status_code,
        )


# ------------------------------------------------------------------ #
# Singleton factory                                                    #
# ------------------------------------------------------------------ #

_client: Optional[Repo2ArchClient] = None


def get_client() -> Repo2ArchClient:
    """
    Return a cached client instance.
    Streamlit re-runs the script on every interaction —
    the singleton avoids re-creating the session each time.
    Uses st.cache_resource when called from Streamlit context.
    """
    global _client
    if _client is None:
        _client = Repo2ArchClient()
    return _client
