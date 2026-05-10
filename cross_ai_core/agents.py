"""
cross_ai_core.agents — agent registry (AGT-1 / AGT-9).

An *agent* is a user-defined nickname mapping
``agent-name → (provider, model)``.  Every CLI command that takes
``--agent`` resolves the value through this module.

⚠️  Behaviour change in **0.8.0** (Agents v2):
    The registry no longer auto-seeds one entry per built-in provider.
    A fresh user with no ``~/.cross_ai_models.json`` gets an *empty*
    registry — every consumer must handle that case.  Migration of
    existing installs to first-class agents is the responsibility of the
    cross-st layer (AGT-2 in cross-st 0.10.0).

⚠️  Module rename in **0.9.0** (AGT-9):
    Was ``cross_ai_core.aliases``; the legacy import path still works
    for one release via a deprecation shim.  Likewise, the on-disk
    override env-var ``CROSS_AI_ALIASES_FILE`` is no longer honoured —
    only ``CROSS_AI_AGENTS_FILE``.  Setting the legacy var emits a
    one-time :class:`DeprecationWarning`.

Storage
-------
Agents live in ``~/.cross_ai_models.json``.  Override the path with
``CROSS_AI_AGENTS_FILE``.

Two on-disk schemas are accepted on read; the writer always emits **v2**.

v1 — legacy flat dict (cross-ai-core ≤ 0.7.x)::

    {
      "anthropic-opus":   {"make": "anthropic", "model": "claude-opus-4-5"},
      "anthropic-sonnet": {"make": "anthropic", "model": "claude-sonnet-4-5"}
    }

v2 — current envelope::

    {
      "version": 2,
      "agents": {
        "anthropic-opus":   {"provider": "anthropic", "model": "claude-opus-4-5"},
        "anthropic-sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-5"}
      },
      "_migrated_to_agents_v2": true
    }

Inner key naming
----------------
v1 used ``make``; v2 uses ``provider``.  The reader normalises both to the
internal name ``make`` (so :class:`AgentSpec` is unchanged).  The writer
emits ``provider`` for forward compatibility — the public-facing word is
*provider*.
"""
from __future__ import annotations

import difflib
import json
import os
import tempfile
import warnings
from collections import OrderedDict
from typing import Any, NamedTuple


# ── Schema version emitted by write_agents_file() ──────────────────────────────
SCHEMA_VERSION = 2
_MIGRATION_MARKER = "_migrated_to_agents_v2"


class AgentSpec(NamedTuple):
    """Resolved agent → (provider, model) pair.

    ``model`` may be ``None``, meaning "use the handler's compiled-in
    default for this provider".  Agents created by the v2 wizard always
    set an explicit model; ``None`` only persists for v1 records read in
    legacy mode.
    """
    make: str
    model: str | None


# Filled by _load_agents() at import time.  Consumers should call
# get_agents() rather than touching this directly.
_AGENTS: "OrderedDict[str, AgentSpec]" = OrderedDict()
_AGENT_LOAD_ERROR: str | None = None

# Track whether we've already warned about CROSS_AI_ALIASES_FILE.
_LEGACY_FILE_WARNED = False


# ── File-path resolution ───────────────────────────────────────────────────────

