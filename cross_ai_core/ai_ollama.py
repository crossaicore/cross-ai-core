"""
ai_ollama.py - Ollama local/LAN provider handler for cross-ai-core (OLL-1).

Ollama (https://ollama.com) runs open-weight models locally or on a LAN host
and exposes an HTTP API (default http://localhost:11434).  Unlike the cloud
providers it needs no API key on a trusted network, and every request stays on
the user's own hardware.

Configuration (env vars, read through the standard
``mmd_startup.load_cross_env()`` layering - CWD ``.env`` > dev ``.env`` >
``~/.crossenv`` > the compiled-in defaults below):

    OLLAMA_BASE_URL         daemon location            (default http://localhost:11434)
    OLLAMA_MODEL            default model              (default llama3.1)
    OLLAMA_API_TOKEN        optional bearer token for reverse-proxied setups
    OLLAMA_REQUEST_TIMEOUT  generation timeout, seconds (default 120)

Note: ``OLLAMA_MODEL`` is honoured automatically by the dispatcher's generic
``<MAKE_UPPER>_MODEL`` resolution in ``process_prompt`` - no special-casing
needed here.

Endpoint: ``POST /api/generate`` with ``"stream": false`` (Phase 1 -
non-streaming).  Relevant response fields::

    {"response": "...text...", "prompt_eval_count": 26, "eval_count": 290,
     "done": true}

Scope: this module is Phase 1 (OLL-1/OLL-2 - handler + registration).  The
init-time health check and LAN-hardening docs are OLL-3; the rate-limit
concurrency cap is OLL-4.  Streaming and ``/api/chat`` are future (Phase 5).
"""

import os

from .ai_base import BaseAIHandler

AI_MAKE = "ollama"
AI_MODEL = "llama3.1"

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_REQUEST_TIMEOUT = 120


def get_base_url() -> str:
    """Return the Ollama daemon base URL (env ``OLLAMA_BASE_URL`` or default)."""
    val = os.environ.get("OLLAMA_BASE_URL", "").strip()
    return val or DEFAULT_BASE_URL


def _get_request_timeout() -> int:
    """Return the generation request timeout in seconds (env or default)."""
    raw = os.environ.get("OLLAMA_REQUEST_TIMEOUT", "").strip()
    try:
        return int(raw) if raw else DEFAULT_REQUEST_TIMEOUT
    except ValueError:
        return DEFAULT_REQUEST_TIMEOUT


class OllamaHandler(BaseAIHandler):

    @classmethod
    def get_payload(cls, prompt: str, system: str | None = None):
        return get_ollama_payload(prompt, system=system)

    @classmethod
    def get_client(cls):
        return get_ollama_client()

    @classmethod
    def _call_api(cls, client, payload: dict) -> dict:
        """POST the payload to ``/api/generate`` and return the JSON response.

        Raises ``ConnectionError`` / ``TimeoutError`` / ``RuntimeError`` with
        actionable messages so the dispatcher's error handler can surface a
        useful hint instead of a raw stack trace.  (A proactive init-time
        health check is OLL-3.)
        """
        import requests

        url = f"{get_base_url().rstrip('/')}/api/generate"
        try:
            resp = client.post(url, json=payload, timeout=_get_request_timeout())
            resp.raise_for_status()
        except requests.Timeout as e:
            raise TimeoutError(
                f"Ollama at {get_base_url()} timed out after "
                f"{_get_request_timeout()}s. Is the model still loading or the "
                f"host under load? Tune OLLAMA_REQUEST_TIMEOUT if needed."
            ) from e
        except requests.ConnectionError as e:
            raise ConnectionError(
                f"Cannot reach Ollama at {get_base_url()}. "
                f"Is `ollama serve` running and the host/port reachable?"
            ) from e
        except requests.HTTPError as e:
            detail = ""
            try:
                detail = resp.json().get("error", "")
            except Exception:
                detail = (resp.text or "")[:200]
            raise RuntimeError(
                f"Ollama returned HTTP {resp.status_code}: {detail or e}"
            ) from e
        return resp.json()

    @classmethod
    def get_model(cls):
        return AI_MODEL

    @classmethod
    def get_make(cls):
        return AI_MAKE

    @classmethod
    def get_content(cls, gen_content):
        return get_content(gen_content)

    @classmethod
    def put_content(cls, report, gen_content):
        return put_content(report, gen_content)

    @classmethod
    def get_data_content(cls, select_data):
        return get_data_content(select_data)

    @classmethod
    def get_usage(cls, response: dict) -> dict:
        """Extract token counts from an Ollama ``/api/generate`` response.

        Ollama reports ``prompt_eval_count`` (input) and ``eval_count``
        (output).  Either may be absent for very short generations, so default
        to 0 - the ``{input_tokens, output_tokens, total_tokens}`` contract is
        always satisfied (never ``None``).
        """
        inp = response.get("prompt_eval_count", 0) or 0
        out = response.get("eval_count", 0) or 0
        return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}


def get_ollama_payload(prompt_from_file, system: str | None = None):
    """Build the ``/api/generate`` request body.

    ``model`` defaults to :data:`AI_MODEL`; ``process_prompt`` overrides it with
    the effective model (e.g. from ``OLLAMA_MODEL`` or a per-call ``model=``).
    """
    return {
        "model": AI_MODEL,
        "prompt": prompt_from_file,
        "system": system if system is not None else BaseAIHandler.DEFAULT_SYSTEM,
        "stream": False,   # Phase 1: non-streaming (streaming is a Phase 5 item)
        "options": {
            "temperature": 0.7,   # 0.0 deterministic ... 1.0 creative
            "top_p": 0.95,        # nucleus sampling
        },
    }


def get_ollama_client():
    """Return a ``requests.Session`` for the Ollama daemon.

    Adds an ``Authorization: Bearer`` header when ``OLLAMA_API_TOKEN`` is set
    (for instances behind a reverse proxy that enforces auth).  The session is
    cached per-make by the dispatcher's client cache, keeping TCP keep-alive
    warm across the many calls st-speed / st-cross make.
    """
    import requests

    session = requests.Session()
    token = os.environ.get("OLLAMA_API_TOKEN", "").strip()
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
    return session


def get_content(gen_response):
    return gen_response["response"]


def put_content(report, gen_response):
    gen_response["response"] = report
    return gen_response


def get_data_content(select_data):
    return select_data["gen_response"]["response"]

