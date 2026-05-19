"""
diagram_view.py
---------------
Renders Mermaid diagrams inside Streamlit using an HTML iframe.
Uses startOnLoad:true — simpler and more reliable than mermaid.run().
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


def render_mermaid_diagram(
    diagram_source: str,
    height: int = 520,
    title: str = "",
) -> None:
    if not diagram_source or not diagram_source.strip():
        st.info("No diagram data available for this repository.")
        return

    if title:
        st.markdown(f"#### {title}")

    components.html(_build_mermaid_html(diagram_source), height=height, scrolling=True)

    with st.expander("📋 View / copy Mermaid source"):
        st.code(diagram_source, language="text")


def render_diagram_tabs(
    architecture_diagram: str,
    dependency_diagram: str,
) -> None:
    tab_arch, tab_dep = st.tabs(["🏗️ Architecture", "🔗 Dependency Graph"])

    with tab_arch:
        if architecture_diagram:
            render_mermaid_diagram(architecture_diagram, height=560, title="Component Architecture")
        else:
            _empty_state("architecture diagram")

    with tab_dep:
        if dependency_diagram:
            render_mermaid_diagram(dependency_diagram, height=560, title="File Dependency Graph")
        else:
            _empty_state("dependency diagram")


def _build_mermaid_html(diagram_source: str) -> str:
    """
    Wrap Mermaid source in a self-contained HTML page.
    Uses startOnLoad:true — avoids mermaid.run() async timing issues.
    Diagram source placed directly in <pre class="mermaid"> — no JS escaping needed.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0e1117;
      padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    pre.mermaid {{
      display: flex;
      justify-content: center;
    }}
    pre.mermaid svg {{
      background: transparent !important;
      max-width: 100%;
      height: auto;
    }}
    #err {{
      display: none;
      background: #2d1515;
      border: 1px solid #c0392b;
      border-radius: 8px;
      padding: 12px;
      color: #e74c3c;
      font-size: 13px;
      white-space: pre-wrap;
      margin-top: 12px;
    }}
  </style>
</head>
<body>
  <pre class="mermaid">
{diagram_source}
  </pre>
  <div id="err"></div>

  <script type="module">
    import mermaid from
      'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';

    mermaid.initialize({{
      startOnLoad: true,
      theme: 'dark',
      flowchart: {{
        curve: 'linear',
        useMaxWidth: true,
        rankSpacing: 60,
        nodeSpacing: 40,
      }},
      securityLevel: 'loose',
    }});

    // Show errors visibly instead of silent blank
    mermaid.parseError = function(err) {{
      const box = document.getElementById('err');
      box.style.display = 'block';
      box.textContent = 'Mermaid parse error: ' + err;
    }};
  </script>
</body>
</html>"""


def _empty_state(label: str) -> None:
    st.markdown(
        f"""
        <div style="text-align:center;padding:60px 20px;color:#888;
          border:1px dashed #444;border-radius:10px;margin-top:12px;">
          <div style="font-size:2rem;margin-bottom:12px;">📊</div>
          <div>No {label} available</div>
          <div style="font-size:12px;margin-top:6px;">
            Analyse a repository to generate diagrams
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )