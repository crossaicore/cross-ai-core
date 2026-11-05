"""Opt-in, one-request integration check. Run from the repository with -m."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
from unittest.mock import patch


PROMPT = "Reply with exactly OK. Do not explain or search the web."
SYSTEM = "Follow the user's instruction."


def _safe_error(exc):
    from cross_ai_core.keys import PROVIDER_API_KEY_ENV

    message = str(exc)
    for names in PROVIDER_API_KEY_ENV.values():
        for name in names:
            key = os.environ.get(name)
            if key:
                message = message.replace(key, "[REDACTED]")
    return {"type": type(exc).__name__, "message": message[:1000]}


def run_smoke(ai_key, *, model=None, max_tokens=128, timeout=30, live=False):
    """Use the real handler and SDK once; never retry or use the local cache.

    Limits and transport options are temporary test overrides, not library
    configuration. Run sequentially in this standalone process.
    """
    # The CLI loads its explicit env file before importing the library, whose
    # agent registry may use CROSS_AI_AGENTS_FILE during initialization.
    from cross_ai_core import AI_HANDLER_REGISTRY, get_ai_model, get_usage_report
    from cross_ai_core.ai_base import BaseAIHandler
    from cross_ai_core.ai_handler import _make_for
    from cross_ai_core.agents import get_agents
    from cross_ai_core.keys import PROVIDER_API_KEY_ENV, has_api_key

    if type(max_tokens) is not int or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    if type(timeout) is not int or timeout < 1:
        raise ValueError("timeout must be a positive integer number of seconds")
    make = _make_for(ai_key)
    handler = AI_HANDLER_REGISTRY[make]
    selected_model = model or (
        get_ai_model(ai_key) if ai_key in get_agents()
        else os.environ.get(f"{make.upper()}_MODEL") or handler.get_model()
    )
    ready = make not in PROVIDER_API_KEY_ENV or has_api_key(make)
    result = {
        "agent": ai_key, "provider": make, "requested_model": selected_model,
        "max_output_tokens": max_tokens, "timeout_seconds": timeout,
        "credentials_present": ready, "attempted_request": False,
        "response_received": False, "status": "dry_run",
    }
    if not live:
        return result
    if not ready:
        return {**result, "status": "failed", "error": {
            "type": "MissingCredentials",
            "message": "Export provider credentials or pass --env-file ~/.crossenv.",
        }}

    try:
        with ExitStack() as stack:
            # Existing payload builders use this limit, including Gemini's SDK
            # config builder. No production defaults or files are changed.
            stack.enter_context(patch.object(BaseAIHandler, "MAX_TOKENS", max_tokens))
            payload = handler.get_payload(PROMPT, system=SYSTEM)
            payload["model"] = selected_model
            if "thinking" in payload:
                payload["thinking"] = {"type": "disabled"}
            if make == "ollama":
                payload["options"]["num_predict"] = max_tokens
                stack.enter_context(patch.dict(os.environ, {"OLLAMA_REQUEST_TIMEOUT": str(timeout)}))
            if make == "gemini":
                from google.genai import types
                from cross_ai_core import ai_gemini
                original_config = ai_gemini.get_gemini_config

                def smoke_config(system):
                    config = original_config(system)
                    config.http_options = types.HttpOptions(
                        timeout=timeout * 1000,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    )
                    return config

                stack.enter_context(patch.object(ai_gemini, "get_gemini_config", smoke_config))

            client = handler.get_client()
            stack.callback(client.close)
            if make not in ("gemini", "ollama"):
                client = client.with_options(max_retries=0, timeout=timeout)
            result["attempted_request"] = True
            response, was_cached = handler.get_cached_response(client, payload, use_cache=False)
            result["response_received"] = True
            # Record usage even if content extraction fails, so a failed check
            # does not conceal metadata from a potentially billable response.
            usage = get_usage_report(make, response)
            result["usage"] = asdict(usage)
            text = handler.get_content(response)
            result["text"] = text
            counts = (usage.input_tokens, usage.output_tokens, usage.total_tokens)
            checks = {
                "fresh_response": not was_cached,
                "expected_text": isinstance(text, str) and text.strip().strip('.!"').upper() == "OK",
                "complete_usage": usage.status == "complete",
                "positive_counts": all(type(n) is int and n > 0 for n in counts),
                "no_usage_errors": not set(usage.issues) - {"total_derived"},
                "native_usage_retained": bool(usage.raw_usage),
            }
            result["checks"] = checks
            result["status"] = "passed" if all(checks.values()) else "failed"
    except Exception as exc:
        result.update(status="failed", error=_safe_error(exc))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", help="Configured agent name or registered provider make")
    parser.add_argument("--model", help="Override the configured model for this check only")
    parser.add_argument("--env-file", type=Path, help="Load an explicit dotenv file, such as ~/.crossenv; exported values take precedence")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument("--live", action="store_true", help="Make one real, potentially billable request")
    args = parser.parse_args(argv)
    if args.env_file:
        try:
            from dotenv import load_dotenv
        except ImportError:
            parser.error('The --env-file option needs python-dotenv; install with: .venv/bin/python -m pip install -e ".[dev]"')
        try:
            with args.env_file.expanduser().open(encoding="utf-8") as stream:
                load_dotenv(stream=stream, override=False)
        except (OSError, UnicodeError):
            parser.error("Cannot read --env-file; check the path, permissions and UTF-8 encoding.")
    try:
        result = run_smoke(args.agent, model=args.model, max_tokens=args.max_tokens,
                           timeout=args.timeout, live=args.live)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
