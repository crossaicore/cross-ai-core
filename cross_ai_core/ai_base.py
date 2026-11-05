"""
ai_base.py — Abstract base class for all cross-ai-core provider handlers.

Every provider (Anthropic, xAI, OpenAI, Gemini, Perplexity) inherits from
BaseAIHandler and implements each classmethod.

Cache directory
---------------
Provider handlers cache responses in a directory resolved by
``_get_cache_dir()``.  The location defaults to ``~/.cross_api_cache/`` and
can be overridden by setting ``CROSS_API_CACHE_DIR`` in the environment (or
in ``~/.crossenv`` before importing the library):

    CROSS_API_CACHE_DIR=~/my-project/cache
"""

import hashlib
import json
import os
from abc import ABC, abstractmethod

from .usage import UsageReport, _mapping, _report

# fcntl is POSIX-only (macOS / Linux).  cross-st is macOS/Linux primary so this
# is the normal path.  On Windows (B6 future work) the lock calls are no-ops —
# the atomic rename still protects against truncation, only concurrent readers
# during a simultaneous write are unprotected on that platform.
try:
    import fcntl as _fcntl
    _LOCK_SH = _fcntl.LOCK_SH
    _LOCK_EX = _fcntl.LOCK_EX

    def _flock(f, flags: int) -> None:
        _fcntl.flock(f, flags)

except ImportError:  # Windows
    _LOCK_SH = 0
    _LOCK_EX = 0

    def _flock(f, flags: int) -> None:  # noqa: F811
        pass  # no-op on Windows


def _get_cache_dir() -> str:
    """
    Return the API response cache directory path (as a string).

    Resolution order:
      1. ``CROSS_API_CACHE_DIR`` environment variable
      2. ``~/.cross_api_cache/``  (default)
    """
    env_val = os.environ.get("CROSS_API_CACHE_DIR", "").strip()
    return os.path.expanduser(env_val if env_val else "~/.cross_api_cache")


