"""
routes.py
---------
All FastAPI route handlers for Repo2Arch.

Endpoints:
  GET  /health               — liveness + dependency check
  POST /analyse-repo         — full pipeline (fetch → analyse → AI → store)
  GET  /history              — recent analyses from Supabase
  GET  /analysis/{repo_name} — fetch a single cached analysis
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse

from app.config import settings
from app.models.schemas import (
    AnalyseRepoRequest,
    AnalyseRepoResponse,
    HealthResponse,
    HistoryResponse,
    AnalysisRecord,
    GraphData,
    TechStackInfo,
    RepoInsights,
)
from app.services.github_fetcher import GitHubFetcher
from app.services.code_analyzer import CodeAnalyzer
from app.services.graph_builder import GraphBuilder
from app.services.mermaid_generator import MermaidGenerator
from app.services.ai_summary import AISummaryEngine
from app.services.supabase_client import db
from app.utils.helpers import (
    normalise_github_url,
    safe_json_serialise,
    timed,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ #
# Service singletons (one per worker process)                         #
# ------------------------------------------------------------------ #

_fetcher   = GitHubFetcher()
_analyzer  = CodeAnalyzer()
_builder   = GraphBuilder()
_mermaid   = MermaidGenerator()
_ai_engine = AISummaryEngine()


# ------------------------------------------------------------------ #
# GET /health                                                          #
# ------------------------------------------------------------------ #

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["meta"],
)
async def health_check() -> HealthResponse:
    """
    Returns service status and dependency connectivity.
    Used by load balancers and the Streamlit frontend status badge.
    """
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        supabase_connected=db.ping(),
        hf_configured=bool(settings.HF_API_KEY),
    )


# ------------------------------------------------------------------ #
# POST /analyse-repo                                                   #
# ------------------------------------------------------------------ #

@router.post(
    "/analyse-repo",
    response_model=AnalyseRepoResponse,
    summary="Analyse a GitHub repository",
    tags=["analysis"],
)
async def analyse_repo(
    request: AnalyseRepoRequest,
    background_tasks: BackgroundTasks,
) -> AnalyseRepoResponse:
    """
    Full analysis pipeline:
      1. Normalise + validate GitHub URL
      2. Check Supabase cache (skip re-analysis if fresh)
      3. Clone repo with GitPython
      4. AST + regex code analysis
      5. NetworkX graph building
      6. Mermaid diagram generation
      7. Hugging Face AI summary
      8. Persist to Supabase (background task)
      9. Return full response

    On any internal error returns a partial response with
    success=False and an error message — never raises 500.
    """
    repo_url  = normalise_github_url(request.github_url)
    repo_name = _parse_repo_name(repo_url)

    logger.info("Analysis requested: %s", repo_url)

    # ── Step 1: Cache check ──────────────────────────────────────────
    if db.is_cached(repo_url):
        logger.info("Cache hit for %s — returning stored result", repo_url)
        cached = _load_from_cache(repo_url, repo_name)
        if cached:
            return cached

    # ── Step 2: Clone ────────────────────────────────────────────────
    tree = None
    local_path = None
    try:
        tree = _fetcher.fetch(repo_url)
        local_path = tree.local_path
        logger.info(
            "Cloned %s — %d files (%d analysable)",
            repo_name, tree.total_files, tree.analysed_files,
        )
    except Exception as exc:
        logger.error("Clone failed for %s: %s", repo_url, exc)
        return AnalyseRepoResponse(
            repo_url=repo_url,
            repo_name=repo_name,
            success=False,
            error=f"Failed to clone repository: {exc}",
        )

    # ── Step 3: Analyse ──────────────────────────────────────────────
    try:
        analysis = _analyzer.analyse(tree)
    except Exception as exc:
        logger.error("Analysis failed: %s", exc)
        _cleanup(local_path)
        return AnalyseRepoResponse(
            repo_url=repo_url,
            repo_name=repo_name,
            success=False,
            error=f"Code analysis failed: {exc}",
        )

    # ── Step 4: Graph ────────────────────────────────────────────────
    try:
        bundle = _builder.build(analysis)
    except Exception as exc:
        logger.error("Graph build failed: %s", exc)
        bundle = None

    # ── Step 5: Mermaid ──────────────────────────────────────────────
    architecture_diagram = ""
    dependency_diagram   = ""
    if bundle:
        try:
            diagrams = _mermaid.generate(bundle)
            architecture_diagram = diagrams.architecture_diagram
            dependency_diagram   = diagrams.dependency_diagram
        except Exception as exc:
            logger.error("Mermaid generation failed: %s", exc)

    # ── Step 6: AI summary ───────────────────────────────────────────
    ai_summary      = ""
    ai_improvements = ""
    readme_overview = ""
    model_used      = ""
    try:
        ai_result       = _ai_engine.summarise(repo_name, analysis)
        ai_summary      = ai_result.architecture_summary
        ai_improvements = ai_result.improvement_suggestions
        readme_overview = ai_result.readme_overview
        model_used      = ai_result.model_used
    except Exception as exc:
        logger.error("AI summary failed: %s", exc)

    # ── Step 7: Cleanup clone (background) ───────────────────────────
    background_tasks.add_task(_cleanup, local_path)

    # ── Step 8: Persist (background) ─────────────────────────────────
    graph_data_dict = safe_json_serialise(
        bundle.graph_data.dict() if bundle else {}
    )
    background_tasks.add_task(
        _persist,
        repo_url=repo_url,
        repo_name=repo_name,
        tech_stack=safe_json_serialise(analysis.tech_stack.dict()),
        insights=safe_json_serialise(analysis.insights.dict()),
        ai_summary=ai_summary,
        ai_improvements=ai_improvements,
        readme_overview=readme_overview,
        model_used=model_used,
        architecture_diagram=architecture_diagram,
        dependency_diagram=dependency_diagram,
        graph_data=graph_data_dict,
    )

    # ── Step 9: Return ───────────────────────────────────────────────
    return AnalyseRepoResponse(
        repo_url=repo_url,
        repo_name=repo_name,
        mermaid_diagram=architecture_diagram,
        graph_data=bundle.graph_data if bundle else GraphData(),
        tech_stack=analysis.tech_stack,
        insights=analysis.insights,
        ai_summary=ai_summary,
        ai_improvements=ai_improvements,
        success=True,
    )


# ------------------------------------------------------------------ #
# GET /history                                                         #
# ------------------------------------------------------------------ #

@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Recent analysis history",
    tags=["analysis"],
)
async def get_history(
    limit: int = Query(default=20, ge=1, le=100),
) -> HistoryResponse:
    """Return the N most recent analyses stored in Supabase."""
    records_raw = db.get_recent_analyses(limit=limit)
    records = [_raw_to_record(r) for r in records_raw]
    return HistoryResponse(records=records, total=len(records))


# ------------------------------------------------------------------ #
# GET /analysis/{repo_name}                                           #
# ------------------------------------------------------------------ #

@router.get(
    "/analysis/{owner}/{repo}",
    response_model=AnalyseRepoResponse,
    summary="Fetch a cached analysis",
    tags=["analysis"],
)
async def get_cached_analysis(owner: str, repo: str) -> AnalyseRepoResponse:
    """
    Return the most recent cached analysis for owner/repo.
    Raises 404 if not found in Supabase.
    """
    repo_url = f"https://github.com/{owner}/{repo}"
    result   = _load_from_cache(repo_url, f"{owner}/{repo}")
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached analysis found for {owner}/{repo}",
        )
    return result


# ------------------------------------------------------------------ #
# Private helpers                                                      #
# ------------------------------------------------------------------ #

def _parse_repo_name(url: str) -> str:
    """Extract 'owner/repo' display name from a normalised GitHub URL."""
    parts = url.replace("https://github.com/", "").split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else url


def _cleanup(local_path: str | None) -> None:
    """Delete cloned repo directory; safe to call even if path is None."""
    if local_path:
        _fetcher.cleanup(local_path)


def _persist(
    *,
    repo_url: str,
    repo_name: str,
    tech_stack: dict,
    insights: dict,
    ai_summary: str,
    ai_improvements: str,
    readme_overview: str,
    model_used: str,
    architecture_diagram: str,
    dependency_diagram: str,
    graph_data: dict,
) -> None:
    """Save analysis + diagram to Supabase. Runs in a background task."""
    analysis_id = db.save_analysis(
        repo_url=repo_url,
        repo_name=repo_name,
        tech_stack=tech_stack,
        insights=insights,
        ai_summary=ai_summary,
        ai_improvements=ai_improvements,
        readme_overview=readme_overview,
        model_used=model_used,
    )
    if analysis_id:
        db.save_diagram(
            analysis_id=analysis_id,
            repo_url=repo_url,
            architecture_diagram=architecture_diagram,
            dependency_diagram=dependency_diagram,
            graph_data=graph_data,
        )


def _load_from_cache(repo_url: str, repo_name: str) -> AnalyseRepoResponse | None:
    """Reconstruct an AnalyseRepoResponse from Supabase cache."""
    record = db.get_analysis_by_url(repo_url)
    if not record:
        return None

    diagram_record = db.get_diagram_by_analysis(record.get("id", ""))

    ts_raw = record.get("tech_stack") or {}
    ins_raw = record.get("insights") or {}

    return AnalyseRepoResponse(
        repo_url=repo_url,
        repo_name=repo_name,
        mermaid_diagram=(diagram_record or {}).get("architecture", ""),
        graph_data=GraphData(),   # graph not cached (too large)
        tech_stack=TechStackInfo(**ts_raw) if ts_raw else TechStackInfo(),
        insights=RepoInsights(**ins_raw) if ins_raw else RepoInsights(),
        ai_summary=record.get("ai_summary", ""),
        ai_improvements=record.get("ai_improvements", ""),
        success=True,
    )


def _raw_to_record(raw: dict) -> AnalysisRecord:
    """Convert a raw Supabase row dict to an AnalysisRecord model."""
    from datetime import datetime
    return AnalysisRecord(
        id=raw.get("id"),
        repo_url=raw.get("repo_url", ""),
        repo_name=raw.get("repo_name", ""),
        analysed_at=raw.get("analysed_at", datetime.utcnow()),
        mermaid_diagram="",
        tech_stack=raw.get("tech_stack") or {},
        ai_summary=raw.get("ai_summary", ""),
        insights=raw.get("insights") or {},
    )
