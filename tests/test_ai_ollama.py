"""
tests/test_ai_ollama.py — Tests for cross_ai_core.ai_ollama (OLL-1 / OLL-2).

Coverage:
    OllamaHandler        — make/model/content/usage extraction, payload shape
    get_base_url         — env override + default, trailing-slash handling
    get_ollama_client    — optional OLLAMA_API_TOKEN bearer header
    _call_api            — URL construction, JSON return, network-error mapping
    Registration         — ollama present in AI_HANDLER_REGISTRY and AI_LIST
    process_prompt       — end-to-end dispatch with a mocked client (no daemon)

All HTTP is mocked — no live Ollama daemon is required, so these run in CI.
"""
import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from cross_ai_core import ai_ollama
from cross_ai_core.ai_ollama import (
    OllamaHandler,
    get_base_url,
    get_ollama_client,
    get_ollama_payload,
    _get_request_timeout,
    _get_health_check_timeout,
)


# ── Identity / config ──────────────────────────────────────────────────────────

class TestIdentity:
    def test_get_make(self):
        assert OllamaHandler.get_make() == "ollama"

    def test_get_model_default(self):
        assert OllamaHandler.get_model() == "llama3.1"


class TestBaseUrl:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        assert get_base_url() == "http://localhost:11434"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://mac-studio.local:11434")
        assert get_base_url() == "http://mac-studio.local:11434"

    def test_blank_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "   ")
        assert get_base_url() == "http://localhost:11434"


