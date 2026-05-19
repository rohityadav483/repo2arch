"""
code_analyzer.py
----------------
Deterministic code analysis — NO AI involved here.
Uses Python AST for .py files, regex for JS/TS.
Detects languages, frameworks, dependencies, entry points,
and inter-module import relationships.
"""

from __future__ import annotations

import ast
import re
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.services.github_fetcher import RepoTree, FileEntry
from app.models.schemas import (
    TechStackInfo,
    RepoInsights,
    ComponentNode,
    ComponentEdge,
    GraphData,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Framework / library fingerprints                                     #
# ------------------------------------------------------------------ #

FRAMEWORK_SIGNATURES: dict[str, list[str]] = {
    # Python
    "FastAPI":      ["fastapi", "from fastapi"],
    "Django":       ["django", "from django"],
    "Flask":        ["flask", "from flask"],
    "SQLAlchemy":   ["sqlalchemy", "from sqlalchemy"],
    "Pydantic":     ["pydantic", "from pydantic"],
    "Celery":       ["celery", "from celery"],
    "Pytest":       ["pytest", "import pytest"],
    "Streamlit":    ["streamlit", "import streamlit"],
    "NumPy":        ["numpy", "import numpy"],
    "Pandas":       ["pandas", "import pandas"],
    "Torch":        ["torch", "import torch"],
    "TensorFlow":   ["tensorflow", "import tensorflow"],
    # JavaScript / TypeScript
    "React":        ["from 'react'", 'from "react"', "require('react')"],
    "Next.js":      ["from 'next'", "next/router", "next/image"],
    "Vue":          ["from 'vue'", 'from "vue"'],
    "Express":      ["require('express')", 'from "express"'],
    "NestJS":       ["@nestjs/core", "@nestjs/common"],
    "Axios":        ["axios", "from 'axios'"],
    "Prisma":       ["@prisma/client", "from '@prisma"],
    "TypeORM":      ["typeorm", "from 'typeorm'"],
    "Jest":         ["from '@jest", "describe(", "it(", "test("],
}

PACKAGE_MANAGER_FILES: dict[str, str] = {
    "requirements.txt":  "pip",
    "pyproject.toml":    "pip/poetry",
    "Pipfile":           "pipenv",
    "package.json":      "npm/yarn",
    "yarn.lock":         "yarn",
    "pnpm-lock.yaml":    "pnpm",
    "poetry.lock":       "poetry",
}

CI_FILES = {".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".circleci"}
DOCKER_FILES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
TEST_PATTERNS = {"test_", "_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js"}
ENTRY_POINTS = {"main.py", "app.py", "server.py", "index.js", "index.ts", "manage.py"}


# ------------------------------------------------------------------ #
# Result dataclass                                                     #
# ------------------------------------------------------------------ #

@dataclass
class AnalysisResult:
    tech_stack: TechStackInfo = field(default_factory=TechStackInfo)
    insights: RepoInsights = field(default_factory=RepoInsights)
    graph_data: GraphData = field(default_factory=GraphData)
    # Raw import map: file_path → list of imported module names
    import_map: dict[str, list[str]] = field(default_factory=dict)


# ------------------------------------------------------------------ #
# Main analyzer                                                        #
# ------------------------------------------------------------------ #

class CodeAnalyzer:
    """
    Analyses a RepoTree and returns an AnalysisResult.

    All logic is deterministic — no network calls, no AI.
    """

    def analyse(self, tree: RepoTree) -> AnalysisResult:
        result = AnalysisResult()

        # Pass 1 — per-file analysis
        for file_entry in tree.files:
            self._analyse_file(file_entry, result)

        # Pass 2 — repo-level aggregation
        self._aggregate_tech_stack(tree, result)
        self._aggregate_insights(tree, result)
        self._build_graph(tree, result)

        return result

    # ---------------------------------------------------------------- #
    # Pass 1 — per-file                                                  #
    # ---------------------------------------------------------------- #

    def _analyse_file(self, entry: FileEntry, result: AnalysisResult) -> None:
        if not entry.content:
            return

        if entry.extension == ".py":
            imports = self._extract_python_imports(entry)
        elif entry.extension in (".js", ".ts", ".jsx", ".tsx"):
            imports = self._extract_js_imports(entry.content)
        else:
            imports = []

        if imports:
            result.import_map[entry.path] = imports

        # Detect frameworks from this file's content
        self._detect_frameworks(entry.content, result)

    # ---------------------------------------------------------------- #
    # Python AST import extraction                                       #
    # ---------------------------------------------------------------- #

    def _extract_python_imports(self, entry: FileEntry) -> list[str]:
        """Parse .py file with AST; fall back to regex on syntax error."""
        imports: list[str] = []
        try:
            tree = ast.parse(entry.content, filename=entry.path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module.split(".")[0])
        except SyntaxError:
            logger.debug("AST parse failed for %s — falling back to regex", entry.path)
            imports = self._regex_python_imports(entry.content)
        return list(set(imports))

    @staticmethod
    def _regex_python_imports(content: str) -> list[str]:
        pattern = re.compile(
            r"^(?:import|from)\s+([\w]+)", re.MULTILINE
        )
        return list({m.group(1) for m in pattern.finditer(content)})

    # ---------------------------------------------------------------- #
    # JS / TS regex import extraction                                    #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _extract_js_imports(content: str) -> list[str]:
        """
        Matches:
          import X from 'module'
          import { X } from "module"
          require('module')
          export { X } from 'module'
        """
        pattern = re.compile(
            r"""(?:import|export).*?from\s+['"]([^'"]+)['"]"""
            r"""|require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
            re.MULTILINE,
        )
        imports = []
        for match in pattern.finditer(content):
            module = match.group(1) or match.group(2)
            if module:
                # Normalise: take the top-level package name
                top = module.lstrip("./").split("/")[0]
                if top:
                    imports.append(top)
        return list(set(imports))

    # ---------------------------------------------------------------- #
    # Framework detection                                                #
    # ---------------------------------------------------------------- #

    def _detect_frameworks(self, content: str, result: AnalysisResult) -> None:
        content_lower = content.lower()
        for framework, signatures in FRAMEWORK_SIGNATURES.items():
            if framework not in result.tech_stack.frameworks:
                if any(sig.lower() in content_lower for sig in signatures):
                    result.tech_stack.frameworks.append(framework)

    # ---------------------------------------------------------------- #
    # Pass 2 — aggregation                                               #
    # ---------------------------------------------------------------- #

    def _aggregate_tech_stack(self, tree: RepoTree, result: AnalysisResult) -> None:
        """Collect unique languages and package managers."""
        langs: set[str] = set()
        deps: set[str] = set()

        for entry in tree.files:
            if entry.language not in ("", "Unknown", "Markdown", "Text", "Config"):
                langs.add(entry.language)

            # Extract deps from manifest files
            fname = Path(entry.path).name
            if fname == "requirements.txt":
                deps.update(self._parse_requirements_txt(entry.content))
            elif fname == "package.json":
                deps.update(self._parse_package_json(entry.content))

            # Package managers
            pm = PACKAGE_MANAGER_FILES.get(fname)
            if pm and pm not in result.tech_stack.package_managers:
                result.tech_stack.package_managers.append(pm)

        result.tech_stack.languages = sorted(langs)
        result.tech_stack.dependencies = sorted(deps)[:40]   # cap at 40

    def _aggregate_insights(self, tree: RepoTree, result: AnalysisResult) -> None:
        ins = result.insights
        ins.total_files = tree.total_files
        ins.analysed_files = tree.analysed_files

        total_lines = 0
        for entry in tree.files:
            total_lines += entry.content.count("\n")
            fname = Path(entry.path).name
            rel = entry.path

            if fname in ENTRY_POINTS:
                ins.entry_points.append(entry.path)
            if fname in PACKAGE_MANAGER_FILES or fname.endswith((".cfg", ".ini", ".toml")):
                ins.config_files.append(entry.path)
            if any(p in rel for p in TEST_PATTERNS):
                ins.has_tests = True
            if any(ci in rel for ci in CI_FILES):
                ins.has_ci = True
            if fname in DOCKER_FILES:
                ins.has_docker = True

        ins.total_lines = total_lines

    # ---------------------------------------------------------------- #
    # Graph building                                                     #
    # ---------------------------------------------------------------- #

    def _build_graph(self, tree: RepoTree, result: AnalysisResult) -> None:
        """
        Nodes  = source files (Python/JS/TS only)
        Edges  = import relationships between files in the same repo
        """
        nodes: dict[str, ComponentNode] = {}
        edges: list[ComponentEdge] = []

        # Build a lookup: module_name → file_path for internal modules
        internal_modules = self._build_module_lookup(tree)

        for entry in tree.files:
            if entry.extension not in (".py", ".js", ".ts", ".tsx", ".jsx"):
                continue

            node_id = entry.path
            node_type = self._classify_node(entry)

            nodes[node_id] = ComponentNode(
                id=node_id,
                label=Path(entry.path).stem,
                node_type=node_type,
                language=entry.language,
                imports=result.import_map.get(entry.path, []),
            )

            # Draw edges only to other internal files
            for imp in result.import_map.get(entry.path, []):
                target_path = internal_modules.get(imp)
                if target_path and target_path != node_id:
                    edges.append(ComponentEdge(
                        source=node_id,
                        target=target_path,
                        relation="imports",
                    ))

        result.graph_data.nodes = list(nodes.values())
        result.graph_data.edges = self._dedupe_edges(edges)

    @staticmethod
    def _build_module_lookup(tree: RepoTree) -> dict[str, str]:
        """Map importable module name → relative file path."""
        lookup: dict[str, str] = {}
        for entry in tree.files:
            stem = Path(entry.path).stem
            lookup[stem] = entry.path
            # Also map the directory name for __init__.py packages
            if stem == "__init__":
                pkg = Path(entry.path).parent.name
                lookup[pkg] = entry.path
        return lookup

    @staticmethod
    def _classify_node(entry: FileEntry) -> str:
        rel = entry.path
        fname = Path(rel).name
        if fname in ENTRY_POINTS:
            return "entrypoint"
        if "test" in rel.lower() or "spec" in rel.lower():
            return "test"
        if any(rel.endswith(e) for e in (".cfg", ".ini", ".toml", ".yaml", ".yml")):
            return "config"
        if "service" in rel.lower() or "services" in rel.lower():
            return "service"
        return "module"

    @staticmethod
    def _dedupe_edges(edges: list[ComponentEdge]) -> list[ComponentEdge]:
        seen: set[tuple[str, str]] = set()
        unique = []
        for e in edges:
            key = (e.source, e.target)
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique

    # ---------------------------------------------------------------- #
    # Dependency file parsers                                            #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _parse_requirements_txt(content: str) -> list[str]:
        deps = []
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # Strip version specifiers: requests>=2.0 → requests
                name = re.split(r"[>=<!;\[]", line)[0].strip()
                if name:
                    deps.append(name)
        return deps

    @staticmethod
    def _parse_package_json(content: str) -> list[str]:
        import json
        deps: list[str] = []
        try:
            data = json.loads(content)
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                deps.extend(data.get(key, {}).keys())
        except (json.JSONDecodeError, AttributeError):
            pass
        return deps


# ------------------------------------------------------------------ #
# Convenience wrapper                                                  #
# ------------------------------------------------------------------ #

def analyse_repo(tree: RepoTree) -> AnalysisResult:
    return CodeAnalyzer().analyse(tree)
