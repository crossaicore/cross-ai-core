"""Offline usage contracts. Fixture counts are synthetic; schemas cite providers."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cross_ai_core import (
    AI_HANDLER_REGISTRY, UsageReport, get_usage, get_usage_report, process_prompt,
)
from cross_ai_core import agents
from cross_ai_core.ai_gemini import GeminiHandler, get_json_response
from tests.test_ai_base import _FakeHandler


CASES = json.loads((Path(__file__).parent / "fixtures/usage_responses.json").read_text())
PROVIDERS = tuple(AI_HANDLER_REGISTRY)


@pytest.fixture(autouse=True)
def no_provider_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Usage reporting must not contact providers")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    for handler in AI_HANDLER_REGISTRY.values():
        monkeypatch.setattr(handler, "get_client", forbidden)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_provider_contract(case):
    raw = deepcopy(case["response"])
    report = get_usage_report(case["provider"], raw)
    assert isinstance(report, UsageReport)
    assert report.provider == case["provider"]
    assert report.model == raw.get("model", raw.get("modelVersion", raw.get("model_version")))
    assert {key: getattr(report, key) for key in case["expected"]} == case["expected"]
    assert raw == case["response"]
    assert AI_HANDLER_REGISTRY[case["provider"]].get_usage_report(raw) == report
    # A value round trip must not depend on provider SDK instances.
    assert json.loads(json.dumps(asdict(report)))["input_tokens"] == report.input_tokens
    assert get_usage(case["provider"], raw) == {
        key: case["expected"][key] for key in ("input_tokens", "output_tokens", "total_tokens")
    }


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("raw", [{}, None, [], "invalid", {"usage": None}, {"usage": []}])
def test_missing_and_invalid_envelopes_do_not_look_like_zero_usage(provider, raw):
    report = get_usage_report(provider, raw)
    assert report.status == "missing"
    assert (report.input_tokens, report.output_tokens, report.total_tokens) == (None, None, None)
    assert "usage_missing" in report.issues
    assert get_usage(provider, raw) == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def response_with_counts(provider, inp, out):
    if provider in ("openai", "perplexity"):
        return {"usage": {"prompt_tokens": inp, "completion_tokens": out}}
    if provider in ("anthropic", "xai"):
        return {"usage": {"input_tokens": inp, "output_tokens": out}}
    if provider == "gemini":
        return {"usageMetadata": {"promptTokenCount": inp, "candidatesTokenCount": out}}
    return {"prompt_eval_count": inp, "eval_count": out}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_explicit_zero_is_known(provider):
    report = get_usage_report(provider, response_with_counts(provider, 0, 0))
    assert report.status == "complete"
    assert (report.input_tokens, report.output_tokens, report.total_tokens) == (0, 0, 0)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("bad", [True, False, -1, 1.0, "42", [], {}])
def test_invalid_counter_types_do_not_become_measurements(provider, bad):
    report = get_usage_report(provider, response_with_counts(provider, bad, 4))
    assert report.input_tokens is None
    assert report.output_tokens == 4
    assert report.total_tokens is None
    assert report.status == "partial"
    assert any(issue.startswith("invalid_count:") for issue in report.issues)
    assert all(type(value) is int for value in get_usage(provider, response_with_counts(provider, bad, 4)).values())


@pytest.mark.parametrize("provider", PROVIDERS)
def test_partial_usage_does_not_invent_a_total(provider):
    report = get_usage_report(provider, response_with_counts(provider, None, 4))
    assert report.status == "partial"
    assert report.input_tokens is None and report.total_tokens is None
    assert report.output_tokens == 4
    # The legacy API keeps its historical partial sum, including zero defaults.
    assert get_usage(provider, response_with_counts(provider, None, 4))["total_tokens"] == 4


@pytest.mark.parametrize("provider", PROVIDERS)
def test_large_integer_counts_are_not_clamped(provider):
    report = get_usage_report(provider, response_with_counts(provider, 2**64, 3))
    assert report.input_tokens == 2**64
    assert report.total_tokens == 2**64 + 3
    assert report.status == "complete"


@pytest.mark.parametrize("total", [0, 99, 101])
def test_provider_total_is_preserved_on_disagreement(total):
    report = get_usage_report("openai", {"usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": total}})
    assert report.total_tokens == total
    assert report.status == "inconsistent"
    assert "total_mismatch" in report.issues


def test_inconsistent_partial_total_and_malformed_total():
    report = get_usage_report("openai", {"usage": {"prompt_tokens": 80, "total_tokens": 20}})
    assert report.status == "inconsistent"
    report = get_usage_report("openai", {"usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": "100"}})
    assert report.total_tokens is None
    assert report.status == "partial"
    assert "invalid_count:total_tokens" in report.issues


@pytest.mark.parametrize("details", [
    {"cached_tokens": 101}, {"cached_tokens": 80, "cache_write_tokens": 30},
])
def test_cache_subsets_cannot_exceed_input(details):
    report = get_usage_report("openai", {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": details}})
    assert report.status == "inconsistent"
    assert report.input_tokens == 100
    assert report.cache_read_tokens is None and report.cache_write_tokens is None
    assert report.raw_usage["prompt_tokens_details"] == details


def test_reasoning_is_a_subset_not_extra_output():
    raw = {"usage": {"prompt_tokens": 5, "completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 30}}}
    report = get_usage_report("openai", raw)
    assert report.status == "inconsistent"
    assert report.reasoning_tokens is None
    assert report.output_tokens == 20 and report.total_tokens == 25


@pytest.mark.parametrize("details", [[], "bad", 3])
def test_malformed_optional_container_preserves_aggregates(details):
    report = get_usage_report("openai", {"usage": {"prompt_tokens": 5, "completion_tokens": 20, "prompt_tokens_details": details}})
    assert report.status == "complete"
    assert report.cache_read_tokens is None
    assert "unsupported_usage_format:prompt_tokens_details" in report.issues


def test_invalid_optional_counter_is_unknown_but_does_not_erase_totals():
    report = get_usage_report("openai", {"usage": {"prompt_tokens": 5, "completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": True}}})
    assert report.status == "complete" and report.reasoning_tokens is None
    assert "invalid_count:reasoning_tokens" in report.issues


@pytest.mark.parametrize("provider", ["anthropic", "xai"])
@pytest.mark.parametrize("value", [None, -1, "12"])
def test_unknown_cache_contribution_keeps_total_input_unknown(provider, value):
    report = get_usage_report(provider, {"usage": {"input_tokens": 10, "cache_read_input_tokens": value, "output_tokens": 3}})
    assert report.input_tokens is None and report.total_tokens is None
    assert report.output_tokens == 3 and report.status == "partial"


def test_nested_metadata_is_detached_and_not_in_repr(capsys):
    raw = {"usage": {"prompt_tokens": 1, "completion_tokens": 2, "extra": {"private": "metadata-marker"}}, "choices": [{"text": "prompt-marker"}]}
    report = get_usage_report("openai", raw)
    raw["usage"]["extra"]["private"] = "changed"
    assert report.raw_usage["extra"]["private"] == "metadata-marker"
    report.raw_usage["extra"]["private"] = "another-change"
    assert raw["usage"]["extra"]["private"] == "changed"
    assert "metadata-marker" not in repr(report)
    assert "prompt-marker" not in repr(asdict(report))
    assert capsys.readouterr() == ("", "")


def test_very_deep_extra_metadata_does_not_lose_counters():
    extra = {}
    for _ in range(1500):
        extra = {"nested": extra}
    report = get_usage_report("openai", {"usage": {"prompt_tokens": 1, "completion_tokens": 2, "extra": extra}})
    assert report.status == "complete" and report.total_tokens == 3
    assert report.raw_usage is None and "raw_usage_unavailable" in report.issues


def test_agent_dispatch_preserves_actual_provider_model(monkeypatch):
    monkeypatch.setitem(agents._AGENTS, "my-reporter", agents.AgentSpec(make="openai", model="requested-model"))
    report = get_usage_report("my-reporter", {"model": "actual-model", "usage": {"prompt_tokens": 1, "completion_tokens": 2}})
    assert report.provider == "openai" and report.model == "actual-model"
    assert get_usage_report("my-reporter", {"_model": "requested-model"}).model is None


def test_unknown_provider_and_legacy_custom_handler(monkeypatch):
    with pytest.raises(ValueError):
        get_usage_report("not-a-provider", {})
    assert get_usage("not-a-provider", {})["total_tokens"] == 0
    monkeypatch.setitem(AI_HANDLER_REGISTRY, "fake", _FakeHandler)
    assert _FakeHandler() is not None
    report = get_usage_report("fake", {"usage": {"unknown_counter": 10}})
    assert report.status == "missing" and "unsupported_usage_format" in report.issues
    assert report.raw_usage == {"unknown_counter": 10}
    assert get_usage("fake", {})["total_tokens"] == 0


def test_agent_with_unregistered_make_raises_value_error(monkeypatch):
    monkeypatch.setitem(agents._AGENTS, "future-agent", agents.AgentSpec(make="future", model=None))
    with pytest.raises(ValueError):
        get_usage_report("future-agent", {})


def test_normalization_needs_no_file_access_or_keys(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected file access")
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for case in CASES:
        assert get_usage_report(case["provider"], case["response"]).status == "complete"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_mixed_valid_and_malformed_counts_keep_public_invariants(provider):
    rng = random.Random(735)
    values = [None, 0, 1, 99, 2**64, True, -1, 1.5, "1", [], {}]
    for _ in range(200):
        raw = response_with_counts(provider, rng.choice(values), rng.choice(values))
        report = get_usage_report(provider, raw)
        counts = (report.input_tokens, report.output_tokens, report.total_tokens)
        assert all(value is None or (type(value) is int and value >= 0) for value in counts)
        if report.status == "complete":
            assert None not in counts
            assert report.total_tokens == report.input_tokens + report.output_tokens


def test_gemini_legacy_gap_is_unknown_not_invented_reasoning():
    raw = {"model_version": "fixture", "prompt_token_count": 100, "candidates_token_count": 20, "total_token_count": 150}
    report = get_usage_report("gemini", raw)
    assert (report.input_tokens, report.output_tokens, report.total_tokens) == (100, None, 150)
    assert report.reasoning_tokens is None and report.status == "partial"
    assert "legacy_usage_incomplete" in report.issues
    assert report.raw_usage["candidates_token_count"] == 20


def test_gemini_nested_metadata_wins_over_old_flat_fields():
    raw = {"prompt_token_count": 999, "candidates_token_count": 999, "usage_metadata": {"prompt_token_count": 4, "candidates_token_count": 2}}
    assert get_usage_report("gemini", raw).total_tokens == 6
    raw["usage_metadata"] = None
    assert get_usage_report("gemini", raw).status == "missing"


@pytest.mark.parametrize("key", ["thoughtsTokenCount", "toolUsePromptTokenCount"])
def test_gemini_unknown_contributions_are_not_zero(key):
    raw = {"usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, key: "bad", "totalTokenCount": 150}}
    report = get_usage_report("gemini", raw)
    assert report.status == "partial" and report.total_tokens == 150
    unknown_count = report.output_tokens if key == "thoughtsTokenCount" else report.input_tokens
    assert unknown_count is None


@pytest.mark.parametrize("metadata", [None, {"prompt_token_count": 100, "candidates_token_count": 20, "thoughts_token_count": 30, "total_token_count": 150, "cached_content_token_count": 40}])
def test_gemini_sdk_conversion_preserves_text_and_usage(metadata):
    types = pytest.importorskip("google.genai.types")
    reply = types.GenerateContentResponse(model_version="fixture", candidates=[{"content": {"parts": [{"text": "Valid report."}]}}], usage_metadata=metadata)
    client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=reply)))
    raw = GeminiHandler._call_api(client, {"model": "fixture", "contents": "prompt"})
    assert GeminiHandler.get_content(raw) == "Valid report."
    assert {"prompt_token_count", "candidates_token_count", "total_token_count", "model_version", "text"} <= raw.keys()
    report = get_usage_report("gemini", raw)
    if metadata is None:
        assert report.status == "missing" and raw["usage_metadata"] is None
    else:
        assert raw["usage_metadata"]["thoughts_token_count"] == 30
        assert report.total_tokens == 150 and report.output_tokens == 50
        assert report.cache_read_tokens == 40


def test_anthropic_sdk_serialization_keeps_optional_absence():
    types = pytest.importorskip("anthropic.types")
    reply = types.Message(id="fixture", type="message", role="assistant", model="fixture", content=[], usage={"input_tokens": 10, "output_tokens": 20})
    report = get_usage_report("anthropic", json.loads(reply.to_json()))
    assert report.status == "complete" and report.total_tokens == 30


@pytest.mark.parametrize("metadata", [[], "bad", 3, {}, {"prompt_token_count": "bad", "candidates_token_count": 2}])
def test_gemini_conversion_keeps_text_with_unexpected_metadata_shape(metadata):
    reply = SimpleNamespace(model_version="fixture", text="Keep this report.", usage_metadata=metadata)
    raw = get_json_response(reply)
    assert raw["text"] == "Keep this report."
    report = get_usage_report("gemini", raw)
    assert report.status in ("missing", "partial")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_local_response_reuse_keeps_historical_usage_without_a_new_call(case, monkeypatch, tmp_path):
    monkeypatch.setenv("CROSS_API_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("CROSS_NO_CACHE", raising=False)
    handler = AI_HANDLER_REGISTRY[case["provider"]]
    call = Mock(return_value=deepcopy(case["response"]))
    monkeypatch.setattr(handler, "_call_api", call)
    first = process_prompt(case["provider"], "fixture", client=object())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    # The second invocation must not construct a client or contact the provider.
    second = process_prompt(case["provider"], "fixture")
    assert not first.was_cached and second.was_cached
    assert call.call_count == 1
    assert get_usage_report(case["provider"], first.response) == get_usage_report(case["provider"], second.response)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    payload, client, response, model = second
    assert response is second.response and len(second) == 4