class TestRequestTimeout:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_REQUEST_TIMEOUT", raising=False)
        assert _get_request_timeout() == 120

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_REQUEST_TIMEOUT", "45")
        assert _get_request_timeout() == 45

    def test_non_numeric_falls_back(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_REQUEST_TIMEOUT", "soon")
        assert _get_request_timeout() == 120


class TestHealthCheckTimeout:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HEALTH_CHECK_TIMEOUT", raising=False)
        assert _get_health_check_timeout() == 5

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HEALTH_CHECK_TIMEOUT", "10")
        assert _get_health_check_timeout() == 10

    def test_non_numeric_falls_back(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HEALTH_CHECK_TIMEOUT", "quick")
        assert _get_health_check_timeout() == 5


# ── Payload ────────────────────────────────────────────────────────────────────

class TestPayload:
    def test_shape_and_defaults(self):
        p = get_ollama_payload("Explain qubits.")
        assert p["model"] == "llama3.1"
        assert p["prompt"] == "Explain qubits."
        assert p["stream"] is False
        assert p["system"]  # default journalism persona is non-empty
        assert "options" in p and "temperature" in p["options"]

    def test_custom_system(self):
        p = get_ollama_payload("Hi", system="You are terse.")
        assert p["system"] == "You are terse."


# ── Content / usage extraction ─────────────────────────────────────────────────

class TestContent:
    def test_get_content(self):
        assert OllamaHandler.get_content({"response": "Hello, world!"}) == "Hello, world!"

    def test_put_content_roundtrip(self):
        resp = {"response": "old"}
        out = OllamaHandler.put_content("new", resp)
        assert out["response"] == "new"

    def test_get_data_content(self):
        select = {"gen_response": {"response": "wrapped text"}}
        assert OllamaHandler.get_data_content(select) == "wrapped text"


class TestUsage:
    def test_extracts_counts(self):
        resp = {"prompt_eval_count": 26, "eval_count": 290}
        u = OllamaHandler.get_usage(resp)
        assert u == {"input_tokens": 26, "output_tokens": 290, "total_tokens": 316}

    def test_missing_counts_default_to_zero(self):
        u = OllamaHandler.get_usage({})
        assert u == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# ── Client ─────────────────────────────────────────────────────────────────────

class TestClient:
    def test_no_token_no_auth_header(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_API_TOKEN", raising=False)
        session = get_ollama_client()
        assert "Authorization" not in session.headers

    def test_token_sets_bearer_header(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_TOKEN", "secret-token")
        session = get_ollama_client()
        assert session.headers["Authorization"] == "Bearer secret-token"


# ── _call_api (mocked HTTP) ─────────────────────────────────────────────────────

def _mock_client(json_payload=None, raise_exc=None, status=200, text=""):
    """Build a fake requests.Session whose .post() returns a mock response."""
    client = MagicMock()
    if raise_exc is not None:
        client.post.side_effect = raise_exc
        return client
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.json.return_value = json_payload or {}
    resp.raise_for_status.return_value = None
    client.post.return_value = resp
    return client


class TestCallApi:
    def test_posts_to_generate_endpoint(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
        client = _mock_client({"response": "hi", "done": True})
        result = OllamaHandler._call_api(client, {"model": "llama3.1", "prompt": "hi"})
        assert result == {"response": "hi", "done": True}
        url = client.post.call_args.args[0]
        assert url == "http://localhost:11434/api/generate"

    def test_base_url_trailing_slash_is_normalised(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://host:11434/")
        client = _mock_client({"response": "ok"})
        OllamaHandler._call_api(client, {"prompt": "x"})
        assert client.post.call_args.args[0] == "http://host:11434/api/generate"

    def test_connection_error_is_wrapped(self):
        client = _mock_client(raise_exc=requests.ConnectionError("refused"))
        with pytest.raises(ConnectionError, match="Cannot reach Ollama"):
            OllamaHandler._call_api(client, {"prompt": "x"})

    def test_timeout_is_wrapped(self):
        client = _mock_client(raise_exc=requests.Timeout("slow"))
        with pytest.raises(TimeoutError, match="timed out"):
            OllamaHandler._call_api(client, {"prompt": "x"})

    def test_http_error_is_wrapped(self):
        resp = MagicMock()
        resp.status_code = 404
        resp.json.return_value = {"error": "model 'nope' not found"}
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        client = MagicMock()
        client.post.return_value = resp
        with pytest.raises(RuntimeError, match="model 'nope' not found"):
            OllamaHandler._call_api(client, {"prompt": "x"})


# ── Connectivity / discovery (OLL-3) ─────────────────────────────────────────

class TestConnectivity:
    def _patch_client(self, monkeypatch, *, json_payload=None, raise_exc=None):
        client = MagicMock()
        if raise_exc is not None:
            client.get.side_effect = raise_exc
        else:
            resp = MagicMock()
            resp.json.return_value = json_payload or {}
            resp.raise_for_status.return_value = None
            client.get.return_value = resp
        monkeypatch.setattr(ai_ollama, "get_ollama_client", lambda: client)
        return client

    def test_health_check_true(self, monkeypatch):
        self._patch_client(monkeypatch, json_payload={"models": []})
        assert OllamaHandler.health_check() is True

    def test_health_check_false_on_connection_error(self, monkeypatch):
        self._patch_client(monkeypatch, raise_exc=requests.ConnectionError("x"))
        assert OllamaHandler.health_check() is False

    def test_health_check_false_on_timeout(self, monkeypatch):
        self._patch_client(monkeypatch, raise_exc=requests.Timeout("x"))
        assert OllamaHandler.health_check() is False

    def test_require_healthy_raises_when_down(self, monkeypatch):
        self._patch_client(monkeypatch, raise_exc=requests.ConnectionError("x"))
        with pytest.raises(ConnectionError, match="Cannot reach Ollama"):
            OllamaHandler.require_healthy()

    def test_require_healthy_ok_when_up(self, monkeypatch):
        self._patch_client(monkeypatch, json_payload={"models": []})
        OllamaHandler.require_healthy()  # must not raise

    def test_list_models_returns_names(self, monkeypatch):
        self._patch_client(monkeypatch, json_payload={
            "models": [{"name": "llama3.1:latest"}, {"name": "mistral:latest"}]
        })
        assert OllamaHandler.list_models() == ["llama3.1:latest", "mistral:latest"]

    def test_list_models_empty_on_error(self, monkeypatch):
        self._patch_client(monkeypatch, raise_exc=requests.ConnectionError("x"))
        assert OllamaHandler.list_models() == []

    def test_list_models_skips_nameless_entries(self, monkeypatch):
        self._patch_client(monkeypatch, json_payload={
            "models": [{"name": "a:latest"}, {"size": 1}]
        })
        assert OllamaHandler.list_models() == ["a:latest"]

    def test_probe_uses_health_check_timeout(self, monkeypatch):
        client = self._patch_client(monkeypatch, json_payload={"models": []})
        monkeypatch.setenv("OLLAMA_HEALTH_CHECK_TIMEOUT", "7")
        OllamaHandler.health_check()
        assert client.get.call_args.kwargs["timeout"] == 7

    def test_probe_hits_tags_endpoint(self, monkeypatch):
        client = self._patch_client(monkeypatch, json_payload={"models": []})
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://mac-studio.local:11434")
        OllamaHandler.list_models()
        assert client.get.call_args.args[0] == "http://mac-studio.local:11434/api/tags"


# ── Registration (OLL-2) ────────────────────────────────────────────────────────

class TestRegistration:
    def test_in_registry(self):
        from cross_ai_core.ai_handler import AI_HANDLER_REGISTRY
        assert AI_HANDLER_REGISTRY.get("ollama") is OllamaHandler

    def test_in_ai_list(self):
        from cross_ai_core.ai_handler import AI_LIST
        assert "ollama" in AI_LIST


# ── process_prompt end-to-end (mocked client, no daemon) ─────────────────────────

class TestProcessPromptE2E:
    def test_dispatch_and_stamp(self, monkeypatch):
        """process_prompt('ollama', ...) routes to OllamaHandler and stamps _make."""
        from cross_ai_core.ai_handler import process_prompt, get_content_auto

        # conftest seeds an 'ollama' self-agent (from AI_LIST), so resolve works.
        client = _mock_client({"response": "Qubits hold superposition.", "eval_count": 5})
        result = process_prompt(
            "ollama", "Summarise qubits.", use_cache=False, client=client,
        )
        assert result.response["_make"] == "ollama"
        assert result.response["_alias"] == "ollama"
        assert get_content_auto(result.response) == "Qubits hold superposition."
        # The effective model flows into the payload sent to the daemon.
        sent_payload = client.post.call_args.kwargs["json"]
        assert sent_payload["model"] == "llama3.1"

