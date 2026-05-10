"""tests/test_legacy_aliases_shim.py — AGT-9 deprecation shim coverage.

The submodule ``cross_ai_core.aliases`` was renamed to
``cross_ai_core.agents`` in 0.9.0.  A thin shim module remains for one
release so external callers that did
``from cross_ai_core.aliases import resolve_alias`` keep working.  This
test pins:

  * Importing the shim module emits a :class:`DeprecationWarning`.
  * Every legacy public name the shim re-exports actually resolves and
    points at the new symbol.
  * The legacy ``CROSS_AI_ALIASES_FILE`` env-var is no longer honoured
    for path resolution; setting it emits a :class:`DeprecationWarning`
    on first use.
"""
from __future__ import annotations

import importlib
import sys
import warnings

import pytest


@pytest.fixture
def fresh_aliases_import():
    """Force a clean re-import of cross_ai_core.aliases each test."""
    sys.modules.pop("cross_ai_core.aliases", None)
    yield
    sys.modules.pop("cross_ai_core.aliases", None)


def test_aliases_shim_emits_deprecation_warning(fresh_aliases_import):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("cross_ai_core.aliases")
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any(
        "cross_ai_core.aliases is deprecated" in str(w.message)
        for w in deprecations
    ), f"expected deprecation; got {[str(w.message) for w in deprecations]}"


def test_aliases_shim_reexports_legacy_names(fresh_aliases_import):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy = importlib.import_module("cross_ai_core.aliases")
    from cross_ai_core import agents as new

    # Every legacy public name should resolve and be the same object as
    # its new-module counterpart.
    pairs = [
        ("AliasSpec", "AgentSpec"),
        ("resolve_alias", "resolve_agent"),
        ("reload_aliases", "reload_agents"),
        ("get_aliases", "get_agents"),
        ("get_alias_load_error", "get_agent_load_error"),
        ("_AI_ALIASES", "_AGENTS"),
        ("_aliases_file_path", "_agents_file_path"),
    ]
    for legacy_name, new_name in pairs:
        assert hasattr(legacy, legacy_name), f"shim missing {legacy_name}"
        assert getattr(legacy, legacy_name) is getattr(new, new_name), (
            f"{legacy_name} should be the same object as {new_name}"
        )


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

