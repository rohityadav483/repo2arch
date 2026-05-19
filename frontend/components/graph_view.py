"""
graph_view.py
-------------
Renders the interactive dependency graph in the Streamlit frontend.

Primary renderer  : PyVis  (physics-based, draggable nodes)
Fallback renderer : Plotly (static scatter + edge traces)

PyVis produces a self-contained HTML file → loaded via
st.components.v1.html(). Plotly renders natively with st.plotly_chart().

Exports:
  render_graph(graph_data)
  render_graph_stats(graph_data)
"""

from __future__ import annotations

import logging
import math
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Colour map (mirrors graph_builder.NODE_COLOURS)                     #
# ------------------------------------------------------------------ #

NODE_COLOURS: dict[str, str] = {
    "entrypoint": "#7F77DD",
    "service":    "#1D9E75",
    "module":     "#378ADD",
    "external":   "#D85A30",
    "config":     "#888780",
    "test":       "#B4B2A9",
}

NODE_SIZE: dict[str, int] = {
    "entrypoint": 28,
    "service":    24,
    "module":     18,
    "external":   20,
    "config":     16,
    "test":       14,
}


# ------------------------------------------------------------------ #
# Public entry point                                                   #
# ------------------------------------------------------------------ #

def render_graph(graph_data: dict[str, Any], height: int = 600) -> None:
    """
    Render the interactive dependency graph.
    Tries PyVis first; falls back to Plotly on import error.

    Args:
        graph_data : dict with keys "nodes" and "edges"
        height     : component height in pixels
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not nodes:
        _empty_state()
        return

    st.markdown(f"**{len(nodes)} nodes · {len(edges)} edges**")

    try:
        _render_pyvis(nodes, edges, height)
    except ImportError:
        logger.warning("PyVis not installed — falling back to Plotly")
        _render_plotly(nodes, edges, height)
    except Exception as exc:
        logger.error("PyVis render failed: %s — falling back to Plotly", exc)
        _render_plotly(nodes, edges, height)


def render_graph_stats(graph_data: dict[str, Any]) -> None:
    """Display a small stats row below the graph."""
    nodes = graph_data.get("nodes", [])
    if not nodes:
        return

    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n.get("node_type", "module")
        type_counts[t] = type_counts.get(t, 0) + 1

    cols = st.columns(len(type_counts) + 1)
    cols[0].metric("Total nodes", len(nodes))
    for i, (ntype, count) in enumerate(type_counts.items(), start=1):
        colour = NODE_COLOURS.get(ntype, "#888")
        cols[i].markdown(
            f"<span style='color:{colour}; font-weight:600'>"
            f"{ntype.capitalize()}</span><br>"
            f"<span style='font-size:1.4rem; font-weight:700'>{count}</span>",
            unsafe_allow_html=True,
        )


# ------------------------------------------------------------------ #
# PyVis renderer                                                       #
# ------------------------------------------------------------------ #

def _render_pyvis(
    nodes: list[dict],
    edges: list[dict],
    height: int,
) -> None:
    from pyvis.network import Network

    net = Network(
        height=f"{height}px",
        width="100%",
        bgcolor="#0e1117",
        font_color="#e0e0e0",
        directed=True,
        notebook=False,
    )

    net.set_options(_pyvis_physics(len(nodes)))

    for node in nodes:
        nid    = node.get("id", "")
        label  = node.get("label", nid)
        ntype  = node.get("node_type", "module")
        colour = NODE_COLOURS.get(ntype, "#378ADD")
        size   = NODE_SIZE.get(ntype, 18)
        lang   = node.get("language") or ""
        title  = (
            f"<b>{label}</b><br>Type: {ntype}<br>Lang: {lang}"
            if lang else
            f"<b>{label}</b><br>Type: {ntype}"
        )
        net.add_node(
            nid,
            label=label,
            color=colour,
            size=size,
            title=title,
            borderWidth=2,
            borderWidthSelected=4,
            font={"size": 11, "color": "#ffffff"},
        )

    for edge in edges:
        net.add_edge(
            edge.get("source", ""),
            edge.get("target", ""),
            title=edge.get("relation", ""),
            color={"color": "#555", "highlight": "#aaa"},
            arrows="to",
            width=1,
            smooth={"type": "curvedCW", "roundness": 0.2},
        )

    html_str = net.generate_html()
    # Patch background — PyVis defaults to white
    for white in ("background-color: #ffffff;", "background-color:#ffffff;"):
        html_str = html_str.replace(white, "background-color: #0e1117;")

    components.html(html_str, height=height + 20, scrolling=False)


def _pyvis_physics(num_nodes: int) -> str:
    """Return a JSON options string tuned for the graph size."""
    if num_nodes > 30:
        return """
        {
          "physics": {
            "barnesHut": {
              "gravitationalConstant": -8000,
              "centralGravity": 0.3,
              "springLength": 120,
              "springConstant": 0.04,
              "damping": 0.09
            },
            "maxVelocity": 50,
            "minVelocity": 0.1,
            "solver": "barnesHut",
            "stabilization": { "iterations": 150 }
          }
        }"""
    return """
    {
      "physics": {
        "repulsion": {
          "centralGravity": 0.2,
          "springLength": 100,
          "springConstant": 0.05,
          "nodeDistance": 120,
          "damping": 0.09
        },
        "solver": "repulsion",
        "stabilization": { "iterations": 100 }
      }
    }"""


# ------------------------------------------------------------------ #
# Plotly fallback renderer                                             #
# ------------------------------------------------------------------ #

def _render_plotly(
    nodes: list[dict],
    edges: list[dict],
    height: int,
) -> None:
    import plotly.graph_objects as go

    # Circular layout
    n = len(nodes)
    positions: dict[str, tuple[float, float]] = {
        node["id"]: (
            math.cos(2 * math.pi * i / max(n, 1)),
            math.sin(2 * math.pi * i / max(n, 1)),
        )
        for i, node in enumerate(nodes)
    }

    # Edge traces
    edge_x, edge_y = [], []
    for edge in edges:
        x0, y0 = positions.get(edge["source"], (0.0, 0.0))
        x1, y1 = positions.get(edge["target"], (0.0, 0.0))
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line={"width": 1, "color": "#555"},
        hoverinfo="none",
    )

    # One trace per node type for legend grouping
    type_groups: dict[str, list[dict]] = {}
    for node in nodes:
        type_groups.setdefault(node.get("node_type", "module"), []).append(node)

    node_traces = []
    for ntype, group in type_groups.items():
        colour = NODE_COLOURS.get(ntype, "#378ADD")
        node_traces.append(go.Scatter(
            x=[positions[n["id"]][0] for n in group],
            y=[positions[n["id"]][1] for n in group],
            mode="markers+text",
            name=ntype.capitalize(),
            text=[n.get("label", n["id"]) for n in group],
            textposition="top center",
            textfont={"size": 9, "color": "#ccc"},
            hoverinfo="text",
            marker={
                "color": colour,
                "size": NODE_SIZE.get(ntype, 18),
                "line": {"width": 1.5, "color": "#333"},
            },
        ))

    st.plotly_chart(
        go.Figure(
            data=[edge_trace, *node_traces],
            layout=go.Layout(
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
                showlegend=True,
                legend={"font": {"color": "#ccc"}, "bgcolor": "#1a1d23"},
                margin={"l": 10, "r": 10, "t": 10, "b": 10},
                xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
                yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
                height=height,
                hovermode="closest",
            ),
        ),
        use_container_width=True,
    )


# ------------------------------------------------------------------ #
# Empty state                                                          #
# ------------------------------------------------------------------ #

def _empty_state() -> None:
    st.markdown(
        """
        <div style="text-align:center;padding:60px 20px;color:#888;
          border:1px dashed #444;border-radius:10px;margin-top:12px;">
          <div style="font-size:2rem;margin-bottom:12px;">🕸️</div>
          <div>No graph data available</div>
          <div style="font-size:12px;margin-top:6px;">
            Analyse a repo with Python / JS / TS source files
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
