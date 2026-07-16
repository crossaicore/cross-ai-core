import os
import threading
from typing import Any, Callable

from .ai_anthropic import AnthropicHandler
from .ai_gemini import GeminiHandler
from .ai_ollama import OllamaHandler
from .ai_openai import OpenAIHandler
from .ai_perplexity import PerplexityHandler
from .ai_xai import XAIHandler
from .ai_error_handler import handle_api_error


class AIResponse:
    """
    Wrapper for AI API responses with metadata.
    
    Provides backward compatibility by unpacking as a 4-tuple,
    while also exposing additional metadata like cache status.
    
    Example:
        # Old code (still works):
        payload, client, response, model = process_prompt(...)
        
        # New code (access metadata):
        result = process_prompt(...)
        if result.was_cached:
            print("Response was cached")
    """
    def __init__(self, payload, client, response, model, was_cached):
        self.payload = payload
        self.client = client
        self.response = response
        self.model = model
        self.was_cached = was_cached
    
    def __iter__(self):
        """Enable backward-compatible tuple unpacking."""
        return iter((self.payload, self.client, self.response, self.model))
    
    def __getitem__(self, index):
        """Enable backward-compatible indexing."""
        return (self.payload, self.client, self.response, self.model)[index]
    
    def __len__(self) -> int:
        """Return tuple length for compatibility."""
        return 4

    def __repr__(self) -> str:
        """Human-readable summary for debugging."""
        preview = ""
        if isinstance(self.response, dict):
            from .ai_handler import get_content_auto
            try:
                text = get_content_auto(self.response)
                preview = repr(text[:80] + "…" if len(text) > 80 else text)
            except Exception:
                pass
        cached = "cached" if self.was_cached else "live"
        return f"AIResponse(model={self.model!r}, {cached}, content={preview})"


AI_HANDLER_REGISTRY = {
    "xai": XAIHandler,
    "anthropic": AnthropicHandler,
    "openai": OpenAIHandler,
    "perplexity": PerplexityHandler,
    "gemini": GeminiHandler,
    "ollama": OllamaHandler,   # OLL-2: local/LAN provider (no API key)
}

AI_LIST = ["xai", "anthropic", "openai", "perplexity", "gemini", "ollama"]

# Per-provider default semaphore sizes for concurrent callers (e.g. PAR-1 in st-cross).
# Values are conservative starting points based on free/starter tier rate limits.
# Consumers can override at runtime; these are advisory defaults only.
_RATE_LIMIT_CONCURRENCY: dict[str, int] = {
    "xai":        3,
    "anthropic":  2,
    "openai":     3,
    "perplexity": 2,
    "gemini":     5,
    # Ollama is local/LAN: concurrency is bound by the host's RAM/VRAM, not a
    # provider rate limit.  Conservative default for typical home hardware;
    # override per-machine with OLLAMA_MAX_CONCURRENCY (see below).
    "ollama":     2,
}


# ── Per-provider client cache (CAC-8) ─────────────────────────────────────────
#
# SDK clients (anthropic.Anthropic, openai.OpenAI, google.genai.Client) carry
# an httpx connection pool, TLS context, and auth state.  Reusing one client
# across calls amortises that cost and keeps TCP keep-alive warm — meaningful
# for st-speed (50 calls / provider) and PAR-1 subprocesses that make multiple
# calls to the same provider.
#
# Constraints (must be preserved by callers):
#   * Not safe across os.fork() — child must call reset_client_cache() first.
#     cross-st uses subprocess (fresh interpreter), so this is currently moot.
#   * API key changes via os.environ are NOT re-read automatically.  Callers
#     that rotate keys (e.g. st-admin --setup rewriting ~/.crossenv) must call
#     reset_client_cache(make) afterwards.
#   * The cache is process-local; PAR-1 subprocesses each get their own.
#
# Disable globally with CROSS_NO_CLIENT_CACHE=1 (mirrors CROSS_NO_CACHE).

_client_cache: dict[str, Any] = {}
_client_cache_lock = threading.Lock()


