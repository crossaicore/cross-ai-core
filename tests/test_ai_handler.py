"""
tests/test_ai_handler.py — Tests for cross_ai_core.ai_handler

Coverage:
    AI_LIST / AI_HANDLER_REGISTRY  — completeness
    get_default_ai                 — env resolution, fallback, unknown value
    get_ai_list                    — returns correct list
    get_ai_model                   — env var override, fallback to handler default
    check_api_key                  — present/missing/unknown provider
    AIResponse                     — tuple unpacking, indexing, was_cached
    process_prompt                 — dispatches to handler; returns AIResponse
    process_prompt model param     — explicit model arg, env var model override
    process_prompt error path      — ValueError for unknown provider
    get_content / put_content      — dispatch wrappers
    get_usage                      — returns zero dict for unknown provider

All tests mock provider SDK calls — no real API calls are made.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from cross_ai_core.ai_handler import (
    AI_HANDLER_REGISTRY,
    AI_LIST,
    AIResponse,
    _API_KEY_ENV_VARS,
    check_api_key,
    get_ai_list,
    get_content,
    get_content_auto,
    get_default_ai,
    get_usage,
    process_prompt,
    put_content,
    put_content_auto,
)


# ── Registry / list completeness ───────────────────────────────────────────────

class TestRegistryCompleteness:
    # OLL-2: ollama is the first local/LAN provider — registered like the
    # cloud makes but keyless (see KEYED below).
    EXPECTED = {"xai", "anthropic", "openai", "perplexity", "gemini", "ollama"}
    # Providers that require an API key.  ollama runs on a trusted network and
    # has no key, so it is deliberately absent from _API_KEY_ENV_VARS.
    KEYED = EXPECTED - {"ollama"}

    def test_ai_list_contains_all_providers(self):
        assert set(AI_LIST) == self.EXPECTED

    def test_registry_contains_all_providers(self):
        assert set(AI_HANDLER_REGISTRY.keys()) == self.EXPECTED

    def test_registry_values_are_classes(self):
        for name, cls in AI_HANDLER_REGISTRY.items():
            assert isinstance(cls, type), f"{name} handler should be a class"

    def test_api_key_env_vars_covers_all_providers(self):
        # Keyless providers (ollama) are excluded from the key-env map.
        assert set(_API_KEY_ENV_VARS.keys()) == self.KEYED


# ── get_default_ai ─────────────────────────────────────────────────────────────

class TestGetDefaultAi:
    def test_returns_first_in_list_when_no_env(self, monkeypatch):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        assert get_default_ai() == AI_LIST[0]

    def test_returns_env_var_when_valid(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_AI", "gemini")
        assert get_default_ai() == "gemini"

    def test_falls_back_when_env_var_is_unknown_provider(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_AI", "bogus_provider")
        assert get_default_ai() == AI_LIST[0]

    def test_falls_back_when_env_var_is_empty(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_AI", "")
        assert get_default_ai() == AI_LIST[0]

    def test_case_sensitive(self, monkeypatch):
        # "Gemini" (capital) is not a valid key — should fall back
        monkeypatch.setenv("DEFAULT_AI", "Gemini")
        assert get_default_ai() == AI_LIST[0]


# ── get_ai_list ────────────────────────────────────────────────────────────────

class TestGetAiList:
    def test_returns_list(self):
        result = get_ai_list()
        assert isinstance(result, list)

    def test_matches_ai_list_constant(self):
        # Post-AGT-1: get_ai_list returns agent keys, not built-in makes.
        # The built-in list is now exposed via get_ai_make_list().  Both
        # surfaces include the 5 canonical providers in the test session
        # (seeded by tests/conftest.py).
        from cross_ai_core.ai_handler import get_ai_make_list
        assert get_ai_make_list() == AI_LIST
        for make in AI_LIST:
            assert make in get_ai_list()

    def test_order_is_deterministic(self):
        """AI_LIST order is fixed — st-cross relies on it for the NN display matrix."""
        from cross_ai_core.ai_handler import get_ai_make_list
        assert get_ai_make_list() == ["xai", "anthropic", "openai", "perplexity", "gemini", "ollama"]

    def test_returns_copy_not_live_reference(self):
        """Mutating the returned list must not affect subsequent calls."""
        first = get_ai_list()
        first.clear()
        second = get_ai_list()
        # Built-ins always survive (seeded by conftest for the session).
        for make in AI_LIST:
            assert make in second


# ── check_api_key ──────────────────────────────────────────────────────────────

class TestCheckApiKey:
    def test_returns_true_when_key_present(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key-abc123")
        assert check_api_key("gemini") is True

    def test_returns_false_when_key_missing(self, monkeypatch, capsys):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = check_api_key("gemini", paths_checked=[])
        assert result is False

    def test_missing_key_prints_diagnostic(self, monkeypatch, capsys):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        check_api_key("openai", paths_checked=["/fake/.env"])
        out = capsys.readouterr().out
        assert "OPENAI_API_KEY" in out
        assert "openai" in out

    def test_unknown_provider_returns_true(self, monkeypatch):
        # Unknown providers pass through — let the SDK surface the real error
        result = check_api_key("unknown_provider")
        assert result is True

    def test_whitespace_only_key_treated_as_missing(self, monkeypatch, capsys):
        monkeypatch.setenv("XAI_API_KEY", "   ")
        result = check_api_key("xai", paths_checked=[])
        assert result is False


# ── AIResponse ─────────────────────────────────────────────────────────────────

class TestAIResponse:
    def _make_response(self, was_cached=False):
        return AIResponse(
            payload={"prompt": "test"},
            client=object(),
            response={"text": "hello"},
            model="test-model",
            was_cached=was_cached,
        )

    def test_was_cached_false(self):
        r = self._make_response(was_cached=False)
        assert r.was_cached is False

    def test_was_cached_true(self):
        r = self._make_response(was_cached=True)
        assert r.was_cached is True

    def test_tuple_unpacking(self):
        r = self._make_response()
        payload, client, response, model = r
        assert payload == {"prompt": "test"}
        assert response == {"text": "hello"}
        assert model == "test-model"

    def test_index_access(self):
        r = self._make_response()
        assert r[2] == {"text": "hello"}
        assert r[3] == "test-model"

    def test_len_is_four(self):
        assert len(self._make_response()) == 4

    def test_attributes_accessible(self):
        r = self._make_response()
        assert r.payload == {"prompt": "test"}
        assert r.model == "test-model"


# ── process_prompt ─────────────────────────────────────────────────────────────

class TestProcessPrompt:
    """process_prompt() is tested with a fully mocked handler class."""

    def _mock_handler(self, response_data=None, was_cached=False):
        """Return a mock handler class that simulates a provider."""
        mock_cls = MagicMock()
        mock_cls.get_payload.return_value = {"mock": "payload"}
        mock_cls.get_client.return_value = MagicMock()
        mock_cls.get_cached_response.return_value = (
            response_data or {"choices": [{"message": {"content": "mocked"}}]},
            was_cached,
        )
        mock_cls.get_model.return_value = "mock-model-1"
        return mock_cls

    def test_returns_ai_response(self):
        mock_cls = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hello", verbose=False, use_cache=True)
        assert isinstance(result, AIResponse)

    def test_response_was_cached_flag_false(self):
        mock_cls = self._mock_handler(was_cached=False)
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hello", verbose=False, use_cache=True)
        assert result.was_cached is False

    def test_response_was_cached_flag_true(self):
        mock_cls = self._mock_handler(was_cached=True)
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hello", verbose=False, use_cache=True)
        assert result.was_cached is True

    def test_passes_prompt_to_get_payload(self):
        mock_cls = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            process_prompt("mock_ai", "my prompt", verbose=False, use_cache=True)
        mock_cls.get_payload.assert_called_once_with("my prompt", system=None)

    def test_passes_use_cache_to_get_cached_response(self):
        mock_cls = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            process_prompt("mock_ai", "p", verbose=False, use_cache=False)
        # use_cache=False must have been passed (positional or keyword)
        call_args = mock_cls.get_cached_response.call_args
        all_args = list(call_args.args) + list(call_args.kwargs.values())
        assert False in all_args

    def test_raises_value_error_for_unknown_provider(self):
        with pytest.raises(ValueError, match="Unsupported AI model"):
            process_prompt("totally_unknown", "hello", verbose=False, use_cache=False)

    def test_backward_compat_tuple_unpack(self):
        mock_cls = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hi", verbose=False, use_cache=False)
        payload, client, response, model = result   # must not raise
        assert model == "mock-model-1"


# ── get_content / put_content ──────────────────────────────────────────────────

class TestContentWrappers:
    def test_get_content_dispatches_to_handler(self):
        mock_cls = MagicMock()
        mock_cls.get_content.return_value = "extracted text"
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = get_content("mock_ai", {"raw": "response"})
        assert result == "extracted text"
        mock_cls.get_content.assert_called_once_with({"raw": "response"})

    def test_put_content_dispatches_to_handler(self):
        mock_cls = MagicMock()
        mock_cls.put_content.return_value = {"updated": True}
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = put_content("mock_ai", "report text", {"raw": "response"})
        assert result == {"updated": True}

    def test_get_content_raises_for_unknown_provider(self):
        with pytest.raises(ValueError):
            get_content("no_such_provider", {})


# ── get_usage ──────────────────────────────────────────────────────────────────

class TestGetUsage:
    def test_unknown_provider_returns_zeros(self):
        result = get_usage("no_such_provider", {})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def test_dispatches_to_handler(self):
        mock_cls = MagicMock()
        mock_cls.get_usage.return_value = {
            "input_tokens": 10, "output_tokens": 20, "total_tokens": 30
        }
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = get_usage("mock_ai", {"usage": {}})
        assert result["total_tokens"] == 30


# ── _make stamp in process_prompt ──────────────────────────────────────────────

class TestMakeStamp:
    """process_prompt() stamps _make into the response dict."""

    def _mock_handler(self, response_data=None):
        mock_cls = MagicMock()
        mock_cls.get_payload.return_value = {"mock": "payload"}
        mock_cls.get_client.return_value = MagicMock()
        mock_cls.get_cached_response.return_value = (
            response_data or {"choices": [{"message": {"content": "hi"}}]},
            False,
        )
        mock_cls.get_model.return_value = "mock-model-1"
        return mock_cls

    def test_make_is_stamped_into_response(self):
        mock_cls = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hello", verbose=False, use_cache=False)
        assert result.response["_make"] == "mock_ai"

    def test_make_stamp_does_not_affect_other_fields(self):
        mock_cls = self._mock_handler(response_data={"text": "hello"})
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hello", verbose=False, use_cache=False)
        assert result.response["text"] == "hello"
        assert result.response["_make"] == "mock_ai"

    def test_non_dict_response_is_not_stamped(self):
        """If a provider returns a non-dict (e.g. None on error path), no AttributeError."""
        mock_cls = self._mock_handler()
        mock_cls.get_cached_response.return_value = (None, False)
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hello", verbose=False, use_cache=False)
        assert result.response is None


# ── get_content_auto / put_content_auto ────────────────────────────────────────

class TestContentAutoWrappers:
    """get_content_auto / put_content_auto dispatch via the embedded _make key."""

    def test_get_content_auto_dispatches_via_make(self):
        mock_cls = MagicMock()
        mock_cls.get_content.return_value = "auto extracted"
        response = {"_make": "mock_ai", "data": "raw"}
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = get_content_auto(response)
        assert result == "auto extracted"
        mock_cls.get_content.assert_called_once_with(response)

    def test_get_content_auto_raises_without_make(self):
        with pytest.raises(ValueError, match="_make"):
            get_content_auto({"data": "raw"})

    def test_get_content_auto_raises_on_empty_make(self):
        with pytest.raises(ValueError, match="_make"):
            get_content_auto({"_make": "", "data": "raw"})

    def test_put_content_auto_dispatches_via_make(self):
        mock_cls = MagicMock()
        mock_cls.put_content.return_value = {"updated": True}
        response = {"_make": "mock_ai", "data": "raw"}
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = put_content_auto("new report", response)
        assert result == {"updated": True}
        mock_cls.put_content.assert_called_once_with("new report", response)

    def test_put_content_auto_raises_without_make(self):
        with pytest.raises(ValueError, match="_make"):
            put_content_auto("report", {"data": "raw"})

    def test_put_content_auto_raises_on_empty_make(self):
        with pytest.raises(ValueError, match="_make"):
            put_content_auto("report", {"_make": "", "data": "raw"})

    def test_get_content_auto_dispatches_via_raw_make_without_agent(self):
        """Regression (OLL): the stamped ``_make`` is a raw provider make, not
        an agent name.  Ollama's make ``"ollama"`` maps to user-named agents
        like ``"ollama-qwen"``, so ``get_content_auto`` must dispatch on the
        make directly and must NOT force agent resolution (which would raise
        ``ValueError`` for a bare make with no self-agent).

        The session conftest seeds every make as a self-agent, masking the bug,
        so we explicitly drop the make from ``_AGENTS`` here to reproduce the
        real Agents-v2 state.
        """
        from cross_ai_core.agents import _AGENTS

        mock_cls = MagicMock()
        mock_cls.get_content.return_value = "local text"
        response = {"_make": "ollama", "data": "raw"}
        with patch.dict(AI_HANDLER_REGISTRY, {"ollama": mock_cls}), \
             patch.dict(_AGENTS, {}, clear=False):
            _AGENTS.pop("ollama", None)          # make is real, but no "ollama" agent
            assert "ollama" not in _AGENTS
            result = get_content_auto(response)
        assert result == "local text"
        mock_cls.get_content.assert_called_once_with(response)


# ── process_prompt model parameter ────────────────────────────────────────────

class TestProcessPromptModel:
    """process_prompt() model override: explicit arg and env var."""

    def _mock_handler(self, default_model="handler-default"):
        mock_cls = MagicMock()
        mock_cls.get_payload.return_value = {"model": default_model, "other": "data"}
        mock_cls.get_client.return_value = MagicMock()
        mock_cls.get_cached_response.return_value = ({"text": "ok"}, False)
        mock_cls.get_model.return_value = default_model
        return mock_cls

    def test_explicit_model_overrides_payload(self):
        mock_cls = self._mock_handler("handler-default")
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hi", model="override-model", use_cache=False)
        # payload["model"] should be replaced with the override
        assert result.payload["model"] == "override-model"

    def test_explicit_model_is_reflected_in_result_model(self):
        mock_cls = self._mock_handler("handler-default")
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hi", model="override-model", use_cache=False)
        assert result.model == "override-model"

    def test_env_var_model_overrides_handler_default(self, monkeypatch):
        monkeypatch.setenv("MOCK_AI_MODEL", "env-model")
        mock_cls = self._mock_handler("handler-default")
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hi", use_cache=False)
        assert result.model == "env-model"
        assert result.payload["model"] == "env-model"

    def test_explicit_model_takes_priority_over_env_var(self, monkeypatch):
        monkeypatch.setenv("MOCK_AI_MODEL", "env-model")
        mock_cls = self._mock_handler("handler-default")
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hi", model="explicit-model", use_cache=False)
        assert result.model == "explicit-model"

    def test_no_override_uses_handler_default(self, monkeypatch):
        monkeypatch.delenv("MOCK_AI_MODEL", raising=False)
        mock_cls = self._mock_handler("handler-default")
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hi", use_cache=False)
        assert result.model == "handler-default"

    def test_whitespace_env_var_falls_through_to_handler_default(self, monkeypatch):
        monkeypatch.setenv("MOCK_AI_MODEL", "   ")
        mock_cls = self._mock_handler("handler-default")
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            result = process_prompt("mock_ai", "hi", use_cache=False)
        assert result.model == "handler-default"


# ── get_ai_model env var resolution ────────────────────────────────────────────

class TestGetAiModel:
    """get_ai_model() checks <MAKE_UPPER>_MODEL env var before the handler default."""

    def test_returns_handler_default_when_no_env(self, monkeypatch):
        from cross_ai_core.ai_handler import get_ai_model
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        # gemini handler default is defined at module level — just check it's a non-empty string
        result = get_ai_model("gemini")
        assert isinstance(result, str) and result

    def test_env_var_overrides_handler_default(self, monkeypatch):
        from cross_ai_core.ai_handler import get_ai_model
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
        assert get_ai_model("gemini") == "gemini-2.5-pro"

    def test_env_var_checked_case_insensitive_key(self, monkeypatch):
        """Key is uppercased: 'xai' → 'XAI_MODEL'."""
        from cross_ai_core.ai_handler import get_ai_model
        monkeypatch.setenv("XAI_MODEL", "grok-3-latest")
        assert get_ai_model("xai") == "grok-3-latest"

    def test_whitespace_env_var_falls_through(self, monkeypatch):
        from cross_ai_core.ai_handler import get_ai_model
        monkeypatch.setenv("OPENAI_MODEL", "   ")
        result = get_ai_model("openai")
        # Should return the handler default, not whitespace
        assert result.strip() == result and result  # non-empty, no surrounding whitespace

    def test_unknown_provider_raises(self):
        from cross_ai_core.ai_handler import get_ai_model
        with pytest.raises(ValueError, match="Unsupported AI model"):
            get_ai_model("no_such_provider")



# ── CAC-5: get_rate_limit_concurrency ─────────────────────────────────────────

class TestGetRateLimitConcurrency:
    """CAC-5 — get_rate_limit_concurrency() returns per-provider default ints."""

    def test_known_providers_return_int(self):
        from cross_ai_core.ai_handler import get_rate_limit_concurrency, AI_LIST
        for make in AI_LIST:
            result = get_rate_limit_concurrency(make)
            assert isinstance(result, int) and result > 0, f"{make} should return positive int"

    @pytest.mark.parametrize("make,expected", [
        ("xai",        3),
        ("anthropic",  2),
        ("openai",     3),
        ("perplexity", 2),
        ("gemini",     5),
    ])
    def test_exact_defaults(self, make, expected):
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        assert get_rate_limit_concurrency(make) == expected

    def test_unknown_provider_raises_key_error(self):
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        with pytest.raises(KeyError, match="no_such_provider"):
            get_rate_limit_concurrency("no_such_provider")

    def test_exported_from_package(self):
        from cross_ai_core import get_rate_limit_concurrency
        assert callable(get_rate_limit_concurrency)

    def test_returns_independent_values(self):
        """Gemini allows more concurrency than Anthropic by default."""
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        assert get_rate_limit_concurrency("gemini") > get_rate_limit_concurrency("anthropic")


class TestOllamaConcurrency:
    """OLL-4 — ollama cap is hardware-bound and OLLAMA_MAX_CONCURRENCY-tunable."""

    def test_default_is_two(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_MAX_CONCURRENCY", raising=False)
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        assert get_rate_limit_concurrency("ollama") == 2

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "6")
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        assert get_rate_limit_concurrency("ollama") == 6

    def test_non_numeric_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "lots")
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        assert get_rate_limit_concurrency("ollama") == 2

    def test_non_positive_env_falls_back(self, monkeypatch):
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "0")
        assert get_rate_limit_concurrency("ollama") == 2
        monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "-3")
        assert get_rate_limit_concurrency("ollama") == 2

    def test_ollama_does_not_leak_override_to_other_makes(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "9")
        from cross_ai_core.ai_handler import get_rate_limit_concurrency
        assert get_rate_limit_concurrency("gemini") == 5  # unaffected


# ── CAC-6: AIResponse.__repr__ ────────────────────────────────────────────────

class TestAIResponseRepr:
    """CAC-6 — AIResponse.__repr__ is informative and doesn't raise."""

    def test_repr_contains_model(self):
        from cross_ai_core.ai_handler import AIResponse
        r = AIResponse({}, None, {"_make": "gemini"}, "gemini-2.5-flash", False)
        assert "gemini-2.5-flash" in repr(r)

    def test_repr_shows_cached(self):
        from cross_ai_core.ai_handler import AIResponse
        r = AIResponse({}, None, {"_make": "openai"}, "gpt-4o", True)
        assert "cached" in repr(r)

    def test_repr_shows_live(self):
        from cross_ai_core.ai_handler import AIResponse
        r = AIResponse({}, None, {"_make": "xai"}, "grok-4", False)
        assert "live" in repr(r)

    def test_repr_does_not_raise_on_missing_make(self):
        from cross_ai_core.ai_handler import AIResponse
        r = AIResponse({}, None, {}, "unknown-model", False)
        rep = repr(r)  # should not raise
        assert "unknown-model" in rep



