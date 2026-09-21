from app.domain.services.prompts.planner import build_runtime_plan_prompt
from app.domain.services.prompts.skill_router import render_skill_context, select_skill_routes
from app.domain.services.prompts.system import get_runtime_system_prompt, get_system_prompt


def test_skill_router_keeps_candidates_relevant_and_bounded():
    routes = select_skill_routes("buat landing page modern", limit=5)
    names = {route.name for route in routes}

    assert {"webdev-readme-static", "web-design-engineer"} <= names
    assert "pptx" not in names
    assert len(routes) <= 5


def test_skill_context_does_not_load_the_whole_catalog():
    context = render_skill_context("analisis file xlsx dan buat chart")

    assert "xlsx" in context
    assert "data-analysis" in context
    assert "pptx" not in context
    assert "Do not load unrelated playbooks" in context


def test_compact_system_prompt_is_smaller_but_keeps_environment_contract():
    compact = get_runtime_system_prompt(
        user_home="/home/user/session",
        upload_dir="/home/user/session/upload",
    )
    legacy = get_system_prompt(
        user_home="/home/user/session",
        upload_dir="/home/user/session/upload",
    )

    assert len(compact) < len(legacy)
    assert "/home/user/session" in compact
    assert "NEVER reveal" in compact


def test_runtime_plan_prompt_injects_only_request_specific_skills():
    prompt = build_runtime_plan_prompt("buat landing page modern", "")

    assert "web-design-engineer" in prompt
    assert "webdev-readme-static" in prompt
    assert "pptx" not in prompt
    assert "Return only JSON" in prompt