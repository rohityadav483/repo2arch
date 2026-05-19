"""
mermaid_generator.py
--------------------
Converts a GraphBundle into valid Mermaid diagram syntax strings.

Produces two diagrams:
  1. architecture_diagram  — component-level (service clusters)
  2. dependency_diagram    — file-level import graph (capped)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from app.services.graph_builder import (
    GraphBundle,
    NT_ENTRYPOINT,
    NT_SERVICE,
    NT_MODULE,
    NT_EXTERNAL,
    NT_CONFIG,
    NT_TEST,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Mermaid node shape templates                                         #
# ------------------------------------------------------------------ #

SHAPE_MAP: dict[str, tuple[str, str]] = {
    NT_ENTRYPOINT: ("[[", "]]"),
    NT_SERVICE:    ("([", "])"),
    NT_MODULE:     ("[",  "]"),
    NT_EXTERNAL:   ("{{", "}}"),
    NT_CONFIG:     ("[(", ")]"),
    NT_TEST:       (">",  "]"),
}

CLASSDEFS = [
    "    classDef entrypoint fill:#7F77DD,stroke:#534AB7,color:#fff",
    "    classDef service    fill:#1D9E75,stroke:#0F6E56,color:#fff",
    "    classDef module     fill:#378ADD,stroke:#185FA5,color:#fff",
    "    classDef external   fill:#D85A30,stroke:#993C1D,color:#fff",
    "    classDef config     fill:#888780,stroke:#5F5E5A,color:#fff",
    "    classDef testnode   fill:#B4B2A9,stroke:#888780,color:#333",
]


# ------------------------------------------------------------------ #
# Result container                                                     #
# ------------------------------------------------------------------ #

@dataclass
class MermaidDiagrams:
    architecture_diagram: str = ""
    dependency_diagram: str = ""


# ------------------------------------------------------------------ #
# Generator                                                            #
# ------------------------------------------------------------------ #

class MermaidGenerator:

    # Reduced from 40 → 25 to avoid Mermaid curve distance bug
    MAX_DEP_NODES = 25

    def generate(self, bundle: GraphBundle) -> MermaidDiagrams:
        diagrams = MermaidDiagrams()
        diagrams.architecture_diagram = self._build_architecture(bundle)
        diagrams.dependency_diagram   = self._build_dependency(bundle)
        return diagrams

    # ---------------------------------------------------------------- #
    # Architecture diagram — component graph                            #
    # ---------------------------------------------------------------- #

    def _build_architecture(self, bundle: GraphBundle) -> str:
        G = bundle.component_graph
        if G.number_of_nodes() == 0:
            return self._fallback_diagram()

        lines: list[str] = ["graph TD", ""] + CLASSDEFS + [""]

        node_ids: dict[str, str] = {}
        for node, attrs in G.nodes(data=True):
            mid = self._sanitise_id(node)
            node_ids[node] = mid
            label = attrs.get("label", node)
            ntype = attrs.get("node_type", NT_MODULE)
            open_s, close_s = SHAPE_MAP.get(ntype, ("[", "]"))
            lines.append(f"    {mid}{open_s}\"{label}\"{close_s}")

        lines.append("")

        for src, tgt, data in G.edges(data=True):
            src_id = node_ids.get(src, self._sanitise_id(src))
            tgt_id = node_ids.get(tgt, self._sanitise_id(tgt))
            relation = data.get("relation", "")
            if relation and relation != "imports":
                lines.append(f"    {src_id} -->|{relation}| {tgt_id}")
            else:
                lines.append(f"    {src_id} --> {tgt_id}")

        lines.append("")

        for node, attrs in G.nodes(data=True):
            mid = node_ids[node]
            ntype = attrs.get("node_type", NT_MODULE)
            cls = "testnode" if ntype == NT_TEST else ntype
            lines.append(f"    class {mid} {cls}")

        return "\n".join(lines)

    # ---------------------------------------------------------------- #
    # Dependency diagram — file-level graph                             #
    # ---------------------------------------------------------------- #

    def _build_dependency(self, bundle: GraphBundle) -> str:
        G = bundle.dependency_graph
        if G.number_of_nodes() == 0:
            return self._fallback_diagram("dependency")

        # Cap by degree rank
        ranked    = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)
        top_nodes = set(ranked[: self.MAX_DEP_NODES])

        # Use TD (not LR) — avoids "could not find suitable point" bug
        lines: list[str] = ["graph TD", ""] + CLASSDEFS + [""]

        node_ids: dict[str, str] = {}
        for node in top_nodes:
            attrs  = G.nodes[node]
            mid    = self._sanitise_id(node)
            node_ids[node] = mid
            label  = Path(node).stem
            ntype  = attrs.get("node_type", NT_MODULE)
            open_s, close_s = SHAPE_MAP.get(ntype, ("[", "]"))
            lines.append(f"    {mid}{open_s}\"{label}\"{close_s}")

        lines.append("")

        for src, tgt in G.edges:
            if src in top_nodes and tgt in top_nodes:
                lines.append(f"    {node_ids[src]} --> {node_ids[tgt]}")

        lines.append("")

        for node in top_nodes:
            mid   = node_ids[node]
            ntype = G.nodes[node].get("node_type", NT_MODULE)
            cls   = "testnode" if ntype == NT_TEST else ntype
            lines.append(f"    class {mid} {cls}")

        return "\n".join(lines)

    # ---------------------------------------------------------------- #
    # Helpers                                                            #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _sanitise_id(raw: str) -> str:
        s = raw.replace("/", "_").replace("\\", "_").replace(".", "_")
        s = re.sub(r"\W", "_", s)
        if s and s[0].isdigit():
            s = "n_" + s
        s = re.sub(r"_+", "_", s).strip("_")
        return s or "node"

    @staticmethod
    def _fallback_diagram(kind: str = "architecture") -> str:
        return (
            "graph TD\n"
            f'    A["No {kind} data detected"]\n'
            '    A --> B["Check repo contains Python / JS / TS files"]\n'
        )


# ------------------------------------------------------------------ #
# Convenience wrapper                                                  #
# ------------------------------------------------------------------ #

def generate_mermaid(bundle: GraphBundle) -> MermaidDiagrams:
    return MermaidGenerator().generate(bundle)