def _agents_file_path() -> str:
    """Path to the agents JSON file.

    Override precedence:
      1. ``CROSS_AI_AGENTS_FILE`` (preferred, post-0.8.0)
      2. ``~/.cross_ai_models.json`` (default — path retained for back-compat)

    The legacy ``CROSS_AI_ALIASES_FILE`` env-var is no longer honoured
    (AGT-9, 0.9.0).  If it is set, a one-time
    :class:`DeprecationWarning` is emitted directing the user to switch.
    """
    global _LEGACY_FILE_WARNED
    if not _LEGACY_FILE_WARNED and os.environ.get("CROSS_AI_ALIASES_FILE", "").strip():
        warnings.warn(
            "CROSS_AI_ALIASES_FILE is no longer honoured (since cross-ai-core 0.9.0); "
            "use CROSS_AI_AGENTS_FILE instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        _LEGACY_FILE_WARNED = True

    override = os.environ.get("CROSS_AI_AGENTS_FILE", "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser("~/.cross_ai_models.json")


# ── Schema parsing (AGT-1d) ────────────────────────────────────────────────────

def _detect_schema_version(raw: Any) -> int:
    """Return ``2`` for the v2 envelope, ``1`` for the legacy flat dict."""
    if isinstance(raw, dict) and raw.get("version") == 2 and isinstance(raw.get("agents"), dict):
        return 2
    return 1


def _normalise_inner_keys(spec: dict) -> tuple[str | None, Any]:
    """Return ``(make, model)`` from an inner agent spec.

    Accepts both v2 (``provider``) and v1 (``make``) inner keys.  When both
    are present, ``provider`` wins (v2 is canonical).
    """
    make = spec.get("provider")
    if make is None:
        make = spec.get("make")
    return make, spec.get("model")


def migrate_v1_to_v2(data: dict) -> dict:
    """Return the v2 envelope produced by migrating a v1 flat dict.

    Pure function — does not touch disk.  Used by the cross-st AGT-2
    migration step to upgrade an existing ``~/.cross_ai_models.json``
    written by cross-ai-core ≤ 0.7.1.

    Idempotent: if *data* is already v2, it is returned unchanged (with
    the migration marker forced to ``True``).

    Args:
        data: Parsed JSON content of the agents file.  May be the v1 flat
            shape ``{name: {"make": …, "model": …}}`` or the v2 envelope.

    Returns:
        A new dict in the v2 shape with ``provider``-keyed inner specs and
        ``_migrated_to_agents_v2: True``.
    """
    if _detect_schema_version(data) == 2:
        out = dict(data)
        out[_MIGRATION_MARKER] = True
        return out

    agents: dict[str, dict[str, Any]] = {}
    for name, spec in data.items():
        if not isinstance(spec, dict):
            # Skip junk silently — the loader will surface a precise error.
            continue
        make, model = _normalise_inner_keys(spec)
        if make is None:
            continue
        agents[name] = {"provider": make, "model": model}

    return {
        "version": SCHEMA_VERSION,
        "agents": agents,
        _MIGRATION_MARKER: True,
    }


# ── Loader (AGT-1a) ────────────────────────────────────────────────────────────

def _load_agents() -> None:
    """Populate ``_AGENTS`` from disk.  No built-in seeding.

    Behaviour matrix:
      * No file present  → empty registry, no error.
      * Empty / blank file → empty registry, no error.
      * Valid v2 envelope → agents loaded.
      * Valid v1 flat dict → agents loaded (inner ``make`` accepted).
      * Malformed JSON / wrong shape / unknown provider → empty registry,
        ``_AGENT_LOAD_ERROR`` populated with the diagnostic.

    The on-disk file is **never** rewritten by the loader — migration to
    v2 is the explicit responsibility of cross-st AGT-2 (which calls
    :func:`migrate_v1_to_v2` and then :func:`write_agents_file`).
    """
    global _AGENT_LOAD_ERROR
    _AGENT_LOAD_ERROR = None
    _AGENTS.clear()

    path = _agents_file_path()
    if not os.path.isfile(path):
        return

    try:
        with open(path) as f:
            text = f.read()
        if not text.strip():
            return
        raw = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        _AGENT_LOAD_ERROR = f"Could not read {path}: {exc}"
        return

    if not isinstance(raw, dict):
        _AGENT_LOAD_ERROR = f"{path}: top-level value must be a JSON object."
        return

    schema = _detect_schema_version(raw)
    body = raw["agents"] if schema == 2 else raw

    if not isinstance(body, dict):
        _AGENT_LOAD_ERROR = f"{path}: 'agents' must be a JSON object."
        return

    # Lazy import to avoid the ai_handler ↔ agents circular dependency.
    from .ai_handler import AI_HANDLER_REGISTRY  # known providers

    validated: list[tuple[str, AgentSpec]] = []
    for name, spec in body.items():
        if not isinstance(name, str) or not name:
            _AGENT_LOAD_ERROR = f"{path}: agent names must be non-empty strings."
            return
        if not isinstance(spec, dict):
            _AGENT_LOAD_ERROR = (
                f"{path}: value for {name!r} must be an object with "
                f"'provider' (or 'make') and 'model'."
            )
            return
        make, model = _normalise_inner_keys(spec)
        if not isinstance(make, str) or make not in AI_HANDLER_REGISTRY:
            _AGENT_LOAD_ERROR = (
                f"{path}: agent {name!r} has unknown provider {make!r}. "
                f"Known providers: {sorted(AI_HANDLER_REGISTRY)}"
            )
            return
        if model is not None and not isinstance(model, str):
            _AGENT_LOAD_ERROR = (
                f"{path}: agent {name!r} 'model' must be a string or null."
            )
            return
        validated.append((name, AgentSpec(make=make, model=model)))

    for name, spec in validated:
        _AGENTS[name] = spec


def reload_agents() -> None:
    """Re-read the agents file from disk.

    Called by tests, by ``st-admin`` after it edits the file, and by
    cross-st AGT-2 after migration.
    """
    _load_agents()


# ── Public accessors ───────────────────────────────────────────────────────────

def get_agents() -> "OrderedDict[str, AgentSpec]":
    """Return the live agent registry (a reference — do not mutate)."""
    return _AGENTS


def get_agent_load_error() -> str | None:
    """Return the last load-error message, or ``None`` if loading succeeded."""
    return _AGENT_LOAD_ERROR


# ── Writer (AGT-1d) ────────────────────────────────────────────────────────────

def write_agents_file(
    agents: "dict[str, AgentSpec] | OrderedDict[str, AgentSpec]",
    path: str | None = None,
) -> str:
    """Atomically write *agents* to disk in the v2 envelope.

    Args:
        agents: Mapping of agent name → :class:`AgentSpec`.  May be a
            plain dict or an OrderedDict; iteration order is preserved.
        path:   Override path.  Defaults to :func:`_agents_file_path`.

    Returns:
        The path actually written.

    Behaviour:
        * Always emits the v2 envelope with ``"provider"`` inner key and
          ``_migrated_to_agents_v2: True``.
        * Atomic: writes to a temp file in the same directory, then
          ``os.replace`` over the destination.
        * Caller is responsible for calling :func:`reload_agents` if the
          in-process registry should pick up the change immediately.
    """
    target = os.path.expanduser(path) if path else _agents_file_path()
    parent = os.path.dirname(target) or "."
    os.makedirs(parent, exist_ok=True)

    envelope: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "agents": {
            name: {"provider": spec.make, "model": spec.model}
            for name, spec in agents.items()
        },
        _MIGRATION_MARKER: True,
    }

    fd, tmp = tempfile.mkstemp(prefix=".cross_ai_models.", dir=parent)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(envelope, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


# ── Resolver (AGT-1a) ──────────────────────────────────────────────────────────

def did_you_mean(bad: str, candidates) -> str | None:
    """Return the closest candidate to *bad*, or ``None`` if no good match."""
    matches = difflib.get_close_matches(bad, list(candidates), n=1, cutoff=0.6)
    return matches[0] if matches else None


_NO_AGENTS_HINT = (
    "No agents defined.  Run 'st-admin --setup' "
    "(or 'st-admin > AI > Manage > Add') to create one."
)


def resolve_agent(agent: str) -> AgentSpec:
    """Return the (provider, model) pair for *agent*.

    Resolution (post-AGT-1a):
      1. Look up *agent* in the loaded registry.  If present → return.
      2. If the registry is **empty**, raise ``ValueError`` with the
         "no agents defined" hint pointing at ``st-admin --setup``.
      3. Otherwise raise ``ValueError`` with a ``did_you_mean`` suggestion.

    There is **no** silent fallback to "is this a known provider name?" —
    that auto-seeded behaviour was removed in 0.8.0.  Callers that want
    to accept a bare provider name must define an agent for it (the
    cross-st AGT-2 migration creates one starter agent per provider with
    an API key in ``~/.crossenv``).
    """
    spec = _AGENTS.get(agent)
    if spec is not None:
        return spec

    if not _AGENTS:
        # Keep the legacy "Unsupported AI" prefix so existing callers /
        # tests that grep on it continue to work, but lead with the
        # actionable hint.
        raise ValueError(
            f"Unsupported AI model: {agent!r}.  {_NO_AGENTS_HINT}"
        )

    suggestion = did_you_mean(agent, _AGENTS.keys())
    hint = f" Did you mean {suggestion!r}?" if suggestion else ""
    raise ValueError(
        f"Unsupported AI model: {agent!r}.{hint} "
        f"Defined agents: {list(_AGENTS.keys())}"
    )


def get_rate_limit_group(agent: str) -> tuple[str, int]:
    """Return ``(group_key, concurrency_cap)`` for *agent*.

    ``group_key`` is the resolved provider — every agent sharing a
    provider shares the same rate-limit group, so callers can key a
    semaphore on the group key to prevent multiple agents from blowing
    through one provider's quota.
    """
    from .ai_handler import get_rate_limit_concurrency
    make, _ = resolve_agent(agent)
    return make, get_rate_limit_concurrency(make)


# ── Back-compat aliases (deprecated, removed in cross-ai-core 0.10.0) ─────────
# These re-export the new symbols under their pre-AGT-9 names so internal
# code (and a small number of external importers) can continue to work
# during the one-release deprecation window.  The submodule
# ``cross_ai_core.aliases`` (the legacy module path) emits a
# DeprecationWarning on import; importing these names from
# ``cross_ai_core.agents`` directly is silent — the warning is path-based.
AliasSpec = AgentSpec
_AI_ALIASES = _AGENTS  # same dict object — mutations stay in sync
resolve_alias = resolve_agent
reload_aliases = reload_agents
get_aliases = get_agents
get_alias_load_error = get_agent_load_error


# Load agents at import time.  Done last so the helpers above are defined.
_load_agents()