def _get_or_create_client(handler_cls, ai_key: str) -> Any:
    """Return a cached client for *ai_key*, creating it on first use.

    Uses double-checked locking: the hot path (cache hit) is lock-free; the
    cold path (first miss) takes the lock, re-checks, then constructs.

    Honours ``CROSS_NO_CLIENT_CACHE=1`` — when set, every call constructs a
    fresh client and the cache is bypassed entirely.
    """
    if os.environ.get("CROSS_NO_CLIENT_CACHE"):
        return handler_cls.get_client()

    cached = _client_cache.get(ai_key)
    if cached is not None:
        return cached

    with _client_cache_lock:
        # Re-check under the lock — another thread may have populated it.
        cached = _client_cache.get(ai_key)
        if cached is not None:
            return cached
        client = handler_cls.get_client()
        _client_cache[ai_key] = client
        return client


def reset_client_cache(make: "str | None" = None) -> None:
    """Drop cached SDK client(s) so the next call rebuilds.

    Call after rotating an API key, after ``os.fork()``, or in test teardown.

    Args:
        make: Provider key or alias to drop (e.g. ``"openai"`` or
              ``"openai-mini"``).  Aliases resolve to their make first, since
              all aliases sharing a make share one cached client.  When
              ``None``, every cached client is dropped.
    """
    with _client_cache_lock:
        if make is None:
            _client_cache.clear()
        else:
            # Resolve alias → make so reset by alias works as expected.
            try:
                from .agents import resolve_agent
                make = resolve_agent(make).make
            except ValueError:
                pass  # unknown — fall through and try the literal key
            _client_cache.pop(make, None)



def process_prompt(
    ai_key: str,
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    verbose: bool = False,
    use_cache: bool = True,
    retry_budget: "float | None" = None,
    client: "Any | None" = None,
) -> "AIResponse":
    """
    Process a prompt with the specified AI.

    Args:
        ai_key:    Provider key, e.g. ``"gemini"`` or ``"anthropic"``.
        prompt:    User prompt text.
        system:    Optional system instruction; ``None`` uses the provider default.
        model:     Optional model override for this call.  Resolution order:
                   explicit ``model`` arg → ``<AI_KEY_UPPER>_MODEL`` env var →
                   handler default (e.g. ``"gemini-2.5-flash"``).
        verbose:   Print cache hit/miss messages.
        use_cache: Read from / write to the on-disk cache (overridden by
                   ``CROSS_NO_CACHE=1``).
        retry_budget: Optional total time budget in seconds passed to
                   ``retry_with_backoff`` when wrapping process_prompt calls.
                   Not used internally by process_prompt itself; callers may
                   pass it through to ``retry_with_backoff``.
        client:    Optional pre-built provider client to use for this call.
                   When ``None`` (the default), a cached singleton is used —
                   see ``_get_or_create_client`` and ``reset_client_cache``.
                   Pass an explicit client (e.g. a mock) to bypass the cache.

    Returns:
        AIResponse: Wrapper object that unpacks as (payload, client, response, model)
                   for backward compatibility, but also provides .was_cached attribute.

    Raises:
        ValueError: For an unknown *ai_key*.
        Exception:  Re-raises any exception after graceful error handling.
    """
    # CAC-10 / AGT-1: resolve agent → (make, agent_default_model).
    # Post-0.8.0 there is no auto-seed of built-in makes — callers that
    # pass a bare provider name (e.g. "xai") must have a matching entry
    # in the agent registry.  resolve_agent raises ValueError with a
    # helpful "run st-admin --setup" hint when the registry is empty.
    from .agents import resolve_agent
    spec = resolve_agent(ai_key)
    make = spec.make

    handler_cls = AI_HANDLER_REGISTRY.get(make)
    if not handler_cls:
        raise ValueError(f"Unsupported AI model: {ai_key}")

    try:
        # Build the payload using the centralized handler.
        payload = handler_cls.get_payload(prompt, system=system)

        # Resolve effective model.  Order:
        #   1. explicit `model=` arg
        #   2. `<ALIAS_UPPER>_MODEL` env var (e.g. ANTHROPIC_OPUS_MODEL)
        #   3. `<MAKE_UPPER>_MODEL` env var  (legacy, pre-alias)
        #   4. alias spec model (from ~/.cross_ai_models.json)
        #   5. handler default
        alias_env  = os.environ.get(f"{ai_key.upper().replace('-', '_')}_MODEL", "").strip()
        make_env   = os.environ.get(f"{make.upper()}_MODEL", "").strip()
        effective_model = (
            model
            or alias_env
            or make_env
            or spec.model
            or None
        )
        if effective_model:
            payload["model"] = effective_model
        else:
            effective_model = handler_cls.get_model()

        # Defer client construction to cache miss (CAC-8) so cache hits never
        # touch the SDK constructor.  Explicit client= kwarg wins.
        # The client cache is keyed on `make` — multiple aliases that share a
        # make share one client (and one connection pool).
        if client is not None:
            client_factory: Callable[[], Any] = lambda c=client: c
        else:
            client_factory = lambda: _get_or_create_client(handler_cls, make)
        cached_response, was_cached = handler_cls.get_cached_response(
            None, payload, verbose, use_cache, client_factory=client_factory,
        )

        # Stamp the provider make + alias + effective model so callers never
        # need to pass them separately.  Self-describing responses power
        # put_content_auto / get_content_auto.  In-memory only — the cache
        # file on disk is NOT modified.
        if isinstance(cached_response, dict):
            cached_response["_make"]  = make
            cached_response["_alias"] = ai_key
            cached_response["_model"] = effective_model

        return AIResponse(payload, client, cached_response, effective_model, was_cached)

    except Exception as e:
        # Handle common API errors gracefully (quota, rate limit, etc.)
        # This will print user-friendly messages and exit on quota errors
        handle_api_error(e, ai_key, exit_on_quota=True, quiet=False)
        # If handle_api_error doesn't exit, re-raise the exception
        raise


