# AGENTS.md — cross-ai-core

## What This Package Does
`cross-ai-core` is a multi-provider AI dispatcher extracted from the `cross-ai` application.
It provides a single `process_prompt()` interface across Anthropic, xAI, OpenAI, Google Gemini,
Perplexity, and Ollama (local/LAN, keyless), with MD5-keyed response caching and unified error handling.

## Repo layout
```
cross_ai_core/
  __init__.py          ← public API re-exports
  ai_base.py           ← BaseAIHandler ABC + _get_cache_dir()
  ai_handler.py        ← registry, process_prompt(), get_default_ai(), check_api_key()
  ai_error_handler.py  ← quota / rate-limit / transient error classification
  ai_anthropic.py      ← Anthropic / Claude provider
  ai_xai.py            ← xAI / Grok provider
  ai_openai.py         ← OpenAI provider
  ai_gemini.py         ← Google Gemini provider
  ai_perplexity.py     ← Perplexity provider
  ai_ollama.py         ← Ollama local/LAN provider (keyless; OLL-series)
pyproject.toml
README.md
```

## Key conventions

**Never call `load_dotenv()` in this library.** The calling application is responsible
for loading keys into `os.environ` before importing. The library only reads env vars.

**Never hardcode AI provider names or model strings.** Use `get_default_ai()` and
`get_ai_model(make)`.

**Cache path** is resolved by `_get_cache_dir()` in `ai_base.py` — reads
`CROSS_API_CACHE_DIR` env var, defaults to `~/.cross_api_cache/`.

## Versioning

`cross-ai-core` uses Calendar Versioning: `YYYY.M.R`.

- `YYYY` = 4-digit year
- `M` = month `1-12` (no leading zero)
- `R` = release index within that month, starting at `0`

Examples: `2026.8.0`, `2026.8.1`.

Tags follow the same pattern prefixed with `v`: `v2026.8.0`.

The old SemVer-style `0.x` line is retired; we intentionally skip a `1.0`
marketing milestone. Keep versions strictly increasing to preserve
PEP 440/pip upgrade ordering.

## Adding a provider
1. Create `cross_ai_core/ai_<name>.py` implementing `BaseAIHandler`
2. Import `_get_cache_dir` from `.ai_base` for the cache directory
3. Register in `ai_handler.py`: add to `AI_HANDLER_REGISTRY` and `AI_LIST`
4. Bump version in `pyproject.toml`

## Ollama (local/LAN provider)

`ai_ollama.py` is the first **local** and first **keyless** provider. It talks to
an Ollama daemon over HTTP (`POST /api/generate`, non-streaming) instead of a
cloud API, so all inference stays on the user's own machine or LAN. Because
there is no API key, `ollama` is intentionally **absent** from
`keys.PROVIDER_API_KEY_ENV` — `check_api_key("ollama")` short-circuits to `True`,
and any consumer that filters by `has_api_key()` must treat `ollama` as
always-available (it will raise `ValueError` if you call `has_api_key("ollama")`
directly — whitelist it).

### Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Daemon location — local or a LAN host |
| `OLLAMA_MODEL` | `llama3.1` | Default model (resolved via the generic `<MAKE>_MODEL` path) |
| `OLLAMA_API_TOKEN` | *(empty)* | Optional `Authorization: Bearer` token for reverse-proxied daemons |
| `OLLAMA_REQUEST_TIMEOUT` | `120` | Generation request timeout, seconds |
| `OLLAMA_HEALTH_CHECK_TIMEOUT` | `5` | Connectivity/discovery probe timeout, seconds (fail fast) |

### Connectivity helpers (OLL-3)

The handler is all-classmethod (the registry stores the class, not an instance),
so there is no `__init__` to run a health check "on init". Instead these
classmethods hit `/api/tags` on demand — the st-admin agent wizard, tests, and
troubleshooting flows call them explicitly:

- `OllamaHandler.health_check() -> bool` — reachable? never raises.
- `OllamaHandler.require_healthy()` — raises `ConnectionError` with a hint if down.
- `OllamaHandler.list_models() -> list[str]` — installed model tags (`[]` on failure).

The generation path (`_call_api`) already **fails fast** with actionable
messages (`ConnectionError` / `TimeoutError` / `RuntimeError`) rather than
retrying forever, so no implicit per-call probe is added.

### Remote Ollama (LAN)

To use a daemon on another machine (e.g. a Mac Studio serving models to a
laptop), point `OLLAMA_BASE_URL` at it:

```bash
# ~/.crossenv
OLLAMA_BASE_URL=http://mac-studio.local:11434
OLLAMA_MODEL=llama3.1
OLLAMA_REQUEST_TIMEOUT=120
OLLAMA_HEALTH_CHECK_TIMEOUT=10   # a little more slack over the LAN
```

**Prerequisites on the remote host:**

1. **Bind to all interfaces.** By default `ollama serve` listens on
   `127.0.0.1` only. Start it with `OLLAMA_HOST=0.0.0.0:11434 ollama serve` (or
   set `OLLAMA_HOST` in the host's launch environment) so LAN clients can reach
   it.
2. **Firewall.** Allow inbound TCP on port `11434` on the host.
3. **Hostname resolution.** macOS resolves `<name>.local` via mDNS/Bonjour on the
   same subnet; otherwise use the host's static IP (`http://192.168.1.x:11434`).
4. **Models.** The daemon serves only models that have been pulled on the host
   (`ollama pull llama3.1`); a daemon can be up with zero models.

**Troubleshooting:**

```bash
ping -c2 mac-studio.local                       # DNS / reachability
curl -s http://mac-studio.local:11434/api/tags  # daemon up + installed models
```

If `curl` hangs or refuses: the daemon is bound to localhost only, the firewall
is blocking 11434, or the hostname doesn't resolve. `OllamaHandler.health_check()`
returns `False` in all of these cases; `require_healthy()` raises with the hint.

Concurrency is **hardware-bound** (host RAM/VRAM), not network-bound — the
per-provider cap and `OLLAMA_MAX_CONCURRENCY` override land in OLL-4.

## Development setup

Each repo has its **own `.venv`** — do not share the venv between `cross-ai-core` and `cross-ai`.

```bash
cd ~/github/cross-ai-core
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # installs the package + pytest + pytest-mock
```

To use the local development version inside `cross-ai` at the same time:

```bash
# In a separate terminal with cross-ai's venv active:
cd ~/github/cross
pip install -e ../cross-ai-core/    # editable — changes are picked up instantly
```

## Running tests

```bash
cd ~/github/cross-ai-core
source .venv/bin/activate
python -m pytest tests/ -v
```

Tests cover:
- `test_ai_base.py` — `_get_cache_dir` env resolution, `BaseAIHandler` ABC enforcement
- `test_ai_error_handler.py` — quota/rate-limit/transient classification, `handle_api_error` exit behaviour
- `test_ai_handler.py` — registry completeness, `get_default_ai`, `check_api_key`, `AIResponse` backward compat, `process_prompt` with mocked handlers, `_make` stamp, `get_content_auto`, `put_content_auto`

**Never call real AI APIs in tests.** Use `unittest.mock.patch.dict(AI_HANDLER_REGISTRY, ...)` to inject mock handler classes.



## Publishing to PyPI

See **[RELEASE.md](RELEASE.md)** for the full step-by-step process, including
first-time PyPI account and token setup, TestPyPI trial uploads, the version
bump checklist, tagging, and the hotfix workflow.

Quick reference (assumes `~/.pypirc` is already configured):

```bash
# bump version in pyproject.toml, then:
rm -rf dist/ && python -m build && twine check dist/*
twine upload --repository testpypi dist/*   # trial
twine upload dist/*                         # real
git tag vYYYY.M.R && git push --tags
```

## Version bump checklist
1. Update `version` in `pyproject.toml` — this is the **single source of truth**; `__init__.py` reads the version via `importlib.metadata` and does **not** contain a hardcoded version string
2. Add entry to `CHANGELOG.md`
3. `git tag vYYYY.M.R && git push --tags`
4. `python -m build && twine upload dist/*`
5. In `cross-ai/pyproject.toml`, bump the `cross-ai-core>=` lower bound if needed

## Model overrides (≥ 0.5.0)

Per-call: `process_prompt("gemini", prompt, model="gemini-2.5-pro")`

Global env var (in `~/.crossenv` or `.env`):
```
XAI_MODEL=grok-3-latest
ANTHROPIC_MODEL=claude-sonnet-4-5
OPENAI_MODEL=gpt-4o-mini
GEMINI_MODEL=gemini-2.5-pro
PERPLEXITY_MODEL=sonar-deep-research
```

`get_ai_model(make)` and `process_prompt()` both resolve: explicit arg → `<MAKE_UPPER>_MODEL` env var → compiled-in handler default.

