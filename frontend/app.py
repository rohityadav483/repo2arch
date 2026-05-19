"""
app.py — Repo2Arch Streamlit frontend entry point.
Run: streamlit run frontend/app.py
"""

from __future__ import annotations

import os
import sys
import time

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from frontend.utils.api_client import get_client
from frontend.components.diagram_view import render_diagram_tabs
from frontend.components.graph_view import render_graph, render_graph_stats
from frontend.components.summary_view import render_summary, render_readme_expander
from frontend.components.tech_badges import render_tech_stack, render_stack_compact

# ------------------------------------------------------------------ #
# Page config                                                          #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Repo2Arch",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------ #
# Global CSS                                                           #
# ------------------------------------------------------------------ #

def _inject_css() -> None:
    st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    .stApp { background-color: #0e1117; }

    .r2a-hero {
      background: linear-gradient(135deg, #1a1d23 0%, #1e2340 50%, #1a2328 100%);
      border: 1px solid #2d3561; border-radius: 14px;
      padding: 28px 32px 24px; margin-bottom: 24px;
      position: relative; overflow: hidden;
    }
    .r2a-hero h1 {
      font-size: 2rem; font-weight: 800; margin: 0 0 6px;
      background: linear-gradient(90deg, #7F77DD, #1D9E75);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .r2a-hero p { color: #888; margin: 0; font-size: 0.95rem; }

    .status-dot {
      display: inline-block; width: 8px; height: 8px;
      border-radius: 50%; margin-right: 6px; vertical-align: middle;
    }
    .status-ok    { background: #1D9E75; box-shadow: 0 0 6px #1D9E75; }
    .status-error { background: #D85A30; box-shadow: 0 0 6px #D85A30; }

    .stTextInput > div > div > input {
      background: #1a1d23 !important; border: 1px solid #2d3561 !important;
      border-radius: 8px !important; color: #e0e0e0 !important; font-size: 15px !important;
    }
    .stTextInput > div > div > input:focus {
      border-color: #7F77DD !important;
      box-shadow: 0 0 0 2px rgba(127,119,221,0.25) !important;
    }

    div[data-testid="stButton"] > button[kind="primary"] {
      background: linear-gradient(135deg, #7F77DD, #534AB7) !important;
      border: none !important; border-radius: 8px !important;
      color: #fff !important; font-weight: 700 !important;
      padding: 0.55rem 2rem !important; font-size: 15px !important;
    }

    .stTabs [data-baseweb="tab"] { font-weight: 600; color: #888; padding: 8px 18px; }
    .stTabs [aria-selected="true"] { color: #7F77DD !important; border-bottom: 2px solid #7F77DD; }

    .history-card {
      background: #1a1d23; border: 1px solid #2a2d36;
      border-radius: 8px; padding: 12px 14px; margin-bottom: 8px;
    }
    .history-card .repo-name { font-weight: 700; color: #e0e0e0; font-size: 13px; }
    .history-card .repo-date { color: #666; font-size: 11px; margin-top: 2px; }

    [data-testid="metric-container"] {
      background: #1a1d23; border: 1px solid #2a2d36;
      border-radius: 8px; padding: 12px;
    }

    #MainMenu, footer, header { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)


# ------------------------------------------------------------------ #
# Session state                                                        #
# ------------------------------------------------------------------ #

def _init_state() -> None:
    defaults = {
        "result": None, "analysing": False,
        "last_url": "", "error": "",
        "history": [], "history_loaded": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ------------------------------------------------------------------ #
# Sidebar                                                              #
# ------------------------------------------------------------------ #

def _render_sidebar(client) -> None:
    with st.sidebar:
        st.markdown("## 🏗️ Repo2Arch")
        st.caption("GitHub → Architecture Diagrams")
        st.divider()

        st.markdown("**Backend Status**")
        with st.spinner("Checking…"):
            health = client.health()

        if health.success:
            data  = health.data
            sb_ok = data.get("supabase_connected", False)
            hf_ok = data.get("hf_configured", False)
            st.markdown(
                f"<span class='status-dot status-ok'></span>"
                f"API <code>v{data.get('version','?')}</code> — Online",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<span class='status-dot {'status-ok' if sb_ok else 'status-error'}'></span>"
                f"Supabase {'connected' if sb_ok else 'unavailable'}",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<span class='status-dot {'status-ok' if hf_ok else 'status-error'}'></span>"
                f"Groq AI {'configured' if hf_ok else 'missing key'}",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<span class='status-dot status-error'></span>Backend offline",
                unsafe_allow_html=True,
            )
            st.caption(health.error or "Cannot reach FastAPI server")

        st.divider()
        st.markdown("**Recent Analyses**")

        if not st.session_state.history_loaded:
            hist = client.get_history(limit=10)
            if hist.success:
                st.session_state.history = hist.data.get("records", [])
            st.session_state.history_loaded = True

        if st.session_state.history:
            for record in st.session_state.history[:8]:
                repo_name   = record.get("repo_name", "unknown")
                analysed_at = record.get("analysed_at", "")[:10]
                tech_stack  = record.get("tech_stack", {})
                st.markdown(
                    f"<div class='history-card'>"
                    f"<div class='repo-name'>📦 {repo_name}</div>"
                    f"<div class='repo-date'>{analysed_at}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                render_stack_compact(tech_stack)
        else:
            st.caption("No history yet — analyse a repo to get started.")

        st.divider()
        st.caption("Built with FastAPI · Streamlit · Supabase · Groq")


# ------------------------------------------------------------------ #
# Hero                                                                 #
# ------------------------------------------------------------------ #

def _render_hero() -> None:
    st.markdown("""
    <div class="r2a-hero">
      <h1>🏗️ Repo2Arch</h1>
      <p>Paste any public GitHub URL and instantly generate architecture diagrams,
      interactive dependency graphs, AI summaries and tech stack insights.</p>
    </div>
    """, unsafe_allow_html=True)


# ------------------------------------------------------------------ #
# Input                                                                #
# ------------------------------------------------------------------ #

def _render_input() -> tuple[str, bool]:
    col_input, col_btn = st.columns([5, 1])
    with col_input:
        url = st.text_input(
            label="GitHub Repository URL",
            placeholder="https://github.com/tiangolo/fastapi",
            label_visibility="collapsed",
            key="github_url_input",
        )
    with col_btn:
        clicked = st.button(
            "🔍 Analyse", type="primary",
            use_container_width=True,
            disabled=st.session_state.analysing,
        )
    st.caption(
        "Try: "
        "[tiangolo/fastapi](https://github.com/tiangolo/fastapi) · "
        "[pallets/flask](https://github.com/pallets/flask) · "
        "[streamlit/streamlit](https://github.com/streamlit/streamlit)"
    )
    return url.strip(), clicked


# ------------------------------------------------------------------ #
# Analysis runner                                                      #
# ------------------------------------------------------------------ #

def _run_analysis(client, url: str) -> None:
    st.session_state.analysing = True
    st.session_state.error     = ""
    st.session_state.result    = None

    progress = st.progress(0, text="Cloning repository…")
    progress.progress(20, text="Cloning repository…")
    response = client.analyse(url)
    progress.progress(90, text="Finalising…")
    progress.progress(100, text="Done!")
    progress.empty()

    if response.success and response.data.get("success"):
        st.session_state.result      = response.data
        st.session_state.last_url    = url
        st.session_state.history_loaded = False
    else:
        st.session_state.error = (
            response.error or response.data.get("error", "Unknown error")
        )
    st.session_state.analysing = False


# ------------------------------------------------------------------ #
# Results                                                              #
# ------------------------------------------------------------------ #

def _render_results(result: dict) -> None:
    repo_name = result.get("repo_name", "")
    st.markdown(f"### 📦 `{repo_name}`")

    tab_diag, tab_graph, tab_ai, tab_stack, tab_insights = st.tabs([
        "🏗️ Diagrams", "🕸️ Graph", "🧠 AI Summary", "⚙️ Tech Stack", "📊 Insights",
    ])

    with tab_diag:
        # architecture_diagram and dependency_diagram are both in mermaid_diagram
        # until backend sends them separately — use same source for both tabs
        arch_diag = result.get("mermaid_diagram", "")
        render_diagram_tabs(
            architecture_diagram=arch_diag,
            dependency_diagram=arch_diag,
        )

    with tab_graph:
        graph_data = result.get("graph_data") or {"nodes": [], "edges": []}
        render_graph(graph_data)
        render_graph_stats(graph_data)

    with tab_ai:
        render_summary(
            ai_summary=result.get("ai_summary", ""),
            ai_improvements=result.get("ai_improvements", ""),
            repo_insights=result.get("insights") or {},
        )
        render_readme_expander(result.get("readme_overview", ""))

    with tab_stack:
        render_tech_stack(result.get("tech_stack") or {})

    with tab_insights:
        from frontend.components.summary_view import render_insights
        render_insights(result.get("insights") or {})


# ------------------------------------------------------------------ #
# Landing                                                              #
# ------------------------------------------------------------------ #

def _render_landing() -> None:
    st.markdown("<br>", unsafe_allow_html=True)
    cols = st.columns(3)
    features = [
        ("🏗️", "Architecture Diagrams",
         "Auto-generated Mermaid diagrams showing component relationships."),
        ("🕸️", "Dependency Graphs",
         "Interactive NetworkX graphs showing file-level import relationships."),
        ("🧠", "AI Summaries",
         "Groq LLM generates architecture explanations and improvement suggestions."),
    ]
    for col, (icon, title, desc) in zip(cols, features):
        col.markdown(
            f"<div style='background:#1a1d23;border:1px solid #2a2d36;"
            f"border-radius:10px;padding:20px;text-align:center;height:160px;'>"
            f"<div style='font-size:2rem'>{icon}</div>"
            f"<div style='font-weight:700;margin:8px 0 6px;color:#e0e0e0'>{title}</div>"
            f"<div style='color:#888;font-size:13px'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ------------------------------------------------------------------ #
# Main                                                                 #
# ------------------------------------------------------------------ #

def main() -> None:
    _inject_css()
    _init_state()
    client = get_client()

    _render_sidebar(client)
    _render_hero()
    url, clicked = _render_input()

    if clicked and url:
        if not url.startswith("https://github.com"):
            st.error("⚠️ Please enter a valid GitHub URL (https://github.com/…)")
        else:
            _run_analysis(client, url)
            st.rerun()
    elif clicked and not url:
        st.warning("Please paste a GitHub repository URL first.")

    if st.session_state.error:
        st.error(f"❌ {st.session_state.error}")

    if st.session_state.result:
        st.divider()
        _render_results(st.session_state.result)
    elif not st.session_state.analysing and not st.session_state.error:
        _render_landing()


if __name__ == "__main__":
    main()