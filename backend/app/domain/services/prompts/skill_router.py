"""Small deterministic skill router used before the planner sees a task.

The workspace contains many playbooks, but loading the whole catalog into every
planning prompt creates instruction noise.  This router only exposes a few
candidate playbooks whose trigger terms match the user's request.  The model
still decides whether a candidate is actually needed; the router only narrows
the search space.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class SkillRoute:
    name: str
    use_when: str
    triggers: frozenset[str]


_ROUTES: tuple[SkillRoute, ...] = (
    SkillRoute(
        "webdev-readme-fullstack",
        "a persistent web app with users, data, auth, or a backend",
        frozenset({"web app", "fullstack", "dashboard", "saas", "chat app", "login", "database"}),
    ),
    SkillRoute(
        "webdev-readme-static",
        "a static landing page, portfolio, brochure, or content site",
        frozenset({"landing page", "portfolio", "brochure", "static site", "company profile"}),
    ),
    SkillRoute(
        "web-design-engineer",
        "any visual frontend, dashboard, UI, or polished browser deliverable",
        frozenset({"ui", "ux", "frontend", "website", "web page", "dashboard", "design", "landing"}),
    ),
    SkillRoute(
        "webapp-testing",
        "browser verification, screenshots, console checks, or local web testing",
        frozenset({"browser test", "playwright", "screenshot", "console error", "verify the app"}),
    ),
    SkillRoute(
        "browser-automation",
        "form filling, scraping, or an interactive logged-in browser workflow",
        frozenset({"browser", "scrape", "scraping", "form", "login flow", "website"}),
    ),
    SkillRoute(
        "python-api-service",
        "a Python REST API or FastAPI/Flask service",
        frozenset({"fastapi", "flask", "rest api", "python api", "backend api"}),
    ),
    SkillRoute(
        "webdev-llm-integration",
        "LLM, chat completion, structured output, or streaming integration in a build",
        frozenset({"llm", "chatbot", "ai chat", "openai", "streaming response", "model"}),
    ),
    SkillRoute(
        "pptx",
        "creating, editing, or analyzing PowerPoint presentations",
        frozenset({"pptx", "powerpoint", "slide deck", "presentation"}),
    ),
    SkillRoute(
        "docx",
        "creating, editing, or analyzing Word documents",
        frozenset({"docx", "word document", "mail merge", "tracked changes"}),
    ),
    SkillRoute(
        "pdf",
        "reading, editing, extracting, or generating PDFs",
        frozenset({"pdf", "portable document"}),
    ),
    SkillRoute(
        "xlsx",
        "spreadsheet editing, formulas, recalculation, or workbook analysis",
        frozenset({"xlsx", "spreadsheet", "excel", "workbook", "formula"}),
    ),
    SkillRoute(
        "web-research",
        "multi-source web research, fact checking, or a sourced report",
        frozenset({"research", "fact check", "sources", "citation", "compare"}),
    ),
    SkillRoute(
        "deep-research",
        "long-form, multi-source research requiring synthesis",
        frozenset({"deep research", "literature review", "investigation", "in-depth"}),
    ),
    SkillRoute(
        "data-analysis",
        "cleaning data, analyzing CSVs, making charts, or writing a data report",
        frozenset({"csv", "data analysis", "dataset", "chart", "visualize data", "statistics"}),
    ),
    SkillRoute(
        "image-processing",
        "deterministic image manipulation, conversion, crop, or resize",
        frozenset({"crop image", "resize image", "convert image", "image processing"}),
    ),
    SkillRoute(
        "imagegen",
        "routing and prompt construction for generated visual assets",
        frozenset({"generate image", "create an image", "illustration", "visual asset"}),
    ),
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def select_skill_routes(text: str, limit: int = 5) -> List[SkillRoute]:
    """Return a small, stable set of routes ordered by relevance."""
    haystack = _normalise(text)
    if not haystack or limit <= 0:
        return []

    scored: list[tuple[int, int, SkillRoute]] = []
    for index, route in enumerate(_ROUTES):
        score = sum(2 if len(trigger.split()) > 1 else 1
                    for trigger in route.triggers if trigger in haystack)
        if score:
            scored.append((score, -index, route))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [route for _, _, route in scored[:limit]]


def render_skill_context(text: str, limit: int = 5) -> str:
    """Render only relevant skill routes for a planner/executor prompt."""
    routes = select_skill_routes(text, limit=limit)
    if not routes:
        return (
            "<skill_context>\n"
            "No specialized playbook is apparent from this request. "
            "Do not load the entire skill catalog; use the normal tools and "
            "verify the result.\n"
            "</skill_context>"
        )

    rows = "\n".join(
        f"- {route.name}: use when {route.use_when}."
        for route in routes
    )
    return (
        "<skill_context>\n"
        "Candidate playbooks selected from the request (not mandatory):\n"
        f"{rows}\n"
        "Read only a matching SKILL.md when the task actually enters that "
        "domain. Do not load unrelated playbooks.\n"
        "</skill_context>"
    )


def route_names(text: str, limit: int = 5) -> Iterable[str]:
    """Expose names for diagnostics/tests without exposing the route table."""
    return (route.name for route in select_skill_routes(text, limit=limit))