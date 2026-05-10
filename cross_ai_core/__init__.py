"""
cross_ai_core — Multi-provider AI dispatcher with caching and error handling.

Public API
----------
::

    from cross_ai_core import process_prompt, get_content, get_default_ai

    result = process_prompt("gemini", prompt, verbose=False, use_cache=True)
    text   = get_content("gemini", result.response)

Supported providers: xai, anthropic, openai, perplexity, gemini

Adding a provider
-----------------
1. Create ``cross_ai_core/ai_<name>.py`` implementing ``BaseAIHandler``.
2. Register in ``cross_ai_core/ai_handler.py``: add to ``AI_HANDLER_REGISTRY``
   and ``AI_LIST``.

Cache
-----
Responses are cached by default in ``~/.cross_api_cache/``.
Override with the ``CROSS_API_CACHE_DIR`` environment variable.
Bypass per-call with ``use_cache=False``, or globally with ``CROSS_NO_CACHE=1``.

Keys
----
The library reads API keys from ``os.environ``.  The calling application is
responsible for loading ``.env`` or ``~/.crossenv`` before importing.
"""

from cross_ai_core.ai_handler import (   # noqa: F401
    AI_HANDLER_REGISTRY,
    AI_LIST,
    AIResponse,
    check_api_key,
    get_ai_list,
    get_ai_make,
    get_ai_make_list,
    get_ai_model,
    get_content,
    get_content_auto,
    get_data_content,
    get_data_title,
    get_default_ai,
    get_rate_limit_concurrency,
    get_usage,
    process_prompt,
    put_content,
    put_content_auto,
    reset_client_cache,
)
from cross_ai_core.agents import (   # noqa: F401
    AgentSpec,
    AliasSpec,           # back-compat (deprecated, removed in 0.10.0)
    did_you_mean,
    get_agent_load_error,
    get_agents,
    get_alias_load_error,  # back-compat (deprecated, removed in 0.10.0)
    get_aliases,           # back-compat (deprecated, removed in 0.10.0)
    get_rate_limit_group,
    migrate_v1_to_v2,
    reload_agents,
    reload_aliases,        # back-compat (deprecated, removed in 0.10.0)
    resolve_agent,
    resolve_alias,         # back-compat (deprecated, removed in 0.10.0)
    write_agents_file,
)
from cross_ai_core.keys import (   # noqa: F401
    PROVIDER_API_KEY_ENV,
    api_key_env_var,
    has_api_key,
)
from cross_ai_core.discovery import (   # noqa: F401
    MODELS_CACHE_TTL_SECONDS,
    ModelInfo,
    get_available_models,
)
from cross_ai_core.recommendations import (   # noqa: F401
    RECOMMENDED_MODELS,
    get_recommended,
    get_recommended_default,
)
from cross_ai_core.ai_base import BaseAIHandler, _get_cache_dir as get_cache_dir  # noqa: F401
from cross_ai_core.ai_error_handler import (    # noqa: F401
    handle_api_error,
    retry_with_backoff,
    CrossAIError,
    QuotaExceededError,
    RateLimitError,
    TransientError,
)

try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    try:
        __version__ = _pkg_version("cross-ai-core")
    except PackageNotFoundError:
        __version__ = "0.0.0"   # running from source without install
except ImportError:
    __version__ = "0.0.0"

__all__ = [
    # Core dispatch
    "process_prompt",
    "get_content",
    "get_content_auto",
    "put_content",
    "put_content_auto",
    "get_data_content",
    "get_data_title",
    "get_default_ai",
    "get_ai_model",
    "get_ai_make",
    "get_ai_make_list",
    "get_ai_list",
    "get_rate_limit_concurrency",
    "get_usage",
    "check_api_key",
    # Registry
    "AI_HANDLER_REGISTRY",
    "AI_LIST",
    "AIResponse",
    "reset_client_cache",
    # Agents (AGT-1 / AGT-9)
    "AgentSpec",
    "resolve_agent",
    "get_agents",
    "get_agent_load_error",
    "did_you_mean",
    "get_rate_limit_group",
    "reload_agents",
    "migrate_v1_to_v2",
    "write_agents_file",
    # Back-compat (deprecated AGT-9, removed in 0.10.0)
    "AliasSpec",
    "resolve_alias",
    "get_aliases",
    "get_alias_load_error",
    "reload_aliases",
    # API-key detection (AGT-1c)
    "PROVIDER_API_KEY_ENV",
    "api_key_env_var",
    "has_api_key",
    # Model discovery (CAC-10h)
    "ModelInfo",
    "get_available_models",
    "MODELS_CACHE_TTL_SECONDS",
    "RECOMMENDED_MODELS",
    "get_recommended",
    "get_recommended_default",
    # Extension points
    "BaseAIHandler",
    "get_cache_dir",
    # Error handling
    "handle_api_error",
    "retry_with_backoff",
    "CrossAIError",
    "QuotaExceededError",
    "RateLimitError",
    "TransientError",
    # Package metadata
    "__version__",
]

