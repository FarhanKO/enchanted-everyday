"""Role prompts: every one renders, carries its brand documents and quotes the enforced numbers."""

import re
from pathlib import Path

import pytest

from engine.llm import schemas as s
from engine.llm.prompts import ROLES, role_prompt, system_prompt

BRAND = Path(__file__).parent.parent / "brand"


@pytest.mark.parametrize("role", ROLES)
def test_role_prompt_renders(role):
    text = role_prompt(role)
    assert text.startswith("# Role: ")
    assert not re.search(r"\$\{?\w", text), "unfilled placeholder"


@pytest.mark.parametrize("role", ROLES)
def test_system_prompt_carries_its_brand_documents(role):
    text = system_prompt(role, BRAND)
    for name in ROLES[role]:
        tag = Path(name).stem
        assert f"<{tag}>" in text and f"</{tag}>" in text


@pytest.mark.parametrize("role", ROLES)
def test_role_prompts_name_no_protected_style(role):
    lowered = role_prompt(role).lower()
    assert not [t for t in s.BANNED_STYLE_TERMS if t in lowered]


def test_script_writer_quotes_the_enforced_limits():
    text = role_prompt("script_writer")
    assert f"{s.MAX_HOOK_WORDS} words at most" in text
    assert f"{s.MIN_WORDS}-{s.MAX_WORDS} spoken words" in text
    assert f"{s.MIN_DURATION_S}-{s.MAX_DURATION_S} seconds" in text


def test_visual_director_quotes_the_enforced_limits():
    text = role_prompt("visual_director")
    assert f"{s.MIN_SHOTS}-{s.MAX_SHOTS} shots" in text
    assert f"At most {s.MAX_AI_CLIPS} `ai_clip`" in text