class BaseAIHandler(ABC):  # Abstract Base Class

    # ── Class-level defaults (providers override only if they differ) ─────────

    DEFAULT_SYSTEM: str = (
        "You are a seasoned investigative reporter, "
        "striving to be accurate, fair and balanced."
    )
    MAX_TOKENS: int = 16000

    # ── Concrete shared implementation ────────────────────────────────────────

    @classmethod
    def get_cached_response(
        cls,
        client,
        payload: dict,
        verbose: bool = False,
        use_cache: bool = True,
        *,
        client_factory=None,
    ) -> tuple[dict, bool]:
        """MD5-keyed file cache shared by all providers.

        Delegates the actual API call to ``cls._call_api(client, payload)``.
        Subclasses implement only ``_call_api``; they do not need to override
        this method unless they have unusual caching requirements.

        Args:
            client:         A pre-built provider client.  Pass ``None`` together
                            with ``client_factory`` to defer construction until
                            a cache miss actually requires it (CAC-8).
            payload:        Provider request payload (also used as the MD5 cache key).
            verbose:        Print cache hit/miss messages.
            use_cache:      Read from / write to the on-disk cache.
            client_factory: Optional zero-arg callable that returns a client.
                            Only invoked on cache miss.  When both ``client`` and
                            ``client_factory`` are supplied, ``client`` wins.
        """
        if os.environ.get("CROSS_NO_CACHE"):
            if verbose:
                print("Cache disabled via CROSS_NO_CACHE; fetching fresh data.")
            if client is None and client_factory is not None:
                client = client_factory()
            return cls._call_api(client, payload), False

        if not use_cache:
            if verbose:
                print("Cache disabled; fetching fresh data.")
            if client is None and client_factory is not None:
                client = client_factory()
            return cls._call_api(client, payload), False

        # Deterministic MD5 hash of the full payload → unique key per request
        param_str = json.dumps(payload, sort_keys=True)
        md5_hash = hashlib.md5(param_str.encode("utf-8")).hexdigest()

        cache_dir = _get_cache_dir()
        cache_file = os.path.join(cache_dir, f"{md5_hash}.json")

        if os.path.exists(cache_file):
            if verbose:
                print(f"api_cache: hit  {cache_file}")
            try:
                with open(cache_file, "r") as f:
                    _flock(f, _LOCK_SH)
                    data = json.load(f)
                return data, True
            except (json.JSONDecodeError, OSError, ValueError) as e:
                # Corrupt file (e.g. truncated by a killed write).  Delete and
                # fall through to a fresh API call so the run continues cleanly.
                if verbose:
                    print(f"api_cache: corrupt file deleted ({e}), refetching")
                try:
                    os.unlink(cache_file)
                except OSError:
                    pass

        if verbose:
            print("api_cache: miss — calling API")

        if client is None and client_factory is not None:
            client = client_factory()
        json_response = cls._call_api(client, payload)
        if not json_response:
            return {}, False

        os.makedirs(cache_dir, exist_ok=True)
        tmp_file = cache_file + ".tmp"
        try:
            with open(tmp_file, "w") as f:
                _flock(f, _LOCK_EX)
                json.dump(json_response, f)
            # Atomic replace: on POSIX, rename is an atomic syscall so readers
            # always see either the old complete file or the new complete file —
            # never a partial write.
            os.replace(tmp_file, cache_file)
            if verbose:
                print(f"api_cache: saved {cache_file}")
        except Exception as e:
            print(f"api_cache: write error: {e}")
            try:
                os.unlink(tmp_file)
            except OSError:
                pass

        return json_response, False

    # ── Abstract methods every provider must implement ────────────────────────

    @classmethod
    @abstractmethod
    def _call_api(cls, client, payload: dict) -> dict:
        """Make the actual API call and return the response as a plain dict.

        This is the only method providers need to implement to participate in
        caching.  ``get_cached_response`` calls this after a cache miss, or
        directly when ``use_cache=False``.
        """
        pass

    @classmethod
    @abstractmethod
    def get_payload(cls, prompt: str, system: str | None = None):
        """Generate the payload for the given prompt.

        Args:
            prompt: The user prompt text.
            system: Optional system instruction.  When *None* the provider's
                    default system prompt is used (the journalism persona).
        """
        pass

    @classmethod
    @abstractmethod
    def get_client(cls, *args, **kwargs):
        """Return the client for making API requests."""
        pass

    @classmethod
    @abstractmethod
    def get_model(cls) -> str:
        """Return the model identifier string (e.g. 'gpt-4o')."""
        pass

    @classmethod
    @abstractmethod
    def get_make(cls) -> str:
        """Return the provider make string (e.g. 'openai')."""
        pass

    @classmethod
    @abstractmethod
    def get_content(cls, response: dict) -> str:
        """Extract the text content from a raw API response dict."""
        pass

    @classmethod
    @abstractmethod
    def put_content(cls, report: str, response: dict) -> dict:
        """Inject updated text content back into a raw API response dict."""
        pass

    @classmethod
    @abstractmethod
    def get_data_content(cls, select_data: dict) -> str:
        """Extract text from a stored data record (gen_response wrapper)."""
        pass

    @classmethod
    def get_title(cls, gen_content: dict) -> str:
        """Return the first line of the data content as a title.

        Delegates to ``cls.get_data_content()`` so the correct provider
        schema is used automatically.  Providers do not need to override this
        unless their title extraction differs from ``splitlines()[0]``.
        """
        return cls.get_data_content(gen_content).splitlines()[0]

    @classmethod
    def get_usage(cls, response: dict) -> dict:
        """Legacy counts: missing values become zero; prefer get_usage_report."""
        report = cls.get_usage_report(response)
        inp, out = report.input_tokens or 0, report.output_tokens or 0
        return {"input_tokens": inp, "output_tokens": out,
                "total_tokens": report.total_tokens if report.total_tokens is not None else inp + out}

    @classmethod
    def get_usage_report(cls, response: dict) -> UsageReport:
        """Optional extension point; old provider subclasses remain compatible."""
        response = _mapping(response)
        return _report(cls.get_make(), response.get("model"), response.get("usage"),
                       issues=("unsupported_usage_format",))

