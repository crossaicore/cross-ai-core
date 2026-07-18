"""tests/test_legacy_aliases_shim.py — AGT-9 shim *removal* coverage.

The submodule ``cross_ai_core.aliases`` was a one-release deprecation
shim (introduced 0.9.0) that re-exported the symbols which moved to
``cross_ai_core.agents``.  It was **removed in cross-ai-core 0.11.0**.

These tests pin the removal (inverted from the old shim-behaviour tests):

  * Importing ``cross_ai_core.aliases`` now raises :class:`ModuleNotFoundError`.
  * The canonical ``cross_ai_core.agents`` module is unaffected.
  * The legacy ``CROSS_AI_ALIASES_FILE`` env-var is still *not* honoured
    for path resolution; using it emits a :class:`DeprecationWarning` on
    first use (this behaviour lives in ``agents.py`` and outlives the shim).
"""
from __future__ import annotations

import importlib
import sys
import warnings

import pytest


@pytest.fixture
def fresh_aliases_import():
    """Ensure no stale cross_ai_core.aliases entry lingers in sys.modules."""
    sys.modules.pop("cross_ai_core.aliases", None)
    yield
    sys.modules.pop("cross_ai_core.aliases", None)


def test_aliases_shim_module_removed(fresh_aliases_import):
    """The deprecated shim module must no longer be importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("cross_ai_core.aliases")


def test_agents_module_still_importable():
    """Removing the shim must not disturb the canonical module."""
    agents = importlib.import_module("cross_ai_core.agents")
    assert hasattr(agents, "resolve_agent")
    assert hasattr(agents, "get_agents")


def test_legacy_env_var_emits_deprecation(monkeypatch, tmp_path):
    """CROSS_AI_ALIASES_FILE is no longer honoured; using it warns once."""
    from cross_ai_core import agents

    monkeypatch.setenv("CROSS_AI_ALIASES_FILE", str(tmp_path / "ignored.json"))
    monkeypatch.delenv("CROSS_AI_AGENTS_FILE", raising=False)

    # Reset the one-shot warned flag so the warning actually fires.
    agents._LEGACY_FILE_WARNED = False

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        path = agents._agents_file_path()

    assert path.endswith(".cross_ai_models.json"), (
        f"legacy env var should NOT redirect path resolution; got {path}"
    )
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any(
        "CROSS_AI_ALIASES_FILE is no longer honoured" in str(w.message)
        for w in deprecations
    )

