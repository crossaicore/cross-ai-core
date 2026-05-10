"""
tests/conftest.py — session-wide test fixtures.

AGT-1 changed the agent registry to no longer auto-seed built-in
provider names.  Pre-existing test files in this suite (test_ai_handler,
TestProcessPrompt, TestMakeStamp, …) call ``process_prompt("xai", …)``
or ``process_prompt("mock_ai", …)`` directly without first defining an
agent — they were written when those names were free.

Rather than rewrite every legacy test, this conftest emulates the
cross-st AGT-2 migration once at session start: it seeds one self-agent
per built-in provider plus the canonical mock provider names that the
ai_handler tests register at runtime via ``patch.dict``.

Tests in ``test_agents.py`` that explicitly want an empty registry use
their own ``agent_file`` fixture which monkey-patches
``CROSS_AI_AGENTS_FILE`` to a fresh tmp path and reloads — that path
takes precedence over this session-wide seed.
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict

import pytest

from cross_ai_core.agents import _AGENTS, AgentSpec, reload_agents
from cross_ai_core.ai_handler import AI_LIST


# Built-ins + mock provider names referenced by legacy tests.
_LEGACY_TEST_PROVIDERS: tuple[str, ...] = (
    "mock_ai", "mock_share", "mock_make", "prov_a", "prov_b",
)


@pytest.fixture(autouse=True)
def _seed_legacy_agent_registry(monkeypatch, tmp_path_factory):
    """Pre-populate ``_AGENTS`` with built-in + mock self-agents.

    Runs for **every** test.  Tests in ``test_agents.py`` overwrite
    ``CROSS_AI_AGENTS_FILE`` and call ``reload_agents()`` themselves —
    that wipes the seed and they get the empty-registry behaviour they
    expect, so this fixture does not interfere.
    """
    seed: "OrderedDict[str, AgentSpec]" = OrderedDict()
    for make in AI_LIST:
        seed[make] = AgentSpec(make=make, model=None)
    for mock in _LEGACY_TEST_PROVIDERS:
        seed[mock] = AgentSpec(make=mock, model=None)

    saved = OrderedDict(_AGENTS)
    _AGENTS.clear()
    _AGENTS.update(seed)
    try:
        yield
    finally:
        _AGENTS.clear()
        _AGENTS.update(saved)

