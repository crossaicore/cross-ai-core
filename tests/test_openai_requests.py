"""Exercise the OpenAI request contract through dispatch and SDK serialization."""
import json

import pytest

httpx = pytest.importorskip("httpx")
openai = pytest.importorskip("openai")

from cross_ai_core import agents
from cross_ai_core.ai_handler import get_content_auto, process_prompt
from cross_ai_core.ai_openai import OpenAIHandler


@pytest.mark.parametrize("selection", ["agent", "environment", "per_call", "default"])
def test_openai_request_accepts_model_defaults(monkeypatch, selection):
    """Reasoning model requests survive every model selection path."""
    model = "gpt-6-astra" if selection != "default" else OpenAIHandler.get_model()
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setitem(agents._AGENTS, "openai", agents.AgentSpec(
        make="openai", model=model if selection == "agent" else None,
    ))
    if selection == "environment":
        monkeypatch.setenv("OPENAI_MODEL", model)
    sent = []

    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        # Reproduce the provider's rejection of legacy/custom parameters.
        for param in ("max_tokens", "temperature", "top_p"):
            if param in body:
                return httpx.Response(400, json={"error": {
                    "message": f"Unsupported parameter: {param}",
                    "type": "invalid_request_error", "param": param,
                    "code": "unsupported_parameter",
                }})
        assert body["model"] == model
        assert body["max_completion_tokens"] > 0
        assert body["messages"] == [
            {"role": "system", "content": "Give a brief answer."},
            {"role": "user", "content": "Say OK."},
        ]
        sent.append(body)
        return httpx.Response(200, json={
            "id": "mock-completion", "object": "chat.completion", "created": 0,
            "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "OK",
            }}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })

    transport = httpx.MockTransport(respond)
    with openai.OpenAI(api_key="mock-only", http_client=httpx.Client(transport=transport)) as client:
        result = process_prompt(
            "openai", "Say OK.", system="Give a brief answer.",
            model=model if selection == "per_call" else None,
            use_cache=False, client=client,
        )
    payload, _, response, effective_model = result
    assert sent == [payload]
    assert effective_model == model
    assert get_content_auto(response) == "OK"
    assert not result.was_cached
