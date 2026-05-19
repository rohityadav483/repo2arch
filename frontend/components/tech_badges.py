"""
tech_badges.py
--------------
Renders coloured tech stack badges and a language breakdown bar
for the detected languages, frameworks and dependencies.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


# ------------------------------------------------------------------ #
# Colour maps                                                          #
# ------------------------------------------------------------------ #

LANGUAGE_COLOURS: dict[str, str] = {
    "Python":     "#3776AB",
    "JavaScript": "#F7DF1E",
    "TypeScript": "#3178C6",
    "JSON":       "#888780",
    "YAML":       "#CB171E",
    "TOML":       "#9C4121",
    "Markdown":   "#083FA1",
    "Config":     "#6C757D",
}

FRAMEWORK_COLOURS: dict[str, str] = {
    "FastAPI":     "#009688",
    "Django":      "#092E20",
    "Flask":       "#000000",
    "React":       "#61DAFB",
    "Next.js":     "#000000",
    "Vue":         "#42B883",
    "Express":     "#000000",
    "NestJS":      "#E0234E",
    "Streamlit":   "#FF4B4B",
    "Pydantic":    "#E92063",
    "SQLAlchemy":  "#D71F00",
    "Pytest":      "#0A9EDC",
    "NumPy":       "#013243",
    "Pandas":      "#150458",
    "Torch":       "#EE4C2C",
    "TensorFlow":  "#FF6F00",
    "Prisma":      "#2D3748",
    "Axios":       "#5A29E4",
    "TypeORM":     "#E83524",
    "Jest":        "#C21325",
}

DEFAULT_LANG_COLOUR = "#444"
DEFAULT_FW_COLOUR   = "#2d3561"
DEFAULT_DEP_COLOUR  = "#1e2a20"


# ------------------------------------------------------------------ #
# Public renderers                                                     #
# ------------------------------------------------------------------ #

def render_tech_stack(tech_stack: dict[str, Any]) -> None:
    if not tech_stack:
        st.info("No tech stack detected.")
        return

    languages    = tech_stack.get("languages", [])
    frameworks   = tech_stack.get("frameworks", [])
    dependencies = tech_stack.get("dependencies", [])
    pkg_managers = tech_stack.get("package_managers", [])

    if languages:
        st.markdown("**Languages**")
        render_language_bar(languages)
        st.markdown(
            _badge_row(languages, LANGUAGE_COLOURS, DEFAULT_LANG_COLOUR),
            unsafe_allow_html=True,
        )
        st.markdown("&nbsp;", unsafe_allow_html=True)

    if frameworks:
        st.markdown("**Frameworks & Libraries**")
        st.markdown(
            _badge_row(frameworks, FRAMEWORK_COLOURS, DEFAULT_FW_COLOUR),
            unsafe_allow_html=True,
        )
        st.markdown("&nbsp;", unsafe_allow_html=True)

    if pkg_managers:
        st.markdown("**Package Managers**")
        st.markdown(
            _badge_row(pkg_managers, {}, "#333"),
            unsafe_allow_html=True,
        )
        st.markdown("&nbsp;", unsafe_allow_html=True)

    if dependencies:
        with st.expander(f"📦 Dependencies ({len(dependencies)})"):
            st.markdown(_chip_row(dependencies), unsafe_allow_html=True)


def render_language_bar(languages: list[str]) -> None:
    if not languages:
        return

    n = len(languages)
    width_pct = 100 / n

    segments = "".join(
        f"<div style='"
        f"width:{width_pct:.1f}%;"
        f"background:{LANGUAGE_COLOURS.get(lang, DEFAULT_LANG_COLOUR)};"
        f"height:10px;display:inline-block;"
        f"' title='{lang}'></div>"
        for lang in languages
    )

    st.markdown(
        f"<div style='border-radius:6px;overflow:hidden;margin-bottom:8px'>"
        f"{segments}</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ #
# Compact summary (sidebar / history)                                  #
# ------------------------------------------------------------------ #

def render_stack_compact(tech_stack: dict[str, Any]) -> None:
    languages  = tech_stack.get("languages", [])
    frameworks = tech_stack.get("frameworks", [])[:4]
    items = languages + frameworks

    if not items:
        st.caption("No tech stack detected")
        return

    st.markdown(
        _badge_row(
            items,
            {**LANGUAGE_COLOURS, **FRAMEWORK_COLOURS},
            DEFAULT_LANG_COLOUR,
            font_size="11px",
            padding="3px 8px",
        ),
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ #
# HTML helpers                                                         #
# ------------------------------------------------------------------ #

def _badge_row(
    items: list[str],
    colour_map: dict[str, str],
    default_colour: str,
    font_size: str = "12px",
    padding: str = "4px 10px",
) -> str:
    badges = []
    for item in items:
        bg = colour_map.get(item, default_colour)
        fg = _readable_text_colour(bg)
        badges.append(
            f"<span style='"
            f"background:{bg};color:{fg};padding:{padding};"
            f"border-radius:20px;font-size:{font_size};font-weight:600;"
            f"margin:3px 4px 3px 0;display:inline-block;"
            f"border:1px solid rgba(255,255,255,0.1);"
            f"'>{item}</span>"
        )
    return (
        "<div style='display:flex;flex-wrap:wrap;gap:2px;margin-bottom:4px'>"
        + "".join(badges)
        + "</div>"
    )


def _chip_row(items: list[str]) -> str:
    chips = "".join(
        f"<code style='"
        f"background:#1e2a20;color:#1D9E75;padding:3px 8px;"
        f"border-radius:4px;font-size:11px;margin:2px 3px 2px 0;"
        f"display:inline-block;border:1px solid #2d5631;"
        f"'>{dep}</code>"
        for dep in items
    )
    return (
        "<div style='display:flex;flex-wrap:wrap;gap:2px'>"
        + chips
        + "</div>"
    )


def _readable_text_colour(hex_colour: str) -> str:
    hex_colour = hex_colour.lstrip("#")
    if len(hex_colour) != 6:
        return "#ffffff"
    try:
        r, g, b = (int(hex_colour[i:i+2], 16) for i in (0, 2, 4))
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#111111" if luminance > 0.55 else "#ffffff"
    except ValueError:
        return "#ffffff"