# ── CAC-8: lazy + cached client per provider ──────────────────────────────────

class TestClientCache:
    """CAC-8 — process_prompt() reuses cached SDK clients and skips construction on cache hits."""

    def setup_method(self):
        from cross_ai_core.ai_handler import reset_client_cache
        reset_client_cache()

    def teardown_method(self):
        from cross_ai_core.ai_handler import reset_client_cache
        reset_client_cache()

    def _mock_handler(self, was_cached=False):
        mock_cls = MagicMock()
        mock_cls.get_payload.return_value = {"mock": "payload"}
        sentinel_client = MagicMock(name="sdk_client")
        mock_cls.get_client.return_value = sentinel_client
        mock_cls.get_cached_response.return_value = (
            {"choices": [{"message": {"content": "x"}}]},
            was_cached,
        )
        mock_cls.get_model.return_value = "mock-model-1"
        return mock_cls, sentinel_client

    def _invoke_factory(self, mock_cls):
        """Trigger the client_factory that process_prompt passes to get_cached_response."""
        call_args = mock_cls.get_cached_response.call_args
        factory = call_args.kwargs.get("client_factory")
        assert factory is not None, "process_prompt must pass client_factory= to get_cached_response"
        return factory()

    def test_repeated_calls_reuse_same_client_instance(self):
        from cross_ai_core.ai_handler import process_prompt
        mock_cls, sentinel = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            process_prompt("mock_ai", "p1", use_cache=False)
            client_first = self._invoke_factory(mock_cls)
            process_prompt("mock_ai", "p2", use_cache=False)
            client_second = self._invoke_factory(mock_cls)
        assert client_first is client_second is sentinel
        assert mock_cls.get_client.call_count == 1,             "get_client should be called exactly once when cache is warm"

    def test_cache_hit_does_not_construct_client(self):
        """When get_cached_response signals a cache hit, the factory must never be invoked."""
        from cross_ai_core.ai_handler import process_prompt
        mock_cls, _ = self._mock_handler(was_cached=True)
        # Make get_cached_response simulate a cache hit by NOT invoking the factory.
        mock_cls.get_cached_response.return_value = ({"_": "cached"}, True)
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            process_prompt("mock_ai", "p", use_cache=True)
        # Factory was passed but never called → get_client never called either.
        assert mock_cls.get_client.call_count == 0

    def test_reset_client_cache_drops_instance(self):
        from cross_ai_core.ai_handler import process_prompt, reset_client_cache
        mock_cls, _ = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            process_prompt("mock_ai", "p1", use_cache=False)
            self._invoke_factory(mock_cls)
            reset_client_cache()
            process_prompt("mock_ai", "p2", use_cache=False)
            self._invoke_factory(mock_cls)
        assert mock_cls.get_client.call_count == 2

    def test_reset_client_cache_per_make_does_not_drop_others(self):
        from cross_ai_core.ai_handler import process_prompt, reset_client_cache
        mock_a, _ = self._mock_handler()
        mock_b, _ = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"prov_a": mock_a, "prov_b": mock_b}):
            process_prompt("prov_a", "p", use_cache=False); self._invoke_factory(mock_a)
            process_prompt("prov_b", "p", use_cache=False); self._invoke_factory(mock_b)
            reset_client_cache("prov_a")
            process_prompt("prov_a", "p", use_cache=False); self._invoke_factory(mock_a)
            process_prompt("prov_b", "p", use_cache=False); self._invoke_factory(mock_b)
        assert mock_a.get_client.call_count == 2  # rebuilt after reset
        assert mock_b.get_client.call_count == 1  # untouched by per-make reset

    def test_concurrent_init_creates_only_one_client(self):
        """Race 10 threads on first-use; assert get_client was called exactly once."""
        import threading
        from cross_ai_core.ai_handler import _get_or_create_client, reset_client_cache
        reset_client_cache()
        mock_cls = MagicMock()
        sentinel = object()

        def slow_get_client():
            # Sleep to widen the race window
            import time
            time.sleep(0.01)
            return sentinel

        mock_cls.get_client = MagicMock(side_effect=slow_get_client)

        barrier = threading.Barrier(10)
        results = []

        def worker():
            barrier.wait()
            results.append(_get_or_create_client(mock_cls, "race_ai"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert mock_cls.get_client.call_count == 1,             f"Expected 1 client construction under concurrent init, got {mock_cls.get_client.call_count}"
        assert all(r is sentinel for r in results)
        reset_client_cache()

    def test_explicit_client_kwarg_bypasses_cache(self):
        from cross_ai_core.ai_handler import process_prompt
        mock_cls, _ = self._mock_handler()
        injected = MagicMock(name="injected_client")
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            process_prompt("mock_ai", "p", use_cache=False, client=injected)
            returned = self._invoke_factory(mock_cls)
        # Explicit client wins; cache helper never consulted
        assert returned is injected
        assert mock_cls.get_client.call_count == 0

    def test_CROSS_NO_CLIENT_CACHE_disables_cache(self, monkeypatch):
        from cross_ai_core.ai_handler import process_prompt
        monkeypatch.setenv("CROSS_NO_CLIENT_CACHE", "1")
        mock_cls, _ = self._mock_handler()
        with patch.dict(AI_HANDLER_REGISTRY, {"mock_ai": mock_cls}):
            process_prompt("mock_ai", "p1", use_cache=False); self._invoke_factory(mock_cls)
            process_prompt("mock_ai", "p2", use_cache=False); self._invoke_factory(mock_cls)
        # Each call constructs a fresh client when the env var is set.
        assert mock_cls.get_client.call_count == 2

    def test_reset_client_cache_exported_from_package(self):
        from cross_ai_core import reset_client_cache
        assert callable(reset_client_cache)