def _make_for(ai_key: str) -> str:
    """Resolve *ai_key* to a provider make.

    Accepts **either** an agent name (resolved via the agents registry) **or**
    a raw provider make already present in ``AI_HANDLER_REGISTRY`` — e.g. the
    ``_make`` string stamped onto every response by ``process_prompt`` and read
    back by ``get_content_auto`` / ``put_content_auto``.

    A raw make is not necessarily a defined agent: Ollama's make ``"ollama"``
    maps to user-named agents like ``"ollama-qwen"``, so the stamped make must
    dispatch directly to the handler registry rather than being forced through
    agent resolution (which would raise ``ValueError`` for a bare make).
    """
    if ai_key in AI_HANDLER_REGISTRY:
        return ai_key
    from .agents import resolve_agent
    return resolve_agent(ai_key).make


def get_data_title(ai_key: str, data: dict):
    handler_cls = AI_HANDLER_REGISTRY.get(_make_for(ai_key))
    if not handler_cls:
        raise ValueError(f"Unsupported AI model: {ai_key}")
    title = handler_cls.get_title(data)
    return title


def get_content(ai_key, response):
    handler_cls = AI_HANDLER_REGISTRY.get(_make_for(ai_key))
    if not handler_cls:
        raise ValueError(f"Unsupported AI model: {ai_key}")
    return handler_cls.get_content(response)


def put_content(ai_key, report, response):
    handler_cls = AI_HANDLER_REGISTRY.get(_make_for(ai_key))
    if not handler_cls:
        raise ValueError(f"Unsupported AI model: {ai_key}")
    return handler_cls.put_content(report, response)


def get_content_auto(response: dict) -> str:
    """Extract text from a self-describing response (requires ``_make`` to be embedded).

    ``process_prompt()`` stamps ``_make`` into every response it returns, so
    callers that hold a response from ``process_prompt()`` can use this helper
    without tracking which provider produced the response.

    Raises:
        ValueError: if ``_make`` is absent (e.g. a response loaded from an old
                    container that predates the stamp).  Use ``get_content(make,
                    response)`` in that case.
    """
    make = response.get("_make")
    if not make:
        raise ValueError(
            "Response is missing '_make'.  Use get_content(make, response) "
            "or ensure the response was produced by process_prompt()."
        )
    return get_content(make, response)


def put_content_auto(report: str, response: dict) -> dict:
    """Update text in a self-describing response (requires ``_make`` to be embedded).

    ``process_prompt()`` stamps ``_make`` into every response it returns, so
    callers that hold a response from ``process_prompt()`` can use this helper
    without tracking which provider produced the response.

    Raises:
        ValueError: if ``_make`` is absent (e.g. a response loaded from an old
                    container that predates the stamp).  Use ``put_content(make,
                    report, response)`` in that case.
    """
    make = response.get("_make")
    if not make:
        raise ValueError(
            "Response is missing '_make'.  Use put_content(make, report, response) "
            "or ensure the response was produced by process_prompt()."
        )
    return put_content(make, report, response)


