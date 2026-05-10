"""
cross_ai_core.aliases — DEPRECATED back-compat shim (AGT-9, 0.9.0).

Importing this module emits a :class:`DeprecationWarning`.  Switch to
:mod:`cross_ai_core.agents` (or import the public names directly from
``cross_ai_core``).

This shim re-exports every public name that lived in the old
``aliases.py`` module so external code that does
``from cross_ai_core.aliases import resolve_alias`` continues to work
unmodified for one release.  Removed in cross-ai-core 0.10.0.
"""
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "cross_ai_core.aliases is deprecated; import from cross_ai_core.agents "
    "(or directly from cross_ai_core).  This shim will be removed in "
    "cross-ai-core 0.10.0.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export every name that used to live here.  The new canonical module
# defines the legacy names as back-compat assignments at the bottom of
# the file, so we can pull them through as-is.
from cross_ai_core.agents import (  # noqa: F401  (re-export)
    AgentSpec,
    AliasSpec,
    SCHEMA_VERSION,
    _AGENTS,
    _AI_ALIASES,
    _MIGRATION_MARKER,
    _agents_file_path,
    _detect_schema_version,
    _load_agents,
    _normalise_inner_keys,
    did_you_mean,
    get_agent_load_error,
    get_agents,
    get_alias_load_error,
    get_aliases,
    get_rate_limit_group,
    migrate_v1_to_v2,
    reload_agents,
    reload_aliases,
    resolve_agent,
    resolve_alias,
    write_agents_file,
)

# The pre-rename internal name for the file-path helper.
_aliases_file_path = _agents_file_path

