"""
cross_ai_core.keys — provider API-key detection (AGT-1c).

Single source of truth for "is this provider available right now?".  The
environment-variable map lives here so that ``check_api_key()`` (in
``ai_handler``) and the Agents v2 filtering surfaces in cross-st (``M``,
the ``A``-key rotation, the ``st-cross`` matrix) all consult the same
list.

Public API
----------
``PROVIDER_API_KEY_ENV`` — ``provider → tuple[str, …]``.  Each provider
maps to one **or more** acceptable env-var names; the first non-empty one
wins.  Multiple names exist because ``gemini`` historically accepts both
``GEMINI_API_KEY`` and ``GOOGLE_API_KEY``.

``has_api_key(provider) -> bool`` — does the current process environment
contain a non-empty key for *provider*?  Raises ``ValueError`` for an
unknown provider.

``api_key_env_var(provider) -> str`` — primary (canonical) env-var name
for *provider*.  Used by diagnostic messages that need a single name to
print.
"""
from __future__ import annotations

import os


# Ordered tuple — first non-empty value wins.  Keep the canonical name first.
PROVIDER_API_KEY_ENV: dict[str, tuple[str, ...]] = {
    "xai":        ("XAI_API_KEY",),
    "anthropic":  ("ANTHROPIC_API_KEY",),
    "openai":     ("OPENAI_API_KEY",),
    "perplexity": ("PERPLEXITY_API_KEY",),
    "gemini":     ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def has_api_key(provider: str) -> bool:
    """Return ``True`` iff a non-empty API key for *provider* is in the env.

    Args:
        provider: Provider identifier — one of the keys in
            :data:`PROVIDER_API_KEY_ENV` (``"xai"``, ``"anthropic"``,
            ``"openai"``, ``"perplexity"``, ``"gemini"``).

    Raises:
        ValueError: if *provider* is not a known provider.

    The check is value-only — we do not validate the key against the
    provider's auth endpoint.  Callers that want a live check should call
    ``check_api_key()`` from ``ai_handler``, which prints a diagnostic.
    """
    try:
        env_names = PROVIDER_API_KEY_ENV[provider]
    except KeyError:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Known providers: {sorted(PROVIDER_API_KEY_ENV)}"
        ) from None
    return any(os.environ.get(name, "").strip() for name in env_names)


def api_key_env_var(provider: str) -> str:
    """Return the canonical (first) env-var name for *provider*.

    Used by :func:`cross_ai_core.ai_handler.check_api_key` when it needs to
    tell the user *which* variable to set.  Raises ``ValueError`` for an
    unknown provider.
    """
    try:
        return PROVIDER_API_KEY_ENV[provider][0]
    except KeyError:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Known providers: {sorted(PROVIDER_API_KEY_ENV)}"
        ) from None

