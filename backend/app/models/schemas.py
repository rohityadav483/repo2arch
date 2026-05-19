"""
schemas.py
----------
All Pydantic models for request validation and response serialisation.
Import from here — never define schemas inline in routes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, HttpUrl, Field, validator


# ------------------------------------------------------------------ #
# Request models                                                       #
# ------------------------------------------------------------------ #

class AnalyseRepoRequest(BaseModel):
    """POST /analyse-repo — user submits a GitHub URL."""

    github_url: str = Field(
        ...,
        description="Full HTTPS URL of a public GitHub repository.",
        example="https://github.com/tiangolo/fastapi",
    )

    @validator("github_url")
    def must_be_github(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if "github.com" not in v:
            raise ValueError("URL must point to github.com")
        if not v.startswith("https://"):
            raise ValueError("URL must use HTTPS")
        return v


# ------------------------------------------------------------------ #
# Sub-models (nested inside the main response)                        #
# ------------------------------------------------------------------ #

class TechStackInfo(BaseModel):
    """Languages, frameworks and key dependencies detected."""

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)


class ComponentNode(BaseModel):
    """Single node in the dependency / component graph."""

    id: str
    label: str
    node_type: str = Field(
        description="One of: module, service, external, entrypoint, config"
    )
    language: Optional[str] = None
    imports: list[str] = Field(default_factory=list)


class ComponentEdge(BaseModel):
    """Directed edge between two component nodes."""

    source: str
    target: str
    relation: str = Field(
        default="imports",
        description="Relationship type: imports | calls | extends | uses",
    )


class GraphData(BaseModel):
    """NetworkX graph serialised to nodes + edges for the frontend."""

    nodes: list[ComponentNode] = Field(default_factory=list)
    edges: list[ComponentEdge] = Field(default_factory=list)


class RepoInsights(BaseModel):
    """High-level stats about the repository."""

    total_files: int = 0
    analysed_files: int = 0
    total_lines: int = 0
    entry_points: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    has_tests: bool = False
    has_ci: bool = False
    has_docker: bool = False


# ------------------------------------------------------------------ #
# Main response model                                                  #
# ------------------------------------------------------------------ #

class AnalyseRepoResponse(BaseModel):
    """
    Full analysis result returned to the Streamlit frontend.
    Every field has a safe default so partial failures don't 500.
    """

    # Identifiers
    repo_url: str
    repo_name: str
    analysed_at: datetime = Field(default_factory=datetime.utcnow)

    # Core outputs
    mermaid_diagram: str = Field(
        default="",
        description="Ready-to-render Mermaid graph TD source string.",
    )
    graph_data: GraphData = Field(default_factory=GraphData)
    tech_stack: TechStackInfo = Field(default_factory=TechStackInfo)
    insights: RepoInsights = Field(default_factory=RepoInsights)

    # AI-generated text
    ai_summary: str = Field(
        default="",
        description="Architecture summary from Hugging Face Inference API.",
    )
    ai_improvements: str = Field(
        default="",
        description="Scalability and improvement suggestions from the AI.",
    )

    # Status
    success: bool = True
    error: Optional[str] = None


# ------------------------------------------------------------------ #
# History / Supabase models                                           #
# ------------------------------------------------------------------ #

class AnalysisRecord(BaseModel):
    """Row shape stored in / retrieved from Supabase."""

    id: Optional[str] = None
    repo_url: str
    repo_name: str
    analysed_at: datetime
    mermaid_diagram: str
    tech_stack: dict[str, Any]
    ai_summary: str
    insights: dict[str, Any]


class HistoryResponse(BaseModel):
    """GET /history response — list of past analyses."""

    records: list[AnalysisRecord] = Field(default_factory=list)
    total: int = 0


# ------------------------------------------------------------------ #
# Health check                                                         #
# ------------------------------------------------------------------ #

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    supabase_connected: bool
    hf_configured: bool
