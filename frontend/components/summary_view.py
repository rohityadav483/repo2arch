"""
summary_view.py
---------------
Renders the AI-generated architecture summary, improvement
suggestions, README overview, and repository insights panel.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


# ------------------------------------------------------------------ #
# Main summary panel                                                   #
# ------------------------------------------------------------------ #

def render_summary(
    ai_summary: str,
    ai_improvements: str,
    repo_insights: dict[str, Any],
) -> None:
    tab_arch, tab_imp, tab_ins = st.tabs([
        "🧠 Architecture Summary",
        "💡 Improvements",
        "📊 Repo Insights",
    ])

    with tab_arch:
        render_architecture_summary(ai_summary)

    with tab_imp:
        render_improvements(ai_improvements)

    with tab_ins:
        render_insights(repo_insights)


# ------------------------------------------------------------------ #
# Architecture summary                                                 #
# ------------------------------------------------------------------ #

def render_architecture_summary(ai_summary: str) -> None:
    if not ai_summary or not ai_summary.strip():
        _ai_empty_state("architecture summary")
        return

    st.markdown(
        """
        <div style="
          background: linear-gradient(135deg, #1a1d23 0%, #1e2340 100%);
          border: 1px solid #2d3561;
          border-radius: 10px;
          padding: 20px 24px;
          margin-bottom: 12px;
        ">
          <div style="
            color: #7F77DD;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            margin-bottom: 10px;
          ">AI Architecture Analysis</div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(ai_summary)
    st.markdown("</div>", unsafe_allow_html=True)

    st.download_button(
        label="⬇️ Download Summary",
        data=ai_summary,
        file_name="architecture_summary.md",
        mime="text/markdown",
    )


# ------------------------------------------------------------------ #
# Improvement suggestions                                              #
# ------------------------------------------------------------------ #

def render_improvements(ai_improvements: str) -> None:
    if not ai_improvements or not ai_improvements.strip():
        _ai_empty_state("improvement suggestions")
        return

    st.markdown(
        """
        <div style="
          background: linear-gradient(135deg, #1a1d23 0%, #1e2a20 100%);
          border: 1px solid #2d5631;
          border-radius: 10px;
          padding: 20px 24px;
          margin-bottom: 12px;
        ">
          <div style="
            color: #1D9E75;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            margin-bottom: 10px;
          ">Suggested Improvements</div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(ai_improvements)
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ #
# Repository insights                                                  #
# ------------------------------------------------------------------ #

def render_insights(insights: dict[str, Any]) -> None:
    if not insights:
        st.info("No repository insights available.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📁 Total Files",    insights.get("total_files", 0))
    c2.metric("🔍 Analysed Files", insights.get("analysed_files", 0))
    c3.metric("📝 Total Lines",    f"{insights.get('total_lines', 0):,}")
    c4.metric("🚪 Entry Points",   len(insights.get("entry_points", [])))

    st.divider()

    col_a, col_b, col_c = st.columns(3)
    col_a.markdown(_flag_badge("Tests",  insights.get("has_tests",  False)), unsafe_allow_html=True)
    col_b.markdown(_flag_badge("CI/CD",  insights.get("has_ci",     False)), unsafe_allow_html=True)
    col_c.markdown(_flag_badge("Docker", insights.get("has_docker", False)), unsafe_allow_html=True)

    st.divider()

    entry_points = insights.get("entry_points", [])
    if entry_points:
        st.markdown("**Entry Points**")
        for ep in entry_points:
            st.markdown(f"- `{ep}`")

    config_files = insights.get("config_files", [])
    if config_files:
        with st.expander(f"⚙️ Config files ({len(config_files)})"):
            for cf in config_files[:20]:
                st.markdown(f"- `{cf}`")


# ------------------------------------------------------------------ #
# README overview                                                      #
# ------------------------------------------------------------------ #

def render_readme_expander(readme_overview: str) -> None:
    if not readme_overview or not readme_overview.strip():
        return
    with st.expander("📄 Generated README Overview", expanded=False):
        st.markdown(readme_overview)
        st.download_button(
            label="⬇️ Download README",
            data=readme_overview,
            file_name="README_generated.md",
            mime="text/markdown",
        )


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _flag_badge(label: str, value: bool) -> str:
    colour = "#1D9E75" if value else "#888780"
    icon   = "✅" if value else "❌"
    status = "Yes" if value else "No"
    return (
        f"<div style='background:#1a1d23;border:1px solid #333;"
        f"border-radius:8px;padding:12px 16px;text-align:center;'>"
        f"<div style='font-size:1.4rem'>{icon}</div>"
        f"<div style='color:{colour};font-weight:600;font-size:13px;"
        f"margin-top:4px'>{label}</div>"
        f"<div style='color:#888;font-size:11px'>{status}</div>"
        f"</div>"
    )


def _ai_empty_state(label: str) -> None:
    st.markdown(
        f"""
        <div style="text-align:center;padding:40px 20px;color:#888;
          border:1px dashed #444;border-radius:10px;">
          <div style="font-size:1.8rem;margin-bottom:10px;">🤖</div>
          <div>No {label} available</div>
          <div style="font-size:12px;margin-top:6px;">
            Check your Groq API key and retry
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )