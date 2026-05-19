"""
supabase_client.py
------------------
All Supabase read/write operations for Repo2Arch.

Tables expected in your Supabase project:
  analyses  — one row per repo analysis
  diagrams  — one row per Mermaid diagram (linked to analyses)

Run the SQL in the docstring below in your Supabase SQL editor
to create both tables before first use.

    CREATE TABLE analyses (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        repo_url      TEXT NOT NULL,
        repo_name     TEXT NOT NULL,
        analysed_at   TIMESTAMPTZ DEFAULT now(),
        tech_stack    JSONB,
        insights      JSONB,
        ai_summary    TEXT,
        ai_improvements TEXT,
        readme_overview TEXT,
        model_used    TEXT
    );

    CREATE TABLE diagrams (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        analysis_id     UUID REFERENCES analyses(id) ON DELETE CASCADE,
        repo_url        TEXT NOT NULL,
        architecture    TEXT,
        dependency      TEXT,
        graph_data      JSONB,
        created_at      TIMESTAMPTZ DEFAULT now()
    );

    CREATE INDEX idx_analyses_repo_url ON analyses(repo_url);
    CREATE INDEX idx_analyses_analysed_at ON analyses(analysed_at DESC);
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Any

from supabase import create_client, Client
from postgrest.exceptions import APIError

from app.config import settings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Supabase client singleton                                           #
# ------------------------------------------------------------------ #

_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    """Return a cached Supabase client. Thread-safe at module level."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_KEY,
        )
        logger.debug("Supabase client initialised: %s", settings.SUPABASE_URL)
    return _supabase_client


# ------------------------------------------------------------------ #
# Repository operations                                               #
# ------------------------------------------------------------------ #

class SupabaseRepository:
    """
    High-level data access layer for Repo2Arch.
    All methods return plain dicts / lists — no Supabase types leak out.
    """

    def __init__(self) -> None:
        self.db = get_supabase()
        self.analyses_table = settings.SUPABASE_TABLE_ANALYSES
        self.diagrams_table = settings.SUPABASE_TABLE_DIAGRAMS

    # ---------------------------------------------------------------- #
    # Write operations                                                  #
    # ---------------------------------------------------------------- #

    def save_analysis(
        self,
        *,
        repo_url: str,
        repo_name: str,
        tech_stack: dict,
        insights: dict,
        ai_summary: str,
        ai_improvements: str,
        readme_overview: str,
        model_used: str,
    ) -> Optional[str]:
        """
        Insert a new analysis record.
        Returns the generated UUID on success, None on failure.
        """
        payload = {
            "repo_url":         repo_url,
            "repo_name":        repo_name,
            "tech_stack":       tech_stack,
            "insights":         insights,
            "ai_summary":       ai_summary,
            "ai_improvements":  ai_improvements,
            "readme_overview":  readme_overview,
            "model_used":       model_used,
        }

        try:
            response = (
                self.db
                .table(self.analyses_table)
                .insert(payload)
                .execute()
            )
            record_id = response.data[0]["id"] if response.data else None
            logger.info("Saved analysis %s → id=%s", repo_name, record_id)
            return record_id

        except APIError as exc:
            logger.error("Supabase insert (analyses) failed: %s", exc)
            return None
        except Exception as exc:
            logger.error("Unexpected error saving analysis: %s", exc)
            return None

    def save_diagram(
        self,
        *,
        analysis_id: str,
        repo_url: str,
        architecture_diagram: str,
        dependency_diagram: str,
        graph_data: dict,
    ) -> Optional[str]:
        """
        Insert a diagram record linked to an analysis.
        Returns the generated UUID on success, None on failure.
        """
        payload = {
            "analysis_id":  analysis_id,
            "repo_url":     repo_url,
            "architecture": architecture_diagram,
            "dependency":   dependency_diagram,
            "graph_data":   graph_data,
        }

        try:
            response = (
                self.db
                .table(self.diagrams_table)
                .insert(payload)
                .execute()
            )
            record_id = response.data[0]["id"] if response.data else None
            logger.info("Saved diagram → id=%s", record_id)
            return record_id

        except APIError as exc:
            logger.error("Supabase insert (diagrams) failed: %s", exc)
            return None
        except Exception as exc:
            logger.error("Unexpected error saving diagram: %s", exc)
            return None

    # ---------------------------------------------------------------- #
    # Read operations                                                    #
    # ---------------------------------------------------------------- #

    def get_analysis_by_url(self, repo_url: str) -> Optional[dict]:
        """
        Fetch the most recent analysis for a given repo URL.
        Returns None if not found.
        """
        try:
            response = (
                self.db
                .table(self.analyses_table)
                .select("*")
                .eq("repo_url", repo_url)
                .order("analysed_at", desc=True)
                .limit(1)
                .execute()
            )
            return response.data[0] if response.data else None

        except APIError as exc:
            logger.error("Supabase select (by_url) failed: %s", exc)
            return None

    def get_diagram_by_analysis(self, analysis_id: str) -> Optional[dict]:
        """Fetch diagram record linked to an analysis UUID."""
        try:
            response = (
                self.db
                .table(self.diagrams_table)
                .select("*")
                .eq("analysis_id", analysis_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return response.data[0] if response.data else None

        except APIError as exc:
            logger.error("Supabase select (diagram) failed: %s", exc)
            return None

    def get_recent_analyses(self, limit: int = 20) -> list[dict]:
        """
        Fetch the N most recent analyses for the history panel.
        Returns an empty list on error — never raises.
        """
        try:
            response = (
                self.db
                .table(self.analyses_table)
                .select(
                    "id, repo_url, repo_name, analysed_at, "
                    "tech_stack, ai_summary, insights"
                )
                .order("analysed_at", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data or []

        except APIError as exc:
            logger.error("Supabase select (recent) failed: %s", exc)
            return []

    # ---------------------------------------------------------------- #
    # Cache helper                                                       #
    # ---------------------------------------------------------------- #

    def is_cached(self, repo_url: str, max_age_hours: int = 6) -> bool:
        """
        Return True if a fresh-enough analysis exists for this URL.
        Avoids re-cloning and re-analysing the same repo repeatedly.
        """
        record = self.get_analysis_by_url(repo_url)
        if not record:
            return False

        try:
            analysed_at_str = record.get("analysed_at", "")
            # Supabase returns ISO 8601 with timezone
            analysed_at = datetime.fromisoformat(
                analysed_at_str.replace("Z", "+00:00")
            )
            from datetime import timezone
            age_hours = (
                datetime.now(tz=timezone.utc) - analysed_at
            ).total_seconds() / 3600
            return age_hours < max_age_hours

        except Exception as exc:
            logger.warning("Cache age check failed: %s", exc)
            return False

    # ---------------------------------------------------------------- #
    # Health check                                                       #
    # ---------------------------------------------------------------- #

    def ping(self) -> bool:
        """
        Lightweight connectivity check used by /health endpoint.
        Returns True if Supabase responds, False otherwise.
        """
        try:
            self.db.table(self.analyses_table).select("id").limit(1).execute()
            return True
        except Exception as exc:
            logger.warning("Supabase ping failed: %s", exc)
            return False


# ------------------------------------------------------------------ #
# Module-level singleton                                              #
# ------------------------------------------------------------------ #

# Import this directly for a zero-boilerplate one-liner:
#   from app.services.supabase_client import db
#   db.save_analysis(...)
db = SupabaseRepository()