def get_data_content(ai_key, select_data):
    handler_cls = AI_HANDLER_REGISTRY.get(_make_for(ai_key))
    if not handler_cls:
        raise ValueError(f"Unsupported AI model: {ai_key}")
    content = handler_cls.get_data_content(select_data)
    return content


def get_ai_list() -> list[str]:
    """Return a copy of the ordered alias list.

    Post-CAC-10: returns alias keys (which include every built-in make as a
    self-alias) rather than just makes.  Order: alias-file declaration order,
    falling back to ``AI_LIST`` when no alias file is present.

    Returns a new list on every call so that callers who mutate the result
    (e.g. ``get_ai_list().remove("xai")``) do not corrupt the global registry.
    """
    from .agents import get_agents
    return list(get_agents().keys())


def get_ai_make_list() -> list[str]:
    """Return a copy of the ordered built-in make list (no aliases).

    Use this when iterating over *providers* (e.g. for an alias-management
    wizard's "pick a make" picker).  For most callers, ``get_ai_list()`` is
    the right choice — it returns alias keys, which are what users type at
    the ``--ai`` flag.
    """
    return list(AI_LIST)


def get_rate_limit_concurrency(make: str) -> int:
    """Return the recommended maximum concurrent requests for *make*.

    These are conservative defaults suitable for free/starter API tiers.
    Callers building thread pools or asyncio semaphores should use this as
    the initial cap and tune upward based on observed error rates.

    Args:
        make: Provider key, e.g. ``"gemini"`` or ``"anthropic"``.

    Returns:
        Recommended concurrency as an int.

    Raises:
        KeyError: if *make* is not a registered provider.
    """
    if make == "ollama":
        # Hardware-bound, not provider-bound — let the user tune it for their
        # box (or their LAN Ollama host).  Falls back to the compiled default
        # for empty / non-numeric / non-positive values.
        raw = os.environ.get("OLLAMA_MAX_CONCURRENCY", "").strip()
        if raw:
            try:
                val = int(raw)
                if val > 0:
                    return val
            except ValueError:
                pass
        return _RATE_LIMIT_CONCURRENCY["ollama"]
    try:
        return _RATE_LIMIT_CONCURRENCY[make]
    except KeyError:
        raise KeyError(
            f"Unknown provider '{make}'. "
            f"Known providers: {list(_RATE_LIMIT_CONCURRENCY)}"
        )


def get_usage(ai_key: str, response: dict) -> dict:
    """
    Extract token usage from a raw API response dict.

    Delegates to the provider-specific handler so callers never need to
    know each provider's response schema.

    Returns:
        dict with keys:
            input_tokens  (int) — prompt / input tokens consumed
            output_tokens (int) — completion / output tokens generated
            total_tokens  (int) — sum of the above (computed if absent)
        All values default to 0 if the field is missing.
    """
    try:
        make = _make_for(ai_key)
    except ValueError:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    handler_cls = AI_HANDLER_REGISTRY.get(make)
    if not handler_cls:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return handler_cls.get_usage(response)


def get_default_ai():
    """
    Return the user-configured default agent.

    Resolution order (post-AGT-1):
      1. ``DEFAULT_AGENT`` environment variable (set by ``st-admin > AI > d``
         in cross-st 0.10+).
      2. ``DEFAULT_AI`` environment variable (legacy — pre-Agents-v2).
      3. First entry in the agent registry.

    Returns ``None`` when no agents are defined and no env var is set.
    Callers that need a provider should print the cross-st AGT-2 hint
    ("run st-admin --setup") rather than fall back to a hardcoded
    provider name.

    Never hardcode a provider name — always call this function.
    """
    from .agents import get_agents
    agents = get_agents()
    for var in ("DEFAULT_AGENT", "DEFAULT_AI"):
        configured = os.environ.get(var, "").strip()
        if configured and configured in agents:
            return configured
    # Post-AGT-1a: registry may be empty for fresh installs.
    return next(iter(agents), None)


