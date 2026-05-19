"""
ai_summary.py
-------------
Generates architecture summaries using Groq Inference API.

IMPORTANT: Raw source code is NEVER sent to the model.
Only structured metadata JSON derived from deterministic analysis
is included in prompts — keeps tokens low, output focused.

Supports:
  - Architecture summary
  - Improvement suggestions
  - README-style overview
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from groq import Groq

from app.config import settings
from app.services.code_analyzer import AnalysisResult

logger = logging.getLogger(__name__)

GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
]

# ------------------------------------------------------------------ #
# Result container                                                     #
# ------------------------------------------------------------------ #

@dataclass
class AISummaryResult:
    architecture_summary: str = ""
    improvement_suggestions: str = ""
    readme_overview: str = ""
    model_used: str = ""
    success: bool = True
    error: Optional[str] = None


# ------------------------------------------------------------------ #
# Prompt builders                                                      #
# ------------------------------------------------------------------ #

def _build_metadata(repo_name: str, result: AnalysisResult) -> dict:
    return {
        "repository": repo_name,
        "languages": result.tech_stack.languages,
        "frameworks": result.tech_stack.frameworks,
        "dependencies": result.tech_stack.dependencies[:20],
        "package_managers": result.tech_stack.package_managers,
        "components": [
            {
                "name": node.label,
                "type": node.node_type,
                "language": node.language,
            }
            for node in result.graph_data.nodes[:30]
        ],
        "insights": {
            "total_files": result.insights.total_files,
            "total_lines": result.insights.total_lines,
            "entry_points": result.insights.entry_points,
            "has_tests": result.insights.has_tests,
            "has_ci": result.insights.has_ci,
            "has_docker": result.insights.has_docker,
        },
    }


def _architecture_prompt(metadata: dict) -> str:
    return f"""You are a senior software architect. Analyse the repository metadata below
and generate a concise, professional architecture summary.

Repository metadata (JSON):
{json.dumps(metadata, indent=2)}

Write a structured architecture summary covering:
1. **System overview** - what this system does and its architecture style
2. **Tech stack** - key languages, frameworks and why they fit together
3. **Component interactions** - how the main components communicate
4. **Data flow** - how data moves through the system
5. **Strengths** - what is well-designed about this architecture

Keep the tone professional. Use markdown formatting. Be concise (300-400 words)."""


def _improvements_prompt(metadata: dict) -> str:
    return f"""You are a senior software architect reviewing a codebase for improvements.

Repository metadata (JSON):
{json.dumps(metadata, indent=2)}

Provide 4-6 actionable improvement suggestions covering:
- Scalability
- Observability (logging, metrics, tracing)
- Security
- Testing coverage
- DevOps / CI-CD
- Code quality or architecture refactoring

Format each suggestion as:
**[Area]**: One-sentence problem -> Recommended fix

Be specific and practical."""


def _readme_prompt(metadata: dict) -> str:
    return f"""Generate a concise README overview section for this repository.

Repository metadata (JSON):
{json.dumps(metadata, indent=2)}

Write:
1. A one-paragraph project description
2. A bullet list of core features (5-7 bullets)
3. A "Tech Stack" table with columns: Layer | Technology

Use markdown. Keep it under 250 words."""


# ------------------------------------------------------------------ #
# AI Summary engine                                                    #
# ------------------------------------------------------------------ #

class AISummaryEngine:
    """Calls Groq API to generate architecture summaries."""

    def __init__(self) -> None:
        self._active_model: str = GROQ_MODELS[0]

    def summarise(self, repo_name: str, result: AnalysisResult) -> AISummaryResult:
        """Generate all three summary types. Returns AISummaryResult."""
        summary = AISummaryResult()
        metadata = _build_metadata(repo_name, result)

        prompts = [
            ("architecture_summary",    _architecture_prompt(metadata)),
            ("improvement_suggestions", _improvements_prompt(metadata)),
            ("readme_overview",         _readme_prompt(metadata)),
        ]

        for attr, prompt in prompts:
            text = self._call_with_fallback(prompt)
            setattr(summary, attr, text)

        summary.model_used = self._active_model
        summary.success = bool(summary.architecture_summary)
        return summary

    def _call_with_fallback(self, prompt: str) -> str:
        """Try each Groq model in order; return empty string on total failure."""
        groq_client = Groq(api_key=settings.GROQ_API_KEY)

        for model in GROQ_MODELS:
            try:
                response = groq_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=settings.HF_MAX_NEW_TOKENS,
                    temperature=0.3,
                )
                text = response.choices[0].message.content.strip()
                if text:
                    self._active_model = model
                    logger.info("Groq OK model=%s chars=%d", model, len(text))
                    return text
            except Exception as exc:
                logger.error("Groq error model=%s: %s", model, exc)
                continue

        logger.error("All Groq models exhausted")
        return ""


# ------------------------------------------------------------------ #
# Convenience wrapper                                                  #
# ------------------------------------------------------------------ #

def generate_summary(repo_name: str, result: AnalysisResult) -> AISummaryResult:
    return AISummaryEngine().summarise(repo_name, result)