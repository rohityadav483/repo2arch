"""
graph_builder.py
----------------
Builds NetworkX directed graphs from AnalysisResult data.
Produces three graph types:
  1. component_graph  — high-level service/module clusters
  2. dependency_graph — file-level import relationships
  3. service_flow     — entry-point → service → external chains

All graphs are pure NetworkX objects; serialisation to JSON or
Mermaid happens in downstream modules (mermaid_generator.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx

from app.services.code_analyzer import AnalysisResult
from app.models.schemas import ComponentNode, ComponentEdge, GraphData

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Node / edge attribute constants                                      #
# ------------------------------------------------------------------ #

# node_type values — used for colour-coding in the frontend
NT_ENTRYPOINT = "entrypoint"
NT_SERVICE     = "service"
NT_MODULE      = "module"
NT_EXTERNAL    = "external"
NT_CONFIG      = "config"
NT_TEST        = "test"

# Colour map sent as a node attribute (Plotly / PyVis uses this)
NODE_COLOURS: dict[str, str] = {
    NT_ENTRYPOINT: "#7F77DD",   # purple
    NT_SERVICE:    "#1D9E75",   # teal
    NT_MODULE:     "#378ADD",   # blue
    NT_EXTERNAL:   "#D85A30",   # coral
    NT_CONFIG:     "#888780",   # gray
    NT_TEST:       "#B4B2A9",   # light gray
}


# ------------------------------------------------------------------ #
# Result container                                                     #
# ------------------------------------------------------------------ #

@dataclass
class GraphBundle:
    """All three graphs plus serialisable GraphData for the API response."""
    component_graph:  nx.DiGraph = field(default_factory=nx.DiGraph)
    dependency_graph: nx.DiGraph = field(default_factory=nx.DiGraph)
    service_flow:     nx.DiGraph = field(default_factory=nx.DiGraph)
    # Serialisable summary (subset of dependency_graph, capped for UI)
    graph_data: GraphData = field(default_factory=GraphData)


# ------------------------------------------------------------------ #
# Builder                                                              #
# ------------------------------------------------------------------ #

class GraphBuilder:
    """
    Converts an AnalysisResult into a GraphBundle.

    Usage:
        bundle = GraphBuilder().build(analysis_result)
    """

    # Max nodes to include in the serialised graph sent to frontend.
    # Large repos can have 500+ files — cap keeps the UI responsive.
    MAX_DISPLAY_NODES = 60

    def build(self, result: AnalysisResult) -> GraphBundle:
        bundle = GraphBundle()

        self._build_dependency_graph(result, bundle)
        self._build_component_graph(result, bundle)
        self._build_service_flow(result, bundle)
        self._serialise(bundle)

        logger.info(
            "Graph built — dep_nodes=%d dep_edges=%d comp_nodes=%d",
            bundle.dependency_graph.number_of_nodes(),
            bundle.dependency_graph.number_of_edges(),
            bundle.component_graph.number_of_nodes(),
        )
        return bundle

    # ---------------------------------------------------------------- #
    # 1. Dependency graph (file-level)                                   #
    # ---------------------------------------------------------------- #

    def _build_dependency_graph(
        self, result: AnalysisResult, bundle: GraphBundle
    ) -> None:
        G = bundle.dependency_graph

        # Add all analysed nodes
        for node in result.graph_data.nodes:
            G.add_node(
                node.id,
                label=node.label,
                node_type=node.node_type,
                language=node.language or "",
                colour=NODE_COLOURS.get(node.node_type, NODE_COLOURS[NT_MODULE]),
            )

        # Add edges
        for edge in result.graph_data.edges:
            if G.has_node(edge.source) and G.has_node(edge.target):
                G.add_edge(edge.source, edge.target, relation=edge.relation)

        # Remove isolated nodes (no connections) unless they are entry points
        isolated = [
            n for n in list(G.nodes)
            if G.degree(n) == 0 and G.nodes[n].get("node_type") != NT_ENTRYPOINT
        ]
        G.remove_nodes_from(isolated)
        logger.debug("Dependency graph: removed %d isolated nodes", len(isolated))

    # ---------------------------------------------------------------- #
    # 2. Component graph (directory / service cluster level)             #
    # ---------------------------------------------------------------- #

    def _build_component_graph(
        self, result: AnalysisResult, bundle: GraphBundle
    ) -> None:
        """
        Collapses file-level nodes into top-level directory clusters.
        e.g. backend/app/services/foo.py → 'services' cluster node.
        """
        G = bundle.component_graph
        dep_G = bundle.dependency_graph

        # Map each file → its top-level directory component
        file_to_component: dict[str, str] = {}
        for node_id in dep_G.nodes:
            parts = Path(node_id).parts
            component = parts[0] if len(parts) > 1 else "root"
            file_to_component[node_id] = component

        # Add component nodes
        component_types: dict[str, str] = {}
        for node_id, attrs in dep_G.nodes(data=True):
            comp = file_to_component.get(node_id, "root")
            if comp not in G:
                ctype = self._infer_component_type(comp)
                component_types[comp] = ctype
                G.add_node(
                    comp,
                    label=comp,
                    node_type=ctype,
                    colour=NODE_COLOURS.get(ctype, NODE_COLOURS[NT_MODULE]),
                )

        # Add edges between components (deduplicated)
        for src, tgt in dep_G.edges:
            src_comp = file_to_component.get(src, "root")
            tgt_comp = file_to_component.get(tgt, "root")
            if src_comp != tgt_comp and not G.has_edge(src_comp, tgt_comp):
                G.add_edge(src_comp, tgt_comp, relation="uses")

        # Add detected external services as leaf nodes
        for framework in result.tech_stack.frameworks:
            ext_id = f"ext:{framework}"
            if ext_id not in G:
                G.add_node(
                    ext_id,
                    label=framework,
                    node_type=NT_EXTERNAL,
                    colour=NODE_COLOURS[NT_EXTERNAL],
                )
            # Connect to the most likely consumer component
            consumer = self._find_framework_consumer(
                framework, result, file_to_component
            )
            if consumer and not G.has_edge(consumer, ext_id):
                G.add_edge(consumer, ext_id, relation="uses")

    # ---------------------------------------------------------------- #
    # 3. Service flow graph (entry-point chains)                         #
    # ---------------------------------------------------------------- #

    def _build_service_flow(
        self, result: AnalysisResult, bundle: GraphBundle
    ) -> None:
        """
        Traces paths from entry-point nodes through the dependency graph.
        Useful for showing the request lifecycle in the Mermaid diagram.
        """
        G = bundle.service_flow
        dep_G = bundle.dependency_graph

        entry_nodes = [
            n for n, d in dep_G.nodes(data=True)
            if d.get("node_type") == NT_ENTRYPOINT
        ]

        if not entry_nodes:
            logger.debug("No entry points found — service flow graph empty")
            return

        for entry in entry_nodes:
            # BFS up to depth 4 from each entry point
            try:
                sub = nx.ego_graph(dep_G, entry, radius=4, undirected=False)
                G.update(sub)
            except nx.NetworkXError:
                pass

        logger.debug(
            "Service flow graph: %d nodes, %d edges",
            G.number_of_nodes(),
            G.number_of_edges(),
        )

    # ---------------------------------------------------------------- #
    # Serialise to GraphData (capped for frontend)                       #
    # ---------------------------------------------------------------- #

    def _serialise(self, bundle: GraphBundle) -> None:
        """
        Convert dependency_graph → GraphData (nodes + edges).
        Ranks nodes by degree and keeps the top MAX_DISPLAY_NODES.
        """
        G = bundle.dependency_graph
        if G.number_of_nodes() == 0:
            # Fall back to component graph if dependency graph is empty
            G = bundle.component_graph

        # Rank by degree — most-connected nodes are most informative
        ranked = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)
        top_nodes = set(ranked[: self.MAX_DISPLAY_NODES])

        nodes = []
        for n in top_nodes:
            attrs = G.nodes[n]
            nodes.append(ComponentNode(
                id=n,
                label=attrs.get("label", n),
                node_type=attrs.get("node_type", NT_MODULE),
                language=attrs.get("language"),
                imports=[],
            ))

        edges = []
        for src, tgt, data in G.edges(data=True):
            if src in top_nodes and tgt in top_nodes:
                edges.append(ComponentEdge(
                    source=src,
                    target=tgt,
                    relation=data.get("relation", "imports"),
                ))

        bundle.graph_data.nodes = nodes
        bundle.graph_data.edges = edges

    # ---------------------------------------------------------------- #
    # Helpers                                                            #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _infer_component_type(directory_name: str) -> str:
        name = directory_name.lower()
        if name in ("frontend", "client", "ui", "web"):
            return NT_MODULE
        if name in ("backend", "server", "api", "app"):
            return NT_SERVICE
        if "service" in name:
            return NT_SERVICE
        if name in ("config", "settings", "conf"):
            return NT_CONFIG
        if name in ("test", "tests", "spec", "__tests__"):
            return NT_TEST
        return NT_MODULE

    @staticmethod
    def _find_framework_consumer(
        framework: str,
        result: AnalysisResult,
        file_to_component: dict[str, str],
    ) -> Optional[str]:
        """Return the component directory most likely using this framework."""
        fw_lower = framework.lower()
        for node in result.graph_data.nodes:
            if any(fw_lower in imp.lower() for imp in node.imports):
                return file_to_component.get(node.id)
        return None


# ------------------------------------------------------------------ #
# Convenience wrapper                                                  #
# ------------------------------------------------------------------ #

def build_graphs(result: AnalysisResult) -> GraphBundle:
    return GraphBuilder().build(result)
