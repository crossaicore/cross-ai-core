"""
tests/conftest.py — session-wide test fixtures.

AGT-1 changed the alias registry to no longer auto-seed built-in
provider names.  Pre-existing test files in this suite (test_ai_handler,
TestProcessPrompt, TestMakeStamp, …) call ``process_prompt("xai", …)``
or ``process_prompt("mock_ai", …)`` directly without first defining an
agent — they were written when those names were free.

Rather than rewrite every legacy test, this conftest emulates the
cross-st AGT-2 migration once at session start: it seeds one self-alias
per built-in provider plus the canonical mock provider names that the
ai_handler tests register at runtime via ``patch.dict``.

Tests in ``test_aliases.py`` that explicitly want an empty registry use
their own ``alias_file`` fixture which monkey-patches
``CROSS_AI_AGENTS_FILE`` to a fresh tmp path and reloads — that path
takes precedence over this session-wide seed.
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict

import pytest

from cross_ai_core.aliases import _AI_ALIASES, AliasSpec, reload_aliases
from cross_ai_core.ai_handler import AI_LIST


# Built-ins + mock provider names referenced by legacy tests.
_LEGACY_TEST_PROVIDERS: tuple[str, ...] = (
    "mock_ai", "mock_share", "mock_make", "prov_a", "prov_b",
)


@pytest.fixture(autouse=True)
def _seed_legacy_alias_registry(monkeypatch, tmp_path_factory):
    """Pre-populate ``_AI_ALIASES`` with built-in + mock self-aliases.

    Runs for **every** test.  Tests in ``test_aliases.py`` overwrite
    ``CROSS_AI_AGENTS_FILE`` and call ``reload_aliases()`` themselves —
    that wipes the seed and they get the empty-registry behaviour they
    expect, so this fixture does not interfere.
    """
    seed: "OrderedDict[str, AliasSpec]" = OrderedDict()
    for make in AI_LIST:
        seed[make] = AliasSpec(make=make, model=None)
    for mock in _LEGACY_TEST_PROVIDERS:
        seed[mock] = AliasSpec(make=mock, model=None)

    saved = OrderedDict(_AI_ALIASES)
    _AI_ALIASES.clear()
    _AI_ALIASES.update(seed)
    try:
        yield
    finally:
        _AI_ALIASES.clear()
        _AI_ALIASES.update(saved)

