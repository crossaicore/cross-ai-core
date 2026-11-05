"""Offline checks for the optional live runner; these never contact providers."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from cross_ai_core import AI_HANDLER_REGISTRY, get_usage_report
from cross_ai_core.ai_base import BaseAIHandler
from tools.live_usage_smoke import main, run_smoke


LIVE_RESULTS = json.loads((Path(__file__).parent / "fixtures/live_usage_smoke_20261105.json").read_text())
LOCAL_RESULTS = json.loads((Path(__file__).parent / "fixtures/local_usage_smoke_20261105.json").read_text())


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline tests must never contact a provider")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)


@pytest.fixture
def openai_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value.to_json.return_value = (
        '{"model":"actual-model","choices":[{"message":{"content":"OK"}}],'
        '"usage":{"prompt_tokens":12,"completion_tokens":1,"total_tokens":13}}'
    )
    monkeypatch.setattr(AI_HANDLER_REGISTRY["openai"], "get_client", lambda: client)
    return client


def test_default_dry_run_never_constructs_a_client(openai_client):
    result = run_smoke("openai")
    assert result["status"] == "dry_run" and not result["attempted_request"]
    assert openai_client.mock_calls == []


def test_live_check_uses_real_handler_once_with_small_request(openai_client, monkeypatch):
    def no_cache_io(*args, **kwargs):
        raise AssertionError("Smoke test must bypass cache files")
    monkeypatch.setattr("builtins.open", no_cache_io)
    limit = BaseAIHandler.MAX_TOKENS
    result = run_smoke("openai", model="test-model", live=True)
    assert result["status"] == "passed"
    assert result["response_received"] and all(result["checks"].values())
    assert result["usage"]["model"] == "actual-model"
    assert result["usage"]["raw_usage"]["total_tokens"] == 13
    openai_client.with_options.assert_called_once_with(max_retries=0, timeout=30)
    call = openai_client.chat.completions.create
    call.assert_called_once()
    assert call.call_args.kwargs["max_completion_tokens"] == 128
    assert call.call_args.kwargs["model"] == "test-model"
    assert BaseAIHandler.MAX_TOKENS == limit
    openai_client.close.assert_called_once()


@pytest.mark.parametrize("usage", ["null", "{}", '{"prompt_tokens":3,"completion_tokens":1,"total_tokens":1}'])
def test_valid_text_cannot_hide_missing_or_inconsistent_usage(openai_client, usage):
    openai_client.chat.completions.create.return_value.to_json.return_value = (
        '{"choices":[{"message":{"content":"OK"}}],"usage":' + usage + '}'
    )
    result = run_smoke("openai", live=True)
    assert result["status"] == "failed" and result["checks"]["expected_text"]
    assert not result["checks"]["complete_usage"]


def test_failed_content_preserves_received_usage(openai_client):
    openai_client.chat.completions.create.return_value.to_json.return_value = (
        '{"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":1,"total_tokens":13}}'
    )
    result = run_smoke("openai", live=True)
    assert result["status"] == "failed" and result["response_received"]
    assert result["usage"]["total_tokens"] == 13


def test_api_failure_is_not_retried_and_key_is_redacted(openai_client):
    openai_client.chat.completions.create.side_effect = RuntimeError("Rejected secret-test-key")
    result = run_smoke("openai", live=True)
    assert result["status"] == "failed" and not result["response_received"]
    assert result["error"]["message"] == "Rejected [REDACTED]"
    openai_client.chat.completions.create.assert_called_once()
    openai_client.close.assert_called_once()


def test_missing_credentials_do_not_make_a_request(openai_client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    result = run_smoke("openai", live=True)
    assert result["error"]["type"] == "MissingCredentials"
    assert not result["attempted_request"] and openai_client.mock_calls == []


@pytest.mark.parametrize("option", [{"max_tokens":0}, {"max_tokens":True}, {"timeout":0}])
def test_invalid_limits_fail_before_a_request(openai_client, option):
    with pytest.raises(ValueError):
        run_smoke("openai", live=True, **option)
    assert openai_client.mock_calls == []


def test_cli_failure_sets_exit_status(openai_client, capsys):
    openai_client.chat.completions.create.side_effect = TimeoutError("timeout")
    assert main(["openai", "--live"]) == 1
    assert '"status": "failed"' in capsys.readouterr().out


def test_gemini_request_cap_timeout_and_no_retries(monkeypatch):
    types = pytest.importorskip("google.genai.types")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-test-key")
    client = Mock()
    client.models.generate_content.return_value = types.GenerateContentResponse(
        model_version="fixture", candidates=[{"content":{"parts":[{"text":"OK"}]}}],
        usage_metadata={"prompt_token_count":12,"candidates_token_count":1,"total_token_count":13},
    )
    monkeypatch.setattr(AI_HANDLER_REGISTRY["gemini"], "get_client", lambda: client)
    result = run_smoke("gemini", live=True)
    assert result["status"] == "passed"
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.max_output_tokens == 128
    assert config.http_options.timeout == 30000
    assert config.http_options.retry_options.attempts == 1


def test_anthropic_disables_large_thinking_budget(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-test-key")
    client = Mock()
    client.with_options.return_value = client
    client.messages.create.return_value.to_json.return_value = (
        '{"content":[{"type":"text","text":"OK"}],"usage":{"input_tokens":12,"output_tokens":1}}'
    )
    monkeypatch.setattr(AI_HANDLER_REGISTRY["anthropic"], "get_client", lambda: client)
    assert run_smoke("anthropic", live=True)["status"] == "passed"
    assert client.messages.create.call_args.kwargs["thinking"] == {"type":"disabled"}
    assert client.messages.create.call_args.kwargs["max_tokens"] == 128


def test_ollama_request_limit_and_timeout(monkeypatch):
    client = Mock()
    client.post.return_value.json.return_value = {"response":"OK", "prompt_eval_count":12, "eval_count":1}
    monkeypatch.setattr(AI_HANDLER_REGISTRY["ollama"], "get_client", lambda: client)
    assert run_smoke("ollama", live=True)["status"] == "passed"
    assert client.post.call_args.kwargs["json"]["options"]["num_predict"] == 128
    assert client.post.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("case", [r for r in LIVE_RESULTS["results"] if r["status"] == "passed"], ids=lambda r: r["provider"])
def test_replay_reviewed_live_metadata_without_network(case):
    # These four live endpoints return a nested `usage` object. Expected counts
    # were reviewed against the recorded native counters, including xAI's hit.
    expected = case["usage"]
    response = {"model": expected["model"], "usage": expected["raw_usage"]}
    actual = get_usage_report(case["provider"], response)
    assert json.loads(json.dumps(asdict(actual))) == expected


@pytest.mark.parametrize("case", LOCAL_RESULTS["results"], ids=lambda r: f'{r["server"]}-{r["max_output_tokens"]}')
def test_replay_local_server_metadata_without_network(case):
    expected = case["usage"]
    response = {"model": expected["model"]}
    if case["provider"] == "ollama":
        response.update(expected["raw_usage"])
    else:
        response["usage"] = expected["raw_usage"]
    actual = get_usage_report(case["provider"], response)
    assert json.loads(json.dumps(asdict(actual))) == expected


def test_reasoning_only_response_does_not_pass_text_check(openai_client):
    case = next(r for r in LOCAL_RESULTS["results"] if r["status"] == "failed")
    openai_client.chat.completions.create.return_value.to_json.return_value = json.dumps({
        "model": case["usage"]["model"], "usage": case["usage"]["raw_usage"],
        "choices": [{"message": {"content": case["text"]}}],
    })
    result = run_smoke("openai", live=True)
    assert result["status"] == "failed" and not result["checks"]["expected_text"]
    assert result["checks"]["complete_usage"]
    assert result["usage"]["output_tokens"] == result["usage"]["reasoning_tokens"] == 128


def test_cli_loads_explicit_env_file_without_exposing_keys(openai_client, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("OPENAI_API_KEY")
    env_file = tmp_path / ".crossenv"
    env_file.write_text('export OPENAI_API_KEY="file-secret#value" # comment\n')
    assert main(["openai", "--env-file", str(env_file)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["credentials_present"] is True
    assert os.environ["OPENAI_API_KEY"] == "file-secret#value"
    assert "file-secret" not in output and openai_client.mock_calls == []


def test_env_file_preserves_exported_credentials(openai_client, tmp_path, capsys):
    env_file = tmp_path / ".crossenv"
    env_file.write_text("OPENAI_API_KEY=file-secret\n")
    assert main(["openai", "--env-file", str(env_file)]) == 0
    assert os.environ["OPENAI_API_KEY"] == "secret-test-key"
    assert "file-secret" not in capsys.readouterr().out


def test_cli_does_not_implicitly_load_env_files(openai_client, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY")
    loader = Mock(side_effect=AssertionError("Unexpected file loading"))
    monkeypatch.setattr("dotenv.load_dotenv", loader)
    assert main(["openai"]) == 0
    assert json.loads(capsys.readouterr().out)["credentials_present"] is False
    loader.assert_not_called()
    assert openai_client.mock_calls == []


def test_unreadable_env_file_stops_before_live_request(openai_client, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["openai", "--live", "--env-file", str(tmp_path / "missing")])
    assert exc.value.code == 2
    assert "Cannot read --env-file" in capsys.readouterr().err
    assert openai_client.mock_calls == []


def test_missing_dotenv_dependency_gives_install_instruction(openai_client, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "dotenv", None)
    with pytest.raises(SystemExit) as exc:
        main(["openai", "--env-file", "unused", "--live"])
    assert exc.value.code == 2
    assert "pip install" in capsys.readouterr().err
    assert openai_client.mock_calls == []


def test_cli_loads_env_before_library_agent_registry(tmp_path):
    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"version":2,"agents":{"env-file-agent":{"make":"openai","model":"env-file-model"}}}))
    env_file = tmp_path / ".crossenv"
    env_file.write_text(f'CROSS_AI_AGENTS_FILE="{agents}"\nOPENAI_API_KEY=file-secret\n')
    env = {k:v for k,v in os.environ.items() if k not in ("CROSS_AI_AGENTS_FILE", "OPENAI_MODEL", "OPENAI_API_KEY", "PYTHON_DOTENV_DISABLED")}
    completed = subprocess.run(
        [sys.executable, "-m", "tools.live_usage_smoke", "env-file-agent", "--env-file", str(env_file)],
        cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True, timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["requested_model"] == "env-file-model"
    assert result["credentials_present"] and not result["attempted_request"]
    assert "file-secret" not in completed.stdout + completed.stderr