def get_ai_make(ai_key: str):
    """Return the canonical *make* for *ai_key* (resolves alias → make first)."""
    from .agents import resolve_agent
    spec = resolve_agent(ai_key)
    handler_cls = AI_HANDLER_REGISTRY.get(spec.make)
    if not handler_cls:
        raise ValueError(f"Unsupported AI model: {ai_key}")
    return handler_cls.get_make()


def get_ai_model(ai_key: str) -> str:
    """Return the active model string for *ai_key* (alias or make).

    Resolution order (CAC-10f):
      1. ``<ALIAS_UPPER>_MODEL`` env var (e.g. ``ANTHROPIC_OPUS_MODEL=…``)
         where dashes in the alias name are converted to underscores.
      2. ``<MAKE_UPPER>_MODEL`` env var  (legacy, pre-alias)
      3. Alias spec model from ``~/.cross_ai_models.json``
      4. Compiled-in handler default

    Set the env var in ``~/.crossenv`` or ``.env`` to switch models globally
    without touching code.  Use ``process_prompt(..., model="...")`` to override
    for a single call.

    Raises:
        ValueError: if *ai_key* is not a registered alias or make.
    """
    from .agents import resolve_agent
    spec = resolve_agent(ai_key)
    alias_env = os.environ.get(f"{ai_key.upper().replace('-', '_')}_MODEL", "").strip()
    if alias_env:
        return alias_env
    make_env = os.environ.get(f"{spec.make.upper()}_MODEL", "").strip()
    if make_env:
        return make_env
    if spec.model:
        return spec.model
    handler_cls = AI_HANDLER_REGISTRY.get(spec.make)
    if not handler_cls:
        raise ValueError(f"Unsupported AI model: {ai_key}")
    return handler_cls.get_model()


# ── API key validation ────────────────────────────────────────────────────────

# Map every registered make → its primary environment-variable name.
# Source of truth lives in ``cross_ai_core.keys`` (AGT-1c) so that
# ``has_api_key()`` and ``check_api_key()`` agree.  Kept here as a thin
# alias for back-compat with any consumer that imported it directly.
from .keys import PROVIDER_API_KEY_ENV as _PROVIDER_API_KEY_ENV  # noqa: E402

_API_KEY_ENV_VARS: dict[str, str] = {
    provider: names[0] for provider, names in _PROVIDER_API_KEY_ENV.items()
}


def check_api_key(ai_make: str, paths_checked: list | None = None) -> bool:
    """
    Verify that the API key for *ai_make* is present in the environment.

    If the key is missing, prints a clear diagnostic showing which config
    files were searched (in load order) and the exact env-var name to add.

    Args:
        ai_make:       Provider make or alias string, e.g. ``"xai"`` or
                       ``"anthropic-opus"``.  Aliases resolve to their make
                       before the API key lookup.
        paths_checked: Ordered list of dotenv file paths that were attempted,
                       in load order (lowest → highest priority).  When omitted
                       the three canonical A1 paths are shown as defaults.

    Returns:
        ``True``  — key is present and non-empty.
        ``False`` — key is missing; diagnostic has already been printed.
    """
    # Accept either a make or an alias — resolve to make for the env-var lookup.
    from .agents import resolve_agent
    try:
        ai_make = resolve_agent(ai_make).make
    except ValueError:
        pass  # unknown alias — fall through to the make-based lookup
    env_var = _API_KEY_ENV_VARS.get(ai_make)
    if not env_var:
        return True  # unknown provider — let the SDK surface the real error

    # has_api_key() honours every accepted env-var name (e.g. gemini
    # accepts GEMINI_API_KEY or GOOGLE_API_KEY).  env_var is just the
    # canonical name shown in the diagnostic.
    from .keys import has_api_key
    if has_api_key(ai_make):
        return True  # key present ✓

    if paths_checked is None:
        paths_checked = [
            os.path.expanduser("~/.crossenv"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
            os.path.join(os.getcwd(), ".env"),
        ]

    print(f"\n  ✗  API key not set for '{ai_make}'  (env var: {env_var})")
    print(f"     Config files searched (in load order):")
    for i, path in enumerate(paths_checked, 1):
        status = "✓ exists" if os.path.isfile(path) else "✗ not found"
        print(f"       {i}. {path}  [{status}]")
    print(f"     Fix: add  {env_var}=<your-key>  to one of the files above.\n")
    return False

